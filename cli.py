"""Commands Will runs on his laptop to prepare contacts. Run `python cli.py -h` for the list.

Typical order:
    python cli.py init
    python cli.py firms data/firms.csv
    python cli.py profile data/resume.pdf          (then review data/sender_profile.json)
    python cli.py guess-emails                     (team-page people -> data/imports/ready/)
    python cli.py import data/imports/ready/*.csv
    python cli.py prepare                          (check emails, pick 20/firm, write emails, order)
    python cli.py preview 10                       (read the next emails that will go out)
"""

import argparse
import json
import random
import sys
from pathlib import Path

from outreach import config, db, drafter, guess, importer, order, quotas, stats, verify
from outreach import profile as profile_mod


def conn():
    return db.connect(config.load().database_url)


def cmd_init(args):
    print("Applied:", ", ".join(db.migrate(conn())))


def cmd_firms(args):
    c = conn()
    n = importer.load_firms(c, Path(args.path))
    rows = c.execute("select unnest(career_paths) as p, count(*) from firms group by 1").fetchall()
    print(f"Loaded {n} firms:", ", ".join(f"{r['p']} {r['count']}" for r in rows))


def cmd_profile(args):
    if args.resume:
        profile = profile_mod.build_from_resume(Path(args.resume))
        config.PROFILE_PATH.write_text(json.dumps(profile, indent=2) + "\n")
        print(f"Saved {config.PROFILE_PATH}. Please read it and delete anything wrong: "
              "only these facts can ever appear in an email.")
    else:
        print(json.dumps(profile_mod.load(), indent=2))


def cmd_import(args):
    c = conn()
    for path in args.paths:
        result = importer.import_contacts(c, Path(path))
        print(f"{Path(path).name}:")
        for k, v in sorted(result.items()):
            print(f"  {k}: {v}")


def cmd_guess_emails(args):
    result = guess.run(Path(args.people), Path(args.formats), Path(args.out), Path(args.firms))
    for k, v in sorted(result.items()):
        print(f"  {k}: {v}")
    print(f"Files with emails are in {args.out}/ (import them with: python cli.py import {args.out}/*.csv)")


def cmd_verify(args):
    s = config.load()
    print("Email check:", dict(verify.run(conn(), s.neverbounce_api_key if args.paid else "",
                                           only_selected=args.paid)))


def cmd_select(args):
    print("Picked:", dict(quotas.select(conn())))


def cmd_draft(args):
    print("Drafts:", dict(drafter.run(conn(), limit=args.limit, fallback_only=args.fallback_only,
                                      workers=args.workers)))


def cmd_order(args):
    print("Send order:", order.build(conn()))


def cmd_prepare(args):
    c = conn()
    s = config.load()
    print("1/5 Checking emails...", dict(verify.run(c)))
    print("2/5 Picking 20 per firm/office...", dict(quotas.select(c)))
    if s.neverbounce_api_key:
        print("    Paid check on picked people...", dict(verify.run(c, s.neverbounce_api_key, True)))
        print("    Re-picking after paid check...", dict(quotas.select(c)))
    print("3/5 Send order...", order.build(c))
    print("4/5 Writing emails...", dict(drafter.run(c, limit=args.limit,
                                                    fallback_only=args.fallback_only,
                                                    workers=args.workers)))
    print("5/5 Done.")
    print(stats.report(c))


def cmd_preview(args):
    settings = config.load()
    rows = conn().execute(
        """select c.send_order, c.first_name, c.last_name, c.email, c.seniority, c.career_path,
                  f.name as firm, c.personalization_tier as tier, d.subject, d.body, d.evidence
           from contacts c join firms f on f.id = c.firm_id
           join drafts d on d.contact_id = c.id and d.kind = 'first'
           where c.status = 'ready' order by c.send_order nulls last limit %s""", (args.n,)).fetchall()
    for r in rows:
        print("=" * 78)
        print(f"#{r['send_order']}  {r['first_name']} {r['last_name']} <{r['email']}>  "
              f"{r['firm']} · {r['career_path']} · {r['seniority']} · tier {r['tier']}")
        claims = (r["evidence"] or {}).get("recipient_claims") or []
        for cl in claims:
            print(f"  evidence [{cl['source_field']}]: \"{cl['quote']}\"")
        print(f"Subject: {r['subject']}\n")
        print(r["body"])
        if settings.resume_path:
            print(f"[attached: {Path(settings.resume_path).name}]")
    if not rows:
        print("No drafted emails waiting. Run `python cli.py prepare` first.")


def cmd_stats(args):
    print(stats.report(conn()))


def cmd_meeting(args):
    c = conn()
    n = c.execute("update contacts set status = 'meeting' where lower(email) = lower(%s)",
                  (args.email,)).rowcount
    c.commit()
    print("Marked as meeting." if n else "No one with that email.")


def cmd_block(args):
    c = conn()
    with c.transaction():
        c.execute("insert into suppression (email, reason) values (lower(%s), %s) "
                  "on conflict (email) do update set reason = excluded.reason",
                  (args.email, args.reason))
        c.execute("update contacts set status = 'blocked', skip_reason = %s "
                  "where lower(email) = lower(%s)", (args.reason, args.email))
    print(f"Blocked {args.email}.")


