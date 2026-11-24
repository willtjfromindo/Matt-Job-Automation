"""Email checks.

Free check (always): address format + the domain can receive mail (MX record).
Paid check (if NEVERBOUNCE_API_KEY is set): NeverBounce single-check on selected contacts.

email_status values: valid / domain_ok / risky / invalid / unchecked
"""

from collections import Counter
from functools import lru_cache

import dns.exception
import dns.resolver
import httpx

from .importer import EMAIL_RE


@lru_cache(maxsize=4096)
def domain_accepts_mail(domain: str) -> bool:
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=8)
        # A "null MX" (exchange ".") means the domain says it never accepts mail.
        return any(str(r.exchange) not in (".", "") for r in answers)
    except dns.resolver.NoAnswer:
        try:  # no MX: mail falls back to the A record
            return len(dns.resolver.resolve(domain, "A", lifetime=8)) > 0
        except dns.exception.DNSException:
            return False
    except dns.exception.DNSException:
        return False


@lru_cache(maxsize=4096)
def has_mail_server(domain: str) -> bool:
    """Stricter than domain_accepts_mail: the domain must name a real mail server (MX). Used
    before guessing addresses, where a domain with only a website is almost surely wrong."""
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=8)
        return any(str(r.exchange) not in (".", "") for r in answers)
    except dns.exception.DNSException:
        return False


def free_check(email: str) -> str:
    if not EMAIL_RE.match(email):
        return "invalid"
    return "domain_ok" if domain_accepts_mail(email.split("@", 1)[1].lower()) else "invalid"


NEVERBOUNCE_MAP = {"valid": "valid", "invalid": "invalid", "disposable": "invalid",
                   "catchall": "risky", "unknown": "risky"}


def neverbounce_check(email: str, api_key: str, client: httpx.Client) -> str:
    r = client.get("https://api.neverbounce.com/v4/single/check",
                   params={"key": api_key, "email": email}, timeout=30)
    r.raise_for_status()
    body = r.json()
    if body.get("status") != "success":
        raise RuntimeError(f"NeverBounce error: {body.get('message') or body}")
    return NEVERBOUNCE_MAP.get(body.get("result"), "risky")


def run(conn, neverbounce_api_key: str = "", only_selected: bool = False) -> Counter:
    stats: Counter = Counter()
    where = "status = 'new' and email_status in ('unchecked', 'domain_ok')"
    if only_selected:
        where += " and selected"
    rows = conn.execute(f"select id, email, email_status, selected from contacts where {where}").fetchall()
    client = httpx.Client() if neverbounce_api_key else None
    try:
        for r in rows:
            status = r["email_status"]
            if status == "unchecked":
                status = free_check(r["email"])
            # Paid check only for people we actually plan to email (saves credits).
            if status == "domain_ok" and client and r["selected"]:
                status = neverbounce_check(r["email"], neverbounce_api_key, client)
            conn.execute("update contacts set email_status = %s where id = %s", (status, r["id"]))
            stats[status] += 1
    finally:
        if client:
            client.close()
    conn.commit()
    return stats
