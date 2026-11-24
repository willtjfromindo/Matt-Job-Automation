import base64
import csv
import email.policy
import json
import os
from datetime import datetime, timedelta, timezone
from email import message_from_bytes

import httpx
import pytest

from outreach import config, crypto, drafter, gmail, guess, importer, inbox, order, quotas, sender
from tests.test_pipeline import big_import

KEY = base64.b64encode(os.urandom(32)).decode()


def settings(**over):
    base = dict(database_url="", sender_email="alex@example.edu", sender_name="Alex Rivera",
                practice_mode=False, practice_inbox="", daily_limit=1000, min_gap_seconds=25,
                max_gap_seconds=40, google_client_id="cid", google_client_secret="secret",
                token_encryption_key=KEY, neverbounce_api_key="", bounce_stop_rate=0.05,
                bounce_stop_min_sends=40, followup1_business_days=5, followup2_business_days=7)
    base.update(over)
    return config.Settings(**base)


class FakeGmail:
    def __init__(self):
        self.sent = []
        self.inbox = {}      # id -> metadata
        self.fail_with = None

    def send(self, to, subject, body, thread_id=None, in_reply_to=None, attachments=None):
        if self.fail_with:
            raise self.fail_with
        n = len(self.sent) + 1
        self.sent.append({"to": to, "subject": subject, "body": body, "thread_id": thread_id,
                          "in_reply_to": in_reply_to, "attachments": attachments})
        return {"id": f"m{n}", "threadId": thread_id or f"t{n}", "rfc_message_id": f"<r{n}@x>"}

    def list_message_ids(self, query, max_results=500):
        return list(self.inbox)

    def get_message(self, mid, headers):
        return self.inbox[mid]


def ready(conn, tmp_path):
    big_import(conn, tmp_path)
    quotas.select(conn)
    order.build(conn)
    drafter.run(conn, fallback_only=True)


def start_run(conn, n):
    rid = conn.execute("insert into runs (requested_count, started_by) values (%s, 'm') returning id",
                       (n,)).fetchone()["id"]
    conn.commit()
    return conn.execute("select * from runs where id = %s", (rid,)).fetchone()


def no_sleep(_):
    pass


def test_run_sends_n_in_order_with_random_gaps(conn, tmp_path):
    ready(conn, tmp_path)
    run = start_run(conn, 5)
    g = FakeGmail()
    gaps = []
    sender.process_run(conn, run, settings(), g, sleep=no_sleep,
                       rand=lambda a, b: gaps.append((a, b)) or 0)
    assert len(g.sent) == 5
    assert gaps == [(25, 40)] * 4          # random wait between every pair of emails
    r = conn.execute("select * from runs where id = %s", (run["id"],)).fetchone()
    assert r["status"] == "done" and r["sent_count"] == 5
    sent_people = conn.execute(
        "select email, send_order from contacts where status = 'sent' order by send_order").fetchall()
    assert [s["email"] for s in sent_people] == [m["to"] for m in g.sent]
    assert [s["send_order"] for s in sent_people] == sorted(s["send_order"] for s in sent_people)
    assert sender.sent_today(conn) == 5


def test_practice_mode_redirects_every_email(conn, tmp_path):
    ready(conn, tmp_path)
    g = FakeGmail()
    sender.process_run(conn, start_run(conn, 3), settings(practice_mode=True,
                       practice_inbox="will@test.com"), g, sleep=no_sleep, rand=lambda a, b: 0)
    assert {m["to"] for m in g.sent} == {"will@test.com"}
    assert conn.execute("select bool_and(practice) as p from sends").fetchone()["p"]


def test_practice_mode_without_inbox_refuses(conn, tmp_path):
    ready(conn, tmp_path)
    g = FakeGmail()
    run = start_run(conn, 3)
    sender.process_run(conn, run, settings(practice_mode=True), g, sleep=no_sleep)
    assert g.sent == []
    assert conn.execute("select status from runs").fetchone()["status"] == "error"


