"""Build the send order: one numbered list.

- Slots repeat Junior, Junior, Mid, Mid, Senior.
- Each slot goes to the next firm in the rotation that still has someone at that level.
- People who share the sender's school or employer go first, across all firms (their own
  full rotation), then everyone else.
- People already emailed keep their number; everyone else is renumbered after them.
"""

from collections import defaultdict, deque

PATTERN = ["junior", "junior", "mid", "mid", "senior"]


def interleave_offices(people: list[dict]) -> list[dict]:
    """Within a firm and level, alternate offices so one office isn't emailed all at once."""
    by_office: dict[str, deque] = defaultdict(deque)
    for p in people:
        by_office[p["office"] or ""].append(p)
    out = []
    queues = list(by_office.values())
    while any(queues):
        for q in queues:
            if q:
                out.append(q.popleft())
    return out


def sequence(people: list[dict], firm_rotation: list[int]) -> list[dict]:
    """Order one batch of people by the pattern + firm rotation."""
    queues: dict[int, dict[str, deque]] = {f: {lvl: deque() for lvl in set(PATTERN)}
                                           for f in firm_rotation}
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for p in sorted(people, key=lambda p: p["id"]):
        grouped[(p["firm_id"], p["seniority"])].append(p)
    for (firm_id, level), members in grouped.items():
        queues.setdefault(firm_id, {lvl: deque() for lvl in set(PATTERN)})
        if firm_id not in firm_rotation:
            firm_rotation.append(firm_id)
        queues[firm_id][level].extend(interleave_offices(members))

    n_firms = len(firm_rotation)
    remaining = len(people)
    out: list[dict] = []
    pointer = 0     # index into firm_rotation of the next firm to try
    slot = 0
    while remaining:
        level = PATTERN[slot % len(PATTERN)]
        slot += 1
        picked = None
        for step in range(n_firms):
            idx = (pointer + step) % n_firms
            q = queues[firm_rotation[idx]][level]
            if q:
                picked = q.popleft()
                pointer = idx + 1
                break
        if picked is None:
            # Nobody left at this level anywhere: skip the slot (pattern continues).
            if not any(q for f in firm_rotation for q in queues[f].values()):
                break
            continue
        out.append(picked)
        remaining -= 1
    return out


def build(conn) -> dict:
    firms = conn.execute(
        "select id from firms where active order by rotation_position nulls last, id"
    ).fetchall()
    rotation = [f["id"] for f in firms]

    done_max = conn.execute(
        "select coalesce(max(send_order), 0) as m from contacts "
        "where status not in ('new', 'ready') and send_order is not null"
    ).fetchone()["m"]
    people = conn.execute(
        """select id, firm_id, seniority, office, ucla_connection, bain_connection from contacts
           where selected and status in ('new', 'ready') and seniority is not null"""
    ).fetchall()

    priority = [p for p in people if p["ucla_connection"] or p["bain_connection"]]
    rest = [p for p in people if not (p["ucla_connection"] or p["bain_connection"])]
    ordered = sequence(priority, list(rotation)) + sequence(rest, list(rotation))

    with conn.transaction():
        conn.execute("update contacts set send_order = null where status in ('new', 'ready')")
        conn.execute(
            """update contacts c set send_order = v.o
               from unnest(%s::int[], %s::int[]) as v(id, o) where c.id = v.id""",
            ([p["id"] for p in ordered],
             list(range(done_max + 1, done_max + 1 + len(ordered)))),
        )
    return {"ordered": len(ordered), "priority_first": len(priority), "starts_at": done_max + 1}
