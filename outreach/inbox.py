"""Read the sender's inbox: mark replies, bounces and opt-outs."""

import re
from collections import Counter
from email.utils import parseaddr

from . import gmail as gmail_mod
from . import guess

OPT_OUT = re.compile(
    r"\b(unsubscribe|remove me|take me off|stop emailing|stop contacting|do not contact|"
    r"don't contact|not interested|no longer interested|please stop)\b", re.I)
AUTO_REPLY_SUBJECT = re.compile(r"(out of (the )?office|automatic reply|auto[- ]?reply|"
                                r"away from (the )?office|on leave|vacation)", re.I)
BOUNCE_FROM = re.compile(r"(mailer-daemon|postmaster|mail delivery)", re.I)

CONTACTED = ("sent", "followup1", "followup2", "closed")


def classify(meta: dict) -> str:
    """'bounce', 'auto', 'opt_out' or 'reply'."""
    sender = gmail_mod.header(meta, "From") or ""
    subject = gmail_mod.header(meta, "Subject") or ""
    snippet = meta.get("snippet") or ""
    if BOUNCE_FROM.search(sender) or gmail_mod.header(meta, "X-Failed-Recipients"):
        return "bounce"
    auto = (gmail_mod.header(meta, "Auto-Submitted") or "").lower()
    if (auto and auto != "no") or AUTO_REPLY_SUBJECT.search(subject):
        return "auto"
    if OPT_OUT.search(snippet) or OPT_OUT.search(subject):
        return "opt_out"
    return "reply"


def block(conn, contact_id: int, email: str, reason: str) -> None:
    conn.execute("update contacts set status = 'blocked', skip_reason = %s, follow_up_date = null "
                 "where id = %s", (reason, contact_id))
    conn.execute("insert into suppression (email, reason) values (%s, %s) on conflict do nothing",
                 (email, reason))


def sync(conn, gmail, days: int = 3, wait_minutes: int = 15) -> Counter:
    stats: Counter = Counter()
    ids = gmail.list_message_ids(f"newer_than:{days}d -from:me", max_results=1000)
    if not ids:
        return stats
    seen = {r["gmail_message_id"] for r in conn.execute(
        "select gmail_message_id from inbox_seen where gmail_message_id = any(%s)", (ids,)).fetchall()}
    for mid in ids:
        if mid in seen:
            continue
        meta = gmail.get_message(mid, headers=["From", "Subject", "X-Failed-Recipients",
                                               "Auto-Submitted"])
        contact = conn.execute(
            "select * from contacts where gmail_thread_id = %s", (meta.get("threadId"),)
        ).fetchone()
        if not contact:
            failed = (gmail_mod.header(meta, "X-Failed-Recipients") or "").split(",")[0].strip().lower()
            from_addr = failed or parseaddr(gmail_mod.header(meta, "From") or "")[1].lower()
            if from_addr:
                contact = conn.execute(
                    "select * from contacts where email = %s and status = any(%s)",
                    (from_addr, list(CONTACTED)),
                ).fetchone()
        with conn.transaction():
            if contact and contact["status"] in CONTACTED:
                kind = classify(meta)
                if kind == "bounce":
                    conn.execute(
                        """update sends set status = 'bounced' where id = (
                             select id from sends where contact_id = %s and status = 'sent'
                             order by sent_at desc limit 1)""", (contact["id"],))
                    # A guessed address: try the person's next likely one. Otherwise block them.
                    if guess.next_guess(conn, contact, wait_minutes):
                        kind = "bounce_retry"
                    else:
                        block(conn, contact["id"], contact["email"], "bounced")
                elif kind == "opt_out":
                    block(conn, contact["id"], contact["email"], "opted_out")
                elif kind == "reply":
                    conn.execute("update contacts set status = 'replied', follow_up_date = null "
                                 "where id = %s", (contact["id"],))
                stats[kind] += 1
            conn.execute("insert into inbox_seen (gmail_message_id) values (%s) on conflict do nothing",
                         (mid,))
    # People who got both follow-ups and never answered are closed.
    closed = conn.execute(
        "update contacts set status = 'closed', follow_up_date = null "
        "where status = 'followup2' and follow_up_date <= now()").rowcount
    if closed:
        stats["closed"] += closed
    conn.commit()
    return stats
