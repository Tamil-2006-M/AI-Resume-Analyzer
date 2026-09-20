"""
services/ai_analyzer.py
=======================
Job of this file: ask a Large Language Model (LLM) to review the resume
and return structured, actionable feedback.

What the rule-based code CANNOT do
----------------------------------
Phases 3 and 4 can count skills and check that a Projects section exists.
They cannot judge whether the sentence

    "Was responsible for handling the database"

is a weak way to describe real work. That needs language understanding,
and that is exactly what an LLM is good at. So we use each tool for what
it is best at:

    rules  -> counting, matching, scoring   (fast, free, never wrong)
    LLM    -> judgement, rewriting, advice  (slow, costs money, creative)

Three things this module is careful about
-----------------------------------------
1. THE API KEY IS NEVER IN THE CODE.
   It is read from the .env file through os.getenv(). The key is never
   logged, never returned to the browser, and never put in a URL.

2. PERSONAL DATA IS REDACTED BEFORE IT LEAVES YOUR SERVER.
   The LLM does not need the candidate's email or phone number to judge
   writing quality, so we replace them with placeholders first. Sending
   less personal data to a third party is simply good practice.

3. THE APP STILL WORKS WITH NO API KEY.
   If no key is configured, or the API call fails, we fall back to a
   rule-based "offline" analysis. The user always gets useful feedback,
   and you can demo the project without paying for anything.

Swapping the provider
---------------------
Each provider is a small class with one method: generate().
To switch providers you change ONE line in .env:

    AI_PROVIDER=openai      (default)
    AI_PROVIDER=anthropic
    AI_PROVIDER=gemini
    AI_PROVIDER=ollama      (runs locally, completely free)

No other file changes. That is the "modular AI integration" the project
specification asked for.
"""

import os
import re
import json
import logging
import time

import requests

from services.skills_data import ACTION_VERBS

logger = logging.getLogger(__name__)


# =====================================================================
# PART 1 - CONFIGURATION (all from .env, nothing hardcoded)
# =====================================================================

def _env(name, default=""):
    """Read an environment variable and strip stray spaces/quotes."""
    return os.getenv(name, default).strip().strip('"').strip("'")


# How long we wait for the API before giving up, in seconds.
# Too short and slow-but-working requests fail; too long and the user
# stares at a spinner. 45 seconds is a reasonable middle ground.
AI_TIMEOUT = int(_env("AI_TIMEOUT", "45") or 45)

# How much of the resume text we send. Sending the whole thing costs more
# tokens (= more money) with very little benefit - a resume is short.
MAX_RESUME_CHARS = 6000


# =====================================================================
# PART 2 - PRIVACY: REDACT PERSONAL DETAILS
# =====================================================================

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(
    r"(?:\+?\d{1,3}[\s.-]?)?"      # country code:  +91 / 91 / +1
    r"(?:\(\d{2,4}\)[\s.-]?)?"     # bracketed area code:  (555)
    r"\d{3,5}[\s.-]?\d{3,5}"       # the main body
    r"(?:[\s.-]?\d{2,4})?"         # optional third group
)
# Two shapes of link, joined with "|" (meaning "or"):
#
#   1. anything starting with http:// or www.      -> always a link
#   2. a bare domain like "priyabuilds.dev"        -> also a link
#
# Shape 2 needs care. An earlier version of this pattern required a "/"
# after the domain, so a portfolio written as a bare "priyabuilds.dev"
# was sent to the AI un-redacted. The test caught it.
#
# The {3,} and the fixed list of endings stop us from redacting things
# that merely look like domains:
#     "B.Tech"   -> "B" is only 1 character  -> not touched
#     "Node.js"  -> ".js" is not in the list -> not touched
_URL_RE = re.compile(
    r"(?:https?://|www\.)[^\s,;)\]]+"
    r"|"
    r"\b[A-Za-z0-9-]{3,}\.(?:com|in|dev|io|me|net|org|tech|app|co|edu|ai)\b"
    r"(?:/[^\s,;)\]]*)?",
    re.IGNORECASE)


