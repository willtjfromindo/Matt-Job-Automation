"""Load and fill the email templates in templates/.

First emails: templates/{ib|pe|vc}_{junior|mid|senior}.txt
    Subject: ...
    ---
    body with {first_name} {firm} {team} {title} {personal_line}
    plus {sender_name} {sender_school} {sender_tagline} {sender_intro}, which come from the
    SENDER_NAME / SENDER_SCHOOL / SENDER_TAGLINE / SENDER_INTRO settings

Follow-ups: templates/followup_1.txt and followup_2.txt (body only; subject is "Re: <first subject>").
"""

import re
from pathlib import Path

from . import config
from .config import TEMPLATES_DIR

# About the person being emailed, and the one AI sentence.
RECIPIENT_FIELDS = ("first_name", "firm", "team", "title", "personal_line")
# About the person sending, from the settings (so no name is written into the templates).
SENDER_FIELDS = ("sender_name", "sender_school", "sender_tagline", "sender_intro")
FIELDS = RECIPIENT_FIELDS + SENDER_FIELDS
PLACEHOLDER = re.compile(r"\{(\w+)\}")


class TemplateError(ValueError):
    pass


def template_name(career_path: str, seniority: str) -> str:
    return f"{career_path.lower()}_{seniority}.txt"


def load(name: str, directory: Path = TEMPLATES_DIR) -> tuple[str | None, str]:
    path = directory / name
    if not path.exists():
        raise TemplateError(f"Missing template file templates/{name}")
    text = path.read_text().replace("\r\n", "\n")
    if "\n---\n" in text and text.lstrip().lower().startswith("subject:"):
        head, body = text.split("\n---\n", 1)
        subject = head.strip()[len("subject:"):].strip()
        return subject, body.strip("\n")
    return None, text.strip("\n")


def fill(text: str, values: dict) -> str:
    """Fill {placeholders}. A line that is only {personal_line} disappears when it's empty."""
    unknown = [p for p in PLACEHOLDER.findall(text) if p not in FIELDS]
    if unknown:
        raise TemplateError(f"Unknown fill-in(s): {', '.join('{' + u + '}' for u in unknown)}")
    for field in FIELDS:
        if f"{{{field}}}" in text and not (values.get(field) or "").strip():
            if field != "personal_line":
                raise TemplateError(f"Template uses {{{field}}} but this person has no {field}")
    lines = []
    for line in text.split("\n"):
        if line.strip() == "{personal_line}" and not (values.get("personal_line") or "").strip():
            continue
        lines.append(PLACEHOLDER.sub(lambda m: (values.get(m.group(1)) or "").strip(), line))
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out)          # no double blank lines after removing a line
    out = re.sub(r"[ \t]{2,}", " ", out)           # no double spaces from empty fill-ins
    return out.strip() + "\n"


def sender_values() -> dict:
    """The sender's own details, from the settings. Missing ones stop the email, loudly."""
    s = config.load()
    return {"sender_name": s.sender_name, "sender_school": s.sender_school,
            "sender_tagline": s.sender_tagline, "sender_intro": s.sender_intro}


def render_first(contact: dict, firm_name: str, personal_line: str) -> tuple[str, str, str]:
    """Return (template_name, subject, body) for a first email."""
    name = template_name(contact["career_path"], contact["seniority"])
    subject, body = load(name)
    if not subject:
        raise TemplateError(f"templates/{name} needs a 'Subject:' line and a '---' line")
    values = {"first_name": contact["first_name"], "firm": firm_name, "team": contact.get("team"),
              "title": contact.get("title"), "personal_line": personal_line, **sender_values()}
    return name, fill(subject, values).strip(), fill(body, values)


def render_followup(n: int, contact: dict, firm_name: str) -> tuple[str, str, str]:
    name = f"followup_{n}.txt"
    _, body = load(name)
    values = {"first_name": contact["first_name"], "firm": firm_name, "team": contact.get("team"),
              "title": contact.get("title"), "personal_line": "", **sender_values()}
    first_subject = contact.get("first_subject") or ""
    subject = first_subject if first_subject.lower().startswith("re:") else f"Re: {first_subject}"
    return name, subject, fill(body, values)
