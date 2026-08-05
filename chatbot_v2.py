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

Retrieval is never run up front — `answer_query` sends the prompt (plus any prior turns
it is given) straight to the model, and a tool executes only if the model calls it.

The demo UI talks to `chatbot_service.py`, which keeps one of these alive and owns the
per-session history. This CLI stays for debugging and is stateless:

    python chatbot_v2.py "<prompt>"
    ... diagnostics ...
    === AI CHATBOT RESPONSE ===
    <answer>
"""

import os
import sys
import json
import time
import tempfile
import traceback
from contextlib import contextmanager

_T0 = time.perf_counter()  # set before the heavy imports so we can time them too

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# --- Diagnostics -----------------------------------------------------------------
# Logs go to stderr by default so they never pollute the answer the sidecar scrapes.
# Set CHATBOT_LOG_STREAM=stdout to surface them in the demo UI's rawOutput instead.
# Set CHATBOT_DEBUG=0 to silence them.
DEBUG = os.getenv("CHATBOT_DEBUG", "1").lower() not in ("0", "false", "no")
_LOG_STREAM = sys.stdout if os.getenv("CHATBOT_LOG_STREAM") == "stdout" else sys.stderr


def log(stage: str, msg: str = "") -> None:
    """Timestamped boundary log: [ 12.34s] [STAGE] message."""
    if not DEBUG:
        return
    print(f"[{time.perf_counter() - _T0:7.2f}s] [{stage}] {msg}", file=_LOG_STREAM, flush=True)


@contextmanager
def timed(stage: str, msg: str = ""):
    """Log entry/exit of a step with its own duration, and never swallow the error."""
    log(stage, f"START {msg}")
    t = time.perf_counter()
    try:
        yield
    except Exception as e:
        log(stage, f"FAILED after {time.perf_counter() - t:.2f}s: {type(e).__name__}: {e}")
        raise
    else:
        log(stage, f"DONE in {time.perf_counter() - t:.2f}s {msg}")


log("BOOT", f"python={sys.version.split()[0]} pid={os.getpid()} cwd={os.getcwd()}")

with timed("IMPORT", "dotenv + google.oauth2"):
    from dotenv import load_dotenv
    from google.oauth2 import service_account

# NOTE: importing db_search_tool pulls in numpy/psycopg2/fastembed's module graph.
with timed("IMPORT", "db_search_tool + setup_db"):
    from db_search_tool import DBSearchTool
    from setup_db import connect_postgres, DB_NAME, SQLITE_DB_PATH, init_sqlite_fallback

with timed("ENV", ".env load"):
    load_dotenv()

# The new SDK is required for automatic function calling. No legacy fallback in v2.
with timed("IMPORT", "google.genai"):
    from google import genai
    from google.genai import types

MAX_CHUNK_CHARS = 800  # keep each tool result token-bounded


def get_gcp_credentials():
    """Load GCP service-account credentials from env JSON, an env path, or Render secrets."""
    svc_key_json = os.getenv("GCP_SERVICE_ACCOUNT_JSON") or os.getenv(
        "GOOGLE_CREDENTIALS_JSON"
    )
    svc_key_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    log(
        "AUTH",
        f"env json={'set' if svc_key_json else 'unset'} "
        f"path={svc_key_path or 'unset'}",
    )

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
            print(
                f"[AUTH SUCCESS] Loaded GCP service account for '{info.get('client_email')}' via env var."
            )
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
        log("AUTH", f"loading service account file '{svc_key_path}'")
        try:
            creds = service_account.Credentials.from_service_account_file(
                svc_key_path, scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = svc_key_path
            print(
                f"[AUTH SUCCESS] Loaded GCP service account from file '{svc_key_path}'."
            )
            return creds
        except Exception as e:
            print(
                f"[AUTH ERROR] Failed to load GCP service account from file '{svc_key_path}': {e}"
            )

    log("AUTH", "no service-account credentials found (will try API key / ADC)")
    return None


SYSTEM_INSTRUCTION = r"""
You are an expert legal & financial research analyst specializing in Indian corporate
(ROC/MCA), litigation, and asset-search reports. You answer questions about a database
of such reports by calling the provided search tools — you do NOT have the data in
context until you retrieve it.