def test_stop_button(conn, tmp_path):
    ready(conn, tmp_path)
    run = start_run(conn, 50)
    g = FakeGmail()

    def sleep_and_press_stop(_):
        if len(g.sent) == 3:
            conn.execute("update runs set status = 'stopping' where id = %s", (run["id"],))
            conn.commit()

    sender.process_run(conn, run, settings(), g, sleep=sleep_and_press_stop, rand=lambda a, b: 1)
    r = conn.execute("select * from runs where id = %s", (run["id"],)).fetchone()
    assert len(g.sent) == 3 and r["status"] == "stopped" and r["sent_count"] == 3


def test_daily_limit(conn, tmp_path):
    ready(conn, tmp_path)
    g = FakeGmail()
    sender.process_run(conn, start_run(conn, 10), settings(daily_limit=4), g, sleep=no_sleep,
                       rand=lambda a, b: 0)
    assert len(g.sent) == 4
    assert "Daily limit" in conn.execute("select message from runs").fetchone()["message"]


def test_followups_first_and_threaded(conn, tmp_path, monkeypatch):
    ready(conn, tmp_path)
    monkeypatch.setattr(sender, "FIRM_SPACING", 1)   # the follow-up's firm wasn't just emailed
    g = FakeGmail()
    sender.process_run(conn, start_run(conn, 2), settings(), g, sleep=no_sleep, rand=lambda a, b: 0)
    first_two = list(g.sent)
    # Pretend 5 business days passed for the first person.
    conn.execute("update contacts set follow_up_date = now() - interval '1 minute' "
                 "where gmail_thread_id = 't1'")
    conn.commit()
    sender.process_run(conn, start_run(conn, 2), settings(), g, sleep=no_sleep, rand=lambda a, b: 0)
    fu = g.sent[2]
    assert fu["to"] == first_two[0]["to"]
    assert fu["thread_id"] == "t1" and fu["in_reply_to"] == "<r1@x>"
    assert fu["subject"].startswith("Re: ")
    assert g.sent[3]["to"] not in {m["to"] for m in first_two}   # then the next new person
    c = conn.execute("select status, follow_up_count from contacts where gmail_thread_id = 't1'").fetchone()
    assert c["status"] == "followup1" and c["follow_up_count"] == 1


def firm_of(conn, email):
    return conn.execute("select firm_id from contacts where email = %s", (email,)).fetchone()["firm_id"]


def test_same_firm_is_never_emailed_twice_close_together(conn, tmp_path):
    ready(conn, tmp_path)
    # Real case: three people at one firm sat next to each other at the end of the warm list.
    first_three = conn.execute("select id, firm_id from contacts where status = 'ready' "
                               "order by send_order limit 3").fetchall()
    conn.execute("update contacts set firm_id = %s where id = any(%s)",
                 (first_three[0]["firm_id"], [r["id"] for r in first_three]))
    firms_left = conn.execute("select count(distinct firm_id) as n from contacts "
                              "where status = 'ready'").fetchone()["n"]
    g = FakeGmail()
    sender.process_run(conn, start_run(conn, 40), settings(), g, sleep=no_sleep, rand=lambda a, b: 0)
    firms = [firm_of(conn, m["to"]) for m in g.sent]
    assert len(firms) == 40
    # Every stretch of emails as long as the number of firms has no firm twice.
    window = min(sender.FIRM_SPACING, firms_left)
    for i in range(len(firms) - window + 1):
        assert len(set(firms[i:i + window])) == window
    # The three are still emailed, just spread out.
    three = conn.execute("select email from contacts where id = any(%s)",
                         ([r["id"] for r in first_three],)).fetchall()
    assert {r["email"] for r in three} <= {m["to"] for m in g.sent}


def test_followup_waits_if_its_firm_was_just_emailed(conn, tmp_path):
    ready(conn, tmp_path)
    g = FakeGmail()
    sender.process_run(conn, start_run(conn, 1), settings(), g, sleep=no_sleep, rand=lambda a, b: 0)
    conn.execute("update contacts set follow_up_date = now() - interval '1 minute' "
                 "where gmail_thread_id = 't1'")
    conn.commit()
    sender.process_run(conn, start_run(conn, 1), settings(), g, sleep=no_sleep, rand=lambda a, b: 0)
    # The follow-up would be a second email to the same firm in a row, so a new person goes first.
    assert g.sent[1]["thread_id"] is None
    assert firm_of(conn, g.sent[1]["to"]) != firm_of(conn, g.sent[0]["to"])


