"""Pick who gets emailed: 20 per firm (or per office at big firms), 8 junior / 8 mid / 4 senior.

People who share the sender's school or employer are picked first. If a level runs short, the rest of the 20 is filled from
the other levels. Everyone else stays in the database as a backup.
"""

from collections import Counter, defaultdict

PER_GROUP = 20
LEVEL_QUOTA = {"junior": 8, "mid": 8, "senior": 4}
STATUS_RANK = {"valid": 0, "domain_ok": 1, "unchecked": 2, "risky": 3}
CONTACTED = ("sent", "followup1", "followup2", "replied", "meeting", "closed")


def group_key(c: dict, per_office: bool) -> tuple:
    return (c["firm_id"], c["career_path"], c["office"] if per_office else "ALL")


def priority(c: dict) -> tuple:
    return (
        0 if (c["ucla_connection"] or c["bain_connection"]) else 1,
        STATUS_RANK.get(c["email_status"], 9),
        c["id"],
    )


def choose(group: list[dict]) -> set[int]:
    """Return ids to select from one group (already-contacted people count toward the quota)."""
    locked = [c for c in group if c["status"] in CONTACTED]
    chosen = {c["id"] for c in locked}
    level_counts = Counter(c["seniority"] for c in locked)
    pool = sorted((c for c in group if c["status"] in ("new", "ready")
                   and c["email_status"] != "invalid"), key=priority)

    for level, quota in LEVEL_QUOTA.items():
        for c in pool:
            if level_counts[level] >= quota:
                break
            if c["seniority"] == level and c["id"] not in chosen:
                chosen.add(c["id"])
                level_counts[level] += 1
    # Fill any shortfall from whoever is left, best first.
    for c in pool:
        if len(chosen) >= PER_GROUP:
            break
        chosen.add(c["id"])
    return chosen


def select(conn) -> Counter:
    rows = conn.execute(
        """select c.id, c.firm_id, c.career_path, c.office, c.seniority, c.status, c.email_status,
                  c.ucla_connection, c.bain_connection, f.per_office
           from contacts c join firms f on f.id = c.firm_id
           where f.active and c.status <> 'blocked'
             and c.email not in (select email from suppression)"""
    ).fetchall()
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        groups[group_key(r, r["per_office"])].append(r)

    chosen: set[int] = set()
    for members in groups.values():
        chosen |= choose(members)

    with conn.transaction():
        conn.execute("update contacts set selected = false where status in ('new', 'ready')")
        if chosen:
            conn.execute("update contacts set selected = true where id = any(%s)", (list(chosen),))
    picked = [r for r in rows if r["id"] in chosen]
    stats = Counter(r["seniority"] for r in picked)
    stats["groups"] = len(groups)
    stats["selected"] = len(picked)
    stats["backups"] = len(rows) - len(picked)
    return stats
