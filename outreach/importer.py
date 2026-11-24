"""Load firms and contacts from CSV files into the database."""

import csv
import re
from collections import Counter
from pathlib import Path

from . import classify, evidence
from . import profile as profile_mod

# ---------- firms ----------


def load_firms(conn, path: Path) -> int:
    """Insert/update firms from data/firms.csv and set the round-robin order."""
    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8-sig")))
    with conn.transaction():
        for row in rows:
            paths = [p.strip().upper() for p in row["career_paths"].split("|") if p.strip()]
            conn.execute(
                """insert into firms (name, career_paths, per_office, rank_source, domain)
                   values (%s, %s, %s, %s, %s)
                   on conflict (name) do update set career_paths = excluded.career_paths,
                     per_office = excluded.per_office, rank_source = excluded.rank_source,
                     domain = excluded.domain""",
                (row["name"].strip(), paths, row.get("per_office", "").strip().lower() == "true",
                 row.get("rank_source") or None, (row.get("domain") or "").strip().lower() or None),
            )
        set_rotation(conn, [r["name"].strip() for r in rows])
    return len(rows)


def set_rotation(conn, names_in_file_order: list[str]) -> None:
    """Interleave banks, PE and VC so the rotation never runs through one type for long.

    The file is ordered banks -> PE -> VC, each by rank. The rotation takes them in proportion
    (e.g. 25 banks, 300 PE, 100 VC -> roughly 1 bank, 12 PE, 4 VC per 17 firms), keeping rank
    order inside each type.
    """
    firms = conn.execute("select id, name, career_paths from firms where active").fetchall()
    by_name = {f["name"]: f for f in firms}
    buckets: dict[str, list[dict]] = {"IB": [], "PE": [], "VC": []}
    for name in names_in_file_order:
        f = by_name.get(name)
        if f:
            buckets[f["career_paths"][0]].append(f)
    # Firms in the DB but not in this file go last.
    listed = {n for n in names_in_file_order}
    extras = [f for f in firms if f["name"] not in listed]

    total = sum(len(b) for b in buckets.values())
    order: list[dict] = []
    taken = {k: 0 for k in buckets}
    for i in range(total):
        # pick the bucket that is furthest behind its fair share
        best = max(
            (k for k in buckets if taken[k] < len(buckets[k])),
            key=lambda k: (len(buckets[k]) * (i + 1) / total) - taken[k],
        )
        order.append(buckets[best][taken[best]])
        taken[best] += 1
    order += extras
    for pos, f in enumerate(order, start=1):
        conn.execute("update firms set rotation_position = %s where id = %s", (pos, f["id"]))


# ---------- contacts ----------

COLUMN_ALIASES = {
    "first_name": ["first name", "firstname", "first"],
    "last_name": ["last name", "lastname", "last"],
    "full_name": ["name", "full name", "person name"],
    "title": ["title", "job title", "position", "current title"],
    "company": ["company", "company name", "organization", "organization name", "firm",
                "account name", "current company"],
    "email": ["email", "work email", "email address", "corporate email", "business email"],
    "email_status": ["email status", "email confidence", "email verification"],
    "city": ["city", "person city"],
    "state": ["state", "person state", "region"],
    "country": ["country", "person country"],
    "location": ["location", "person location"],
    "profile_url": ["person linkedin url", "linkedin url", "linkedin", "profile url",
                    "linkedin profile"],
    "education": ["education", "schools", "school", "education history"],
    "past_employers": ["past employers", "employment history", "previous companies",
                       "experience", "work history", "past companies"],
    "interests": ["interests", "hobbies", "volunteering", "activities"],
    "headline_or_bio": ["headline", "bio", "summary", "about"],
    "team": ["team", "group", "department", "departments", "division"],
    "focus": ["focus", "industry focus", "sector focus", "coverage", "sectors"],
    "years_at_firm": ["years at company", "years at firm", "tenure years", "years in role"],
    # Written by `cli.py guess-emails`: the address is a guess, with backups if it bounces.
    "email_domain": ["email domain"],
    "email_patterns": ["email patterns"],
}

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", (h or "").lower()).strip()


def map_columns(headers: list[str]) -> dict[str, str]:
    normalized = {_norm_header(h): h for h in headers}
    mapping = {}
    for field, aliases in COLUMN_ALIASES.items():
        for alias in [field.replace("_", " ")] + aliases:
            if alias in normalized:
                mapping[field] = normalized[alias]
                break
    return mapping


SUFFIXES = re.compile(
    r"\b(llc|l\.?p\.?|inc|incorporated|corp|corporation|co|company|ltd|plc|group|holdings|"
    r"the|management|advisors|advisers|securities|& co)\b"
)


def norm_company(name: str) -> str:
    n = (name or "").lower().replace("&", " and ")
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    n = SUFFIXES.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip()


class FirmMatcher:
    def __init__(self, firms: list[dict]):
        self.firms = firms
        self.by_norm = {norm_company(f["name"]): f for f in firms}
        self.by_domain = {f["domain"]: f for f in firms if f.get("domain")}

    def match(self, company: str | None, email: str | None) -> dict | None:
        if email and "@" in email:
            domain = email.split("@", 1)[1].lower()
            for d, f in self.by_domain.items():
                if domain == d or domain.endswith("." + d):
                    return f
        n = norm_company(company or "")
        if not n:
            return None
        if n in self.by_norm:
            return self.by_norm[n]
        # "goldman sachs and" vs "goldman sachs": firm name as a whole-word prefix of the company
        candidates = [f for k, f in self.by_norm.items()
                      if k and (n.startswith(k + " ") or k.startswith(n + " "))]
        if len(candidates) == 1:
            return candidates[0]
        return None