def test_needs_reauth_stops_run(conn, tmp_path):
    ready(conn, tmp_path)
    g = FakeGmail()
    g.fail_with = gmail.NeedsReauth("expired")
    sender.process_run(conn, start_run(conn, 3), settings(), g, sleep=no_sleep)
    r = conn.execute("select * from runs").fetchone()
    assert r["status"] == "error" and r["message"] == "Please sign in again"
    assert conn.execute("select count(*) as n from sends").fetchone()["n"] == 0
    assert conn.execute("select count(*) as n from contacts where status = 'ready'").fetchone()["n"] > 0


def test_repeated_failures_stop_run_and_pending_is_skipped(conn, tmp_path):
    ready(conn, tmp_path)
    g = FakeGmail()
    g.fail_with = gmail.GmailError("Gmail POST /messages/send: 500 oops", 500)
    sender.process_run(conn, start_run(conn, 10), settings(), g, sleep=no_sleep, rand=lambda a, b: 0)
    assert conn.execute("select status from runs").fetchone()["status"] == "error"
    assert conn.execute("select count(*) as n from sends where status = 'failed'").fetchone()["n"] == 3
    # A send interrupted mid-way ('pending') is never retried automatically.
    nxt = sender.next_item(conn)
    conn.execute("insert into sends (contact_id, kind, to_email, status) values (%s, 'first', 'x', 'pending')",
                 (nxt["contact"]["id"],))
    assert sender.next_item(conn)["contact"]["id"] != nxt["contact"]["id"]


def test_suppressed_people_are_never_sent(conn, tmp_path):
    ready(conn, tmp_path)
    nxt = sender.next_item(conn)["contact"]
    conn.execute("insert into suppression (email, reason) values (%s, 'manual')", (nxt["email"],))
    g = FakeGmail()
    sender.process_run(conn, start_run(conn, 3), settings(), g, sleep=no_sleep, rand=lambda a, b: 0)
    assert nxt["email"] not in {m["to"] for m in g.sent}


def meta(thread, sender_, subject="Re: hi", snippet="", **headers):
    hs = [{"name": "From", "value": sender_}, {"name": "Subject", "value": subject}]
    hs += [{"name": k.replace("_", "-"), "value": v} for k, v in headers.items()]
    return {"threadId": thread, "snippet": snippet, "payload": {"headers": hs}}


def test_inbox_sync_reply_bounce_optout_autoreply(conn, tmp_path):
    ready(conn, tmp_path)
    g = FakeGmail()
    sender.process_run(conn, start_run(conn, 4), settings(), g, sleep=no_sleep, rand=lambda a, b: 0)
    emails = [m["to"] for m in g.sent]
    g.inbox = {
        "a": meta("t1", f"Person <{emails[0]}>", snippet="Happy to chat next week"),
        "b": meta("t2", "Mail Delivery Subsystem <mailer-daemon@googlemail.com>",
                  subject="Delivery Status Notification (Failure)"),
        "c": meta("t3", emails[2], snippet="Please remove me from your list"),
        "d": meta("t4", emails[3], subject="Automatic reply: Out of Office", Auto_Submitted="auto-replied"),
        "e": meta("zzz", "stranger@x.com", snippet="hello"),
    }
    stats = inbox.sync(conn, g)
    assert stats == {"reply": 1, "bounce": 1, "opt_out": 1, "auto": 1}
    status = {r["email"]: r["status"] for r in conn.execute("select email, status from contacts").fetchall()}
    assert status[emails[0]] == "replied"
    assert status[emails[1]] == "blocked"
    assert status[emails[2]] == "blocked"
    assert status[emails[3]] == "sent"          # out-of-office doesn't count as a reply
    blocked = {r["email"]: r["reason"] for r in conn.execute("select * from suppression").fetchall()}
    assert blocked == {emails[1]: "bounced", emails[2]: "opted_out"}
    assert conn.execute("select count(*) as n from sends where status = 'bounced'").fetchone()["n"] == 1
    # Running it again doesn't double count.
    assert inbox.sync(conn, g) == {}


