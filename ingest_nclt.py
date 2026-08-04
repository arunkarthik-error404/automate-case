import os
import sys
import shutil
import sqlite3

# Ensure local project modules can be imported
sys.path.insert(0, os.path.dirname(__file__))

from rag.pdf_extractor import PDFExtractor
from rag.chunker import DocumentChunker
from rag.embeddings import EmbeddingManager
from ingest_documents import ingest_to_sqlite

def run_nclt_ingestion():
    # Source PDF files from Downloads
    sources = [
        ("C:\\Users\\arunk\\Downloads\\NCLT - Sada-1.pdf", "Sada IT Parks Private Limited", "NCLT - Sada-1.pdf"),
        ("C:\\Users\\arunk\\Downloads\\NCLT - Tulip 1.pdf", "Tulip Data Services", "NCLT - Tulip 1.pdf"),
        ("C:\\Users\\arunk\\Downloads\\NCLT - Tulip 2.pdf", "Tulip Data Services", "NCLT - Tulip 2.pdf"),
    ]

    # Destination directory following Cloudflare R2 bucket structure:
    # test-case / Litigation Search / NCLT / Entities / <Entity Name> / <File Name>
    dest_base = os.path.join(
        os.path.dirname(__file__),
        "Search Reports-20260730T080443Z-1-001",
        "Search Reports",
        "Litigation Search",
        "NCLT",
        "Entities"
    )

    copied_files = []

    print("=" * 60)
    print("STEP 1: Copying NCLT PDF Files to Workspace")
    print("=" * 60)
    for src, entity_folder, filename in sources:
        if os.path.exists(src):
            target_dir = os.path.join(dest_base, entity_folder)
            os.makedirs(target_dir, exist_ok=True)
            target_path = os.path.join(target_dir, filename)
            shutil.copy2(src, target_path)
            print(f"[OK] Copied: {os.path.basename(src)} -> {target_path}")
            copied_files.append(target_path)
        else:
            print(f"[WARNING] Source file not found: {src}")

    if not copied_files:
        print("\n[ERROR] No source files found in Downloads. Ingestion aborted.")
        return

    print("\n" + "=" * 60)
    print(f"STEP 2: Parsing & Ingesting {len(copied_files)} NCLT Document(s) into DB")
    print("=" * 60)
    
    reports_base = os.path.join(
        os.path.dirname(__file__),
        "Search Reports-20260730T080443Z-1-001",
        "Search Reports"
    )
    
    extractor = PDFExtractor(base_dir=reports_base)
    chunker = DocumentChunker(chunk_size=800, overlap=150)
    embedder = EmbeddingManager()

    docs, chunks = ingest_to_sqlite(copied_files, extractor, chunker, embedder, force=True)

    print("\n" + "=" * 60)
    print("STEP 3: Database Verification")
    print("=" * 60)
    db_path = os.path.join(os.path.dirname(__file__), "case_search_local.db")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    for fpath in copied_files:
        norm_p = os.path.normpath(fpath)
        c.execute("SELECT id, file_name, category, entity_name, total_pages FROM documents WHERE file_path = ?", (norm_p,))
        row = c.fetchone()
        if row:
            print(f"[DB RECORD] Doc ID #{row[0]} | File: {row[1]} | Category: {row[2]} | Entity: {row[3]} | Pages: {row[4]}")
            c.execute("SELECT COUNT(*) FROM document_chunks WHERE document_id = ?", (row[0],))
            chk_count = c.fetchone()[0]
            print(f"            -> Stored Chunks & Vector Embeddings: {chk_count}")
    conn.close()

    print("\n[SUCCESS] All NCLT documents have been ingested successfully!")

if __name__ == "__main__":
    run_nclt_ingestion()
