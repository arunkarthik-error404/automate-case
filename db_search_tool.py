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

    def _search_postgres(self, conn, query, top_k, father_name, state, entity_name):
        query_vec = self.embedder.generate_embedding(query)
        vec_str = f"[{','.join(map(str, query_vec))}]"

        cursor = conn.cursor()
        where_clauses = ["1=1"]
        params = []

        if father_name:
            where_clauses.append("(c.metadata->>'father_name' ILIKE %s OR c.chunk_text ILIKE %s)")
            params.extend([f"%{father_name}%", f"%{father_name}%"])

        if state:
            where_clauses.append("(c.metadata->>'state' ILIKE %s OR c.chunk_text ILIKE %s)")
            params.extend([f"%{state}%", f"%{state}%"])

        if entity_name:
            where_clauses.append("(d.entity_name ILIKE %s OR c.chunk_text ILIKE %s)")
            params.extend([f"%{entity_name}%", f"%{entity_name}%"])

        where_sql = " AND ".join(where_clauses)
        sql = f"""
            SELECT 
                c.id, d.file_name, d.entity_name, d.category, c.page_number, c.chunk_text, c.metadata,
                (c.embedding <=> %s::vector) AS cosine_distance
            FROM document_chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE {where_sql}
            ORDER BY c.embedding <=> %s::vector ASC
            LIMIT %s;
        """
        cursor.execute(sql, (vec_str, *params, vec_str, top_k))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        return [{
            "chunk_id": r[0], "file_name": r[1], "entity_name": r[2], "category": r[3],
            "page_number": r[4], "chunk_text": r[5], "metadata": r[6],
            "similarity_score": round(1.0 - float(r[7]), 4)
        } for r in rows]

    def _search_sqlite(self, query, top_k, father_name, state, entity_name):
        init_sqlite_fallback()
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()

        query_vec = np.array(self.embedder.generate_embedding(query), dtype=np.float32)

        sql = """
            SELECT c.id, d.file_name, d.entity_name, d.category, c.page_number, c.chunk_text, c.metadata, c.embedding
            FROM document_chunks c
            JOIN documents d ON c.document_id = d.id;
        """
        cursor.execute(sql)
        rows = cursor.fetchall()
        conn.close()

        scored_results = []
        for r in rows:
            chunk_id, file_name, ent_name, cat, page_num, chunk_text, meta_raw, emb_raw = r
            meta = json.loads(meta_raw) if isinstance(meta_raw, str) else meta_raw or {}

            # Filters check
            if father_name:
                f_meta = meta.get("father_name", "")
                if father_name.lower() not in f_meta.lower() and father_name.lower() not in chunk_text.lower():
                    continue

            if state:
                s_meta = meta.get("state", "")
                if state.lower() not in s_meta.lower() and state.lower() not in chunk_text.lower():
                    continue

            if entity_name:
                if entity_name.lower() not in ent_name.lower() and entity_name.lower() not in chunk_text.lower():
                    continue

            # Vector cosine similarity
            try:
                emb = np.array(json.loads(emb_raw), dtype=np.float32)
                sim = float(np.dot(query_vec, emb) / (np.linalg.norm(query_vec) * np.linalg.norm(emb) + 1e-9))
            except Exception:
                sim = 0.0

            scored_results.append({
                "chunk_id": chunk_id, "file_name": file_name, "entity_name": ent_name, "category": cat,
                "page_number": page_num, "chunk_text": chunk_text, "metadata": meta,
                "similarity_score": round(sim, 4)
            })

        scored_results.sort(key=lambda x: x["similarity_score"], reverse=True)
        return scored_results[:top_k]

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