def cmd_reset_practice(args):
    """Undo practice runs: people who only ever got practice emails go back to 'ready'."""
    c = conn()
    with c.transaction():
        ids = [r["contact_id"] for r in c.execute(
            "select contact_id from sends group by contact_id having bool_and(practice)").fetchall()]
        if ids:
            c.execute("""update contacts set status = 'ready', follow_up_count = 0,
                           last_contacted_at = null, follow_up_date = null, gmail_thread_id = null,
                           first_message_id = null, first_subject = null
                         where id = any(%s) and status in ('sent', 'followup1', 'followup2',
                           'replied', 'closed')""", (ids,))
            c.execute("delete from drafts where contact_id = any(%s) and kind <> 'first'", (ids,))
            c.execute("delete from sends where practice")
        c.execute("delete from runs where id not in (select distinct run_id from sends "
                  "where run_id is not null) and status not in ('running', 'stopping')")
    print(f"Reset {len(ids)} people back to ready.")


def cmd_pending(args):
    rows = conn().execute(
        """select s.id, s.sent_at, c.email, s.kind from sends s join contacts c on c.id = s.contact_id
           where s.status = 'pending'""").fetchall()
    if not rows:
        print("No stuck sends.")
    for r in rows:
        print(f"send {r['id']}: {r['kind']} to {r['email']} at {r['sent_at']} "
              "(the worker stopped mid-send; check the sender's Sent folder, then run "
              f"`python cli.py resolve {r['id']} sent|failed`)")


def cmd_resolve(args):
    c = conn()
    with c.transaction():
        row = c.execute("update sends set status = %s where id = %s and status = 'pending' "
                        "returning contact_id, kind", (args.status, args.send_id)).fetchone()
        if row and args.status == "sent" and row["kind"] == "first":
            # It went out but we never got the thread back: count it, skip follow-ups.
            c.execute("update contacts set status = 'sent', last_contacted_at = now() "
                      "where id = %s", (row["contact_id"],))
    print("Updated." if row else "No pending send with that number.")


def cmd_doctor(args):
    """Check that everything is set up, in plain words."""
    from outreach import ai, templates

    s = config.load()
    ok = True

    def line(good, text):
        nonlocal ok
        ok &= bool(good)
        print(("  OK    " if good else "  FIX   ") + text)

    print("Settings")
    line(s.database_url, "DATABASE_URL is set")
    line(ai.available(), f"AI key is set ({ai.provider() or 'none'})")
    print("Templates")
    sample = {"career_path": "PE", "seniority": "mid", "first_name": "Kevin", "title": "Associate",
              "team": "Investment Team", "first_subject": "Hello"}
    for path in ("IB", "PE", "VC"):
        for level in ("junior", "mid", "senior"):
            try:
                templates.render_first({**sample, "career_path": path, "seniority": level},
                                       "Clearlake", "I was interested in your path.")
                line(True, templates.template_name(path, level))
            except templates.TemplateError as e:
                line(False, str(e))
    for n in (1, 2):
        try:
            templates.render_followup(n, sample, "Clearlake")
            line(True, f"followup_{n}.txt")
        except templates.TemplateError as e:
            line(False, str(e))
    if not s.database_url:
        return
    c = conn()
    print("Database")
    try:
        counts = c.execute(
            """select (select count(*) from firms) as firms,
                      (select count(*) from contacts) as people,
                      (select count(*) from contacts where selected) as picked,
                      (select count(*) from contacts where status = 'ready') as ready,
                      (select count(*) from google_tokens where status = 'ok') as signed_in,
                      (select value->>'at' from app_state where key = 'worker_heartbeat') as heartbeat
            """).fetchone()
    except Exception as e:  # tables missing
        line(False, f"database tables missing ({e.__class__.__name__}); run `python cli.py init`")
        return
    line(counts["firms"], f"{counts['firms']} firms loaded")
    line(counts["people"], f"{counts['people']} people imported, {counts['picked']} picked")
    line(counts["ready"], f"{counts['ready']} emails written and waiting to send")
    line(counts["signed_in"], f"{counts['signed_in']} Google sign-in(s) saved")
    line(counts["heartbeat"], f"sender last checked in: {counts['heartbeat'] or 'never'}")
    print("\nAll good." if ok else "\nSome things need fixing (see FIX above).")


FIRST = ["Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Avery", "Quinn", "Jamie", "Drew",
         "Cameron", "Reese", "Skyler", "Parker", "Rowan", "Emerson"]
LAST = ["Chen", "Patel", "Kim", "Nguyen", "Garcia", "Smith", "Lee", "Shah", "Brown", "Lopez",
        "Wang", "Park", "Singh", "Davis", "Cohen", "Rossi"]