def redact_personal_data(text):
    """
    Replace contact details with placeholders before sending to the API.

    "Call me on +91 98765 43210"  ->  "Call me on [PHONE]"

    The LLM is being asked about writing quality, not about who the
    person is, so it loses nothing. We keep the placeholders (rather than
    deleting the text) so the model can still see that a phone number
    exists - useful if it wants to comment on the contact section.
    """
    if not text:
        return ""

    redacted = _EMAIL_RE.sub("[EMAIL]", text)
    redacted = _URL_RE.sub("[LINK]", redacted)

    # Phone numbers are replaced last, because the phone pattern would
    # otherwise chew up the digits inside URLs and email addresses.
    def _replace_phone(match):
        digits = re.sub(r"\D", "", match.group())
        return "[PHONE]" if 10 <= len(digits) <= 13 else match.group()

    redacted = _PHONE_RE.sub(_replace_phone, redacted)
    return redacted


# =====================================================================
# PART 3 - BUILDING THE PROMPT
# =====================================================================

# The "system prompt" sets the model's role and rules. Keeping it
# separate from the data makes it easy to tune the behaviour.
SYSTEM_PROMPT = """You are an experienced technical recruiter and resume \
coach who reviews resumes for entry-level software roles in India.

Your job is to give specific, honest, actionable feedback that a student \
can apply in 30 minutes.

Rules you must follow:
- Be specific. "Add measurable results to your projects" is useless. \
"Change 'Built a library system' to 'Built a library system managing \
5,000+ book records for 300 students'" is useful.
- Never invent facts about the candidate. If the resume does not say how \
many users a project had, do not make a number up - instead show the \
pattern with a placeholder like [NUMBER].
- Quote the candidate's real wording when you criticise something.
- Be encouraging but do not flatter. A weak resume must be told it is weak.
- Reply with valid JSON only. No markdown, no code fences, no commentary."""


# The exact shape we want back. Showing the model a schema is far more
# reliable than describing it in prose.
JSON_SCHEMA_HINT = """{
  "summary": "2-3 sentence honest overall verdict",
  "strengths": ["3-5 specific things this resume does well"],
  "weaknesses": ["3-5 specific problems, each naming what to fix"],
  "missing_skills": ["5-8 skills this candidate should learn or add"],
  "weak_bullets": [
    {
      "original": "the exact weak line copied from the resume",
      "improved": "your rewritten version",
      "why": "one short sentence explaining the change"
    }
  ],
  "generic_statements": ["cliched phrases found, quoted exactly"],
  "suggestions": ["5-7 concrete improvement actions, most important first"],
  "professional_summary": "a 2-3 sentence summary the candidate can paste \
at the top of their resume, written in first person without 'I'",
  "action_verbs": ["8-10 strong verbs this candidate should use"],
  "keywords": ["8-12 ATS keywords worth adding for their target role"]
}"""


def build_resume_digest(parsed, ats, resume_text):
    """
    Turn our analysis into a compact briefing for the model.

    Why not just send the raw resume?
    Because the model then has to redo all the work we already did. Giving
    it our structured findings (skills found, sections missing, score
    breakdown) means it can focus on judgement instead of extraction -
    better answers, fewer tokens, lower cost.

    We send BOTH the digest and the (redacted, trimmed) raw text, because
    the model needs the original wording to quote and rewrite bullets.
    """
    contact = parsed["contact"]
    skills = parsed["skills"]

    # Which contact details exist - as yes/no, not as actual values.
    contact_summary = ", ".join(
        f"{field}={'yes' if contact.get(field) else 'NO'}"
        for field in ("name", "email", "phone", "linkedin", "github")
    )

    present = [s["label"] for s in parsed["sections"]["present"]]
    missing = [s["label"] for s in parsed["sections"]["missing"]]

    skill_lines = [
        f"  {category}: {', '.join(items)}"
        for category, items in skills["by_category"].items()
    ] or ["  (none recognised)"]

    score_lines = [
        f"  {c['label']}: {c['score']}/{c['max']}"
        for c in (ats["categories"] if ats else [])
    ]

    digest = f"""RESUME ANALYSIS DATA
====================
Contact fields present: {contact_summary}

Sections present: {', '.join(present) or 'none'}
Sections missing: {', '.join(missing) or 'none'}

Technical skills detected ({skills['technical_count']}):
{chr(10).join(skill_lines)}

Soft skills detected: {', '.join(skills['soft']) or 'none'}

Counts: {parsed['projects']['count']} project lines, \
{parsed['certifications']['count']} certifications, \
{parsed['experience']['count']} experience lines, \
{parsed['achievements']['count']} achievements

Writing signals: {parsed['stats']['word_count']} words, \
{parsed['stats']['bullet_count']} bullets, \
{parsed['stats']['action_verb_count']} distinct action verbs, \
{parsed['stats']['quantified_count']} numbers used

Our rule-based ATS score: {ats['total'] if ats else 'n/a'}/100
{chr(10).join(score_lines)}"""

    return digest


