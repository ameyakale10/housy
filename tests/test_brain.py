"""Brain tool-loop test with a mocked Gemini client (no network).

This covers the highest-value gap the review flagged: brain.run_turn's function-calling
loop — that a function call is dispatched (the tool actually runs), the model's text is
returned, and the candidates[0] guard / summary path don't crash.
"""
from google.genai import types

import app.brain as brain
import app.identity as identity
import app.store as store


class _FC:
    def __init__(self, name, args):
        self.name = name
        self.args = args


class _Resp:
    def __init__(self, function_calls=None, text=""):
        self.function_calls = function_calls or []
        self.text = text
        # a real model Content so contents.append(resp.candidates[0].content) works
        self.candidates = [type("C", (), {"content": types.Content(
            role="model", parts=[types.Part.from_text(text=text or "")])})()]


class _FakeClient:
    def __init__(self, scripted):
        self._scripted = scripted
        self._i = 0

        class _Models:
            def generate_content(_self, **kw):
                r = scripted[self._i]
                self._i += 1
                return r

        self.models = _Models()


def test_run_turn_dispatches_tool_and_returns_text(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    h = identity.resolve_or_create_household("+111")

    scripted = [
        _Resp(function_calls=[_FC("set_speaker_name", {"name": "Ameya"})]),  # round 1: tool
        _Resp(text="Nice to meet you, Ameya!"),                              # round 2: text
    ]
    monkeypatch.setattr(brain, "_get_client", lambda: _FakeClient(scripted))
    monkeypatch.setattr(brain, "_update_summary", lambda *a, **k: None)  # don't re-call client

    out = brain.run_turn("Hi, I'm Ameya", household_id=h, speaker_phone="+111")
    assert out["text"] == "Nice to meet you, Ameya!"
    assert "set_speaker_name" in out["wrote"]
    assert identity.member_name(h, "+111") == "Ameya"  # the tool actually executed


def test_run_turn_handles_empty_candidates(tmp_path, monkeypatch):
    """A function-call response with no candidates must not crash the turn."""
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    h = identity.resolve_or_create_household("+111")
    bad = _Resp(function_calls=[_FC("set_speaker_name", {"name": "X"})])
    bad.candidates = []  # safety-blocked / empty
    monkeypatch.setattr(brain, "_get_client", lambda: _FakeClient([bad]))
    monkeypatch.setattr(brain, "_update_summary", lambda *a, **k: None)
    out = brain.run_turn("hi", household_id=h, speaker_phone="+111")
    assert isinstance(out["text"], str)  # graceful fallback, no exception
