"""Results: reply and meeting rates by tier, career path, seniority and firm."""

STATUS_SUMMARY = """
select status, count(*) as n from contacts where selected or status not in ('new', 'ready')
group by status order by n desc
"""

RATES = """
select {dim} as bucket,
       count(*) as contacted,
       count(*) filter (where status in ('replied', 'meeting')) as replies,
       count(*) filter (where status = 'meeting') as meetings
from contacts c join firms f on f.id = c.firm_id
where c.last_contacted_at is not null and c.id not in (
  select contact_id from sends group by contact_id having bool_and(practice))
group by 1 order by contacted desc
"""

DIMENSIONS = {
    "tier": "c.personalization_tier",
    "career path": "c.career_path",
    "seniority": "c.seniority",
    "office": "c.office",
    "firm": "f.name",
}


def report(conn, top_firms: int = 15) -> str:
    out = []
    today = conn.execute(
        """select count(*) filter (where not practice) as live, count(*) filter (where practice) as practice
           from sends where status in ('sent', 'bounced')
           and (sent_at at time zone 'America/Los_Angeles')::date
               = (now() at time zone 'America/Los_Angeles')::date""").fetchone()
    out.append(f"Sent today: {today['live']} real, {today['practice']} practice")
    out.append("\nPeople by status:")
    for r in conn.execute(STATUS_SUMMARY).fetchall():
        out.append(f"  {r['status']:<10} {r['n']:>6}")
    for label, dim in DIMENSIONS.items():
        rows = conn.execute(RATES.format(dim=dim)).fetchall()
        if not rows:
            continue
        out.append(f"\nBy {label}:")
        out.append(f"  {'':<28} {'emailed':>8} {'replied':>8} {'rate':>6} {'meetings':>9}")
        for r in rows[: top_firms if label == "firm" else None]:
            rate = r["replies"] / r["contacted"] if r["contacted"] else 0
            out.append(f"  {str(r['bucket'])[:28]:<28} {r['contacted']:>8} {r['replies']:>8} "
                       f"{rate:>6.0%} {r['meetings']:>9}")
    if len(out) <= 3:
        out.append("\n(No real emails sent yet.)")
    return "\n".join(out)
