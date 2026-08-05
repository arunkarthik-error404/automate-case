"""
Database Deduplication Utility
Removes duplicate document records (and their corresponding chunks) that share the same file_name,
keeping only the earliest ingested record.
Supports both PostgreSQL and SQLite.
"""

import sqlite3
import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from setup_db import SQLITE_DB_PATH, DB_NAME, connect_postgres

def deduplicate_sqlite():
    if not os.path.exists(SQLITE_DB_PATH):
        print(f"SQLite database not found at '{SQLITE_DB_PATH}'. Skipping.")
        return

    print(f"Deduplicating SQLite database at '{SQLITE_DB_PATH}'...")
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON;")

    cur.execute("SELECT id FROM documents WHERE id NOT IN (SELECT MIN(id) FROM documents GROUP BY file_name);")
    dup_ids = [r[0] for r in cur.fetchall()]

    if dup_ids:
        print(f"Found {len(dup_ids)} duplicate document records. Cleaning...")
        cur.executemany("DELETE FROM document_chunks WHERE document_id = ?;", [(i,) for i in dup_ids])
        cur.executemany("DELETE FROM documents WHERE id = ?;", [(i,) for i in dup_ids])
        conn.commit()
        print(f"Successfully deleted {len(dup_ids)} duplicate documents and their chunks.")
    else:
        print("SQLite database is already clean (0 duplicate documents found).")

    conn.close()

def deduplicate_postgres():
    pg_conn = connect_postgres(DB_NAME)
    if not pg_conn:
        print("PostgreSQL connection unavailable. Skipping PostgreSQL deduplication.")
        return

    print("Deduplicating PostgreSQL database...")
    try:
        cur = pg_conn.cursor()
        sql = """
            DELETE FROM documents
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM documents
                GROUP BY file_name
            );
        """
        cur.execute(sql)
        deleted_count = cur.rowcount
        pg_conn.commit()
        cur.close()
        pg_conn.close()
        print(f"Successfully deduplicated PostgreSQL: deleted {deleted_count} duplicate document records.")
    except Exception as e:
        print(f"PostgreSQL deduplication error: {e}")
        if pg_conn:
            pg_conn.close()

if __name__ == "__main__":
    print("=== STARTING DATABASE DEDUPLICATION ===")
    deduplicate_sqlite()
    deduplicate_postgres()
    print("=== DEDUPLICATION COMPLETE ===")
