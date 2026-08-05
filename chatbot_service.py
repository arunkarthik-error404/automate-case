"""
Long-lived HTTP front end for the agentic chatbot (v2).

The demo UI used to spawn a fresh Python process per message, so the genai client,
the embedding model and any conversation state died after every reply. This keeps one
CaseChatbotV2 alive and holds the last N messages per browser session in memory.

Nothing is retrieved before the model asks for it — this service only supplies prior
turns as context; the tools still run only when Gemini calls them.

    python chatbot_service.py          # 127.0.0.1:8765 by default

    GET  /health  -> {"status": "ready"|"degraded", "sessions": n}
    POST /chat    <- {"sessionId": "...", "prompt": "..."}
                  -> {"answer": "...", "sessionId": "...", "historyMessages": n}
    POST /reset   <- {"sessionId": "..."}   drops that session's history
"""

import json
import os
import signal
import sys
import threading
from collections import OrderedDict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from chatbot_v2 import CaseChatbotV2, log, model_turn, timed, user_turn

HOST = os.getenv("CHATBOT_HOST", "127.0.0.1")
PORT = int(os.getenv("CHATBOT_PORT", "8765"))
# Messages, not exchanges: 10 == roughly five back-and-forths. Appended in user/model
# pairs so trimming can never leave the history starting on a model turn.
HISTORY_MESSAGES = int(os.getenv("CHAT_HISTORY_MESSAGES", "10"))
MAX_SESSIONS = int(os.getenv("CHAT_MAX_SESSIONS", "200"))
MAX_BODY_BYTES = 64 * 1024

BOT = None


def _is_error_answer(answer: str) -> bool:
    """Client-facing failure strings shouldn't be remembered as real turns."""
    return answer.startswith("[Vertex AI Response Error") or answer.startswith("[Notice:")


class SessionStore:
    """Per-session conversation history. Memory only — a restart forgets everything."""

    def __init__(self, max_messages=HISTORY_MESSAGES, max_sessions=MAX_SESSIONS):
        self._max_messages = max_messages
        self._max_sessions = max_sessions
        self._sessions = OrderedDict()  # session id -> deque of types.Content
        self._locks = {}  # session id -> lock, so one session answers one at a time
        self._guard = threading.Lock()

    def _touch(self, session_id):
        """Return the session's deque, creating it and evicting the oldest if needed.

        Caller must hold `self._guard`.
        """
        if session_id in self._sessions:
            self._sessions.move_to_end(session_id)
        else:
            self._sessions[session_id] = deque(maxlen=self._max_messages)
            self._locks[session_id] = threading.Lock()
            while len(self._sessions) > self._max_sessions:
                stale, _ = self._sessions.popitem(last=False)
                self._locks.pop(stale, None)
                log("SESSION", f"evicted {stale!r} (cap {self._max_sessions})")
        return self._sessions[session_id]

    def lock_for(self, session_id):
        with self._guard:
            self._touch(session_id)
            return self._locks[session_id]

    def history(self, session_id):
        with self._guard:
            return list(self._touch(session_id))

    def record(self, session_id, prompt, answer):
        with self._guard:
            turns = self._touch(session_id)
            turns.append(user_turn(prompt))
            turns.append(model_turn(answer))
            return len(turns)

    def reset(self, session_id):
        with self._guard:
            existed = self._sessions.pop(session_id, None) is not None
            self._locks.pop(session_id, None)
            return existed

    def count(self):
        with self._guard:
            return len(self._sessions)


SESSIONS = SessionStore()


class ChatHandler(BaseHTTPRequestHandler):
    server_version = "CaseChatbot/2"
    protocol_version = "HTTP/1.1"  # every response below sets Content-Length

    # --- plumbing ---------------------------------------------------------------
    def _send(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        # HEAD carries the same headers as GET but no body
        if not getattr(self, "_head_only", False):
            self.wfile.write(body)

    def _read_json(self):
        """Return the parsed body, or None after having already sent an error."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length <= 0:
            self._send(400, {"error": "Request body required."})
            return None
        if length > MAX_BODY_BYTES:
            self._send(413, {"error": f"Body exceeds {MAX_BODY_BYTES} bytes."})
            return None
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:
            self._send(400, {"error": f"Invalid JSON body: {e}"})
            return None
        if not isinstance(data, dict):
            self._send(400, {"error": "Body must be a JSON object."})
            return None
        return data

    def log_message(self, fmt, *args):
        log("HTTP", fmt % args)

    # --- routes -----------------------------------------------------------------
    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path in ("/", "/health"):
            ready = BOT is not None and BOT.client is not None
            self._send(
                200 if ready else 503,
                {
                    "status": "ready" if ready else "degraded",
                    "sessions": SESSIONS.count(),
                    "historyMessages": HISTORY_MESSAGES,
                },
            )
        else:
            self._send(404, {"error": f"No route {path}"})

    def do_HEAD(self):
        """Health checkers probe with HEAD; without this the base class returns 501."""
        self._head_only = True
        try:
            self.do_GET()
        finally:
            self._head_only = False

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path == "/reset":
            data = self._read_json()
            if data is None:
                return
            session_id = str(data.get("sessionId") or "default").strip() or "default"
            existed = SESSIONS.reset(session_id)
            log("SESSION", f"reset {session_id!r} (existed={existed})")
            self._send(200, {"sessionId": session_id, "cleared": existed})
            return

        if path != "/chat":
            self._send(404, {"error": f"No route {path}"})
            return

        data = self._read_json()
        if data is None:
            return

        prompt = str(data.get("prompt") or "").strip()
        session_id = str(data.get("sessionId") or "default").strip() or "default"
        if not prompt:
            self._send(400, {"error": "Prompt string is required."})
            return
        if BOT is None or BOT.client is None:
            self._send(503, {"error": "Chatbot model client is not initialized."})
            return

        # One in-flight answer per session, so two fast messages from the same tab
        # can't interleave into the history. Separate sessions still run in parallel.
        with SESSIONS.lock_for(session_id):
            history = SESSIONS.history(session_id)
            log("SESSION", f"{session_id!r} sending {len(history)} prior messages")
            answer = BOT.answer_query(prompt, history=history)
            if _is_error_answer(answer):
                stored = len(history)
                log("SESSION", f"{session_id!r} not recording an error answer")
            else:
                stored = SESSIONS.record(session_id, prompt, answer)

        self._send(200, {"answer": answer, "sessionId": session_id, "historyMessages": stored})


def main():
    global BOT
    with timed("SERVICE", "CaseChatbotV2 construction"):
        BOT = CaseChatbotV2()

    server = ThreadingHTTPServer((HOST, PORT), ChatHandler)
    server.daemon_threads = True

    def shutdown(signum, _frame):
        log("SERVICE", f"signal {signum}, shutting down")
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    log(
        "SERVICE",
        f"listening on http://{HOST}:{PORT} "
        f"(history={HISTORY_MESSAGES} msgs/session, max {MAX_SESSIONS} sessions)",
    )
    print(f"Chatbot service ready on http://{HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        log("SERVICE", "stopped")


if __name__ == "__main__":
    sys.exit(main())
