"""The sender's approved fact list.

The profile file (data/sender_profile.json) is the ONLY source of facts about the sender that
may appear in an email. It is built from their resume with `cli.py profile <resume>`, then
reviewed and edited by hand. Shape:

{
  "name": "Alex Rivera",
  "facts": [{"id": "school", "text": "Economics student at State University"}, ...],
  "schools":   [{"name": "State University", "aliases": ["State University", "State"]}],
  "employers": [{"name": "Example Consulting", "aliases": ["Example Consulting", "Example"],
                 "exclude": ["Example Capital"]}],
  "hobbies":   [{"name": "tennis", "keywords": ["tennis"]}],
  "extra_allowed_words": ["Bruin"]
}

Until this file exists there are no approved facts, so every email uses the plain fallback
sentence. That is deliberate: nothing about the sender is ever invented.
"""

import json
import re
from pathlib import Path

from . import ai
from .config import PROFILE_PATH

# Used until the sender's real profile file exists: no facts, so no claims about the sender
# can appear in an email.
DEFAULT_PROFILE = {
    "name": "",
    "facts": [],
    "schools": [],
    "employers": [],
    "hobbies": [],
    "extra_allowed_words": [],
}


def load(path: Path = PROFILE_PATH) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return DEFAULT_PROFILE


def fact_ids(profile: dict) -> set[str]:
    return {f["id"] for f in profile.get("facts", [])}


def _word_pattern(phrase: str) -> re.Pattern:
    return re.compile(r"(?<![\w&])" + re.escape(phrase) + r"(?![\w&])", re.I)


def find_alias(text: str | None, aliases: list[str], exclude: list[str] | None = None) -> str | None:
    """Return the alias found in text (word-boundary, case-insensitive), ignoring excluded names."""
    if not text:
        return None
    cleaned = text
    for name in exclude or []:
        cleaned = _word_pattern(name).sub(" ", cleaned)
    for alias in sorted(aliases, key=len, reverse=True):
        m = _word_pattern(alias).search(cleaned)
        if m:
            return m.group(0)
    return None


# ---------- building the profile from a resume ----------

PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "category": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["id", "category", "text"],
                "additionalProperties": False,
            },
        },
        "schools": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "aliases"],
                "additionalProperties": False,
            },
        },
        "employers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "exclude": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "aliases", "exclude"],
                "additionalProperties": False,
            },
        },
        "hobbies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "keywords"],
                "additionalProperties": False,
            },
        },
        "extra_allowed_words": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["name", "facts", "schools", "employers", "hobbies", "extra_allowed_words"],
    "additionalProperties": False,
}

PROFILE_PROMPT = """Turn this resume into a structured fact list for networking emails.

Rules:
- Only include facts stated in the resume. Do not infer or embellish.
- facts: short, plain statements usable in an email (e.g. "Economics student at State
  University", "Interned at Example Consulting in Los Angeles", "Member of the student
  investment club", "Plays club tennis"). Give each a short snake_case id. Categories: school,
  work, club, activity, hobby, location, interest, skill.
- schools: each school with aliases people write on LinkedIn (e.g. UCLA,
  University of California, Los Angeles).
- extra_allowed_words: other words tied to those schools or employers that may appear in an
  email, such as what the school's students call themselves (UCLA -> Bruin). Empty list if none.
- employers: each employer with aliases, and "exclude" names that look similar but are
  different companies (e.g. Bain & Company -> exclude Bain Capital).
- hobbies: hobbies/sports/activities with 1-3 lowercase keywords each that would appear in
  someone's bio if they shared it (e.g. tennis -> ["tennis"]).
"""


def resume_text(resume_path: Path) -> str:
    if resume_path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        return "\n".join(page.extract_text() or "" for page in PdfReader(resume_path).pages)
    if resume_path.suffix.lower() == ".docx":
        raise SystemExit("Please save the resume as PDF or .txt first.")
    return resume_path.read_text(errors="replace")


def build_from_resume(resume_path: Path) -> dict:
    text = resume_text(resume_path)
    if len(text.strip()) < 100:
        raise SystemExit("Couldn't read text from the resume (is it a scanned image?). "
                         "Save it as a .txt file and try again.")
    profile = ai.complete_json(PROFILE_PROMPT, f"<resume>\n{text}\n</resume>",
                               PROFILE_SCHEMA, "profile")
    return profile
