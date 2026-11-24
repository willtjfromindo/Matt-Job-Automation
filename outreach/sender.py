"""The sending loop that runs on Railway.

When the sender presses Send, the website adds a row to `runs`. This loop picks it up and sends
one email at a time (follow-ups that are due first, then the next person in the send order,
never the same firm twice within FIRM_SPACING emails while anyone else is left), waiting a random MIN_GAP_SECONDS-MAX_GAP_SECONDS (20-34 s) between emails and checking for Stop before each one.

Guessed addresses: when one bounces, the inbox check moves the person to their next likely
address and they're emailed again (see guess.py). Before a run finishes it waits until its last
guess has gone 15 minutes without a bounce, so those resends happen in the same run.
"""

import logging
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from psycopg.types.json import Jsonb

from . import gmail as gmail_mod
from . import guess, inbox, templates
from .config import LOCAL_TZ

log = logging.getLogger("sender")

INBOX_SYNC_EVERY = 3 * 60       # seconds, while sending
IDLE_INBOX_SYNC_EVERY = 30 * 60  # seconds, while idle
MAX_FAILURES_IN_A_ROW = 3


def add_business_days(start: datetime, days: int) -> datetime:
    d = start
    added = 0
    while added < days:
        d += timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d


def sent_today(conn) -> int:
    return conn.execute(
        """select count(*) as n from sends where status in ('sent', 'bounced')
           and (sent_at at time zone %s)::date = (now() at time zone %s)::date""",
        (LOCAL_TZ, LOCAL_TZ),
    ).fetchone()["n"]


def bounces_today(conn) -> int:
    return conn.execute(
        """select count(*) as n from sends where status = 'bounced' and not practice
           and (sent_at at time zone %s)::date = (now() at time zone %s)::date""",
        (LOCAL_TZ, LOCAL_TZ),
    ).fetchone()["n"]


def awaiting_bounces(conn, run_id: int, settings) -> bool:
    """True while a guessed address sent in this run could still bounce back."""
    if settings.practice_mode or settings.bounce_wait_minutes <= 0:
        return False
    return conn.execute(
        """select exists (select 1 from sends where run_id = %s and kind = 'first'
             and status = 'sent' and not practice and email_pattern is not null
             and sent_at > now() - make_interval(mins => %s)) as waiting""",
        (run_id, settings.bounce_wait_minutes)).fetchone()["waiting"]


RETRY = "exists (select 1 from sends b where b.contact_id = c.id and b.kind = 'first' and b.status = 'bounced')"

# A firm isn't emailed again until this many emails have gone to other firms (when anyone else
# is left). The send order already rotates firms, but UCLA/Bain people cluster at a few firms
# and resends after a bounce jump the queue, so this is checked against what was really sent.
FIRM_SPACING = 10
# Sort key: firms not among the last FIRM_SPACING emails first, then the one emailed longest ago.
FRESH_FIRM_FIRST = "coalesce(array_position(%(recent)s::int[], c.firm_id), 1000000) desc"


def recent_firms(conn) -> list[int]:
    """The firms of the last FIRM_SPACING emails, most recent first."""
    return [r["firm_id"] for r in conn.execute(
        """select c.firm_id from sends s join contacts c on c.id = s.contact_id
           where s.status <> 'failed' order by s.sent_at desc, s.id desc limit %s""",
        (FIRM_SPACING,)).fetchall()]