def test_business_days():
    fri = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
    assert sender.add_business_days(fri, 5) == fri + timedelta(days=7)
    assert sender.add_business_days(fri, 1).weekday() == 0


def test_loop_picks_up_run_and_writes_heartbeat(conn, tmp_path):
    ready(conn, tmp_path)
    start_run(conn, 1)
    g = FakeGmail()
    sender.loop(conn, settings(), g, once=True)
    assert len(g.sent) == 1
    assert conn.execute("select value from app_state where key = 'worker_heartbeat'").fetchone()


# ---------- the real Gmail client against a fake Google ----------

def google_transport(state):
    def handler(request: httpx.Request):
        if request.url.path == "/token":
            body = dict(x.split("=") for x in request.content.decode().split("&"))
            state["refresh_token_seen"] = body["refresh_token"]
            if state.get("revoked"):
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "AT", "expires_in": 3600})
        assert request.headers["Authorization"] == "Bearer AT"
        if request.url.path.endswith("/messages/send"):
            payload = json.loads(request.content)
            state["raw"] = message_from_bytes(base64.urlsafe_b64decode(payload["raw"]), policy=email.policy.default)
            state["thread"] = payload.get("threadId")
            return httpx.Response(200, json={"id": "M1", "threadId": "T1"})
        if "/messages/M1" in request.url.path:
            return httpx.Response(200, json={"payload": {"headers": [
                {"name": "Message-ID", "value": "<gmail-id@mail.gmail.com>"}]}})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def test_real_gmail_client_send_and_reauth(conn):
    s = settings()
    conn.execute("insert into google_tokens (email, encrypted_refresh_token) values (%s, %s)",
                 (s.sender_email, crypto.encrypt("REFRESH", KEY)))
    conn.commit()
    state = {}
    client = gmail.Gmail(conn, s, http=httpx.Client(transport=google_transport(state)),
                         token_url="https://google.test/token", api="https://google.test/gmail")
    out = client.send("kevin@clearlake.com", "Hello", "Body text", thread_id="T0",
                      in_reply_to="<orig@x>")
    assert state["refresh_token_seen"] == "REFRESH"
    assert out == {"id": "M1", "threadId": "T1", "rfc_message_id": "<gmail-id@mail.gmail.com>"}
    raw = state["raw"]
    assert raw["To"] == "kevin@clearlake.com" and raw["Subject"] == "Hello"
    assert raw["From"] == "Alex Rivera <alex@example.edu>"
    assert raw["In-Reply-To"] == "<orig@x>" and state["thread"] == "T0"
    assert raw.get_body(preferencelist=("plain",)).get_content().strip() == "Body text"
    assert "<div>Body text</div>" in raw.get_body(preferencelist=("html",)).get_content()

    state["revoked"] = True
    client2 = gmail.Gmail(conn, s, http=httpx.Client(transport=google_transport(state)),
                          token_url="https://google.test/token", api="https://google.test/gmail")
    with pytest.raises(gmail.NeedsReauth):
        client2.send("a@b.com", "x", "y")
    assert conn.execute("select status from google_tokens").fetchone()["status"] == "needs_reauth"


def test_only_one_sender_at_a_time(conn, tmp_path, _database):
    from outreach import db

    ready(conn, tmp_path)
    start_run(conn, 1)
    assert sender.acquire_lock(conn, once=True)
    other = db.connect(_database)
    try:
        g = FakeGmail()
        sender.loop(other, settings(), g, once=True)    # second copy can't get the lock
        assert g.sent == []
    finally:
        other.close()


# ---------- guessed emails: resend to the next guess when one bounces ----------

BOUNCE_FROM = "Mail Delivery Subsystem <mailer-daemon@googlemail.com>"