WHEN TO RETRIEVE AT ALL:
- No search runs unless you call one. Greetings, small talk, questions about what you
  can do, and follow-ups already answered earlier in this conversation are answered
  directly — do NOT call a tool for them.
- Reach for a tool only when the user wants report data you do not already have in the
  conversation.

TOOL ROUTING (once you have decided retrieval is needed):
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
2. Entity & Person Disambiguation:
   - When multiple records match a query, inspect party headers, father's names, company
     CINs, PAN numbers, addresses, and designations carefully.
   - Create dedicated sections for EVERY distinct individual or entity identified in
     the retrieved records (e.g. grouped by Father's Name, Unique Entity Name, or CIN).
   - NEVER omit or collapse distinct individuals or entities that share a similar name.
3. Co-party & Family Relationship Recognition:
   - Recognize co-respondents, co-petitioners, or family members sharing the same father
     or family name as co-parties in the same proceeding.
   - Accurately report each party's specific role (Petitioner, Respondent, Objector,
     Guarantor, Charge Holder, Borrower).
4. Clean section hierarchy: organize into clear `###` sections (e.g. `### [Entity / Person Name]`,
   `### Filings & Charges`, `### Litigation & Legal Actions`, `### CERSAI / Asset Search`).
5. Concise bullets: present key fields as bullet points (`* **Party Name:** ...`,
   `* **Father's Name:** ...`, `* **Case Status:** ...`, `* **Amount:** ...`).
6. Grouped source citations: list the source PDF file(s) at the end of each section
   (e.g. `📄 **Source File:** \`filename.pdf\``).
7. Completeness: report all dates, amounts, case numbers, courts, and parties present
   in the retrieved chunks accurately without omitting matching records.
