"""
Tests for services/ai_analyzer.py

No test here makes a real API call. Real calls cost money, need a key,
and fail when the network is down - none of which belongs in a test
suite. We stub requests.post instead and check how our code reacts.
"""

import json
import pytest
import requests

from services import ai_analyzer as ai
from services.ai_analyzer import (
    redact_personal_data, extract_json, analyze_resume, LLMError,
)

VALID_REPLY = {
    "summary": "A solid fresher resume.",
    "strengths": ["Clear sections", "Real metrics"],
    "weaknesses": ["Too short"],
    "missing_skills": ["Kubernetes"],
    "weak_bullets": [{"original": "Built a thing",
                      "improved": "Built a thing serving [NUMBER] users",
                      "why": "Adds a measurable outcome."}],
    "generic_statements": ["hardworking"],
    "suggestions": ["Add metrics"],
    "professional_summary": "CSE graduate with backend experience.",
    "action_verbs": ["Engineered"],
    "keywords": ["REST API"],
}

# A markdown code fence, built rather than typed, so the backticks do
# not confuse any editor or shell that reads this file.
FENCE = "`" * 3


class FakeResponse:
    """Stands in for a requests.Response object."""

    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


@pytest.fixture
def fake_openai(monkeypatch):
    """
    Point the OpenAI provider at a stub.

    monkeypatch is pytest's built-in tool for temporarily replacing
    something. It puts the original back after the test, so one test can
    never leak a stub into another.
    """
    def _install(status_code=200, content=None, exception=None,
                 payload_override=None):
        monkeypatch.setenv("AI_ENABLED", "true")
        monkeypatch.setenv("AI_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")

        def fake_post(url, headers=None, json=None, timeout=None):
            # The key must NEVER end up in a URL, where it would be
            # written to proxy and server access logs.
            assert "sk-test-not-a-real-key" not in url
            if exception:
                raise exception
            if payload_override is not None:
                return FakeResponse(status_code, payload_override)
            return FakeResponse(
                status_code,
                {"choices": [{"message": {"content": content}}]})

        monkeypatch.setattr(ai.requests, "post", fake_post)
    return _install


class TestRedaction:
    """Personal data must not leave the server."""

    def test_removes_email_phone_and_links(self):
        text = ("Contact priya.v99@example.com or +91-98400-12345, "
                "see github.com/priyav and priyabuilds.dev")
        out = redact_personal_data(text)
        assert "@" not in out
        assert "98400" not in out
        assert "priyav" not in out
        assert "priyabuilds" not in out

    def test_bare_domain_is_redacted(self):
        """Regression: a portfolio with no /path used to slip through."""
        assert redact_personal_data("priyabuilds.dev") == "[LINK]"

    def test_keeps_everything_that_matters_for_judging_quality(self):
        for keep in ["B.Tech / M.Tech", "Node.js and React.js",
                     "CGPA: 8.7 / 10",
                     "Reduced query time by 40% for 1200 students",
                     "Anna University, 2022 - 2026"]:
            assert redact_personal_data(keep) == keep


class TestJsonExtraction:
    def test_plain_json(self):
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_markdown_fenced_json(self):
        fenced = FENCE + 'json\n{"a": 1}\n' + FENCE
        assert extract_json(fenced) == {"a": 1}

    def test_json_surrounded_by_chatter(self):
        assert extract_json('Sure! {"a": 1} Hope that helps.') == {"a": 1}

    def test_raises_on_rubbish(self):
        with pytest.raises(LLMError):
            extract_json("no json here at all")

    def test_raises_on_empty(self):
        with pytest.raises(LLMError):
            extract_json("")


class TestSuccessPath:
    def test_uses_the_ai_reply(self, fake_openai, parsed_good, ats_good,
                               good_text):
        fake_openai(content=json.dumps(VALID_REPLY))
        result = analyze_resume(parsed_good, ats_good, good_text)
        assert result["source"] == "ai"
        assert result["strengths"] == ["Clear sections", "Real metrics"]
        assert len(result["weak_bullets"]) == 1

    def test_copes_with_wrong_types(self, fake_openai, parsed_good,
                                    ats_good, good_text):
        """
        A model can return a string where we expect a list. That must
        produce sensible output, not a 500 error page.
        """
        fake_openai(content=json.dumps({
            "summary": 123,
            "strengths": "just one string",
            "weaknesses": None,
            "missing_skills": [{"skill": "Docker"}],
            "suggestions": [1, 2, "real tip"],
        }))
        result = analyze_resume(parsed_good, ats_good, good_text)
        assert result["source"] == "ai"
        assert result["strengths"] == ["just one string"]
        assert result["missing_skills"] == ["Docker"]
        assert result["suggestions"] == ["real tip"]


class TestFallback:
    """
    Every failure must fall back to rule-based advice, never raise.
    analyze_resume() is the one function in the project that promises it
    can never throw.
    """

    @pytest.mark.parametrize("label,kwargs", [
        ("bad key",        {"status_code": 401, "payload_override": {"e": 1}}),
        ("rate limited",   {"status_code": 429, "payload_override": {"e": 1}}),
        ("server error",   {"status_code": 500, "payload_override": {"e": 1}}),
        ("reply not json", {"content": "this is not json"}),
        ("odd body shape", {"payload_override": {"unexpected": "shape"}}),
        ("timeout",        {"exception": requests.exceptions.Timeout()}),
        ("no internet",    {"exception": requests.exceptions.ConnectionError()}),
    ])
    def test_falls_back_without_raising(self, label, kwargs, fake_openai,
                                        parsed_good, ats_good, good_text):
        fake_openai(**kwargs)
        result = analyze_resume(parsed_good, ats_good, good_text)
        assert result["source"] == "offline", label
        assert result["message"], "the user should be told why"
        assert result["suggestions"], "offline advice is still useful advice"

    def test_ai_disabled_uses_rules(self, monkeypatch, parsed_good,
                                    ats_good, good_text):
        monkeypatch.setenv("AI_ENABLED", "false")
        assert analyze_resume(parsed_good, ats_good,
                              good_text)["source"] == "offline"

    def test_unknown_provider_uses_rules(self, monkeypatch, parsed_good,
                                         ats_good, good_text):
        monkeypatch.setenv("AI_ENABLED", "true")
        monkeypatch.setenv("AI_PROVIDER", "not-a-real-provider")
        assert analyze_resume(parsed_good, ats_good,
                              good_text)["source"] == "offline"

    def test_missing_key_uses_rules(self, monkeypatch, parsed_good,
                                    ats_good, good_text):
        monkeypatch.setenv("AI_ENABLED", "true")
        monkeypatch.setenv("AI_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "")
        assert analyze_resume(parsed_good, ats_good,
                              good_text)["source"] == "offline"


class TestOfflineQuality:
    def test_spots_cliches(self, monkeypatch, parsed_good, ats_good):
        monkeypatch.setenv("AI_ENABLED", "false")
        text = "I am a hardworking team player and a quick learner."
        result = analyze_resume(parsed_good, ats_good, text)
        assert len(result["generic_statements"]) >= 2

    def test_always_returns_every_key(self, monkeypatch, parsed_good,
                                      ats_good, good_text):
        monkeypatch.setenv("AI_ENABLED", "false")
        result = analyze_resume(parsed_good, ats_good, good_text)
        for key in ("summary", "strengths", "weaknesses", "missing_skills",
                    "weak_bullets", "generic_statements", "suggestions",
                    "professional_summary", "action_verbs", "keywords",
                    "source", "provider", "model"):
            assert key in result, key