def cmd_fake_contacts(args):
    """Make a CSV of made-up people at real firms (emails at example.com) for testing."""
    c = conn()
    firms = c.execute("select name, career_paths from firms order by rotation_position limit %s",
                      (args.firms,)).fetchall()
    if not firms:
        sys.exit("Load firms first.")
    rng = random.Random(7)
    titles = {"IB": ["Investment Banking Analyst", "Investment Banking Associate", "Vice President"],
              "PE": ["Private Equity Analyst", "Associate", "Vice President"],
              "VC": ["Investment Analyst", "Associate", "Principal"]}
    schools = ["UCLA", "University of Michigan", "NYU Stern", "University of California, Los Angeles",
               "Wharton", "Stanford University", "USC"]
    pasts = ["Bain & Company", "Goldman Sachs", "McKinsey & Company", "J.P. Morgan", "Bain Capital",
             "Evercore", "Deloitte", ""]
    cities = ["Los Angeles, CA", "New York, NY", "San Francisco, CA", "Chicago, IL"]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    import csv

    with out.open("w", newline="") as f:
        w = csv.writer(f)
        # "Verified" so the email check leaves these made-up addresses alone.
        w.writerow(["First Name", "Last Name", "Title", "Company", "Email", "Email Status", "City",
                    "State", "Country", "Education", "Past Employers", "Headline"])
        n = 0
        for firm in firms:
            path = firm["career_paths"][0]
            for i in range(args.per_firm):
                fn, ln = rng.choice(FIRST), rng.choice(LAST)
                title = titles[path][0 if i % 5 < 2 else 1 if i % 5 < 4 else 2]
                city, state = rng.choice(cities).split(", ")
                past = rng.choice(pasts)
                w.writerow([fn, ln, title, firm["name"], f"{fn}.{ln}.{n}@example.com".lower(),
                            "Verified", city, state, "United States", rng.choice(schools),
                            past, f"{title} at {firm['name']}" + (f"; previously {past}" if past else "")])
                n += 1
    print(f"Wrote {n} fake people to {out}")


def main():
    p = argparse.ArgumentParser(description="Outreach pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create the database tables").set_defaults(fn=cmd_init)
    s = sub.add_parser("firms", help="load the firm list CSV")
    s.add_argument("path", nargs="?", default="data/firms.csv")
    s.set_defaults(fn=cmd_firms)
    s = sub.add_parser("profile", help="build the sender's fact list from their resume (or show it)")
    s.add_argument("resume", nargs="?")
    s.set_defaults(fn=cmd_profile)
    s = sub.add_parser("import", help="import contact CSVs from the data provider")
    s.add_argument("paths", nargs="+")
    s.set_defaults(fn=cmd_import)
    s = sub.add_parser("guess-emails", help="guess emails (with backups if one bounces) from each firm's email format")
    s.add_argument("--people", default="data/imports/teampages")
    s.add_argument("--formats", default="data/imports/email_formats")
    s.add_argument("--out", default="data/imports/ready")
    s.add_argument("--firms", default="data/firms.csv")
    s.set_defaults(fn=cmd_guess_emails)
    s = sub.add_parser("verify", help="check emails")
    s.add_argument("--paid", action="store_true", help="also use NeverBounce on picked people")
    s.set_defaults(fn=cmd_verify)
    sub.add_parser("select", help="pick 20 per firm/office (8/8/4)").set_defaults(fn=cmd_select)
    for name, fn, helptext in (("draft", cmd_draft, "write emails"),
                               ("prepare", cmd_prepare, "verify + select + order + draft")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("--limit", type=int, help="only this many people")
        s.add_argument("--fallback-only", action="store_true",
                       help="no AI: use the plain fallback sentence for everyone")
        s.add_argument("--workers", type=int, default=6, help="AI requests at the same time")
        s.set_defaults(fn=fn)
    sub.add_parser("order", help="build the round-robin send order").set_defaults(fn=cmd_order)
    s = sub.add_parser("preview", help="show the next emails that will go out")
    s.add_argument("n", nargs="?", type=int, default=5)
    s.set_defaults(fn=cmd_preview)
    sub.add_parser("stats", help="results").set_defaults(fn=cmd_stats)
    s = sub.add_parser("meeting", help="mark that someone booked a meeting")
    s.add_argument("email")
    s.set_defaults(fn=cmd_meeting)
    s = sub.add_parser("block", help="never email this address")
    s.add_argument("email")
    s.add_argument("--reason", default="manual")
    s.set_defaults(fn=cmd_block)
    sub.add_parser("reset-practice", help="undo practice sends").set_defaults(fn=cmd_reset_practice)
    sub.add_parser("pending", help="show sends interrupted mid-way").set_defaults(fn=cmd_pending)
    s = sub.add_parser("resolve", help="settle an interrupted send")
    s.add_argument("send_id", type=int)
    s.add_argument("status", choices=["sent", "failed"])
    s.set_defaults(fn=cmd_resolve)
    sub.add_parser("doctor", help="check that everything is set up").set_defaults(fn=cmd_doctor)
    s = sub.add_parser("fake-contacts", help="make a test CSV of made-up people")
    s.add_argument("--firms", type=int, default=30)
    s.add_argument("--per-firm", type=int, default=10)
    s.add_argument("--out", default="data/imports/fake_contacts.csv")
    s.set_defaults(fn=cmd_fake_contacts)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
