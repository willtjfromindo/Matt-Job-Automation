"""Guessed work emails: build them, and try the next likely address when one bounces.

Before sending (`python cli.py guess-emails`):
  data/imports/teampages/*.csv       people from firm team pages (Email blank unless the bio
                                     page showed a real address)
  data/imports/email_formats/*.csv   one row per firm: email_domain, pattern, status
Each person gets up to 3 likely address patterns, best first. A "confirmed" firm format (2+ real
staff addresses seen on public pages) goes first and only one backup is kept behind it.
Names that are easy to get wrong (hyphens, accents, apostrophes, two-word last names, initials)
are skipped. Output: data/imports/ready/, same columns plus Email Domain and Email Patterns.

While sending (used by the sender and the inbox check):
  - Before someone's first email, the sender switches to the pattern that has worked best at
    their firm so far.
  - When a guess bounces, the person moves to their next pattern and is emailed again.
  - If the firm's pattern has already reached other people there, a bounce means this person
    probably left (or has an unusual address), so no more guesses are made for them.
A domain that has never bounced anything may accept every address, so "no bounce" there proves
nothing and isn't counted as the pattern working.
"""

import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

PLAIN_NAME = re.compile(r"^[A-Za-z]+$")
TOKENS = re.compile(r"\{(first|last|f|l)\}")
# The most common formats at finance firms, most common first.
COMMON_PATTERNS = ["{first}.{last}", "{f}{last}", "{first}"]
MAX_GUESSES = 3


def build_email(first: str, last: str, pattern: str, domain: str) -> str | None:
    """Apply a pattern like "{first}.{last}" to a name. None if the name is risky."""
    first, last = (first or "").strip(), (last or "").strip()
    if not (PLAIN_NAME.match(first) and PLAIN_NAME.match(last)):
        return None
    if len(first) < 2 or len(last) < 2:
        return None  # initials ("J. Smith") don't tell us the real first name
    values = {"first": first.lower(), "last": last.lower(), "f": first[0].lower(), "l": last[0].lower()}
    local = TOKENS.sub(lambda m: values[m.group(1)], pattern)
    if "{" in local or not re.fullmatch(r"[a-z0-9._-]+", local):
        return None  # pattern uses a token we don't know
    return f"{local}@{domain.strip().lower()}"


def patterns_for(fmt: dict | None) -> list[str]:
    """Patterns to try for a firm, best first."""
    status = (fmt or {}).get("status", "").strip().lower()
    known = (fmt or {}).get("pattern", "").strip()
    if status in ("confirmed", "likely") and known:
        ordered = [known] + [p for p in COMMON_PATTERNS if p != known]
        return ordered[:2] if status == "confirmed" else ordered[:MAX_GUESSES]
    return COMMON_PATTERNS[:MAX_GUESSES]


# ---------- before sending: CSV files ----------


def load_formats(formats_dir: Path) -> dict[str, dict]:
    formats = {}
    for path in sorted(formats_dir.glob("*.csv")):
        for row in csv.DictReader(path.open(newline="", encoding="utf-8")):
            formats[row["Company"].strip()] = row
    return formats


def load_firm_domains(firms_csv: Path) -> dict[str, str]:
    return {r["name"].strip(): (r.get("domain") or "").strip().lower()
            for r in csv.DictReader(firms_csv.open(newline="", encoding="utf-8-sig"))}


def run(team_dir: Path, formats_dir: Path, out_dir: Path, firms_csv: Path,
        accepts_mail=None) -> Counter:
    if accepts_mail is None:
        from .verify import has_mail_server as accepts_mail
    formats = load_formats(formats_dir)
    firm_domains = load_firm_domains(firms_csv)
    out_dir.mkdir(parents=True, exist_ok=True)
    stats: Counter = Counter()
    for path in sorted(team_dir.glob("*.csv")):
        reader = csv.DictReader(path.open(newline="", encoding="utf-8"))
        rows = list(reader)
        if not rows:
            continue
        company = rows[0]["Company"].strip()
        fmt = formats.get(company)
        domain = ((fmt or {}).get("email_domain") or firm_domains.get(company) or "").strip().lower()
        if not domain or not accepts_mail(domain):
            stats["skipped: firm's email domain unknown or takes no mail"] += len(rows)
            stats["people"] += len(rows)
            continue
        wanted = patterns_for(fmt)
        # Two people at one firm can't share an address: drop any pattern that collides.
        by_address = defaultdict(list)
        for i, row in enumerate(rows):
            for p in wanted:
                address = build_email(row["First Name"], row["Last Name"], p, domain)
                if address:
                    by_address[address].append(i)
        kept = []
        for i, row in enumerate(rows):
            stats["people"] += 1
            if (row.get("Email") or "").strip():
                kept.append({**row, "Email Domain": "", "Email Patterns": ""})
                stats["real address from bio page"] += 1
                continue
            options = []
            for p in wanted:
                address = build_email(row["First Name"], row["Last Name"], p, domain)
                if address and by_address[address] == [i]:
                    options.append((p, address))
            if not options:
                stats["skipped: name too risky to guess"] += 1
                continue
            kept.append({**row, "Email": options[0][1], "Email Domain": domain,
                         "Email Patterns": " ".join(p for p, _ in options)})
            stats["confirmed firm format" if (fmt or {}).get("status") == "confirmed"
                  else "guessed, will try backups if it bounces"] += 1
        if kept:
            with (out_dir / path.name).open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(reader.fieldnames) + ["Email Domain", "Email Patterns"])
                w.writeheader()
                w.writerows(kept)
    return stats


