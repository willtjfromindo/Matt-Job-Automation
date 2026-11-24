"""Automatic checks that reject weak or made-up personal lines.

Every claim about the recipient must quote their saved record word-for-word, every fact about
the sender must come from the approved profile list, and no names/places may appear that aren't
in either.
"""

import re
from difflib import SequenceMatcher

QUOTE_FIELDS = ("firm", "title", "team", "focus", "education", "past_employers",
                "headline_or_bio", "interests")

BANNED = [
    "i hope this", "came across your profile", "noticed your profile", "impressive", "amazing",
    "incredible", "passionate", "synergy", "leverage my", "reach out", "pick your brain",
    "rockstar", "world-class", "esteemed", "as an ai", "linkedin",
]

# Capitalized words that are fine even if they aren't in the record. Everything specific to
# the sender (their school, employers, nickname words like "Bruin") comes from their profile:
# school and employer aliases are always allowed, and anything else can be listed in the
# profile's "extra_allowed_words".
ALLOWED_WORDS = {
    "i", "i'm", "i've", "i'd", "my", "company", "like", "as", "your", "having", "seeing",
    "given", "since", "with", "after", "the", "both", "while", "because", "it", "it's",
    "that", "having",
}


def allowed_words(profile: dict) -> set[str]:
    words = set(ALLOWED_WORDS)
    for group in ("schools", "employers"):
        for item in profile.get(group, []):
            for alias in [item.get("name"), *item.get("aliases", [])]:
                words.update(w.strip(".,&'").lower() for w in (alias or "").split())
    words.update(w.lower() for w in profile.get("extra_allowed_words", []))
    words.discard("")
    return words

MIN_WORDS, MAX_WORDS = 12, 40

# Dots that don't end a sentence: Ph.D., B.S., U.S., Inc., Jr. and the like.
ABBREVIATIONS = re.compile(r"\b(?:[A-Za-z]{1,2}\.){2,}|\b(?:Inc|Co|Corp|Ltd|Jr|Sr|St|Dr|Mr|Ms|Mrs|No|vs)\.")

# Signs the model pasted its evidence into the email: quote marks, brackets, field names.
PASTED_EVIDENCE = re.compile(
    r"[\"“”()]|(?:^|\s)'\w|\b(?:" + "|".join(QUOTE_FIELDS) + r")\s*:|_", re.IGNORECASE)


def _short_and_long(item: dict) -> tuple[str, list[str]]:
    """The shortest way to write a school/employer, and the longer spellings of it.

    Deduplicated, longest first, so one mention of "Bain & Company" is never counted again as
    "Bain & Co".
    """
    names = list(dict.fromkeys(n for n in [item.get("name"), *item.get("aliases", [])] if n))
    if not names:
        return "", []
    short = min(names, key=len)
    longer = [n for n in names if len(n) > len(short)]
    return short, sorted(longer, key=len, reverse=True)


def _count_mentions(low: str, forms: list[str]) -> int:
    """How many times any of these spellings appears, counting each mention once."""
    text, found = low, 0
    for form in forms:
        f = _norm(form)
        if not f:
            continue
        found += text.count(f)
        text = text.replace(f, " ")
    return found


