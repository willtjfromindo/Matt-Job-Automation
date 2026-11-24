"""Find real connections between the sender and a contact (tiers A-C, no AI).

A: same school            -> from the contact's `education`
B: shared employer        -> from `past_employers` (or `headline_or_bio`)
C: shared hobby           -> from `interests` (or `headline_or_bio`)
D: specific career fact   -> picked by the AI later, with an exact quote
E: nothing personal       -> plain professional email
"""

import re
from dataclasses import dataclass

from . import profile as profile_mod


@dataclass
class Evidence:
    tier: str                    # 'A', 'B', 'C' or '' (to be decided by the drafter: D or E)
    source_field: str | None = None
    quote: str | None = None     # exact text from the contact's record
    sender_fact_id: str | None = None
    label: str | None = None     # e.g. the school, the shared employer, "tennis"


def _fact_for(profile: dict, needle: str) -> str | None:
    for fact in profile.get("facts", []):
        if needle.lower() in fact["text"].lower():
            return fact["id"]
    return None


def _sentence_around(text: str, match: str) -> str:
    """The clause containing the match, kept verbatim so it can be checked later."""
    idx = text.lower().find(match.lower())
    if idx < 0:
        return match
    start = max(text.rfind(sep, 0, idx) for sep in (".", ";", "|", "\n", "•"))
    end_candidates = [i for i in (text.find(sep, idx) for sep in (".", ";", "|", "\n", "•")) if i >= 0]
    end = min(end_candidates) if end_candidates else len(text)
    return text[start + 1:end].strip() or match


def school_match(contact: dict, profile: dict) -> Evidence | None:
    for school in profile.get("schools", []):
        found = profile_mod.find_alias(contact.get("education"), school["aliases"])
        if found:
            return Evidence("A", "education", _sentence_around(contact["education"], found),
                            _fact_for(profile, school["name"]), school["name"])
    return None


def employer_match(contact: dict, profile: dict) -> Evidence | None:
    for employer in profile.get("employers", []):
        for field in ("past_employers", "headline_or_bio"):
            text = contact.get(field)
            found = profile_mod.find_alias(text, employer["aliases"], employer.get("exclude"))
            if found:
                return Evidence("B", field, _sentence_around(text, found),
                                _fact_for(profile, employer["name"].split()[0]), employer["name"])
    return None


def hobby_match(contact: dict, profile: dict) -> Evidence | None:
    for hobby in profile.get("hobbies", []):
        for field in ("interests", "headline_or_bio"):
            text = contact.get(field)
            if not text:
                continue
            for kw in hobby["keywords"]:
                if re.search(r"\b" + re.escape(kw) + r"\b", text, re.I):
                    return Evidence("C", field, _sentence_around(text, kw),
                                    _fact_for(profile, hobby["name"]), hobby["name"])
    return None


def find(contact: dict, profile: dict) -> Evidence:
    return (school_match(contact, profile) or employer_match(contact, profile)
            or hobby_match(contact, profile) or Evidence(""))


def flags(contact: dict, profile: dict) -> tuple[bool, bool]:
    """(ucla_connection, bain_connection) used to put these people first."""
    return school_match(contact, profile) is not None, employer_match(contact, profile) is not None