def build_user_prompt(parsed, ats, resume_text, job_description=""):
    """
    Assemble the full message sent to the model.

    Order matters: instructions first, then data, then the required output
    format last. Models follow the final instruction most reliably.
    """
    digest = build_resume_digest(parsed, ats, resume_text)

    # Redact, then trim. Trimming first could cut a phone number in half
    # and leave the first six digits in the text.
    safe_text = redact_personal_data(resume_text)[:MAX_RESUME_CHARS]

    job_block = ""
    if job_description:
        job_block = f"""

TARGET JOB DESCRIPTION
======================
{job_description[:2000]}

Take this job description into account: your missing_skills and keywords
should be the ones this specific job asks for."""

    return f"""Review the resume below and return your feedback as JSON.

{digest}

RESUME TEXT (contact details have been replaced with placeholders)
==================================================================
{safe_text}{job_block}

Return ONLY a JSON object with exactly this shape:
{JSON_SCHEMA_HINT}

Include 2-4 entries in weak_bullets, copying the "original" text exactly
as it appears in the resume above. If the resume genuinely has no weak
bullets, return an empty list rather than inventing one."""


# =====================================================================
# PART 4 - THE PROVIDERS
# =====================================================================
# Every provider is a class with the same generate() method. Because the
# rest of the file only ever calls provider.generate(...), swapping one
# for another changes nothing else. This is "polymorphism", and it is the
# textbook reason object-oriented design exists.

class LLMError(Exception):
    """Raised when we cannot get an answer from the model."""


class BaseProvider:
    """
    The contract every provider must fulfil.

    name            - shown in the UI
    is_configured() - do we have what we need to call it?
    generate()      - send the prompt, return the model's raw text
    """

    name = "base"
    model = ""

    def is_configured(self):
        raise NotImplementedError

    def generate(self, system_prompt, user_prompt):
        raise NotImplementedError

    def _post(self, url, headers, payload):
        """
        Shared HTTP logic: send the request, convert failures into LLMError.

        Every provider's errors end up looking the same to the rest of the
        program, so app.py only needs to handle one exception type.
        """
        for attempt in range(3):
            try:
                response = requests.post(url, headers=headers, json=payload,
                                         timeout=AI_TIMEOUT)
            except requests.exceptions.Timeout as error:
                raise LLMError(
                    f"The AI service did not respond within {AI_TIMEOUT} seconds."
                ) from error
            except requests.exceptions.ConnectionError as error:
                raise LLMError(
                    "Could not reach the AI service. Check your internet "
                    "connection."
                ) from error
            except requests.exceptions.RequestException as error:
                raise LLMError("The AI request failed.") from error

            if response.status_code != 503 or attempt == 2:
                break
            time.sleep(1 << attempt)

        if response.status_code == 401 or response.status_code == 403:
            raise LLMError("The AI API key was rejected. Check your .env file.")
        if response.status_code == 429:
            raise LLMError("The AI service is rate limiting us, or the "
                           "account is out of credit. Try again shortly.")
        if response.status_code >= 400:
            # We log the body for ourselves but never show it to the user -
            # provider error bodies can echo back request details.
            logger.error("%s API error %s: %s", self.name,
                         response.status_code, response.text[:400])
            raise LLMError("The AI service returned an error.")

        try:
            return response.json()
        except ValueError as error:
            raise LLMError("The AI service returned an unreadable reply.") \
                from error


