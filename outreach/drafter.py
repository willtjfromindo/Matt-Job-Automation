"""Write each person's email: template + an AI-written personal line (1-2 sentences), checked by qa.py.

Flow per person:
  1. evidence.find() looks for a real school / employer / hobby connection (tiers A-C).
  2. The AI writes the personal sentence, citing exact quotes from the record (A-C, or D/E).
  3. qa.check() verifies it. One retry with the problems listed. If it still fails, the safe
     fallback sentence (templates/fallback_line.txt) is used instead.
  4. The filled-in email is saved as a draft and the person becomes 'ready'.
"""

import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from psycopg.types.json import Jsonb

from . import ai, config, evidence, qa, templates
from . import profile as profile_mod
from .config import TEMPLATES_DIR

FIELDS_FOR_AI = ("firm", "title", "team", "focus", "education", "past_employers",
                 "headline_or_bio", "interests")

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "personal_line": {"type": "string"},
        "tier": {"type": "string", "enum": ["A", "B", "C", "D", "E"]},
        "sender_fact_ids": {"type": "array", "items": {"type": "string"}},
        "recipient_claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "source_field": {"type": "string", "enum": list(FIELDS_FOR_AI)},
                    "quote": {"type": "string"},
                },
                "required": ["claim", "source_field", "quote"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["personal_line", "tier", "sender_fact_ids", "recipient_claims"],
    "additionalProperties": False,
}


def system_prompt(profile: dict) -> str:
    facts = "\n".join(f"- [{f['id']}] {f['text']}" for f in profile.get("facts", []))
    settings = config.load()
    sender = profile.get("name") or settings.sender_name or "the student"
    school = settings.sender_school or "their university"
    intro = settings.sender_intro or "<the sender's one-line introduction>"
    return f"""You write one or two sentences for a networking email from {sender},
a {school} student, to someone in investment banking, private equity or venture capital. They go
right after their intro and before their ask:

  "{intro} <YOUR SENTENCES>

   I'd be grateful for 15 minutes to hear about your career and how you developed your
   perspective on private equity investing. I've attached my resume for context."

Write in the sender's own plain voice. Lines of this shape work well:
  Record showed UCLA, then Advent and CVC:
    "I came across your background and was excited to see that you also studied Business
     Economics at UCLA. Your path from UCLA through investing roles at Advent and CVC
     particularly caught my attention."
  Record showed Duke's investment club, then Houlihan Lokey's Financial Restructuring group:
    "I've been learning more about Houlihan Lokey's Los Angeles investment banking practice and
     came across your path from Duke's investment club and economics work into Houlihan Lokey's
     Financial Restructuring group."

Too much (sounds like a robot reading a bio):
    "Your move to the technology team at Advent International focusing on growth and
     buyout-stage investments, and then to TCV where you focus on infrastructure software,
     cybersecurity, and AI, stood out to me."
Just right (same person):
    "I came across your background and was excited to see that you also started your career at
     Bain. Your path from Bain through Advent to TCV particularly caught my attention."
Just right (no shared school or employer):
    "I came across your background and saw your path from Citi's investment banking team into
     TJC, which particularly caught my attention."

How to write it:
- Simple, warm, polite: a real student writing to someone he looks up to. Everyday words.
- 15 to 35 words. One or two sentences.
- Name at most two or three things from their path (a school, past firms, a group). Use the
  short name people say out loud (Advent, CVC, Citi, Goldman), not the full legal name.
- No lists of sectors, no years, cities, job titles, degrees, deal or company names they
  invested in, and no describing their day-to-day work.
- If there is a shared school or employer, lead with it: "you also studied at UCLA", "you also
  started your career at Bain", "you also spent time at Bain". Call the school UCLA; say Bain,
  not Bain & Company (the intro already says it).
- Otherwise talk only about the person's path. Don't add anything about the sender.
- Only say "from X to Y" when the record says which came first.
- Don't repeat the intro, ask for anything, ask questions, use exclamation marks, flatter
  (impressive, amazing, a strong foundation), or mention LinkedIn or a profile.
- No quote marks, brackets or field names in the sentences.
- Write the current firm's name exactly as given.

Facts about the sender you may use (cite their ids; nothing else about them):
{facts}

Evidence: for every fact about the person, give the record field and a quote copied
character-for-character from that field (a short name like "Advent" is fine to quote when the
field says "Advent International"). Never invent anything.

Tiers: if a connection is provided, use its tier (A = same school, B = shared employer,
C = shared interest) and mention it. If none is provided, use tier D when the record says
something about their path (past firms or roles, school, group), otherwise tier E, which only
mentions their work at the firm."""


def user_prompt(record: dict, ev: evidence.Evidence) -> str:
    data = {k: record.get(k) for k in FIELDS_FOR_AI if record.get(k)}
    msg = "Person's record:\n" + json.dumps(data, indent=2)
    if ev.tier:
        msg += (f"\n\nConnection found (tier {ev.tier}): {ev.label}. "
                f"Field {ev.source_field!r} says: {ev.quote!r}")
    else:
        msg += "\n\nNo school/employer/hobby connection found. Use tier D or E."
    return msg


def fallback_line(record: dict) -> str:
    text = (TEMPLATES_DIR / "fallback_line.txt").read_text().strip()
    return templates.fill(text, {"first_name": record["first_name"], "firm": record["firm"],
                                 "title": record.get("title"), "team": record.get("team")}).strip()