# ---------- while sending: learn from bounces ----------


def pattern_scores(conn, domain: str, wait_minutes: int) -> dict[str, int]:
    """How well each pattern has done at this domain: reached people minus bounces.

    A send counts as having reached someone once `wait_minutes` passed with no bounce, but only
    at domains that have bounced at least once (others may accept any address)."""
    rows = conn.execute(
        """select email_pattern,
             count(*) filter (where status = 'sent'
                              and sent_at < now() - make_interval(mins => %s)) as reached,
             count(*) filter (where status = 'bounced') as bounced
           from sends
           where kind = 'first' and not practice and email_pattern is not null
             and split_part(to_email, '@', 2) = %s
           group by email_pattern""", (wait_minutes, domain)).fetchall()
    rejects_unknown = any(r["bounced"] for r in rows)
    return {r["email_pattern"]: (r["reached"] if rejects_unknown else 0) - r["bounced"] for r in rows}


def rank(patterns: list[str], scores: dict[str, int]) -> list[str]:
    """Best-scoring first; ties keep their original order."""
    return sorted(patterns, key=lambda p: -scores.get(p, 0))


def _switch(conn, contact: dict, patterns: list[str]) -> dict | None:
    """Point the contact at the first usable pattern in `patterns`. Returns the updated row."""
    for i, p in enumerate(patterns):
        address = build_email(contact["first_name"], contact["last_name"], p, contact["email_domain"])
        if not address:
            continue
        taken = conn.execute(
            """select 1 from contacts where email = %(a)s and id <> %(id)s
               union all select 1 from suppression where email = %(a)s""",
            {"a": address, "id": contact["id"]}).fetchone()
        if taken:
            continue
        conn.execute(
            """update contacts set email = %s, email_pattern = %s, email_patterns_left = %s
               where id = %s""", (address, p, patterns[i + 1:], contact["id"]))
        return {**contact, "email": address, "email_pattern": p, "email_patterns_left": patterns[i + 1:]}
    return None


def apply_learning(conn, contact: dict, wait_minutes: int) -> dict:
    """Before someone's first email: switch to the pattern that has worked best at their firm."""
    left = contact.get("email_patterns_left") or []
    if not contact.get("email_pattern") or not left or not contact.get("email_domain"):
        return contact
    scores = pattern_scores(conn, contact["email_domain"], wait_minutes)
    options = rank([contact["email_pattern"]] + left, scores)
    if options[0] == contact["email_pattern"]:
        return contact
    with conn.transaction():
        return _switch(conn, contact, options) or contact


def next_guess(conn, contact: dict, wait_minutes: int) -> bool:
    """The current guess bounced (the send is already marked). Move the person to their next
    likely address and queue them to be emailed again. False if there's nothing sensible left."""
    if not contact.get("email_pattern") or not contact.get("email_domain"):
        return False  # a real address from a bio page: nothing to guess
    scores = pattern_scores(conn, contact["email_domain"], wait_minutes)
    if scores.get(contact["email_pattern"], 0) > 0:
        return False  # this pattern reaches others at the firm, so the person likely left
    left = [p for p in rank(contact.get("email_patterns_left") or [], scores) if scores.get(p, 0) >= 0]
    old = contact["email"]
    updated = _switch(conn, contact, left)
    if not updated:
        return False
    conn.execute("insert into suppression (email, reason) values (%s, 'bounced') on conflict do nothing",
                 (old,))
    conn.execute(
        """update contacts set status = 'ready', gmail_thread_id = null, first_message_id = null,
             first_subject = null, follow_up_date = null where id = %s""", (contact["id"],))
    return True
