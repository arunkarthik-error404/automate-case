import os
import sys
import sqlite3
import subprocess
import time
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")
DB_NAME = os.getenv("POSTGRES_DB", "case_search_db")
DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "postgres")
SQLITE_DB_PATH = os.path.join(os.path.dirname(__file__), "case_search_local.db")

def connect_postgres(db_name=None):
    target_db = db_name if db_name else DB_NAME
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=target_db,
            user=DB_USER,
            password=DB_PASS,
            connect_timeout=3
        )
        return conn
    except Exception:
        return None

def init_sqlite_fallback():
    print(f"Initializing local database engine at '{SQLITE_DB_PATH}'...")
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name TEXT NOT NULL,
            file_path TEXT NOT NULL UNIQUE,
            category TEXT,
            entity_name TEXT,
            total_pages INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS document_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            page_number INTEGER NOT NULL,
            chunk_text TEXT NOT NULL,
            metadata TEXT DEFAULT '{}',
            embedding TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    conn.commit()
    conn.close()
    print("Local database schema ready.")

def init_database():
    print(f"Checking PostgreSQL connection at {DB_HOST}:{DB_PORT}...")
    conn = connect_postgres("postgres")
    
    if conn:
        conn.autocommit = True
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s;", (DB_NAME,))
        if not cursor.fetchone():
            cursor.execute(f'CREATE DATABASE "{DB_NAME}";')
        cursor.close()
        conn.close()

        conn = connect_postgres(DB_NAME)
        conn.autocommit = True
        cursor = conn.cursor()
        schema_path = os.path.join(os.path.dirname(__file__), "database", "schema.sql")
        with open(schema_path, "r", encoding="utf-8") as f:
            cursor.execute(f.read())
        print("PostgreSQL + pgvector schema initialized successfully!")
        cursor.close()
        conn.close()
    else:
        print("PostgreSQL server not directly reachable. Activating local SQLite database backend.")
        init_sqlite_fallback()

if __name__ == "__main__":
    init_database()