def next_item(conn, settings=None, retries_only: bool = False) -> dict | None:
    """The next email to send: a due follow-up, else the next person in the send order, skipping
    firms that were just emailed. With retries_only, just people whose guessed address bounced
    and who have a new guess."""
    recent = recent_firms(conn)
    followup = None if retries_only else conn.execute(
        """select c.*, f.name as firm from contacts c join firms f on f.id = c.firm_id
           where c.status in ('sent', 'followup1') and c.follow_up_date <= now()
             and c.gmail_thread_id is not null
             and c.email not in (select email from suppression)
             and not exists (select 1 from sends s where s.contact_id = c.id and s.status = 'pending')
           order by """ + FRESH_FIRM_FIRST + """, c.follow_up_date limit 1""",
        {"recent": recent}).fetchone()
    first = conn.execute(
        """select c.*, f.name as firm, d.id as draft_id, d.subject as d_subject, d.body as d_body,
                  d.template as d_template
           from contacts c join firms f on f.id = c.firm_id
           join drafts d on d.contact_id = c.id and d.kind = 'first' and d.qa_passed
           where c.status = 'ready' and c.selected and c.send_order is not null
             and c.email_status <> 'invalid'
             and c.email not in (select email from suppression)
             and not exists (select 1 from sends s where s.contact_id = c.id and s.status = 'pending')
             """ + (f"and {RETRY}" if retries_only else "") + """
           order by """ + FRESH_FIRM_FIRST + """, c.send_order limit 1""",
        {"recent": recent}).fetchone()
    # Follow-ups are due, so they go first, unless theirs is a firm just emailed and a new
    # person at another firm can go instead.
    if followup and not (followup["firm_id"] in recent and first and first["firm_id"] not in recent):
        n = 1 if followup["status"] == "sent" else 2
        name, subject, body = templates.render_followup(n, followup, followup["firm"])
        return {"contact": followup, "kind": f"followup{n}", "template": name,
                "subject": subject, "body": body, "draft_id": None}
    if first:
        retry = conn.execute(f"select {RETRY} as r from contacts c where c.id = %s",
                             (first["id"],)).fetchone()["r"]
        if not retry and settings is not None:
            first = guess.apply_learning(conn, first, settings.bounce_wait_minutes)
        return {"contact": first, "kind": "first", "template": first["d_template"],
                "subject": first["d_subject"], "body": first["d_body"], "draft_id": first["draft_id"],
                "retry": retry}
    return None


def record_send(conn, run_id: int, send_id: int, item: dict, result: dict, settings) -> None:
    """Mark the pending send as sent and move the person along (sent -> followup1 -> followup2)."""
    with conn.transaction():
        c = item["contact"]
        kind = item["kind"]
        now = datetime.now(timezone.utc)
        draft_id = item["draft_id"]
        if kind != "first":
            draft_id = conn.execute(
                """insert into drafts (contact_id, kind, template, subject, body, qa_passed)
                   values (%s, %s, %s, %s, %s, true)
                   on conflict (contact_id, kind) do update set body = excluded.body
                   returning id""",
                (c["id"], kind, item["template"], item["subject"], item["body"])).fetchone()["id"]
        conn.execute(
            """update sends set status = 'sent', draft_id = %s, sent_at = now(), gmail_message_id = %s,
                 gmail_thread_id = %s, rfc_message_id = %s where id = %s""",
            (draft_id, result["id"], result["threadId"], result["rfc_message_id"], send_id))
        if kind == "first":
            conn.execute(
                """update contacts set status = 'sent', last_contacted_at = %s, follow_up_date = %s,
                     gmail_thread_id = %s, first_message_id = %s, first_subject = %s
                   where id = %s""",
                (now, add_business_days(now, settings.followup1_business_days), result["threadId"],
                 result["rfc_message_id"], item["subject"], c["id"]))
        else:
            n = 1 if kind == "followup1" else 2
            conn.execute(
                """update contacts set status = %s, follow_up_count = %s, last_contacted_at = %s,
                     follow_up_date = %s where id = %s""",
                (kind, n, now, add_business_days(now, settings.followup2_business_days), c["id"]))
        if not item.get("retry"):  # a resend after a bounce is the same person, not a new one
            conn.execute("update runs set sent_count = sent_count + 1 where id = %s", (run_id,))


def finish(conn, run_id: int, status: str, message: str | None = None) -> None:
    conn.execute("update runs set status = %s, message = %s, ended_at = now() where id = %s",
                 (status, message, run_id))
    conn.commit()
    log.info("run %s -> %s %s", run_id, status, message or "")


