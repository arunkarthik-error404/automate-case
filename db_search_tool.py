import json
import sqlite3
import numpy as np
import psycopg2
from rag.embeddings import EmbeddingManager
from setup_db import connect_postgres, DB_NAME, SQLITE_DB_PATH, init_sqlite_fallback

class DBSearchTool:
    """Tool for querying document chunks with hybrid vector search and metadata filters."""

    def __init__(self, db_name=DB_NAME):
        self.db_name = db_name
        self.embedder = EmbeddingManager()

    def search_similar_chunks(self, query: str, top_k: int = 5, father_name: str = None, state: str = None, entity_name: str = None):
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

    def _search_postgres(self, conn, query, top_k, father_name, state, entity_name):
        query_vec = self.embedder.generate_embedding(query)
        vec_str = f"[{','.join(map(str, query_vec))}]"

        father_tokens = self._tokenize_name(father_name)
        entity_tokens = self._tokenize_name(entity_name)

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

        scored_results = []
        for r in rows:
            chunk_id, file_name, ent_name, cat, page_num, chunk_text, meta, cos_dist, chunk_idx, doc_id = r
            sim = 1.0 - float(cos_dist)
            chunk_text_lower = chunk_text.lower()
            meta_str_lower = json.dumps(meta or {}).lower()
            combined_text = f"{chunk_text_lower} {meta_str_lower} {file_name.lower()} {ent_name.lower()}"

            import re
            if state and state.lower() not in combined_text:
                sim -= 0.1

            if father_tokens and all(re.search(r'\b' + re.escape(tok) + r'\b', combined_text) for tok in father_tokens):
                sim += 0.35

            if entity_tokens and any(re.search(r'\b' + re.escape(tok) + r'\b', combined_text) for tok in entity_tokens):
                sim += 0.15

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
            chunk_id, file_name, ent_name, cat, page_num, chunk_text, meta, cos_dist, chunk_idx, doc_id = r
            if doc_id in top_doc_ids and page_num == 1 and chunk_idx == 0 and chunk_id not in existing_chunk_ids:
                top_chunks.append({
                    "chunk_id": chunk_id, "file_name": file_name, "entity_name": ent_name, "category": cat,
                    "page_number": page_num, "chunk_text": chunk_text, "metadata": meta,
                    "similarity_score": 0.9999, "chunk_index": chunk_idx, "doc_id": doc_id
                })
                existing_chunk_ids.add(chunk_id)

        top_chunks.sort(key=lambda x: (x["file_name"], x["page_number"], x["chunk_index"]))
        return top_chunks

    def _search_sqlite(self, query, top_k, father_name, state, entity_name):
        init_sqlite_fallback()
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()

        query_vec = np.array(self.embedder.generate_embedding(query), dtype=np.float32)

        sql = """
            SELECT c.id, d.file_name, d.entity_name, d.category, c.page_number, c.chunk_text, c.metadata, c.embedding, c.chunk_index, d.id
            FROM document_chunks c
            JOIN documents d ON c.document_id = d.id;
        """
        cursor.execute(sql)
        rows = cursor.fetchall()
        conn.close()

        father_tokens = self._tokenize_name(father_name)
        entity_tokens = self._tokenize_name(entity_name)

        import re
        scored_results = []
        for r in rows:
            chunk_id, file_name, ent_name, cat, page_num, chunk_text, meta_raw, emb_raw, chunk_idx, doc_id = r
            meta = json.loads(meta_raw) if isinstance(meta_raw, str) else meta_raw or {}
            chunk_text_lower = chunk_text.lower()
            meta_str_lower = json.dumps(meta).lower()
            combined_text = f"{chunk_text_lower} {meta_str_lower} {file_name.lower()} {ent_name.lower()}"

            try:
                emb = np.array(json.loads(emb_raw), dtype=np.float32)
                sim = float(np.dot(query_vec, emb) / (np.linalg.norm(query_vec) * np.linalg.norm(emb) + 1e-9))
            except Exception:
                sim = 0.0

            if state and state.lower() not in combined_text:
                sim -= 0.1

            if father_tokens and all(re.search(r'\b' + re.escape(tok) + r'\b', combined_text) for tok in father_tokens):
                sim += 0.35

            if entity_tokens and any(re.search(r'\b' + re.escape(tok) + r'\b', combined_text) for tok in entity_tokens):
                sim += 0.15

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
            chunk_id, file_name, ent_name, cat, page_num, chunk_text, meta_raw, emb_raw, chunk_idx, doc_id = r
            if doc_id in top_doc_ids and page_num == 1 and chunk_idx == 0 and chunk_id not in existing_chunk_ids:
                meta = json.loads(meta_raw) if isinstance(meta_raw, str) else meta_raw or {}
                top_chunks.append({
                    "chunk_id": chunk_id, "file_name": file_name, "entity_name": ent_name, "category": cat,
                    "page_number": page_num, "chunk_text": chunk_text, "metadata": meta,
                    "similarity_score": 0.9999, "chunk_index": chunk_idx, "doc_id": doc_id
                })
                existing_chunk_ids.add(chunk_id)

        top_chunks.sort(key=lambda x: (x["file_name"], x["page_number"], x["chunk_index"]))
        return top_chunks

    def get_document_chunks_for_summary(self, entity_or_file: str, max_chunks: int = 25):
        search_pattern = f"%{entity_or_file}%"
        pg_conn = connect_postgres(self.db_name)
        if pg_conn:
            cursor = pg_conn.cursor()
            sql = """
                SELECT d.file_name, d.entity_name, d.category, c.page_number, c.chunk_text
                FROM document_chunks c JOIN documents d ON c.document_id = d.id
                WHERE (d.entity_name ILIKE %s OR d.file_name ILIKE %s OR c.chunk_text ILIKE %s)
                  AND LENGTH(c.chunk_text) > 40
                ORDER BY d.file_name ASC, c.page_number ASC, c.chunk_index ASC LIMIT %s;
            """
            cursor.execute(sql, (search_pattern, search_pattern, search_pattern, max_chunks))
            rows = cursor.fetchall()
            cursor.close()
            pg_conn.close()
            return [{"file_name": r[0], "entity_name": r[1], "category": r[2], "page_number": r[3], "chunk_text": r[4]} for r in rows]
        else:
            conn = sqlite3.connect(SQLITE_DB_PATH)
            cursor = conn.cursor()
            sql = """
                SELECT d.file_name, d.entity_name, d.category, c.page_number, c.chunk_text
                FROM document_chunks c JOIN documents d ON c.document_id = d.id
                WHERE (d.entity_name LIKE ? OR d.file_name LIKE ? OR c.chunk_text LIKE ?)
                  AND LENGTH(c.chunk_text) > 40
                ORDER BY d.file_name ASC, c.page_number ASC, c.chunk_index ASC LIMIT ?;
            """
            cursor.execute(sql, (search_pattern, search_pattern, search_pattern, max_chunks))
            rows = cursor.fetchall()
            conn.close()
            return [{"file_name": r[0], "entity_name": r[1], "category": r[2], "page_number": r[3], "chunk_text": r[4]} for r in rows]

if __name__ == "__main__":
    tool = DBSearchTool()
    print("Testing DBSearchTool...")
    res = tool.search_similar_chunks("G Janardhan Reddy son of Gurumurthy Reddy", top_k=3)
    print(f"Results returned: {len(res)}")