class BouncingGmail(FakeGmail):
    """Bounces every address not in `good`, the way Gmail does: a failure notice in the thread."""

    def __init__(self, good=()):
        super().__init__()
        self.good = set(good)

    def send(self, to, subject, body, thread_id=None, in_reply_to=None, attachments=None):
        result = super().send(to, subject, body, thread_id, in_reply_to, attachments)
        if to not in self.good:
            self.inbox[f"bounce{len(self.sent)}"] = meta(
                result["threadId"], BOUNCE_FROM, subject="Delivery Status Notification (Failure)",
                X_Failed_Recipients=to)
        return result


def guessed_people(conn, names, domain="firm.com"):
    """Make the first people in the send order guessed addresses at one domain."""
    rows = conn.execute("select id from contacts where status = 'ready' and selected "
                        "order by send_order limit %s", (len(names),)).fetchall()
    for r, (first, last) in zip(rows, names):
        p = guess.COMMON_PATTERNS
        conn.execute(
            """update contacts set first_name = %s, last_name = %s, email = %s, email_domain = %s,
                 email_pattern = %s, email_patterns_left = %s where id = %s""",
            (first, last, guess.build_email(first, last, p[0], domain), domain, p[0], p[1:], r["id"]))
    return [r["id"] for r in rows]


@pytest.fixture
def fast_clock(monkeypatch):
    """Waiting moves every send back in time instead of really sleeping."""
    def fake_wait(conn, run_id, seconds, sleep=None):
        conn.execute("update sends set sent_at = sent_at - make_interval(secs => %s)", (seconds,))
        return conn.execute("select status from runs where id = %s", (run_id,)).fetchone()["status"] == "running"
    monkeypatch.setattr(sender, "wait", fake_wait)


def contact(conn, cid):
    return conn.execute("select * from contacts where id = %s", (cid,)).fetchone()


def test_bounced_guess_is_resent_to_next_guess_in_same_run(conn, tmp_path, fast_clock):
    ready(conn, tmp_path)
    [nathan] = guessed_people(conn, [("Nathan", "Halim")])
    g = BouncingGmail(good={"nhalim@firm.com"})
    run = start_run(conn, 1)
    sender.process_run(conn, run, settings(), g, rand=lambda a, b: 0)
    assert [m["to"] for m in g.sent] == ["nathan.halim@firm.com", "nhalim@firm.com"]
    r = conn.execute("select * from runs where id = %s", (run["id"],)).fetchone()
    assert r["status"] == "done" and r["sent_count"] == 1     # one person, two tries
    c = contact(conn, nathan)
    assert c["status"] == "sent" and c["email"] == "nhalim@firm.com"
    assert c["gmail_thread_id"] == "t2"                       # follow-ups go to the address that worked
    sends = conn.execute("select to_email, status, email_pattern from sends order by id").fetchall()
    assert [(s["status"], s["email_pattern"]) for s in sends] == [("bounced", "{first}.{last}"),
                                                                  ("sent", "{f}{last}")]
    assert conn.execute("select reason from suppression where email = 'nathan.halim@firm.com'"
                        ).fetchone()["reason"] == "bounced"


def test_next_person_at_firm_starts_with_the_pattern_that_worked(conn, tmp_path, fast_clock):
    ready(conn, tmp_path)
    nathan, jane, bob = guessed_people(conn, [("Nathan", "Halim"), ("Jane", "Smith"), ("Bob", "Jones")])
    g = BouncingGmail(good={"nhalim@firm.com", "jsmith@firm.com"})
    sender.process_run(conn, start_run(conn, 1), settings(), g, rand=lambda a, b: 0)
    sender.process_run(conn, start_run(conn, 1), settings(), g, rand=lambda a, b: 0)
    assert [m["to"] for m in g.sent][2:] == ["jsmith@firm.com"]   # no wasted first.last guess
    assert contact(conn, jane)["status"] == "sent"
    # The firm's pattern is now proven, so a bounce means Bob likely left: no more guesses.
    sender.process_run(conn, start_run(conn, 1), settings(), g, rand=lambda a, b: 0)
    assert [m["to"] for m in g.sent][3:] == ["bjones@firm.com"]
    b = contact(conn, bob)
    assert b["status"] == "blocked" and b["skip_reason"] == "bounced"


