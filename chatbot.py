import os
import sys
import re

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
from db_search_tool import DBSearchTool

load_dotenv()

import tempfile
from google.oauth2 import service_account

def get_gcp_credentials():
    svc_key_json = os.getenv("GCP_SERVICE_ACCOUNT_JSON") or os.getenv("GOOGLE_CREDENTIALS_JSON")
    svc_key_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

    # If local path in env var doesn't exist on this machine, clean it up
    if svc_key_path and not os.path.exists(svc_key_path):
        os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
        svc_key_path = None

    if svc_key_json:
        try:
            raw_str = svc_key_json.strip()
            if (raw_str.startswith('"') and raw_str.endswith('"')) or (raw_str.startswith("'") and raw_str.endswith("'")):
                raw_str = raw_str[1:-1].strip()
            
            try:
                info = json.loads(raw_str)
            except Exception:
                fixed_str = raw_str.replace('\\n', '\n')
                info = json.loads(fixed_str)

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
            print(f"[AUTH SUCCESS] Loaded GCP service account credentials for '{info.get('client_email')}' via env var.")
            return creds
        except Exception as e:
            print(f"[AUTH ERROR] Failed to parse GCP_SERVICE_ACCOUNT_JSON env var: {e}")

    # Check for Render Secret Files at /etc/secrets/
    render_secret = "/etc/secrets/gcp-service.json"
    if not svc_key_path and os.path.exists(render_secret):
        svc_key_path = render_secret

    if not svc_key_path:
        for f in os.listdir("/etc/secrets") if os.path.exists("/etc/secrets") else []:
            if f.endswith(".json"):
                svc_key_path = os.path.join("/etc/secrets", f)
                break

    if svc_key_path and os.path.exists(svc_key_path):
        try:
            creds = service_account.Credentials.from_service_account_file(
                svc_key_path, scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = svc_key_path
            print(f"[AUTH SUCCESS] Loaded GCP service account credentials from file '{svc_key_path}'.")
            return creds
        except Exception as e:
            print(f"[AUTH ERROR] Failed to load GCP service account from file '{svc_key_path}': {e}")

    return None

gcp_credentials = get_gcp_credentials()

try:
    from google import genai
    GENAI_NEW_SDK = True
except ImportError:
    GENAI_NEW_SDK = False

try:
    import google.generativeai as genai_legacy
    GENAI_LEGACY_SDK = True
except ImportError:
    GENAI_LEGACY_SDK = False

class CaseChatbot:
    """AI Chatbot integrating PostgreSQL + pgvector vector search with LLM generation."""

    def __init__(self):
        self.search_tool = DBSearchTool()
        self.client = None
        self.legacy_model = None

        project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "eco-seeker-458712-i8")
        location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "true").lower() == "true"
        api_key = os.getenv("GEMINI_API_KEY")

        if GENAI_NEW_SDK:
            try:
                if gcp_credentials:
                    print(f"Initializing Gemini Client via Vertex AI Service Account (Project: {project_id})...")
                    self.client = genai.Client(
                        vertexai=True,
                        project=project_id,
                        location=location,
                        credentials=gcp_credentials
                    )
                elif api_key:
                    print("Initializing Gemini Client via API Key...")
                    self.client = genai.Client(api_key=api_key)
                elif use_vertex:
                    print(f"Attempting Gemini Client via default Vertex AI ADC (Project: {project_id})...")
                    self.client = genai.Client(
                        vertexai=True,
                        project=project_id,
                        location=location
                    )
            except Exception as e:
                print(f"GenAI Client initialization notice: {e}")

        if not self.client and GENAI_LEGACY_SDK and api_key:
            try:
                genai_legacy.configure(api_key=api_key)
                self.legacy_model = genai_legacy.GenerativeModel("gemini-2.5-flash")
            except Exception as e:
                print(f"Legacy GenAI model initialization notice: {e}")

    def extract_filters_from_query(self, query: str):
        """Extract father name or state filters from natural language user prompt."""
        father_name = None
        state = None

        father_match = re.search(r'(?:son of|s/o|father[\'s]*)\s*([A-Za-z]+(?:\s+[A-Za-z]+){0,2})', query, re.IGNORECASE)
        if father_match:
            father_name = father_match.group(1).strip()

        states = ['Karnataka', 'Telangana', 'Andhra Pradesh', 'Maharashtra', 'Delhi', 'Tamil Nadu', 'Kerala', 'Gujarat']
        for st in states:
            if re.search(r'\b' + re.escape(st) + r'\b', query, re.IGNORECASE):
                state = st
                break

        return father_name, state

    def answer_query(self, user_query: str) -> str:
        """Processes user query, searches pgvector DB, and generates AI answer."""
        is_summary_request = any(kw in user_query.lower() for kw in ["summary", "summarize", "overview", "report"])
        father_name, state = self.extract_filters_from_query(user_query)

        print(f"\n[QUERY] {user_query}")
        if father_name or state:
            print(f"[METADATA FILTER] Father Name: {father_name} | State: {state}")

        if is_summary_request:
            entity_match = re.search(r'summary of\s+(.+)', user_query, re.IGNORECASE)
            raw_key = entity_match.group(1).strip() if entity_match else user_query
            entity_key = re.sub(r'^(?:ROC search for|litigation search for|search for|about|details of)\s+', '', raw_key, flags=re.IGNORECASE).strip()
            chunks = self.search_tool.get_document_chunks_for_summary(entity_key, max_chunks=20)
            if not chunks or len(chunks) < 3:
                chunks = self.search_tool.search_similar_chunks(user_query, top_k=10)
        else:
            chunks = self.search_tool.search_similar_chunks(
                query=user_query,
                top_k=8,
                father_name=father_name,
                state=state
            )

        if not chunks:
            return "No matching records or chunks found in the database for your query."

        context_str = ""
        for i, chk in enumerate(chunks, start=1):
            context_str += f"\n--- Chunk {i} (File: {chk['file_name']}, Page: {chk['page_number']}, Entity: {chk['entity_name']}) ---\n"
            context_str += chk['chunk_text'] + "\n"

        system_prompt = f"""
You are an expert legal & financial research analyst specializing in Indian corporate (ROC/MCA), litigation, and asset search reports.
Answer the user's query accurately using ONLY the provided database context chunks below.

CRITICAL INSTRUCTIONS FOR SUMMARIES:
1. DO NOT produce a meta-list of filenames or page numbers (e.g. DO NOT say "Found in File X on Page Y").
2. Synthesize and report the ACTUAL FACTUAL CONTENTS inside the documents, including:
   - **Entity Details**: Company/LLP Name, LLPIN/CIN, Incorporation Date, Registered Address, Main Business Activity.
   - **Partners / Directors**: Designated Partners, Directors, DINs, Shares/Contribution details.
   - **Financials & Solvency**: Small LLP status, Turnover, Total Contribution/Capital, Assets, Solvency declarations.
   - **Filings & Charges**: Key details from Form 11 (Annual Returns), Form 8 (Solvency & Charge Creations/Modifications).
   - **Litigation & Legal Actions**: Case numbers, courts, parties, and status if litigation chunks are present.
3. If specific information (e.g. exact turnover or charge amount) is not stated in the chunks, explicitly state what is available and what is omitted.
4. Under each section or case finding, include a reference tag with the exact document file name so the user knows which PDF to open (e.g. 📄 **Source File:** `file_name.pdf`).

Database Context Chunks:
{context_str}

User Question: {user_query}
"""

        model_name = os.getenv("VERTEX_MODEL", "gemini-2.5-flash")

        if self.client:
            try:
                response = self.client.models.generate_content(
                    model=model_name,
                    contents=system_prompt
                )
                return response.text
            except Exception as e:
                return f"[Vertex AI Response Error: {e}]\n\nDirect Database Context Retrieved:\n{context_str}"
        elif self.legacy_model:
            try:
                response = self.legacy_model.generate_content(system_prompt)
                return response.text
            except Exception as e:
                return f"[LLM Response Error: {e}]\n\nDirect Database Context Retrieved:\n{context_str}"
        else:
            return f"[Notice: Service Account / Gemini API client not initialized. Displaying Database Context Directly]\n{context_str}"

if __name__ == "__main__":
    bot = CaseChatbot()
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
        ans = bot.answer_query(prompt)
        print("\n=== AI CHATBOT RESPONSE ===")
        print(ans)
    else:
        print("\nCase Search AI Chatbot Ready.")
        print("Example queries:")
        print(" - python chatbot.py 'can you tell me the details about the g janarthan reddy son of gurumurthy reddy'")
        print(" - python chatbot.py 'summary of ROC search for GVR ELECTRO TECHNICS'")
