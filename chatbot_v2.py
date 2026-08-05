"""
Agentic RAG chatbot (v2).

Unlike chatbot.py — which hardcodes retrieval (regex filters -> always embedding
search -> stuff every chunk into one prompt) — this version exposes retrieval as
*function-call tools* and lets Gemini decide which to call, looping via the Google
Gen AI SDK's automatic function calling until it can answer.

Tools:
  - keyword_search(term, category)   : direct SQL LIKE lookup (no embeddings)
  - semantic_search(query, top_k)    : embedding / vector search (only when needed)
  - get_entity_documents(entity_name): bulk ordered chunks for one entity (summaries)

CLI contract is identical to chatbot.py so the existing sidecar can call it unchanged:
    python chatbot_v2.py "<prompt>"
    ... diagnostics ...
    === AI CHATBOT RESPONSE ===
    <answer>
"""

import os
import sys
import json
import tempfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
from google.oauth2 import service_account

from db_search_tool import DBSearchTool
from setup_db import connect_postgres, DB_NAME, SQLITE_DB_PATH, init_sqlite_fallback

load_dotenv()

# The new SDK is required for automatic function calling. No legacy fallback in v2.
from google import genai
from google.genai import types

MAX_CHUNK_CHARS = 800  # keep each tool result token-bounded