class OpenAIProvider(BaseProvider):
    """
    OpenAI Chat Completions API.

    response_format={"type": "json_object"} is JSON mode: the API
    guarantees the reply parses as JSON, which removes a whole class of
    "the model wrapped it in ```json" bugs.
    """

    name = "openai"
    URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self):
        self.api_key = _env("OPENAI_API_KEY")
        self.model = _env("OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini"

    def is_configured(self):
        return bool(self.api_key)

    def generate(self, system_prompt, user_prompt):
        data = self._post(
            self.URL,
            headers={
                # The key goes in a header, never in the URL, so it can
                # never end up in a server access log.
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            payload={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                # Low temperature = consistent, factual answers.
                # High temperature would make the advice creative but
                # unreliable, which is wrong for this use case.
                "temperature": 0.3,
                "response_format": {"type": "json_object"},
            },
        )
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as error:
            raise LLMError("Unexpected reply format from OpenAI.") from error


class AnthropicProvider(BaseProvider):
    """
    Anthropic Messages API (Claude).

    Anthropic has no JSON mode flag, so we use "prefilling": we start the
    assistant's turn with "{". The model then has no choice but to
    continue the JSON object, and we add the "{" back afterwards.
    """

    name = "anthropic"
    URL = "https://api.anthropic.com/v1/messages"

    def __init__(self):
        self.api_key = _env("ANTHROPIC_API_KEY")
        self.model = (_env("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
                      or "claude-haiku-4-5-20251001")

    def is_configured(self):
        return bool(self.api_key)

    def generate(self, system_prompt, user_prompt):
        data = self._post(
            self.URL,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            payload={
                "model": self.model,
                "max_tokens": 2000,
                "temperature": 0.3,
                "system": system_prompt,
                "messages": [
                    {"role": "user", "content": user_prompt},
                    {"role": "assistant", "content": "{"},
                ],
            },
        )
        try:
            return "{" + data["content"][0]["text"]
        except (KeyError, IndexError) as error:
            raise LLMError("Unexpected reply format from Anthropic.") from error


class GeminiProvider(BaseProvider):
    """
    Google Gemini API.

    Note: Google's docs often show the key as a "?key=" URL parameter.
    We use the x-goog-api-key HEADER instead, because anything in a URL
    can end up written to proxy logs and browser history.
    """

    name = "gemini"
    BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self):
        self.api_key = _env("GEMINI_API_KEY")
        self.model = _env("GEMINI_MODEL", "gemini-2.0-flash") or "gemini-2.0-flash"

    def is_configured(self):
        return bool(self.api_key)

    def generate(self, system_prompt, user_prompt):
        data = self._post(
            f"{self.BASE}/{self.model}:generateContent",
            headers={
                "x-goog-api-key": self.api_key,
                "Content-Type": "application/json",
            },
            payload={
                "system_instruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"parts": [{"text": user_prompt}]}],
                "generationConfig": {
                    "temperature": 0.3,
                    "responseMimeType": "application/json",
                },
            },
        )
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as error:
            raise LLMError("Unexpected reply format from Gemini.") from error


class OllamaProvider(BaseProvider):
    """
    Ollama - runs an open model on your OWN computer.

    No API key, no internet, no cost. Perfect for a college demo when you
    do not want to pay for an API. Install from https://ollama.com then:

        ollama pull llama3.2

    The trade-off is quality: a small local model gives noticeably weaker
    advice than a hosted one.
    """

    name = "ollama"

    def __init__(self):
        self.base_url = _env("OLLAMA_BASE_URL",
                             "http://localhost:11434") or "http://localhost:11434"
        self.model = _env("OLLAMA_MODEL", "llama3.2") or "llama3.2"

    def is_configured(self):
        # Ollama needs no key, but it must actually be running.
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=3)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False

    def generate(self, system_prompt, user_prompt):
        data = self._post(
            f"{self.base_url}/api/chat",
            headers={"Content-Type": "application/json"},
            payload={
                "model": self.model,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.3},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        try:
            return data["message"]["content"]
        except KeyError as error:
            raise LLMError("Unexpected reply format from Ollama.") from error


# The registry. Adding a fifth provider means writing one class and
# adding one line here.
PROVIDERS = {
    "openai":    OpenAIProvider,
    "anthropic": AnthropicProvider,
    "gemini":    GeminiProvider,
    "ollama":    OllamaProvider,
}


def get_provider():
    """
    Build the provider named in .env.

    Returns None if AI is switched off or the name is unknown, so the
    caller can fall back to the offline analysis.
    """
    if _env("AI_ENABLED", "true").lower() in ("false", "0", "no"):
        return None

    name = _env("AI_PROVIDER", "openai").lower() or "openai"

    provider_class = PROVIDERS.get(name)
    if provider_class is None:
        logger.warning("Unknown AI_PROVIDER '%s'. Valid options: %s",
                       name, ", ".join(PROVIDERS))
        return None

    return provider_class()


# =====================================================================
# PART 5 - READING THE MODEL'S REPLY
# =====================================================================

def extract_json(raw_text):
    """
    Pull a JSON object out of the model's reply.

    Even with JSON mode enabled, a model can occasionally wrap its answer
    in a markdown code fence:

        ```json
        { "summary": "..." }
        ```

    So we clean the fence, and if that still fails we grab everything
    between the first "{" and the last "}". Defensive parsing like this
    is essential whenever the input comes from a language model.
    """
    if not raw_text:
        raise LLMError("The AI returned an empty response.")

    text = raw_text.strip()

    # Remove a ```json ... ``` fence if one is present.
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Last resort: the outermost braces.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    raise LLMError("The AI reply was not valid JSON.")


def _as_list(value, limit=10):
    """
    Force a value into a clean list of strings.

    A model might return a list, a single string, or a list of dicts.
    Rather than crashing the page, we normalise whatever arrives.
    """
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []

    cleaned = []
    for item in value:
        if isinstance(item, str) and item.strip():
            cleaned.append(item.strip())
        elif isinstance(item, dict):
            # Sometimes a model returns [{"skill": "Docker"}]
            for candidate in item.values():
                if isinstance(candidate, str) and candidate.strip():
                    cleaned.append(candidate.strip())
                    break
        if len(cleaned) >= limit:
            break
    return cleaned


def _as_bullet_list(value, limit=5):
    """Normalise the weak_bullets list into {original, improved, why}."""
    if not isinstance(value, list):
        return []

    bullets = []
    for item in value:
        if not isinstance(item, dict):
            continue
        original = str(item.get("original", "")).strip()
        improved = str(item.get("improved", "")).strip()
        if not original or not improved:
            continue
        bullets.append({
            "original": original[:300],
            "improved": improved[:300],
            "why": str(item.get("why", "")).strip()[:200],
        })
        if len(bullets) >= limit:
            break
    return bullets


def normalize_ai_response(data, provider_name, model_name):
    """
    Turn the model's JSON into the exact structure our template expects.

    We never trust the shape of the reply. Every field is read with .get()
    and passed through a normaliser, so a missing or malformed key gives
    an empty list instead of a 500 error page.
    """
    return {
        "available":  True,
        "source":     "ai",
        "provider":   provider_name,
        "model":      model_name,
        "message":    "",
        "summary":              str(data.get("summary", "")).strip()[:600],
        "strengths":            _as_list(data.get("strengths"), 6),
        "weaknesses":           _as_list(data.get("weaknesses"), 6),
        "missing_skills":       _as_list(data.get("missing_skills"), 10),
        "weak_bullets":         _as_bullet_list(data.get("weak_bullets"), 5),
        "generic_statements":   _as_list(data.get("generic_statements"), 6),
        "suggestions":          _as_list(data.get("suggestions"), 8),
        "professional_summary": str(
            data.get("professional_summary", "")).strip()[:800],
        "action_verbs":         _as_list(data.get("action_verbs"), 12),
        "keywords":             _as_list(data.get("keywords"), 14),
    }


# =====================================================================
# PART 6 - THE OFFLINE FALLBACK
# =====================================================================
# Used when there is no API key, AI is disabled, or the call failed.
# It is rule-based, so it is instant, free and always available - just
# less insightful than a real model.

# Phrases that appear on thousands of fresher resumes and say nothing.
GENERIC_PHRASES = [
    "hardworking", "hard working", "team player", "quick learner",
    "fast learner", "responsible for", "good knowledge of",
    "basic knowledge of", "passionate about", "self motivated",
    "out of the box", "think out of the box", "seeking a challenging",
    "looking for a challenging", "utilize my skills",
    "grow with the organization", "dynamic organization",
    "detail oriented", "go-getter", "excellent communication skills",
]

# High-value skills we commonly see missing from fresher resumes.
COMMONLY_MISSING = [
    "Git", "REST API", "Docker", "SQL", "AWS", "Unit Testing",
    "Data Structures", "Agile", "Linux", "CI/CD",
]


def _find_generic_phrases(text):
    """Return the cliches actually present in this resume."""
    lowered = text.lower()
    return [phrase for phrase in GENERIC_PHRASES if phrase in lowered]


def _find_weak_bullets(parsed):
    """
    Spot bullets that could be stronger, using three rules:

      1. It does not start with a strong action verb.
      2. It contains no number, so there is no measurable result.
      3. It is very short, so it says almost nothing.

    For each one we produce a rewrite TEMPLATE with [NUMBER] placeholders
    rather than inventing figures, because we do not know the real ones.
    """
    verbs = set(ACTION_VERBS)
    candidates = (parsed["projects"]["entries"]
                  + parsed["experience"]["entries"])

    weak = []
    for line in candidates:
        if len(line) < 15:
            continue

        first_word = re.split(r"[\s,:-]+", line.strip())[0].lower()
        starts_with_verb = first_word in verbs
        has_number = bool(re.search(r"\d", line))

        if starts_with_verb and has_number:
            continue                      # this bullet is already good

        reasons = []
        if not starts_with_verb:
            reasons.append("does not start with a strong action verb")
        if not has_number:
            reasons.append("has no measurable result")

        weak.append({
            "original": line[:300],
            "improved": (f"Developed {line[:120].rstrip('.')} , handling "
                         f"[NUMBER] records / users and reducing "
                         f"[METRIC] by [NUMBER]%"),
            "why": "This line " + " and ".join(reasons) + ".",
        })

        if len(weak) >= 4:
            break

    return weak


def _suggest_action_verbs(parsed_text):
    """Recommend strong verbs the resume is not using yet."""
    lowered = parsed_text.lower()
    unused = [verb.capitalize() for verb in ACTION_VERBS
              if not re.search(r"\b" + verb + r"\b", lowered)]
    return unused[:10]


def _build_summary_template(parsed):
    """
    Build a professional summary the student can edit.

    We only use facts the resume already contains - degree and top
    skills - so nothing is invented.
    """
    degrees = parsed["education"]["degrees"]
    degree = degrees[0] if degrees else "Computer Science"
    top_skills = parsed["skills"]["technical"][:4]
    skill_text = ", ".join(top_skills) if top_skills else "software development"

    project_count = max(parsed["projects"]["count"], 1)

    return (f"{degree} graduate with hands-on experience in {skill_text}. "
            f"Built {project_count}+ projects covering the full development "
            f"cycle, from design through deployment. Looking for a "
            f"[ROLE] position where I can apply [SPECIFIC SKILL] to "
            f"[COMPANY'S PROBLEM]. Replace the bracketed parts for each "
            f"application.")


def offline_analysis(parsed, ats, resume_text, reason=""):
    """
    Produce useful feedback without any API call.

    This reuses the ATS scorer's findings, so the advice stays consistent
    with the score the user can already see on screen.
    """
    strengths = [f"{c['label']} scored {c['score']}/{c['max']}"
                 for c in (ats["strengths"] if ats else [])]
    if not strengths:
        strengths = ["You have uploaded a readable, text-based PDF - "
                     "many candidates fail at this first step."]

    weaknesses = [
        f"{c['label']} scored only {c['score']}/{c['max']}"
        for c in (ats["categories"] if ats else [])
        if c["percent"] < 60
    ][:5]

    suggestions = [item["tip"] for item in
                   (ats["improvements"][:8] if ats else [])]

    present_skills = set(parsed["skills"]["technical"])
    missing_skills = [s for s in COMMONLY_MISSING if s not in present_skills]

    return {
        "available":  True,
        "source":     "offline",
        "provider":   "rule-based",
        "model":      "built-in rules",
        "message":    reason or ("AI analysis is not configured, so this "
                                 "feedback comes from our built-in rules."),
        "summary": (
            f"Your resume scored {ats['total'] if ats else 0}/100 on our "
            f"ATS-style checks. "
            f"{ats['grade_message'] if ats else ''} "
            "The points below come from rule-based checks. Add an API key "
            "in your .env file to get deeper, AI-written feedback."
        ),
        "strengths":            strengths[:6],
        "weaknesses":           weaknesses,
        "missing_skills":       missing_skills[:8],
        "weak_bullets":         _find_weak_bullets(parsed),
        "generic_statements":   _find_generic_phrases(resume_text)[:6],
        "suggestions":          suggestions,
        "professional_summary": _build_summary_template(parsed),
        "action_verbs":         _suggest_action_verbs(resume_text),
        "keywords":             missing_skills[:10],
    }


# =====================================================================
# PART 7 - THE MAIN FUNCTION
# =====================================================================

def analyze_resume(parsed, ats, resume_text, job_description=""):
    """
    Get AI feedback, falling back to rules if that is not possible.

    This is the only function app.py needs to call. It NEVER raises -
    whatever goes wrong, the user gets a usable result.

    Parameters
    ----------
    parsed          : output of resume_parser.parse_resume()
    ats             : output of ats_scorer.calculate_ats_score()
    resume_text     : the clean resume text
    job_description : optional, used properly in Phase 6

    Returns
    -------
    dict - see normalize_ai_response() / offline_analysis() for the keys.
           The "source" key is "ai" or "offline" so the UI can say which.
    """
    provider = get_provider()

    # --- No provider configured: go straight to the offline path ---
    if provider is None:
        return offline_analysis(
            parsed, ats, resume_text,
            "AI analysis is switched off in your .env file. "
            "These suggestions come from our built-in rules.")

    if not provider.is_configured():
        return offline_analysis(
            parsed, ats, resume_text,
            f"No API key found for '{provider.name}'. Add one to your .env "
            "file to unlock AI-written feedback. Until then, these "
            "suggestions come from our built-in rules.")

    # --- Call the model ---
    try:
        user_prompt = build_user_prompt(parsed, ats, resume_text,
                                        job_description)
        raw_reply = provider.generate(SYSTEM_PROMPT, user_prompt)
        data = extract_json(raw_reply)

        result = normalize_ai_response(data, provider.name, provider.model)

        logger.info("AI analysis complete via %s (%s)",
                    provider.name, provider.model)
        return result

    except LLMError as error:
        # A known, explainable failure - show the user our message.
        logger.warning("AI analysis unavailable: %s", error)
        return offline_analysis(
            parsed, ats, resume_text,
            f"{error} Showing rule-based suggestions instead.")

    except Exception as error:
        # Anything unexpected. Log the full traceback for the developer,
        # show the user a neutral sentence.
        logger.exception("Unexpected AI failure: %s", error)
        return offline_analysis(
            parsed, ats, resume_text,
            "The AI service could not be reached. Showing rule-based "
            "suggestions instead.")


# =====================================================================
# Quick manual test
# =====================================================================
# Run:  python -m services.ai_analyzer uploads\some_resume.pdf
if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s: %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python -m services.ai_analyzer <path-to-pdf>")
        sys.exit(1)

    from services.pdf_parser import extract_text_from_pdf, PDFError
    from services.resume_parser import parse_resume
    from services.ats_scorer import calculate_ats_score

    try:
        extracted = extract_text_from_pdf(sys.argv[1])
    except PDFError as error:
        print(f"ERROR: {error}")
        sys.exit(1)

    parsed_resume = parse_resume(extracted["text"])
    ats_report = calculate_ats_score(parsed_resume)
    analysis = analyze_resume(parsed_resume, ats_report, extracted["text"])

    print("=" * 62)
    print(f"  SOURCE: {analysis['source']} "
          f"({analysis['provider']} / {analysis['model']})")
    if analysis["message"]:
        print(f"  NOTE  : {analysis['message']}")
    print("=" * 62)

    print(f"\nSUMMARY\n{analysis['summary']}")

    for title, key in [("STRENGTHS", "strengths"),
                       ("WEAKNESSES", "weaknesses"),
                       ("SUGGESTIONS", "suggestions"),
                       ("MISSING SKILLS", "missing_skills"),
                       ("GENERIC STATEMENTS", "generic_statements"),
                       ("ACTION VERBS TO USE", "action_verbs"),
                       ("KEYWORDS TO ADD", "keywords")]:
        print(f"\n{title}")
        print("-" * len(title))
        for item in analysis[key] or ["(none)"]:
            print(f"  - {item}")

    print("\nWEAK BULLETS")
    print("-" * 12)
    for bullet in analysis["weak_bullets"] or []:
        print(f"  BEFORE: {bullet['original']}")
        print(f"  AFTER : {bullet['improved']}")
        print(f"  WHY   : {bullet['why']}\n")

    print("SUGGESTED PROFESSIONAL SUMMARY")
    print("-" * 30)
    print(analysis["professional_summary"])
