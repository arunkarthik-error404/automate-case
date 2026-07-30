import os
import sys
import json
import sqlite3
import argparse
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

from rag.pdf_extractor import PDFExtractor
from rag.chunker import DocumentChunker
from rag.embeddings import EmbeddingManager
from setup_db import connect_postgres, DB_NAME, SQLITE_DB_PATH, init_sqlite_fallback

DEFAULT_REPORTS_DIR = os.getenv(
    "REPORTS_DIR", 
    os.path.join(os.path.dirname(__file__), "Search Reports-20260730T080443Z-1-001")
)

def ingest_to_postgres(pdf_files, extractor, chunker, embedder, force=False):
    conn = connect_postgres(DB_NAME)
    cursor = conn.cursor()

    total_docs = 0
    total_chunks = 0

    for idx, pdf_path in enumerate(pdf_files, start=1):
        rel_path = os.path.normpath(pdf_path)
        if not force:
            cursor.execute("SELECT id FROM documents WHERE file_path = %s;", (rel_path,))
            if cursor.fetchone():
                print(f"[{idx}/{len(pdf_files)}] [PG] Skipping ingested file: {os.path.basename(pdf_path)}")
                continue

        print(f"[{idx}/{len(pdf_files)}] [PG] Parsing: {os.path.basename(pdf_path)}...")
        parsed_doc = extractor.parse_pdf(pdf_path)
        doc_meta = parsed_doc["document_metadata"]
        chunks = chunker.chunk_document(parsed_doc)
        if not chunks:
            continue

        chunk_texts = [c["chunk_text"] for c in chunks]
        embeddings = embedder.generate_batch_embeddings(chunk_texts)

        cursor.execute(
            """
            INSERT INTO documents (file_name, file_path, category, entity_name, total_pages)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (file_path) DO UPDATE SET
                file_name = EXCLUDED.file_name,
                category = EXCLUDED.category,
                entity_name = EXCLUDED.entity_name,
                total_pages = EXCLUDED.total_pages
            RETURNING id;
            """,
            (doc_meta["file_name"], rel_path, doc_meta["category"], doc_meta["entity_name"], doc_meta.get("total_pages", 0))
        )
        doc_id = cursor.fetchone()[0]

        chunk_tuples = []
        for chunk, emb in zip(chunks, embeddings):
            emb_str = f"[{','.join(map(str, emb))}]"
            chunk_tuples.append((
                doc_id, chunk["chunk_index"], chunk["page_number"],
                chunk["chunk_text"], json.dumps(chunk["metadata"]), emb_str
            ))

        execute_values(
            cursor,
            "INSERT INTO document_chunks (document_id, chunk_index, page_number, chunk_text, metadata, embedding) VALUES %s;",
            chunk_tuples,
            template="(%s, %s, %s, %s, %s::jsonb, %s::vector)"
        )
        conn.commit()
        total_docs += 1
        total_chunks += len(chunks)

    cursor.close()
    conn.close()
    return total_docs, total_chunks

def ingest_to_sqlite(pdf_files, extractor, chunker, embedder, force=False):
    init_sqlite_fallback()
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()

    total_docs = 0
    total_chunks = 0

    for idx, pdf_path in enumerate(pdf_files, start=1):
        rel_path = os.path.normpath(pdf_path)
        if not force:
            cursor.execute("SELECT id FROM documents WHERE file_path = ?;", (rel_path,))
            if cursor.fetchone():
                print(f"[{idx}/{len(pdf_files)}] [SQLite] Skipping ingested file: {os.path.basename(pdf_path)}")
                continue

        print(f"[{idx}/{len(pdf_files)}] [SQLite] Parsing: {os.path.basename(pdf_path)}...")
        parsed_doc = extractor.parse_pdf(pdf_path)
        doc_meta = parsed_doc["document_metadata"]
        chunks = chunker.chunk_document(parsed_doc)
        if not chunks:
            continue

        chunk_texts = [c["chunk_text"] for c in chunks]
        embeddings = embedder.generate_batch_embeddings(chunk_texts)

        cursor.execute(
            """
            INSERT OR REPLACE INTO documents (file_name, file_path, category, entity_name, total_pages)
            VALUES (?, ?, ?, ?, ?);
            """,
            (doc_meta["file_name"], rel_path, doc_meta["category"], doc_meta["entity_name"], doc_meta.get("total_pages", 0))
        )
        doc_id = cursor.lastrowid

        for chunk, emb in zip(chunks, embeddings):
            emb_str = json.dumps(emb)
            cursor.execute(
                """
                INSERT INTO document_chunks (document_id, chunk_index, page_number, chunk_text, metadata, embedding)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (doc_id, chunk["chunk_index"], chunk["page_number"], chunk["chunk_text"], json.dumps(chunk["metadata"]), emb_str)
            )

        conn.commit()
        total_docs += 1
        total_chunks += len(chunks)

    conn.close()
    return total_docs, total_chunks

def ingest_all_documents(target_dir=DEFAULT_REPORTS_DIR, limit=None, force=False):
    if not os.path.exists(target_dir):
        print(f"[ERROR] Target directory '{target_dir}' does not exist.")
        sys.exit(1)

    pdf_files = []
    for root, _, files in os.walk(target_dir):
        for f in files:
            if f.lower().endswith(".pdf"):
                pdf_files.append(os.path.join(root, f))

    print(f"Found {len(pdf_files)} PDF document(s).")
    if limit:
        pdf_files = pdf_files[:limit]

    extractor = PDFExtractor(base_dir=target_dir)
    chunker = DocumentChunker(chunk_size=800, overlap=150)
    embedder = EmbeddingManager()

    pg_conn = connect_postgres(DB_NAME)
    if pg_conn:
        pg_conn.close()
        print("Using PostgreSQL + pgvector database backend...")
        docs, chunks = ingest_to_postgres(pdf_files, extractor, chunker, embedder, force)
    else:
        print("Using SQLite vector database backend...")
        docs, chunks = ingest_to_sqlite(pdf_files, extractor, chunker, embedder, force)

    print("\n" + "="*60)
    print("Ingestion Complete!")
    print(f"Documents Processed: {docs}")
    print(f"Chunks Stored: {chunks}")
    print("="*60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=str, default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    ingest_all_documents(target_dir=args.dir, limit=args.limit, force=args.force)