def _years(value: str | None) -> float | None:
    if not value:
        return None
    m = re.search(r"\d+(\.\d+)?", value)
    return float(m.group(0)) if m else None


def import_contacts(conn, path: Path, profile: dict | None = None) -> Counter:
    """Read a provider CSV export. Returns counts of what happened to each row."""
    profile = profile or profile_mod.load()
    firms = conn.execute("select * from firms where active").fetchall()
    matcher = FirmMatcher(firms)
    stats: Counter = Counter()

    reader = csv.DictReader(path.open(newline="", encoding="utf-8-sig"))
    cols = map_columns(reader.fieldnames or [])
    missing = [c for c in ("title", "email") if c not in cols]
    if missing or ("company" not in cols):
        raise SystemExit(f"{path.name}: can't find columns {missing or ['company']}. "
                         f"Found: {reader.fieldnames}")

    def get(row, field):
        col = cols.get(field)
        v = (row.get(col) or "").strip() if col else ""
        return v or None

    suppressed = {r["email"] for r in conn.execute("select email from suppression").fetchall()}

    with conn.transaction():
        for row in reader:
            stats["rows"] += 1
            email = (get(row, "email") or "").lower()
            first, last = get(row, "first_name"), get(row, "last_name")
            if not (first and last) and get(row, "full_name"):
                parts = get(row, "full_name").split()
                first, last = parts[0], " ".join(parts[1:]) or None
            if not email or not EMAIL_RE.match(email):
                stats["skipped: no valid email"] += 1
                continue
            if email in suppressed:
                stats["skipped: on block list"] += 1
                continue
            if not (first and last):
                stats["skipped: no name"] += 1
                continue
            firm = matcher.match(get(row, "company"), email)
            if not firm:
                stats["skipped: firm not on list"] += 1
                continue
            city, state, country = get(row, "city"), get(row, "state"), get(row, "country")
            location = get(row, "location") or ", ".join(p for p in (city, state, country) if p)
            if not classify.in_us(country, state, city or location):
                stats["skipped: outside U.S."] += 1
                continue
            title = get(row, "title") or ""
            path_ = classify.career_path(firm["career_paths"], title, get(row, "team"),
                                         get(row, "headline_or_bio"))
            level = classify.seniority(title, path_)
            if not level:
                stats["skipped: title not a target"] += 1
                continue
            office = classify.office(city, location)
            if path_ == "IB" and office == "Other":
                stats["skipped: bank office not LA/NY/SF/Chicago"] += 1
                continue

            record = {
                "first_name": first.strip().title() if first.isupper() or first.islower() else first,
                "last_name": last,
                "education": get(row, "education"),
                "past_employers": get(row, "past_employers"),
                "interests": get(row, "interests"),
                "headline_or_bio": get(row, "headline_or_bio"),
            }
            ucla, bain = evidence.flags(record, profile)
            patterns = (get(row, "email_patterns") or "").split()
            provider_status = (get(row, "email_status") or "").lower()
            email_status = ("valid" if provider_status in ("verified", "valid", "deliverable")
                            else "invalid" if provider_status in ("invalid", "undeliverable", "bounced")
                            else "unchecked")

            result = conn.execute(
                """insert into contacts (first_name, last_name, firm_id, career_path, title, team,
                     focus, seniority, office, location, timezone, years_at_firm, email,
                     email_status, profile_url, education, past_employers, interests,
                     headline_or_bio, source, ucla_connection, bain_connection, email_domain,
                     email_pattern, email_patterns_left)
                   values (%(first_name)s, %(last_name)s, %(firm_id)s, %(career_path)s, %(title)s,
                     %(team)s, %(focus)s, %(seniority)s, %(office)s, %(location)s, %(timezone)s,
                     %(years)s, %(email)s, %(email_status)s, %(profile_url)s, %(education)s,
                     %(past_employers)s, %(interests)s, %(headline_or_bio)s, %(source)s,
                     %(ucla)s, %(bain)s, %(email_domain)s, %(email_pattern)s, %(patterns_left)s)
                   on conflict (email) do update set
                     title = excluded.title, team = excluded.team, focus = excluded.focus,
                     seniority = excluded.seniority, office = excluded.office,
                     location = excluded.location, timezone = excluded.timezone,
                     profile_url = coalesce(excluded.profile_url, contacts.profile_url),
                     education = coalesce(excluded.education, contacts.education),
                     past_employers = coalesce(excluded.past_employers, contacts.past_employers),
                     interests = coalesce(excluded.interests, contacts.interests),
                     headline_or_bio = coalesce(excluded.headline_or_bio, contacts.headline_or_bio),
                     ucla_connection = excluded.ucla_connection,
                     bain_connection = excluded.bain_connection,
                     email_domain = excluded.email_domain, email_pattern = excluded.email_pattern,
                     email_patterns_left = excluded.email_patterns_left
                   where contacts.status = 'new'
                   returning (xmax = 0) as inserted""",
                {**record, "firm_id": firm["id"], "career_path": path_, "title": title,
                 "team": get(row, "team"), "focus": get(row, "focus"), "seniority": level,
                 "office": office, "location": location or None,
                 "timezone": classify.TIMEZONES.get(office), "years": _years(get(row, "years_at_firm")),
                 "email": email, "email_status": email_status,
                 "profile_url": get(row, "profile_url"), "source": path.name,
                 "ucla": ucla, "bain": bain,
                 "email_domain": get(row, "email_domain") if patterns else None,
                 "email_pattern": patterns[0] if patterns else None, "patterns_left": patterns[1:]},
            ).fetchone()
            if result is None:
                stats["unchanged: already being contacted"] += 1
            elif result["inserted"]:
                stats["added"] += 1
            else:
                stats["updated"] += 1
    return stats
