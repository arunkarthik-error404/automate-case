"""
Scriptable stand-in for the google-genai client.

Tests drive it through the module-level knobs below: queue a tool the "model" should
call, or an exception it should raise, then inspect what the chatbot actually sent.
"""

from . import types  # noqa: F401  (re-exported the way the real package is)

RECORDED = []  # one entry per generate_content call: {"roles": [...], "texts": [...]}
TOOL_QUEUE = []  # (tool_name, kwargs) the model should invoke on the next call
TOOL_CALLS = []  # tool names actually executed, in order
RAISE_NEXT = []  # push anything to make the next call blow up
REPLY = ["stub answer"]  # mutable so tests can change the reply text


def reset():
    RECORDED.clear()
    TOOL_QUEUE.clear()
    TOOL_CALLS.clear()
    RAISE_NEXT.clear()
    REPLY[:] = ["stub answer"]


class _Usage:
    prompt_token_count = 100
    candidates_token_count = 20
    total_token_count = 120


class _Candidate:
    def __init__(self, text):
        self.content = types.Content(role="model", parts=[types.Part(text=text)])
        self.finish_reason = "STOP"


class _Response:
    def __init__(self, text):
        self.text = text
        self.candidates = [_Candidate(text)]
        self.automatic_function_calling_history = []
        self.function_calls = []
        self.usage_metadata = _Usage()


class _Models:
    def generate_content(self, model=None, contents=None, config=None):
        turns = list(contents or [])
        RECORDED.append(
            {
                "model": model,
                "roles": [getattr(c, "role", "?") for c in turns],
                "texts": [getattr(c, "text", "") for c in turns],
                "tools": [t.__name__ for t in getattr(config, "tools", [])],
            }
        )

        if RAISE_NEXT:
            RAISE_NEXT.pop(0)
            raise RuntimeError("stub model failure")

        while TOOL_QUEUE:
            name, kwargs = TOOL_QUEUE.pop(0)
            fn = next(t for t in config.tools if t.__name__ == name)
            fn(**kwargs)
            TOOL_CALLS.append(name)

        return _Response(REPLY[0])


class Client:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.models = _Models()