def _norm(s: str | None) -> str:
    s = (s or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip().lower()


def check(result: dict, record: dict, profile: dict, tier_hint: str = "",
          hint_label: str | None = None, same_firm_lines: list[str] | None = None) -> list[str]:
    """Return a list of problems (empty list = passed)."""
    issues: list[str] = []
    line = (result.get("personal_line") or "").strip()
    tier = result.get("tier") or ""
    claims = result.get("recipient_claims") or []
    fact_ids = result.get("sender_fact_ids") or []
    ok_words = allowed_words(profile)
    low = _norm(line)

    if not line:
        return ["empty personal line"]
    words = len(line.split())
    if words < MIN_WORDS or words > MAX_WORDS:
        issues.append(f"length {words} words (want {MIN_WORDS}-{MAX_WORDS})")
    if len(re.findall(r"[.!?](\s|$)", ABBREVIATIONS.sub("", line))) > 2:
        issues.append("more than two sentences")
    if "?" in line or "!" in line:
        issues.append("contains a question or exclamation")
    if re.search(r"[{}\[\]<>]", line):
        issues.append("leftover placeholder or bracket")
    plain = line.replace(record.get("firm") or "\0", "Firm")
    if plain.count(",") > 2:
        issues.append("too many details strung together with commas: keep it simple")
    if PASTED_EVIDENCE.search(plain):
        issues.append("quote marks, brackets or field names in the email text: write it plainly "
                      "and put quotes only in recipient_claims")
    # Use the short name of the sender's own school and employers (UCLA, not University of
    # California, Los Angeles), and don't repeat a long employer name the intro already gives.
    for school in profile.get("schools", []):
        short, long_forms = _short_and_long(school)
        # Only the formal, spelled-out names (3+ words), not a shorter nickname like a campus.
        for long_form in (f for f in long_forms if len(f.split()) >= 3):
            if _norm(long_form) in low:
                issues.append(f"write {short} instead of {long_form}")
    for employer in profile.get("employers", []):
        short, long_forms = _short_and_long(employer)
        if long_forms and _count_mentions(low, long_forms) > 1:
            issues.append(f"{long_forms[0]} named more than once; the intro already names it, "
                          f"so say {short}")
    for phrase in BANNED:
        if phrase in low:
            issues.append(f"banned phrase: {phrase!r}")

    # Tier must match what the matching code found.
    if tier_hint and tier != tier_hint:
        issues.append(f"tier {tier!r} but the record shows tier {tier_hint}")
    if tier not in ("A", "B", "C", "D", "E"):
        issues.append(f"bad tier {tier!r}")

    # Claims about the recipient: exact quotes from the record.
    for c in claims:
        field = c.get("source_field")
        quote = _norm(c.get("quote"))
        if field not in QUOTE_FIELDS:
            issues.append(f"claim cites unknown field {field!r}")
        elif not quote or quote not in _norm(record.get(field)):
            issues.append(f"quote not found in {field}: {c.get('quote')!r}")
    if tier in ("A", "B", "C", "D") and not claims:
        issues.append("personal tier but no evidence quoted")

    # Facts about the sender: only approved ones.
    allowed_ids = {f["id"] for f in profile.get("facts", [])}
    for fid in fact_ids:
        if fid not in allowed_ids:
            issues.append(f"unknown sender fact id {fid!r}")

    # The connection the tier promises must actually be in the sentence.
    if tier == "A":
        aliases = [a for s in profile.get("schools", []) for a in s["aliases"]] + ["Bruin"]
        if not any(_norm(a) in low for a in aliases):
            issues.append("tier A but the school isn't mentioned")
    if tier == "B":
        employers = profile.get("employers", [])
        aliases = [a for e in employers for a in e["aliases"]]
        if hint_label:
            aliases.append(hint_label)
        if not any(_norm(a) in low for a in aliases):
            issues.append("tier B but the shared employer isn't mentioned")
    if tier == "C" and hint_label and _norm(hint_label) not in low:
        issues.append("tier C but the shared interest isn't mentioned")

    # Names/places must come from the record, the sender's facts, or the firm name.
    sources = " ".join(_norm(record.get(f)) for f in QUOTE_FIELDS)
    sources += " " + " ".join(_norm(f["text"]) for f in profile.get("facts", []))
    sources += " " + _norm(record.get("first_name")) + " " + _norm(record.get("last_name"))
    tokens = re.findall(r"[A-Za-z][A-Za-z&'.\-]*", line)
    for i, tok in enumerate(tokens):
        if i == 0 or not tok[0].isupper():
            continue
        word = re.sub(r"'s$", "", tok.strip(".-'").lower())
        if word in ok_words or len(word) < 2:
            continue
        if word not in sources:
            issues.append(f"name or place not backed by the record: {tok!r}")

    # Firm name must be written exactly as on record when it appears.
    firm = record.get("firm") or ""
    if firm and firm.lower() in low and firm not in line:
        issues.append("firm name capitalized differently than on record")

    # Don't send near-identical lines to two people at the same firm.
    for other in same_firm_lines or []:
        if other and SequenceMatcher(None, low, _norm(other)).ratio() > 0.9:
            issues.append("nearly identical to another email at the same firm")
            break
    return issues