def bounce_rate(conn, run_id: int) -> tuple[int, float]:
    """People emailed in this run, and the share that couldn't be reached at any address.
    (A bounced guess that led to a resend doesn't count here; bounces_today caps those.)"""
    row = conn.execute(
        """select count(distinct s.contact_id) as n,
             count(distinct s.contact_id) filter (
               where s.status = 'bounced' and c.status = 'blocked' and c.skip_reason = 'bounced') as b
           from sends s join contacts c on c.id = s.contact_id
           where s.run_id = %s and s.status in ('sent', 'bounced')""", (run_id,)).fetchone()
    return row["n"], (row["b"] / row["n"] if row["n"] else 0.0)


def heartbeat(conn) -> None:
    """Tell the website the sender is alive."""
    conn.execute("insert into app_state (key, value) values ('worker_heartbeat', %s) "
                 "on conflict (key) do update set value = excluded.value",
                 (Jsonb({"at": datetime.now(timezone.utc).isoformat()}),))


def wait(conn, run_id: int, seconds: float, sleep=time.sleep) -> bool:
    """Sleep in short steps. Returns False if Stop was pressed meanwhile."""
    end = time.monotonic() + seconds
    while True:
        status = conn.execute("select status from runs where id = %s", (run_id,)).fetchone()["status"]
        heartbeat(conn)
        if status != "running":
            return False
        left = end - time.monotonic()
        if left <= 0:
            return True
        sleep(min(2.0, left))


def sync_inbox(conn, gmail, settings) -> float:
    """Check for replies and bounces. Returns the time it ran (for the next-sync timer)."""
    try:
        inbox.sync(conn, gmail, wait_minutes=settings.bounce_wait_minutes)
    except gmail_mod.GmailError as e:
        log.warning("inbox sync failed: %s", e)
        conn.rollback()
    return time.monotonic()


def process_run(conn, run: dict, settings, gmail, sleep=time.sleep, rand=random.uniform) -> None:
    run_id = run["id"]
    if settings.practice_mode and not settings.practice_inbox:
        return finish(conn, run_id, "error", "Practice mode is on but PRACTICE_INBOX is not set")
    if settings.resume_path and not Path(settings.resume_path).is_file():
        # The emails say "I've attached my resume", so never send them without it.
        return finish(conn, run_id, "error", "The resume file is missing, so nothing was sent")
    last_sync = time.monotonic()
    failures = 0
    first = True
    while True:
        current = conn.execute("select * from runs where id = %s", (run_id,)).fetchone()
        conn.commit()
        if current["status"] == "stopping":
            return finish(conn, run_id, "stopped", f"Stopped after {current['sent_count']}")
        if current["status"] != "running":
            return
        if sent_today(conn) >= settings.daily_limit:
            return finish(conn, run_id, "done", f"Daily limit of {settings.daily_limit} reached")
        if not settings.practice_mode and bounces_today(conn) >= settings.max_bounces_per_day:
            return finish(conn, run_id, "auto_stopped",
                          f"Paused: {settings.max_bounces_per_day} emails bounced today. "
                          "Press Send again tomorrow.")

        people_done = current["sent_count"] >= current["requested_count"]
        item = next_item(conn, settings, retries_only=people_done)
        if not item:
            if awaiting_bounces(conn, run_id, settings):
                # Give the last guesses time to bounce so their resends go out in this run.
                if wait(conn, run_id, 60, sleep):
                    last_sync = sync_inbox(conn, gmail, settings)
                continue
            if people_done:
                return finish(conn, run_id, "done", f"Done: {current['sent_count']} sent")
            return finish(conn, run_id, "done",
                          f"No one left to email ({current['sent_count']} sent). Add more contacts.")

        if not first and not wait(conn, run_id, rand(settings.min_gap_seconds,
                                                      settings.max_gap_seconds), sleep):
            continue  # loop back: picks up 'stopping'
        first = False

        contact = item["contact"]
        to = settings.practice_inbox if settings.practice_mode else contact["email"]
        # Write down the attempt first. If the worker dies mid-send, this person is never
        # emailed twice: anyone with a 'pending' send is skipped until Will checks them.
        send_id = conn.execute(
            """insert into sends (run_id, contact_id, draft_id, kind, to_email, practice, status,
                 email_pattern)
               values (%s, %s, %s, %s, %s, %s, 'pending', %s) returning id""",
            (run_id, contact["id"], item["draft_id"], item["kind"], to, settings.practice_mode,
             contact.get("email_pattern") if item["kind"] == "first" else None),
        ).fetchone()["id"]
        conn.commit()
        try:
            first_email = item["kind"] == "first"
            result = gmail.send(to, item["subject"], item["body"],
                                thread_id=None if first_email else contact.get("gmail_thread_id"),
                                in_reply_to=None if first_email else contact.get("first_message_id"),
                                attachments=[settings.resume_path] if first_email and settings.resume_path else None)
        except gmail_mod.NeedsReauth:
            conn.rollback()
            conn.execute("delete from sends where id = %s", (send_id,))
            return finish(conn, run_id, "error", "Please sign in again")
        except gmail_mod.GmailError as e:
            conn.rollback()
            failures += 1
            log.warning("send failed for contact %s: %s", contact["id"], e)
            with conn.transaction():
                conn.execute("update sends set status = 'failed', error = %s where id = %s",
                             (str(e)[:500], send_id))
                if e.status == 400:
                    # Gmail rejected this address/message itself: don't retry this person.
                    inbox.block(conn, contact["id"], contact["email"], "send_rejected")
            if failures >= MAX_FAILURES_IN_A_ROW:
                return finish(conn, run_id, "error", f"Sending failed {failures} times in a row: {e}"[:300])
            continue
        failures = 0
        record_send(conn, run_id, send_id, item, result, settings)
        heartbeat(conn)
        log.info("run %s: sent %s to contact %s (%s)", run_id, item["kind"], contact["id"],
                 "practice" if settings.practice_mode else "live")

        if time.monotonic() - last_sync > INBOX_SYNC_EVERY:
            last_sync = sync_inbox(conn, gmail, settings)
            n, rate = bounce_rate(conn, run_id)
            if n >= settings.bounce_stop_min_sends and rate > settings.bounce_stop_rate:
                return finish(conn, run_id, "auto_stopped",
                              f"Stopped: {rate:.0%} of people couldn't be reached at any address. "
                              "Check the contact list.")