def test_out_of_guesses_blocks_person(conn, tmp_path, fast_clock):
    ready(conn, tmp_path)
    [nathan] = guessed_people(conn, [("Nathan", "Halim")])
    g = BouncingGmail()
    sender.process_run(conn, start_run(conn, 1), settings(), g, rand=lambda a, b: 0)
    assert [m["to"] for m in g.sent] == ["nathan.halim@firm.com", "nhalim@firm.com", "nathan@firm.com"]
    c = contact(conn, nathan)
    assert c["status"] == "blocked" and c["skip_reason"] == "bounced"


def test_daily_bounce_cap_pauses_sending(conn, tmp_path, fast_clock):
    ready(conn, tmp_path)
    guessed_people(conn, [("Nathan", "Halim"), ("Jane", "Smith")])
    g = BouncingGmail()
    run = start_run(conn, 2)
    sender.process_run(conn, run, settings(max_bounces_per_day=2), g, rand=lambda a, b: 0)
    r = conn.execute("select * from runs where id = %s", (run["id"],)).fetchone()
    assert r["status"] == "auto_stopped" and r["message"].startswith("Paused: 2 emails bounced today")
    assert sender.bounces_today(conn) == 2


def test_real_addresses_are_never_swapped(conn, tmp_path, fast_clock):
    ready(conn, tmp_path)
    g = BouncingGmail()
    sender.process_run(conn, start_run(conn, 1), settings(), g, rand=lambda a, b: 0)
    assert len(g.sent) == 1          # a real address isn't waited on or swapped...
    assert inbox.sync(conn, g) == {"bounce": 1}   # ...a bounce just blocks them
    assert conn.execute("select count(*) as n from contacts where skip_reason = 'bounced'").fetchone()["n"] == 1


def test_guess_files_and_import(conn, tmp_path):
    team, formats, out = tmp_path / "team", tmp_path / "formats", tmp_path / "out"
    team.mkdir(), formats.mkdir()
    header = ["First Name", "Last Name", "Title", "Company", "Email", "City", "State", "Country"]

    def write(path, header, rows):
        with path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)

    write(team / "a.csv", header, [
        ["Nathan", "Halim", "Associate", "Acme Capital", "", "New York", "NY", "United States"],
        ["Nina", "Halim", "Associate", "Acme Capital", "", "New York", "NY", "United States"],
        ["Ana", "Ruiz-Lee", "Analyst", "Acme Capital", "", "", "", ""],
        ["Real", "Person", "Principal", "Acme Capital", "rp@acme.com", "", "", ""],
    ])
    write(team / "b.csv", header, [["Bo", "Chen", "Associate", "Beta Partners", "", "", "", ""]])
    write(team / "c.csv", header, [["Cy", "Dunn", "Associate", "No Mail Fund", "", "", "", ""]])
    write(formats / "f.csv", ["Company", "email_domain", "pattern", "status"],
          [["Acme Capital", "acme.com", "{first}.{last}", "confirmed"]])
    write(tmp_path / "firms.csv", ["name", "career_paths", "per_office", "rank_source", "domain"],
          [["Acme Capital", "PE", "false", "", "acme-capital.com"],
           ["Beta Partners", "VC", "false", "", "beta.vc"],
           ["No Mail Fund", "VC", "false", "", "nomail.com"]])
    stats = guess.run(team, formats, out, tmp_path / "firms.csv", accepts_mail=lambda d: d != "nomail.com")
    rows = {r["First Name"]: r for f in sorted(out.glob("*.csv")) for r in csv.DictReader(f.open())}
    # Confirmed format first, one backup; nhalim would collide for Nathan and Nina, so it's dropped.
    assert rows["Nathan"]["Email"] == "nathan.halim@acme.com"
    assert rows["Nathan"]["Email Patterns"] == "{first}.{last}"
    assert rows["Real"]["Email"] == "rp@acme.com" and rows["Real"]["Email Patterns"] == ""
    assert "Ana" not in rows and "Cy" not in rows
    # Unknown format: the 3 common patterns, at the firm's website domain.
    assert rows["Bo"]["Email"] == "bo.chen@beta.vc"
    assert rows["Bo"]["Email Patterns"] == "{first}.{last} {f}{last} {first}"
    assert stats["skipped: name too risky to guess"] == 1

    importer.load_firms(conn, tmp_path / "firms.csv")
    importer.import_contacts(conn, out / "b.csv")
    c = conn.execute("select * from contacts where email = 'bo.chen@beta.vc'").fetchone()
    assert (c["email_domain"], c["email_pattern"], c["email_patterns_left"]) == (
        "beta.vc", "{first}.{last}", ["{f}{last}", "{first}"])


