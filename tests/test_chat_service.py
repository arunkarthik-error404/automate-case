"""
End-to-end checks for the agentic chatbot service, run against a stubbed genai SDK.

No network, no Google credentials, no real model. The stub in `tests/stubs/google/genai`
records exactly what the chatbot sent and lets each test decide whether the "model"
calls a tool. That is what makes "nothing is retrieved unless the model asks" testable.

    python tests/test_chat_service.py
"""

import json
import os
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Stubs must precede the real packages (and the project root) on the path.
sys.path.insert(0, os.path.join(ROOT, "tests", "stubs"))
sys.path.insert(1, ROOT)

os.environ.setdefault("CHATBOT_DEBUG", "0")  # keep test output readable
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")

from google import genai  # noqa: E402  (stub)

import chatbot_service as svc  # noqa: E402
import rag.embeddings as embeddings  # noqa: E402

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name} — {detail}")
        FAILURES.append(name)


def post(port, path, payload):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def start_service():
    """Build the bot and serve on an ephemeral port (main() would install signals)."""
    svc.BOT = svc.CaseChatbotV2()
    server = ThreadingHTTPServer(("127.0.0.1", 0), svc.ChatHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def main():
    genai.reset()
    server, port = start_service()
    print(f"service on 127.0.0.1:{port}\n")

    print("health")
    status, body = get(port, "/health")
    check("health reports ready", status == 200 and body["status"] == "ready", body)

    print("\nno retrieval unless the model asks")
    check(
        "embedding model not loaded at startup",
        embeddings._MANAGER is None,
        "EmbeddingManager was constructed before any search",
    )
    status, body = post(port, "/chat", {"sessionId": "a", "prompt": "HI"})
    check("greeting answered", status == 200 and body["answer"] == "stub answer", body)
    check("no tool ran for a greeting", genai.TOOL_CALLS == [], genai.TOOL_CALLS)
    check(
        "embedding model still not loaded",
        embeddings._MANAGER is None,
        "a greeting loaded the embedding model",
    )
    check(
        "first call sent one turn",
        genai.RECORDED[-1]["roles"] == ["user"],
        genai.RECORDED[-1]["roles"],
    )
    check(
        "all three tools were offered",
        set(genai.RECORDED[-1]["tools"])
        == {"keyword_search", "semantic_search", "get_entity_documents"},
        genai.RECORDED[-1]["tools"],
    )

    print("\nconversation history")
    status, body = post(port, "/chat", {"sessionId": "a", "prompt": "and the second one?"})
    check(
        "second call carries the first exchange",
        genai.RECORDED[-1]["roles"] == ["user", "model", "user"],
        genai.RECORDED[-1]["roles"],
    )
    check(
        "history holds the original prompt",
        genai.RECORDED[-1]["texts"][0] == "HI",
        genai.RECORDED[-1]["texts"],
    )
    check("history counted", body["historyMessages"] == 4, body)

    print("\nsessions are isolated")
    status, body = post(port, "/chat", {"sessionId": "b", "prompt": "fresh tab"})
    check(
        "new session starts empty",
        genai.RECORDED[-1]["roles"] == ["user"],
        genai.RECORDED[-1]["roles"],
    )
    check("session b history is its own", body["historyMessages"] == 2, body)

    print(f"\nhistory trims to {svc.HISTORY_MESSAGES} messages")
    for i in range(8):
        _, body = post(port, "/chat", {"sessionId": "a", "prompt": f"msg {i}"})
    check(
        f"capped at {svc.HISTORY_MESSAGES}",
        body["historyMessages"] == svc.HISTORY_MESSAGES,
        body,
    )
    sent_roles = genai.RECORDED[-1]["roles"]
    check(
        "trimmed history still starts on a user turn",
        sent_roles[0] == "user",
        sent_roles,
    )
    check(
        "sent history stays bounded",
        len(sent_roles) == svc.HISTORY_MESSAGES + 1,
        len(sent_roles),
    )

    print("\ntools run only when the model calls them")
    genai.TOOL_QUEUE.append(("keyword_search", {"term": "GVR", "category": ""}))
    status, body = post(port, "/chat", {"sessionId": "c", "prompt": "tell me about GVR"})
    check("keyword_search executed on request", genai.TOOL_CALLS == ["keyword_search"], genai.TOOL_CALLS)
    check(
        "keyword search alone does not load embeddings",
        embeddings._MANAGER is None,
        "keyword_search loaded the embedding model",
    )

    genai.TOOL_QUEUE.append(("semantic_search", {"query": "asset disputes", "top_k": 3}))
    status, body = post(port, "/chat", {"sessionId": "c", "prompt": "anything similar?"})
    check("semantic_search executed on request", "semantic_search" in genai.TOOL_CALLS, genai.TOOL_CALLS)
    check(
        "embedding model loaded lazily on first semantic search",
        embeddings._MANAGER is not None,
        "semantic_search did not load the embedding model",
    )
    loaded = embeddings._MANAGER
    embeddings.get_embedding_manager()
    check("embedding manager is a process-wide singleton", embeddings._MANAGER is loaded)

    print("\nfailures are not remembered")
    _, before = post(port, "/chat", {"sessionId": "d", "prompt": "first"})
    genai.RAISE_NEXT.append(True)
    status, body = post(port, "/chat", {"sessionId": "d", "prompt": "this one explodes"})
    check("model error surfaces as an answer", body["answer"].startswith("[Vertex AI Response Error"), body)
    check(
        "failed turn not written to history",
        body["historyMessages"] == before["historyMessages"],
        (before, body),
    )

    print("\nrequest validation and reset")
    status, body = post(port, "/chat", {"sessionId": "d", "prompt": "   "})
    check("blank prompt rejected", status == 400, (status, body))
    status, body = post(port, "/reset", {"sessionId": "d"})
    check("reset clears the session", status == 200 and body["cleared"] is True, body)
    _, body = post(port, "/chat", {"sessionId": "d", "prompt": "after reset"})
    check("history restarts after reset", body["historyMessages"] == 2, body)
    status, body = post(port, "/nope", {})
    check("unknown route 404s", status == 404, (status, body))

    server.shutdown()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed: {', '.join(FAILURES)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