SENDER_LOCK = 727001  # any fixed number; only one connection can hold it


def acquire_lock(conn, poll_seconds: float = 5.0, sleep=time.sleep, once: bool = False) -> bool:
    """Only one sender may run at a time (e.g. during a redeploy two copies can overlap),
    otherwise the same person could be emailed twice. Waits until the lock is free."""
    while True:
        if conn.execute("select pg_try_advisory_lock(%s) as ok", (SENDER_LOCK,)).fetchone()["ok"]:
            return True
        if once:
            return False
        log.info("another sender is running; waiting")
        sleep(poll_seconds)


def loop(conn, settings, gmail, poll_seconds: float = 5.0, once: bool = False) -> None:
    if not acquire_lock(conn, poll_seconds, once=once):
        return
    # Lets the website say where emails really go (practice mode sends them all to one inbox).
    conn.execute("insert into app_state (key, value) values ('worker_info', %s) "
                 "on conflict (key) do update set value = excluded.value",
                 (Jsonb({"practice_mode": settings.practice_mode,
                         "practice_inbox": settings.practice_inbox}),))
    last_idle_sync = 0.0
    while True:
        run = conn.execute(
            "select * from runs where status in ('running', 'stopping') order by id limit 1"
        ).fetchone()
        conn.commit()
        if run:
            try:
                process_run(conn, run, settings, gmail)
            except Exception as e:  # keep the worker alive; surface the problem on the page
                log.exception("run %s crashed", run["id"])
                conn.rollback()
                finish(conn, run["id"], "error", f"Something went wrong: {e}"[:300])
        elif time.monotonic() - last_idle_sync > IDLE_INBOX_SYNC_EVERY:
            last_idle_sync = time.monotonic()
            try:
                stats = inbox.sync(conn, gmail, wait_minutes=settings.bounce_wait_minutes)
                if stats:
                    log.info("inbox sync: %s", dict(stats))
            except gmail_mod.NeedsReauth:
                pass
            except Exception:
                log.exception("idle inbox sync failed")
                conn.rollback()
        heartbeat(conn)
        if once:
            return
        time.sleep(poll_seconds)
