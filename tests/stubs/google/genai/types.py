"""Minimal stand-ins for the genai content types the chatbot builds."""


class Part:
    def __init__(self, text=None):
        self.text = text
        self.function_call = None

    def __repr__(self):
        return f"Part({self.text!r})"


class Content:
    def __init__(self, role=None, parts=None):
        self.role = role
        self.parts = parts or []

    @property
    def text(self):
        return "".join(p.text or "" for p in self.parts)

    def __repr__(self):
        return f"Content({self.role!r}, {self.text!r})"


class GenerateContentConfig:
    def __init__(self, tools=None, system_instruction=None):
        self.tools = tools or []
        self.system_instruction = system_instruction