""".strip()


def user_turn(text: str):
    """A user message as SDK content, for building conversation history."""
    return types.Content(role="user", parts=[types.Part(text=text)])


def model_turn(text: str):
    """A model reply as SDK content, for building conversation history."""
    return types.Content(role="model", parts=[types.Part(text=text)])


def _truncate(text: str, limit: int = MAX_CHUNK_CHARS) -> str:
    if text and len(text) > limit:
        return text[:limit] + " …[truncated]"
    return text or ""


def _keyword_search_rows(term: str, category: str):
    """Run tokenized substring query against Postgres if available, else SQLite fallback."""
    import re
    STOP_WORDS = {
        'summary', 'search', 'report', 'reports', 'details', 'info', 'information', 
        'show', 'get', 'give', 'find', 'the', 'for', 'a', 'an', 'of', 'in', 'c/w', 
        'and', 'all', 'cases', 'case', 'related', 'to', 'me', 'please', 'can', 'you'
    }
    tokens = [t for t in re.findall(r'\b[A-Za-z0-9]+\b', term) if t.lower() not in STOP_WORDS]
    if not tokens:
        tokens = [term]

    if category:
        cat_lower = category.lower().strip()
        if "asset" in cat_lower:
            cat_like = "%asset%"
        elif "debtor" in cat_lower:
            cat_like = "%debtor%"
        elif "roc" in cat_lower:
            cat_like = "%roc%"
        elif "litigation" in cat_lower:
            cat_like = "%litigation%"
        else:
            cat_like = f"%{category}%"
    else:
        cat_like = None

    t = time.perf_counter()
    pg_conn = connect_postgres(DB_NAME)
    log(
        "DB",
        f"connect_postgres -> {'connected' if pg_conn else 'unavailable, using sqlite'} "
        f"({time.perf_counter() - t:.2f}s)",
    )
    if pg_conn:
        cur = pg_conn.cursor()
        where_clauses = []
        pg_params = []
        for tok in tokens:
            t_like = f"%{tok}%"
            where_clauses.append("(d.entity_name ILIKE %s OR d.file_name ILIKE %s OR c.chunk_text ILIKE %s OR d.category ILIKE %s)")
            pg_params.extend([t_like, t_like, t_like, t_like])

        token_sql = " AND ".join(where_clauses)
        cat_sql = " AND d.category ILIKE %s" if cat_like else ""
        if cat_like:
            pg_params.append(cat_like)

        sql = f"""
            WITH RankedChunks AS (
                SELECT d.file_name, d.entity_name, d.category, c.page_number, c.chunk_text,
                       ROW_NUMBER() OVER(PARTITION BY d.file_name ORDER BY c.page_number ASC, c.chunk_index ASC) as rn
                FROM document_chunks c JOIN documents d ON c.document_id = d.id
                WHERE {token_sql} {cat_sql}
                  AND LENGTH(c.chunk_text) > 40
            )
            SELECT file_name, entity_name, category, page_number, chunk_text
            FROM RankedChunks
            WHERE rn <= 2
            ORDER BY file_name ASC
            LIMIT 50;
        """
        cur.execute(sql, pg_params)
        rows = cur.fetchall()
        cur.close()
        pg_conn.close()
        return rows

    init_sqlite_fallback()
    import sqlite3

    conn = sqlite3.connect(SQLITE_DB_PATH)
    cur = conn.cursor()
    where_clauses = []
    sq_params = []
    for tok in tokens:
        t_like = f"%{tok}%"
        where_clauses.append("(d.entity_name LIKE ? OR d.file_name LIKE ? OR c.chunk_text LIKE ? OR d.category LIKE ?)")
        sq_params.extend([t_like, t_like, t_like, t_like])

    token_sql = " AND ".join(where_clauses)
    cat_sql = " AND d.category LIKE ?" if cat_like else ""
    if cat_like:
        sq_params.append(cat_like)

    sql = f"""
        WITH RankedChunks AS (
            SELECT d.file_name, d.entity_name, d.category, c.page_number, c.chunk_text,
                   ROW_NUMBER() OVER(PARTITION BY d.file_name ORDER BY c.page_number ASC, c.chunk_index ASC) as rn
            FROM document_chunks c JOIN documents d ON c.document_id = d.id
            WHERE {token_sql} {cat_sql}
              AND LENGTH(c.chunk_text) > 40
        )
        SELECT file_name, entity_name, category, page_number, chunk_text
        FROM RankedChunks
        WHERE rn <= 2
        ORDER BY file_name ASC
        LIMIT 50;
    """
    cur.execute(sql, sq_params)
    rows = cur.fetchall()
    conn.close()
    return rows


class CaseChatbotV2:
    """Agentic RAG chatbot: Gemini drives retrieval via automatic function calling."""

    def __init__(self):
        # Cheap: DBSearchTool resolves its EmbeddingManager lazily, so the ONNX model
        # only loads if semantic_search is actually called (and then only once per process).
        with timed("INIT", "DBSearchTool"):
            self.search_tool = DBSearchTool()
        self.client = None

        project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "eco-seeker-458712-i8")
        location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "true").lower() == "true"
        api_key = os.getenv("GEMINI_API_KEY")
        log(
            "INIT",
            f"project={project_id} location={location} use_vertex={use_vertex} "
            f"api_key={'set' if api_key else 'unset'} "
            f"model={os.getenv('VERTEX_MODEL', 'gemini-2.5-flash')}",
        )

        with timed("INIT", "get_gcp_credentials"):
            creds = get_gcp_credentials()

        t = time.perf_counter()
        try:
            if creds:
                print(
                    f"Initializing Gemini Client via Vertex AI Service Account (Project: {project_id})..."
                )
                self.client = genai.Client(
                    vertexai=True,
                    project=project_id,
                    location=location,
                    credentials=creds,
                )
            elif api_key:
                print("Initializing Gemini Client via API Key...")
                self.client = genai.Client(api_key=api_key)
            elif use_vertex:
                print(
                    f"Attempting Gemini Client via default Vertex AI ADC (Project: {project_id})..."
                )
                self.client = genai.Client(
                    vertexai=True, project=project_id, location=location
                )
        except Exception as e:
            print(f"GenAI Client initialization notice: {e}")
            log("INIT", f"client init FAILED: {type(e).__name__}: {e}")

        log(
            "INIT",
            f"genai client {'ready' if self.client else 'NOT created'} "
            f"({time.perf_counter() - t:.2f}s)",
        )

    # --- Tools ------------------------------------------------------------------
    # Defined as closures so they capture self.search_tool while presenting the clean
    # signature the SDK turns into a FunctionDeclaration (type hints + docstring).

    def _build_tools(self):
        # A fresh tool per query: DBSearchTool keeps per-search scratch state
        # (`_cached_query_vec`), which two concurrent sessions would otherwise clobber.
        # Cheap now that the embedding model is a lazy process-wide singleton.
        search_tool = DBSearchTool()

        def keyword_search(term: str, category: str = "") -> dict:
            """Direct database keyword search using SQL substring (LIKE) matching over
            entity names, file names, and chunk text. Use this FIRST for specific named
            people or entities and exact strings; it does not use embeddings.

            Args:
                term: The name or exact substring to search for (e.g. "GVR Electro" or
                    "Janardhan Reddy").
                category: Optional category filter, e.g. "ROC Search", "Litigation Search".
            """
            log("TOOL", f"keyword_search(term={term!r}, category={category!r})")
            t = time.perf_counter()
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
                log(
                    "TOOL",
                    f"keyword_search -> {len(results)} rows ({time.perf_counter() - t:.2f}s)",
                )
                return {"results": results, "count": len(results)}
            except Exception as e:
                log("TOOL", f"keyword_search ERROR: {type(e).__name__}: {e}")
                return {"results": [], "error": str(e)}

        def semantic_search(query: str, top_k: int = 10) -> dict:
            """Embedding / vector similarity search over document chunks. Use for vague,
            conceptual, or paraphrased queries, or as a fallback when keyword_search
            returns nothing useful.

            Args:
                query: The natural-language query to embed and match semantically.
                top_k: Maximum number of chunks to return (default 10).
            """
            log("TOOL", f"semantic_search(query={query!r}, top_k={top_k})")
            t = time.perf_counter()
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
                log(
                    "TOOL",
                    f"semantic_search -> {len(results)} chunks ({time.perf_counter() - t:.2f}s)",
                )
                return {"results": results, "count": len(results)}
            except Exception as e:
                log("TOOL", f"semantic_search ERROR: {type(e).__name__}: {e}")
                return {"results": [], "error": str(e)}

        def get_entity_documents(entity_name: str) -> dict:
            """Retrieve a specific entity's document chunks in reading order (page then
            chunk index). Use when the user asks for a summary, overview, or full report
            of one named entity.

            Args:
                entity_name: The entity or file name to pull documents for.
            """
            log("TOOL", f"get_entity_documents(entity_name={entity_name!r})")
            t = time.perf_counter()
            try:
                chunks = search_tool.get_document_chunks_for_summary(
                    entity_name, max_chunks=25
                )
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
                log(
                    "TOOL",
                    f"get_entity_documents -> {len(results)} chunks "
                    f"({time.perf_counter() - t:.2f}s)",
                )
                return {"results": results, "count": len(results)}
            except Exception as e:
                log("TOOL", f"get_entity_documents ERROR: {type(e).__name__}: {e}")
                return {"results": [], "error": str(e)}

        return [keyword_search, semantic_search, get_entity_documents]

    # --- Query ------------------------------------------------------------------
    def answer_query(self, user_query: str, history=None) -> str:
        """Answer a query by letting Gemini call the search tools (automatic FC).

        `history` is an optional list of prior `types.Content` turns (see
        `user_turn` / `model_turn`). It is sent as leading context so the model can
        answer follow-ups without retrieving anything. Nothing is retrieved unless
        the model itself calls a tool.
        """
        print(f"\n[QUERY] {user_query}")
        log("QUERY", f"{user_query!r} ({len(user_query)} chars, history={len(history or [])} turns)")

        if not self.client:
            log("QUERY", "ABORT: no genai client")
            return (
                "[Notice: Gemini client not initialized. Set GCP service-account "
                "credentials or GEMINI_API_KEY to enable the agentic chatbot.]"
            )

        model_name = os.getenv("VERTEX_MODEL", "gemini-2.5-flash")
        tools = self._build_tools()
        config = types.GenerateContentConfig(
            tools=tools,
            system_instruction=SYSTEM_INSTRUCTION,
        )
        contents = list(history or []) + [user_turn(user_query)]
        log(
            "MODEL",
            f"generate_content model={model_name} contents={len(contents)} turns "
            f"tools=[{', '.join(t.__name__ for t in tools)}] (automatic FC on)",
        )

        t = time.perf_counter()
        try:
            response = self.client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config,
            )
        except Exception as e:
            log("MODEL", f"FAILED after {time.perf_counter() - t:.2f}s: {type(e).__name__}: {e}")
            if DEBUG:
                traceback.print_exc(file=_LOG_STREAM)
                _LOG_STREAM.flush()
            return f"[Vertex AI Response Error: {e}]"

        log("MODEL", f"responded in {time.perf_counter() - t:.2f}s")
        self._log_response(response)
        text = response.text or ""
        if not text.strip():
            log("MODEL", "WARNING: response.text is empty -> returning placeholder")
        return text or "No answer produced."

    @staticmethod
    def _log_response(response) -> None:
        """Explain WHY a response is empty/slow: FC round-trips, finish reason, tokens."""
        if not DEBUG:
            return
        try:
            history = getattr(response, "automatic_function_calling_history", None) or []
            log("MODEL", f"automatic FC history entries: {len(history)}")

            calls = getattr(response, "function_calls", None) or []
            if calls:
                # Pending calls here mean the SDK stopped before executing them.
                log("MODEL", f"UNEXECUTED function_calls: {[c.name for c in calls]}")

            for i, cand in enumerate(getattr(response, "candidates", None) or []):
                parts = getattr(getattr(cand, "content", None), "parts", None) or []
                kinds = [
                    "fn:" + p.function_call.name
                    if getattr(p, "function_call", None)
                    else (f"text:{len(p.text)}" if getattr(p, "text", None) else "other")
                    for p in parts
                ]
                log(
                    "MODEL",
                    f"candidate[{i}] finish_reason={getattr(cand, 'finish_reason', None)} "
                    f"parts={kinds}",
                )

            usage = getattr(response, "usage_metadata", None)
            if usage:
                log(
                    "MODEL",
                    f"tokens prompt={getattr(usage, 'prompt_token_count', None)} "
                    f"candidates={getattr(usage, 'candidates_token_count', None)} "
                    f"total={getattr(usage, 'total_token_count', None)}",
                )
        except Exception as e:
            log("MODEL", f"response introspection failed: {type(e).__name__}: {e}")


if __name__ == "__main__":
    with timed("MAIN", "CaseChatbotV2 construction"):
        bot = CaseChatbotV2()
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
        ans = bot.answer_query(prompt)
        log("MAIN", f"answer {len(ans)} chars; total wall clock {time.perf_counter() - _T0:.2f}s")
        print("\n=== AI CHATBOT RESPONSE ===")
        print(ans)
    else:
        print("\nAgentic Case Search Chatbot (v2) Ready.")
        print("Example queries:")
        print(
            " - python chatbot_v2.py 'details about G Janardhan Reddy son of Gurumurthy Reddy'"
        )
        print(
            " - python chatbot_v2.py 'summary of ROC search for GVR ELECTRO TECHNICS'"
        )