def get_gcp_credentials():
    """Load GCP service-account credentials from env JSON, an env path, or Render secrets."""
    svc_key_json = os.getenv("GCP_SERVICE_ACCOUNT_JSON") or os.getenv("GOOGLE_CREDENTIALS_JSON")
    svc_key_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

    # If the path in the env var doesn't exist on this machine, ignore it.
    if svc_key_path and not os.path.exists(svc_key_path):
        os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
        svc_key_path = None

    if svc_key_json:
        try:
            raw_str = svc_key_json.strip()
            if (raw_str.startswith('"') and raw_str.endswith('"')) or (
                raw_str.startswith("'") and raw_str.endswith("'")
            ):
                raw_str = raw_str[1:-1].strip()

            try:
                info = json.loads(raw_str)
            except Exception:
                info = json.loads(raw_str.replace("\\n", "\n"))

            if isinstance(info, str):
                info = json.loads(info)

            if "private_key" in info and isinstance(info["private_key"], str):
                info["private_key"] = info["private_key"].replace("\\n", "\n")

            tmp_file = os.path.join(tempfile.gettempdir(), "gcp_service_account.json")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(info, f)

            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = tmp_file
            creds = service_account.Credentials.from_service_account_info(
                info, scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            print(f"[AUTH SUCCESS] Loaded GCP service account for '{info.get('client_email')}' via env var.")
            return creds
        except Exception as e:
            print(f"[AUTH ERROR] Failed to parse GCP_SERVICE_ACCOUNT_JSON env var: {e}")

    # Render Secret Files live under /etc/secrets/
    render_secret = "/etc/secrets/gcp-service.json"
    if not svc_key_path and os.path.exists(render_secret):
        svc_key_path = render_secret

    if not svc_key_path and os.path.exists("/etc/secrets"):
        for f in os.listdir("/etc/secrets"):
            if f.endswith(".json"):
                svc_key_path = os.path.join("/etc/secrets", f)
                break

    if svc_key_path and os.path.exists(svc_key_path):
        try:
            creds = service_account.Credentials.from_service_account_file(
                svc_key_path, scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = svc_key_path
            print(f"[AUTH SUCCESS] Loaded GCP service account from file '{svc_key_path}'.")
            return creds
        except Exception as e:
            print(f"[AUTH ERROR] Failed to load GCP service account from file '{svc_key_path}': {e}")

    return None


SYSTEM_INSTRUCTION = r"""
You are an expert legal & financial research analyst specializing in Indian corporate
(ROC/MCA), litigation, and asset-search reports. You answer questions about a database
of such reports by calling the provided search tools — you do NOT have the data in
context until you retrieve it.

TOOL ROUTING:
- Use `keyword_search` FIRST when the query names a specific person or entity, or
  contains distinctive exact strings (company names, case numbers, father's name). It
  is a precise SQL substring match and cheaper than embeddings.
- Use `semantic_search` for vague, conceptual, or paraphrased queries, or as a fallback
  when `keyword_search` returns nothing useful.
- Use `get_entity_documents` when the user asks for a summary/overview/report of a
  specific entity — it returns that entity's document chunks in order.
- Call multiple tools if needed. Do not fabricate; if the tools return nothing relevant,
  say no matching records were found.

FORMATTING & RESPONSE GUIDELINES:
1. Direct executive summary: jump straight into the factual answer. No filler like
   "Here is a summary...".
2. Party identification & disambiguation: inspect party headers carefully (e.g.
   "Between: [Target Person], S/o [Father Name], Petitioner/Plaintiff/Respondent"). If
   the target person is explicitly listed with their father's name (e.g. G. Janardhan
   Reddy, S/o Late G. Ram Reddy), confirm their presence, role, case number, court,
   date, and relief sought.
3. Co-party recognition: co-respondents or family members sharing the same father's
   name (e.g. brothers) are co-parties in the same proceeding. Do NOT claim a document
   is solely about someone else if the target person is named as a primary party.
4. Clean section hierarchy: organize into clear `###` sections (e.g. `### Entity
   Details`, `### Filings & Charges`, `### Litigation & Legal Actions`,
   `### CERSAI / Asset Search`).
5. Concise bullets: present key fields as bullet points
   (`* **Party Name:** ...`, `* **Father's Name:** ...`).
6. Grouped source citations: list the source PDF file(s) at the end of each section
   (e.g. `📄 **Source File:** \`filename.pdf\``).
7. Completeness: report all dates, amounts, case numbers, courts, and parties present
   in the retrieved chunks accurately.
""".strip()


def _truncate(text: str, limit: int = MAX_CHUNK_CHARS) -> str:
    if text and len(text) > limit:
        return text[:limit] + " …[truncated]"
    return text or ""


def _keyword_search_rows(term: str, category: str):
    """Run the LIKE query against Postgres if available, else the SQLite fallback."""
    like = f"%{term}%"
    cat_like = f"%{category}%" if category else None

    pg_conn = connect_postgres(DB_NAME)
    if pg_conn:
        cur = pg_conn.cursor()
        sql = """
            SELECT d.file_name, d.entity_name, d.category, c.page_number, c.chunk_text
            FROM document_chunks c JOIN documents d ON c.document_id = d.id
            WHERE (d.entity_name ILIKE %s OR d.file_name ILIKE %s OR c.chunk_text ILIKE %s)
              {cat_clause}
              AND LENGTH(c.chunk_text) > 40
            ORDER BY d.file_name ASC, c.page_number ASC, c.chunk_index ASC
            LIMIT 15;
        """.format(cat_clause="AND d.category ILIKE %s" if cat_like else "")
        params = [like, like, like] + ([cat_like] if cat_like else [])
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        pg_conn.close()
        return rows

    init_sqlite_fallback()
    import sqlite3
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cur = conn.cursor()
    sql = """
        SELECT d.file_name, d.entity_name, d.category, c.page_number, c.chunk_text
        FROM document_chunks c JOIN documents d ON c.document_id = d.id
        WHERE (d.entity_name LIKE ? OR d.file_name LIKE ? OR c.chunk_text LIKE ?)
          {cat_clause}
          AND LENGTH(c.chunk_text) > 40
        ORDER BY d.file_name ASC, c.page_number ASC, c.chunk_index ASC
        LIMIT 15;
    """.format(cat_clause="AND d.category LIKE ?" if cat_like else "")
    params = [like, like, like] + ([cat_like] if cat_like else [])
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return rows


class CaseChatbotV2:
    """Agentic RAG chatbot: Gemini drives retrieval via automatic function calling."""

    def __init__(self):
        self.search_tool = DBSearchTool()
        self.client = None

        project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "eco-seeker-458712-i8")
        location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "true").lower() == "true"
        api_key = os.getenv("GEMINI_API_KEY")
        creds = get_gcp_credentials()

        try:
            if creds:
                print(f"Initializing Gemini Client via Vertex AI Service Account (Project: {project_id})...")
                self.client = genai.Client(vertexai=True, project=project_id, location=location, credentials=creds)
            elif api_key:
                print("Initializing Gemini Client via API Key...")
                self.client = genai.Client(api_key=api_key)
            elif use_vertex:
                print(f"Attempting Gemini Client via default Vertex AI ADC (Project: {project_id})...")
                self.client = genai.Client(vertexai=True, project=project_id, location=location)
        except Exception as e:
            print(f"GenAI Client initialization notice: {e}")

    # --- Tools ------------------------------------------------------------------
    # Defined as closures so they capture self.search_tool while presenting the clean
    # signature the SDK turns into a FunctionDeclaration (type hints + docstring).

    def _build_tools(self):
        search_tool = self.search_tool

        def keyword_search(term: str, category: str = "") -> dict:
            """Direct database keyword search using SQL substring (LIKE) matching over
            entity names, file names, and chunk text. Use this FIRST for specific named
            people or entities and exact strings; it does not use embeddings.

            Args:
                term: The name or exact substring to search for (e.g. "GVR Electro" or
                    "Janardhan Reddy").
                category: Optional category filter, e.g. "ROC Search", "Litigation Search".
            """
            print(f"[TOOL] keyword_search(term={term!r}, category={category!r})")
            try:
                rows = _keyword_search_rows(term, category)
                results = [
                    {
                        "file_name": r[0],
                        "entity_name": r[1],
                        "category": r[2],
                        "page_number": r[3],
                        "chunk_text": _truncate(r[4]),
                    }
                    for r in rows
                ]
                return {"results": results, "count": len(results)}
            except Exception as e:
                return {"results": [], "error": str(e)}

        def semantic_search(query: str, top_k: int = 10) -> dict:
            """Embedding / vector similarity search over document chunks. Use for vague,
            conceptual, or paraphrased queries, or as a fallback when keyword_search
            returns nothing useful.

            Args:
                query: The natural-language query to embed and match semantically.
                top_k: Maximum number of chunks to return (default 10).
            """
            print(f"[TOOL] semantic_search(query={query!r}, top_k={top_k})")
            try:
                chunks = search_tool.search_similar_chunks(query=query, top_k=top_k)
                results = [
                    {
                        "file_name": c["file_name"],
                        "entity_name": c["entity_name"],
                        "page_number": c["page_number"],
                        "chunk_text": _truncate(c["chunk_text"]),
                        "score": c.get("similarity_score"),
                    }
                    for c in chunks
                ]
                return {"results": results, "count": len(results)}
            except Exception as e:
                return {"results": [], "error": str(e)}

        def get_entity_documents(entity_name: str) -> dict:
            """Retrieve a specific entity's document chunks in reading order (page then
            chunk index). Use when the user asks for a summary, overview, or full report
            of one named entity.

            Args:
                entity_name: The entity or file name to pull documents for.
            """
            print(f"[TOOL] get_entity_documents(entity_name={entity_name!r})")
            try:
                chunks = search_tool.get_document_chunks_for_summary(entity_name, max_chunks=25)
                results = [
                    {
                        "file_name": c["file_name"],
                        "entity_name": c["entity_name"],
                        "category": c["category"],
                        "page_number": c["page_number"],
                        "chunk_text": _truncate(c["chunk_text"]),
                    }
                    for c in chunks
                ]
                return {"results": results, "count": len(results)}
            except Exception as e:
                return {"results": [], "error": str(e)}

        return [keyword_search, semantic_search, get_entity_documents]

    # --- Query ------------------------------------------------------------------
    def answer_query(self, user_query: str) -> str:
        """Answer a query by letting Gemini call the search tools (automatic FC)."""
        print(f"\n[QUERY] {user_query}")

        if not self.client:
            return (
                "[Notice: Gemini client not initialized. Set GCP service-account "
                "credentials or GEMINI_API_KEY to enable the agentic chatbot.]"
            )

        model_name = os.getenv("VERTEX_MODEL", "gemini-2.5-flash")
        config = types.GenerateContentConfig(
            tools=self._build_tools(),
            system_instruction=SYSTEM_INSTRUCTION,
        )

        try:
            response = self.client.models.generate_content(
                model=model_name,
                contents=user_query,
                config=config,
            )
            return response.text or "No answer produced."
        except Exception as e:
            return f"[Vertex AI Response Error: {e}]"


if __name__ == "__main__":
    bot = CaseChatbotV2()
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
        ans = bot.answer_query(prompt)
        print("\n=== AI CHATBOT RESPONSE ===")
        print(ans)
    else:
        print("\nAgentic Case Search Chatbot (v2) Ready.")
        print("Example queries:")
        print(" - python chatbot_v2.py 'details about G Janardhan Reddy son of Gurumurthy Reddy'")
        print(" - python chatbot_v2.py 'summary of ROC search for GVR ELECTRO TECHNICS'")