def thin_record(record: dict, ev: evidence.Evidence) -> bool:
    """Only a title and team to go on: the AI can't say anything real, so use the plain sentence."""
    return not ev.tier and not any(record.get(k) for k in
                                   ("education", "past_employers", "headline_or_bio", "interests", "focus"))


def write_line(record: dict, profile: dict, ev: evidence.Evidence, same_firm: list[str]) -> dict:
    """Get a checked personal line, or the fallback. Never raises for AI/QA problems."""
    system = system_prompt(profile)
    prompt = user_prompt(record, ev)
    all_issues: list[list[str]] = []
    for attempt in (1, 2):
        try:
            result = ai.complete_json(system, prompt, RESULT_SCHEMA, "personal_line")
        except ai.AIError as e:
            all_issues.append([f"AI error: {e}"])
            continue
        issues = qa.check(result, record, profile, ev.tier, ev.label, same_firm)
        if not issues:
            return {**result, "attempts": attempt, "qa_issues": all_issues, "fallback": False}
        all_issues.append(issues)
        prompt = (user_prompt(record, ev) + "\n\nYour previous answer was rejected:\n"
                  + json.dumps(result) + "\nProblems:\n- " + "\n- ".join(issues)
                  + "\nFix them.")
    return {"personal_line": fallback_line(record), "tier": "E", "sender_fact_ids": [],
            "recipient_claims": [], "attempts": 2, "qa_issues": all_issues, "fallback": True}


def pending(conn, limit: int | None) -> list[dict]:
    sql = """select c.*, f.name as firm from contacts c join firms f on f.id = c.firm_id
             where c.selected and c.status = 'new' and c.email_status <> 'invalid'
               and c.email not in (select email from suppression)
             order by c.send_order nulls last, c.id"""
    if limit:
        sql += f" limit {int(limit)}"
    return conn.execute(sql).fetchall()


def save(conn, record: dict, ev: evidence.Evidence, line_result: dict) -> None:
    name, subject, body = templates.render_first(record, record["firm"], line_result["personal_line"])
    tier = line_result["tier"]
    claims = line_result.get("recipient_claims") or []
    first_claim = claims[0] if claims else {}
    with conn.transaction():
        conn.execute(
            """insert into drafts (contact_id, kind, template, subject, body, personal_line,
                 evidence, qa_passed, qa_issues, attempts)
               values (%s, 'first', %s, %s, %s, %s, %s, true, %s, %s)
               on conflict (contact_id, kind) do update set template = excluded.template,
                 subject = excluded.subject, body = excluded.body,
                 personal_line = excluded.personal_line, evidence = excluded.evidence,
                 qa_passed = true, qa_issues = excluded.qa_issues, attempts = excluded.attempts,
                 created_at = now()""",
            (record["id"], name, subject, body, line_result["personal_line"],
             Jsonb({"tier": tier, "sender_fact_ids": line_result.get("sender_fact_ids"),
                    "recipient_claims": claims, "fallback": line_result.get("fallback", False),
                    "matched": {"tier": ev.tier, "label": ev.label, "field": ev.source_field,
                                "quote": ev.quote}}),
             Jsonb(line_result.get("qa_issues") or []), line_result.get("attempts", 1)),
        )
        conn.execute(
            """update contacts set status = 'ready', personalization_tier = %s,
                 personalization_source = %s, personalization_fact = %s, other_connection = %s
               where id = %s and status = 'new'""",
            (tier, first_claim.get("source_field") or ev.source_field,
             first_claim.get("quote") or ev.quote, ev.label if ev.tier == "C" else None,
             record["id"]),
        )


def run(conn, limit: int | None = None, fallback_only: bool = False, workers: int = 6,
        progress=print) -> Counter:
    """Draft emails for selected people who don't have one yet."""
    profile = profile_mod.load()
    records = pending(conn, limit)
    stats: Counter = Counter()
    if not records:
        return stats
    if not fallback_only and not ai.available():
        raise SystemExit("No AI key found. Add OPENAI_API_KEY to .env "
                         "(or run with --fallback-only to use the plain sentence for everyone).")

    # Lines already written at each firm, to avoid near-duplicates.
    firm_lines: dict[int, list[str]] = {}
    for row in conn.execute(
        "select c.firm_id, d.personal_line from drafts d join contacts c on c.id = d.contact_id "
        "where d.kind = 'first'"
    ).fetchall():
        firm_lines.setdefault(row["firm_id"], []).append(row["personal_line"])

    def job(record):
        ev = evidence.find(record, profile)
        if fallback_only or thin_record(record, ev):
            return record, ev, {"personal_line": fallback_line(record), "tier": "E",
                                "sender_fact_ids": [], "recipient_claims": [], "attempts": 0,
                                "fallback": True}
        return record, ev, write_line(record, profile, ev, list(firm_lines.get(record["firm_id"], [])))

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(job, r) for r in records]
        for i, fut in enumerate(as_completed(futures), start=1):
            record, ev, result = fut.result()
            try:
                save(conn, record, ev, result)
            except templates.TemplateError as e:
                conn.execute("update contacts set skip_reason = %s where id = %s",
                             (str(e), record["id"]))
                conn.commit()
                stats["skipped: template problem"] += 1
                continue
            firm_lines.setdefault(record["firm_id"], []).append(result["personal_line"])
            stats[f"tier {result['tier']}"] += 1
            if result.get("fallback") and not fallback_only:
                stats["plain sentence: bio too thin" if result.get("attempts") == 0
                      else "plain sentence: AI line failed checks"] += 1
            if i % 25 == 0:
                progress(f"  {i}/{len(records)} drafted")
    return stats