def test_resume_attached_to_first_emails_only(conn, tmp_path, monkeypatch):
    ready(conn, tmp_path)
    monkeypatch.setattr(sender, "FIRM_SPACING", 1)   # let the follow-up go right away
    resume = tmp_path / "Alex_Rivera_Resume.pdf"
    resume.write_bytes(b"%PDF-1.4 test")
    g = FakeGmail()
    sender.process_run(conn, start_run(conn, 2), settings(resume_path=str(resume)), g,
                       sleep=no_sleep, rand=lambda a, b: 0)
    assert [m["attachments"] for m in g.sent] == [[str(resume)]] * 2
    conn.execute("update contacts set follow_up_date = now() - interval '1 day' where status = 'sent'")
    sender.process_run(conn, start_run(conn, 1), settings(resume_path=str(resume)), g,
                       sleep=no_sleep, rand=lambda a, b: 0)
    assert g.sent[2]["thread_id"] and g.sent[2]["attachments"] is None   # follow-up: no resume


def test_missing_resume_stops_before_sending(conn, tmp_path):
    ready(conn, tmp_path)
    g = FakeGmail()
    run = start_run(conn, 2)
    sender.process_run(conn, run, settings(resume_path=str(tmp_path / "missing.pdf")), g,
                       sleep=no_sleep, rand=lambda a, b: 0)
    assert g.sent == []
    assert conn.execute("select status from runs where id = %s", (run["id"],)).fetchone()["status"] == "error"


def test_gmail_message_carries_the_attachment(tmp_path):
    resume = tmp_path / "Alex_Rivera_Resume.pdf"
    resume.write_bytes(b"%PDF-1.4 test")
    captured = {}

    def handler(request):
        if request.url.path.endswith("/messages/send"):
            captured["raw"] = json.loads(request.content)["raw"]
            return httpx.Response(200, json={"id": "m1", "threadId": "t1"})
        return httpx.Response(200, json={"payload": {"headers": []}})

    g = gmail.Gmail(None, settings(), http=httpx.Client(transport=httpx.MockTransport(handler)))
    g._access_token, g._expires_at = "x", 1e12
    g.send("a@b.com", "Hi", "Body text", attachments=[str(resume)])
    msg = message_from_bytes(base64.urlsafe_b64decode(captured["raw"]), policy=email.policy.default)
    assert msg.get_body(preferencelist=("plain",)).get_content().strip() == "Body text"
    assert msg.get_body(preferencelist=("html",)).get_content().strip() == '<div dir="ltr"><div>Body text</div></div>'
    [attachment] = list(msg.iter_attachments())
    assert attachment.get_filename() == "Alex_Rivera_Resume.pdf"
    assert attachment.get_content_type() == "application/pdf"
    assert attachment.get_content() == b"%PDF-1.4 test"


def test_html_body_keeps_paragraphs_and_escapes():
    html_body = gmail.as_html("Hi Ana,\n\nBain & Company <3\nBest,\nAlex\n")
    assert html_body == ('<div dir="ltr"><div>Hi Ana,</div><div><br></div>'
                         '<div>Bain &amp; Company &lt;3</div><div>Best,</div><div>Alex</div></div>')
