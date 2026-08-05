import json
import sqlite3
import numpy as np
import psycopg2
from rag.embeddings import get_embedding_manager
from setup_db import connect_postgres, DB_NAME, SQLITE_DB_PATH, init_sqlite_fallback

class DBSearchTool:
    """Tool for querying document chunks with hybrid vector search and metadata filters."""

    def __init__(self, db_name=DB_NAME):
        self.db_name = db_name

    @property
    def embedder(self):
        """Resolved lazily — constructing the tool must not load the ONNX model."""
        return get_embedding_manager()

    def _extract_query_terms(self, query: str):
        import re
        STOP_WORDS = {
            'find', 'search', 'get', 'give', 'show', 'tell', 'me', 'please', 'can', 'you',
            'details', 'information', 'info', 'records', 'cases', 'case', 'report', 'summary',
            'the', 'a', 'an', 'of', 'in', 'for', 'about', 'on', 'at', 'by', 'from', 'with',
            'to', 'is', 'are', 'was', 'were', 'what', 'where', 'who', 'when', 'why', 'how',
            'or', 'and', 'not', 'no', 'court', 'status'
        }
        words = [w.lower() for w in re.findall(r'\b[A-Za-z0-9]+\b', query) if w.lower() not in STOP_WORDS and len(w) > 1]
        return words

    def _extract_phrases(self, query: str):
        import re
        STOP_WORDS = {'find', 'search', 'get', 'give', 'show', 'tell', 'me', 'details', 'information', 'records', 'cases', 'for', 'about', 'the', 'a', 'an', 'in', 'of'}
        clean = re.sub(r'(?:son of|s/o|father[\'s]*)\s*[A-Za-z\s]+', '', query, flags=re.IGNORECASE)
        words = [w for w in re.findall(r'\b[A-Za-z0-9]+\b', clean) if w.lower() not in STOP_WORDS]
        phrases = []
        if len(words) >= 2:
            for i in range(len(words) - 1):
                phrases.append(" ".join(words[i:i+2]).lower())
        if len(words) >= 3:
            for i in range(len(words) - 2):
                phrases.append(" ".join(words[i:i+3]).lower())
        return phrases

    def search_similar_chunks(self, query: str, top_k: int = 15, father_name: str = None, state: str = None, entity_name: str = None):
        pg_conn = connect_postgres(self.db_name)
        if pg_conn:
            return self._search_postgres(pg_conn, query, top_k, father_name, state, entity_name)
        else:
            return self._search_sqlite(query, top_k, father_name, state, entity_name)

    def _tokenize_name(self, name_str):
        if not name_str:
            return []
        import re
        tokens = [t.lower() for t in re.split(r'[\s\.\,]+', name_str) if t.lower() not in ('g', 'late', 's/o', 'son', 'of', 'mr', 'sri', '')]
        return tokens

    def _score_and_filter_rows(self, rows, query, father_name, state, entity_name, top_k):
        import re
        father_tokens = self._tokenize_name(father_name)
        entity_tokens = self._tokenize_name(entity_name)
        query_terms = self._extract_query_terms(query)
        query_phrases = self._extract_phrases(query)

        scored_results = []
        for r in rows:
            chunk_id, file_name, ent_name, cat, page_num, chunk_text, meta_data, cos_dist_or_emb, chunk_idx, doc_id = r
            meta = json.loads(meta_data) if isinstance(meta_data, str) else meta_data or {}
            chunk_text_lower = chunk_text.lower()
            meta_str_lower = json.dumps(meta).lower()
            combined_text = f"{chunk_text_lower} {meta_str_lower} {file_name.lower()} {ent_name.lower()}"

            if isinstance(cos_dist_or_emb, (list, tuple, np.ndarray)) or (isinstance(cos_dist_or_emb, str) and cos_dist_or_emb.startswith("[")):
                try:
                    if isinstance(cos_dist_or_emb, str):
                        emb = np.array(json.loads(cos_dist_or_emb), dtype=np.float32)
                    else:
                        emb = np.array(cos_dist_or_emb, dtype=np.float32)
                    query_vec = getattr(self, '_cached_query_vec', None)
                    if query_vec is None:
                        query_vec = np.array(self.embedder.generate_embedding(query), dtype=np.float32)
                        self._cached_query_vec = query_vec
                    sim = float(np.dot(query_vec, emb) / (np.linalg.norm(query_vec) * np.linalg.norm(emb) + 1e-9))
                except Exception:
                    sim = 0.0
            else:
                sim = 1.0 - float(cos_dist_or_emb)

            if state and state.lower() not in combined_text:
                sim -= 0.1

            # Exact Father Name Boost
            if father_tokens and all(re.search(r'\b' + re.escape(tok) + r'\b', combined_text) for tok in father_tokens):
                sim += 0.35

            # Explicit Entity Tokens Boost
            if entity_tokens and any(re.search(r'\b' + re.escape(tok) + r'\b', combined_text) for tok in entity_tokens):
                sim += 0.15

            # Universal Significant Query Term Boost
            term_matches = sum(1 for tok in query_terms if re.search(r'\b' + re.escape(tok) + r'\b', combined_text))
            if term_matches > 0:
                sim += 0.10 * term_matches

            # Universal Phrase Match Boost
            for phrase in query_phrases:
                if phrase in combined_text:
                    sim += 0.25
                    break

            scored_results.append({
                "chunk_id": chunk_id, "file_name": file_name, "entity_name": ent_name, "category": cat,
                "page_number": page_num, "chunk_text": chunk_text, "metadata": meta,
                "similarity_score": round(sim, 4), "chunk_index": chunk_idx, "doc_id": doc_id
            })

        scored_results.sort(key=lambda x: x["similarity_score"], reverse=True)

        # Deduplicate identical chunks (e.g. from duplicate documents)
        seen_content = set()
        unique_results = []
        for res in scored_results:
            key = (res["file_name"], res["page_number"], res["chunk_index"])
            if key not in seen_content:
                seen_content.add(key)
                unique_results.append(res)

        top_chunks = unique_results[:top_k]

        # Guarantee header chunks (page 1, chunk 0) for matched documents
        top_doc_ids = {c["doc_id"] for c in top_chunks}
        existing_chunk_ids = {c["chunk_id"] for c in top_chunks}

        for r in rows:
            chunk_id, file_name, ent_name, cat, page_num, chunk_text, meta_data, cos_dist_or_emb, chunk_idx, doc_id = r
            if doc_id in top_doc_ids and page_num == 1 and chunk_idx == 0 and chunk_id not in existing_chunk_ids:
                meta = json.loads(meta_data) if isinstance(meta_data, str) else meta_data or {}
                top_chunks.append({
                    "chunk_id": chunk_id, "file_name": file_name, "entity_name": ent_name, "category": cat,
                    "page_number": page_num, "chunk_text": chunk_text, "metadata": meta,
                    "similarity_score": 0.9999, "chunk_index": chunk_idx, "doc_id": doc_id
                })
                existing_chunk_ids.add(chunk_id)

        top_chunks.sort(key=lambda x: (x["file_name"], x["page_number"], x["chunk_index"]))
        return top_chunks

    def _search_postgres(self, conn, query, top_k, father_name, state, entity_name):
        self._cached_query_vec = None
        query_vec = self.embedder.generate_embedding(query)
        vec_str = f"[{','.join(map(str, query_vec))}]"

        cursor = conn.cursor()
        sql = """
            SELECT 
                c.id, d.file_name, d.entity_name, d.category, c.page_number, c.chunk_text, c.metadata,
                (c.embedding <=> %s::vector) AS cosine_distance, c.chunk_index, d.id AS doc_id
            FROM document_chunks c
            JOIN documents d ON c.document_id = d.id;
        """
        cursor.execute(sql, (vec_str,))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        return self._score_and_filter_rows(rows, query, father_name, state, entity_name, top_k)

    def _search_sqlite(self, query, top_k, father_name, state, entity_name):
        self._cached_query_vec = None
        init_sqlite_fallback()
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()

        sql = """
            SELECT c.id, d.file_name, d.entity_name, d.category, c.page_number, c.chunk_text, c.metadata, c.embedding, c.chunk_index, d.id
            FROM document_chunks c
            JOIN documents d ON c.document_id = d.id;
        """
        cursor.execute(sql)
        rows = cursor.fetchall()
        conn.close()

        results = self._score_and_filter_rows(rows, query, father_name, state, entity_name, top_k)

        # Fallback wildcard search if top score is below confidence threshold
        query_terms = self._extract_query_terms(query)
        if (not results or results[0]["similarity_score"] < 0.75) and len(query_terms) >= 1:
            conn = sqlite3.connect(SQLITE_DB_PATH)
            cursor = conn.cursor()
            like_conditions = " AND ".join(["(d.file_name LIKE ? OR d.entity_name LIKE ? OR c.chunk_text LIKE ?)" for _ in query_terms])
            params = []
            for t in query_terms:
                pat = f"%{t}%"
                params.extend([pat, pat, pat])
            sql_fallback = f"""
                SELECT c.id, d.file_name, d.entity_name, d.category, c.page_number, c.chunk_text, c.metadata, c.embedding, c.chunk_index, d.id
                FROM document_chunks c JOIN documents d ON c.document_id = d.id
                WHERE {like_conditions} LIMIT {top_k * 2};
            """
            try:
                cursor.execute(sql_fallback, params)
                fallback_rows = cursor.fetchall()
                conn.close()
                if fallback_rows:
                    fb_results = self._score_and_filter_rows(fallback_rows, query, father_name, state, entity_name, top_k)
                    existing_ids = {r["chunk_id"] for r in results}
                    for fbr in fb_results:
                        if fbr["chunk_id"] not in existing_ids:
                            results.append(fbr)
                    results.sort(key=lambda x: x["similarity_score"], reverse=True)
                    results = results[:top_k]
            except Exception:
                if conn: conn.close()

        return results

    def get_document_chunks_for_summary(self, entity_or_file: str, max_chunks: int = 35):
        import re
        STOP_WORDS = {
            'center', 'centre', 'limited', 'pvt', 'services', 'report', 'reports', 'details', 
            'show', 'get', 'give', 'find', 'the', 'for', 'a', 'an', 'of', 'in', 'and', 'all', 
            'cases', 'case', 'related', 'to', 'me', 'please', 'can', 'you', 'debtor', 'asset'
        }
        tokens = [t for t in re.findall(r'\b[A-Za-z0-9]+\b', entity_or_file) if t.lower() not in STOP_WORDS]
        if not tokens:
            tokens = [entity_or_file]

        pg_conn = connect_postgres(self.db_name)
        if pg_conn:
            cursor = pg_conn.cursor()
            where_clauses = []
            pg_params = []
            for tok in tokens:
                pat = f"%{tok}%"
                where_clauses.append("(d.entity_name ILIKE %s OR d.file_name ILIKE %s OR c.chunk_text ILIKE %s)")
                pg_params.extend([pat, pat, pat])
            
            token_sql = " AND ".join(where_clauses)
            pg_params.append(max_chunks)

            sql = f"""
                WITH RankedChunks AS (
                    SELECT d.file_name, d.entity_name, d.category, c.page_number, c.chunk_text,
                           ROW_NUMBER() OVER(PARTITION BY d.file_name ORDER BY c.page_number ASC, c.chunk_index ASC) as rn
                    FROM document_chunks c JOIN documents d ON c.document_id = d.id
                    WHERE {token_sql}
                      AND LENGTH(c.chunk_text) > 40
                )
                SELECT file_name, entity_name, category, page_number, chunk_text
                FROM RankedChunks
                WHERE rn <= 3
                ORDER BY file_name ASC LIMIT %s;
            """
            cursor.execute(sql, pg_params)
            rows = cursor.fetchall()
            cursor.close()
            pg_conn.close()
            return [{"file_name": r[0], "entity_name": r[1], "category": r[2], "page_number": r[3], "chunk_text": r[4]} for r in rows]
        else:
            conn = sqlite3.connect(SQLITE_DB_PATH)
            cursor = conn.cursor()
            where_clauses = []
            sq_params = []
            for tok in tokens:
                pat = f"%{tok}%"
                where_clauses.append("(d.entity_name LIKE ? OR d.file_name LIKE ? OR c.chunk_text LIKE ?)")
                sq_params.extend([pat, pat, pat])
            
            token_sql = " AND ".join(where_clauses)
            sq_params.append(max_chunks)

            sql = f"""
                WITH RankedChunks AS (
                    SELECT d.file_name, d.entity_name, d.category, c.page_number, c.chunk_text,
                           ROW_NUMBER() OVER(PARTITION BY d.file_name ORDER BY c.page_number ASC, c.chunk_index ASC) as rn
                    FROM document_chunks c JOIN documents d ON c.document_id = d.id
                    WHERE {token_sql}
                      AND LENGTH(c.chunk_text) > 40
                )
                SELECT file_name, entity_name, category, page_number, chunk_text
                FROM RankedChunks
                WHERE rn <= 3
                ORDER BY file_name ASC LIMIT ?;
            """
            cursor.execute(sql, sq_params)
            rows = cursor.fetchall()
            conn.close()
            return [{"file_name": r[0], "entity_name": r[1], "category": r[2], "page_number": r[3], "chunk_text": r[4]} for r in rows]

if __name__ == "__main__":
    tool = DBSearchTool()
    print("Testing DBSearchTool...")
    res = tool.search_similar_chunks("G Janardhan Reddy son of Gurumurthy Reddy", top_k=3)
    print(f"Results returned: {len(res)}")
