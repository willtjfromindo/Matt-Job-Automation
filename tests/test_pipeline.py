import csv
from collections import Counter

from outreach import drafter, importer, order, quotas, verify


def write_firms(tmp_path, rows):
    p = tmp_path / "firms.csv"
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "career_paths", "per_office", "rank_source", "domain"])
        w.writerows(rows)
    return p


FIRMS = [
    ["Goldman Sachs", "IB", "true", "IB #1", "gs.com"],
    ["Evercore", "IB", "false", "IB #2", ""],
    ["Blackstone", "PE", "true", "PEI #1", "blackstone.com"],
    ["Clearlake", "PE", "false", "PEI #20", ""],
    ["Leonard Green", "PE", "false", "PEI #30", ""],
    ["Sequoia Capital", "VC", "false", "VC #1", ""],
    ["Andreessen Horowitz", "VC", "false", "VC #2", ""],
]


def person(i, first, title, company, city="New York", state="NY", education="", past="",
           email=None):
    return {"First Name": first, "Last Name": f"Last{i}", "Title": title, "Company": company,
            "Email": email or f"p{i}@example.com", "City": city, "State": state,
            "Country": "United States", "Education": education, "Past Employers": past,
            "Headline": f"{title} at {company}"}


def write_people(tmp_path, people, name="people.csv"):
    p = tmp_path / name
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(people[0].keys()))
        w.writeheader()
        w.writerows(people)
    return p


def test_firm_rotation_interleaves_types(conn, tmp_path):
    importer.load_firms(conn, write_firms(tmp_path, FIRMS))
    rows = conn.execute("select name, career_paths from firms order by rotation_position").fetchall()
    paths = [r["career_paths"][0] for r in rows]
    assert len(rows) == 7
    # Never two banks in a row when banks are 2 of 7.
    assert "IB IB" not in " ".join(paths)


def test_import_filters_and_flags(conn, tmp_path):
    importer.load_firms(conn, write_firms(tmp_path, FIRMS))
    people = [
        person(1, "Ann", "Investment Banking Analyst", "Goldman Sachs & Co. LLC", education="UCLA"),
        person(2, "Ben", "Managing Director", "Goldman Sachs"),                       # too senior
        person(3, "Cat", "Analyst", "Goldman Sachs", city="Dallas", state="TX"),     # bank office
        person(4, "Dan", "Associate", "Clearlake Capital", city="Santa Monica", state="CA",
               past="Bain & Company"),
        person(5, "Eve", "Associate", "Unknown Partners"),                           # not on list
        person(6, "Fay", "Principal", "Sequoia Capital", city="Menlo Park", state="CA"),
        person(7, "Gus", "Analyst", "Evercore", city="London", state="", email="g@evercore.com"),
    ]
    people[6]["Country"] = "United Kingdom"
    stats = importer.import_contacts(conn, write_people(tmp_path, people))
    assert stats["added"] == 3
    assert stats["skipped: title not a target"] == 1
    assert stats["skipped: bank office not LA/NY/SF/Chicago"] == 1
    assert stats["skipped: firm not on list"] == 1
    assert stats["skipped: outside U.S."] == 1
    rows = {r["first_name"]: r for r in conn.execute("select * from contacts").fetchall()}
    assert rows["Ann"]["ucla_connection"] and rows["Ann"]["office"] == "NY"
    assert rows["Dan"]["bain_connection"] and rows["Dan"]["office"] == "LA"
    assert rows["Fay"]["seniority"] == "senior" and rows["Fay"]["office"] == "SF"


def big_import(conn, tmp_path):
    importer.load_firms(conn, write_firms(tmp_path, FIRMS))
    people, i = [], 0
    firms_titles = {
        "Goldman Sachs": ["Investment Banking Analyst", "Investment Banking Associate", "Vice President"],
        "Evercore": ["Analyst", "Associate", "Vice President"],
        "Blackstone": ["Analyst", "Associate", "Vice President"],
        "Clearlake": ["Analyst", "Associate", "Vice President"],
        "Leonard Green": ["Analyst", "Associate", "Vice President"],
        "Sequoia Capital": ["Investment Analyst", "Associate", "Principal"],
        "Andreessen Horowitz": ["Investment Analyst", "Associate", "Principal"],
    }
    offices = [("New York", "NY"), ("Los Angeles", "CA"), ("Chicago", "IL"), ("San Francisco", "CA")]
    for firm, titles in firms_titles.items():
        for k in range(40):
            city, state = offices[k % 4]
            level = 0 if k % 5 < 2 else 1 if k % 5 < 4 else 2
            people.append(person(i, f"N{i}", titles[level], firm, city, state,
                                 education="UCLA" if k == 39 else "NYU"))
            i += 1
    importer.import_contacts(conn, write_people(tmp_path, people))


def test_quotas_8_8_4_per_group(conn, tmp_path):
    big_import(conn, tmp_path)
    stats = quotas.select(conn)
    rows = conn.execute(
        """select f.name, f.per_office, c.office, c.seniority, c.ucla_connection, c.selected
           from contacts c join firms f on f.id = c.firm_id""").fetchall()
    groups = Counter()
    levels = Counter()
    for r in rows:
        if r["selected"]:
            key = (r["name"], r["office"] if r["per_office"] else "ALL")
            groups[key] += 1
            levels[(key, r["seniority"])] += 1
    # per-office firms: 40 people over 4 offices = 10 each, all selected (under 20)
    assert groups[("Goldman Sachs", "NY")] == 10
    # per-firm firms: exactly 20, 8/8/4
    assert groups[("Clearlake", "ALL")] == 20
    assert levels[(("Clearlake", "ALL"), "junior")] == 8
    assert levels[(("Clearlake", "ALL"), "mid")] == 8
    assert levels[(("Clearlake", "ALL"), "senior")] == 4
    # UCLA people always make the cut
    assert all(r["selected"] for r in rows if r["ucla_connection"])
    assert stats["selected"] == sum(groups.values())


def test_send_order_pattern_and_rotation(conn, tmp_path):
    big_import(conn, tmp_path)
    quotas.select(conn)
    result = order.build(conn)
    rows = conn.execute(
        """select c.send_order, c.seniority, c.firm_id, c.ucla_connection from contacts c
           where c.send_order is not null order by c.send_order""").fetchall()
    assert result["ordered"] == len(rows) > 0
    # UCLA people first
    n_pri = result["priority_first"]
    assert all(r["ucla_connection"] for r in rows[:n_pri])
    rest = rows[n_pri:]
    # Pattern J J M M S holds for the first several cycles
    pattern = [r["seniority"] for r in rest[:40]]
    assert pattern[:10] == ["junior", "junior", "mid", "mid", "senior"] * 2
    # Never more than 2 of the same level in a row while all levels remain
    for a, b, c in zip(pattern, pattern[1:], pattern[2:]):
        assert not (a == b == c)
    # The same firm never appears twice in a row
    firms = [r["firm_id"] for r in rest[:60]]
    assert all(x != y for x, y in zip(firms, firms[1:]))


def test_verify_free_check(conn, tmp_path, monkeypatch):
    big_import(conn, tmp_path)
    monkeypatch.setattr(verify, "domain_accepts_mail", lambda d: d == "example.com")
    conn.execute("update contacts set email = 'bad@nowhere.invalid' where id = 1")
    conn.commit()
    stats = verify.run(conn)
    assert stats["invalid"] == 1
    assert stats["domain_ok"] == len(conn.execute("select id from contacts").fetchall()) - 1


def test_drafter_with_ai_and_fallback(conn, tmp_path, monkeypatch):
    big_import(conn, tmp_path)
    quotas.select(conn)
    order.build(conn)
    calls = Counter()

    def fake_ai(system, user, schema, name):
        calls["n"] += 1
        if "Connection found (tier A)" in user:
            return {"personal_line": ("As a fellow Bruin, I was interested in your path to "
                                      "your current role, as I've similarly had exposure to both "
                                      "consulting and banking and am increasingly focused on investing."),
                    "tier": "A", "sender_fact_ids": ["school", "consulting_banking", "investing"],
                    "recipient_claims": [{"claim": "UCLA", "source_field": "education",
                                          "quote": "UCLA"}]}
        # Everyone else: an invented quote -> rejected twice -> fallback sentence
        return {"personal_line": "I was interested in your time at Lazard, as I've similarly had exposure to banking.",
                "tier": "D", "sender_fact_ids": [], "recipient_claims": [
                    {"claim": "x", "source_field": "past_employers", "quote": "Lazard"}]}

    monkeypatch.setattr(drafter.ai, "complete_json", fake_ai)
    monkeypatch.setattr(drafter.ai, "available", lambda: True)
    stats = drafter.run(conn, limit=12, workers=2)
    assert sum(v for k, v in stats.items() if k.startswith("tier")) == 12
    drafts = conn.execute("select d.*, c.ucla_connection from drafts d join contacts c "
                          "on c.id = d.contact_id").fetchall()
    for d in drafts:
        assert "{" not in d["body"] and "Lazard" not in d["body"]
        if d["ucla_connection"]:
            assert "fellow Bruin" in d["body"]
        else:
            assert "I've been learning more about" in d["body"]   # fallback line
    ready = conn.execute("select count(*) as n from contacts where status = 'ready'").fetchone()["n"]
    assert ready == 12


def test_drafter_fallback_only(conn, tmp_path):
    big_import(conn, tmp_path)
    quotas.select(conn)
    stats = drafter.run(conn, fallback_only=True)
    assert stats["tier E"] == conn.execute(
        "select count(*) as n from contacts where selected").fetchone()["n"]


def test_everything_is_saved_for_other_connections(conn, tmp_path, _database):
    """Regression: imports/selection/drafts must be committed, not just visible to one session."""
    from outreach import db

    big_import(conn, tmp_path)
    quotas.select(conn)
    order.build(conn)
    drafter.run(conn, fallback_only=True)
    other = db.connect(_database)
    try:
        counts = other.execute(
            """select count(*) as people, count(*) filter (where selected) as picked,
                      count(send_order) as ordered, count(*) filter (where status = 'ready') as ready
               from contacts""").fetchone()
        assert counts["people"] == 280
        assert counts["picked"] > 0 and counts["ordered"] == counts["picked"] == counts["ready"]
    finally:
        other.close()


def test_apollo_style_headers(conn, tmp_path):
    importer.load_firms(conn, write_firms(tmp_path, FIRMS))
    p = tmp_path / "apollo.csv"
    p.write_text(
        "First Name,Last Name,Title,Company,Company Name for Emails,Email,Email Status,Seniority,"
        "Departments,Person Linkedin Url,City,State,Country\n"
        "Kevin,Lee,Associate,Clearlake Capital Group,Clearlake,kevin@clearlake.com,Verified,Entry,"
        "Finance,http://www.linkedin.com/in/kevin,Santa Monica,California,United States\n"
        "Jo,Park,Analyst,Goldman Sachs,Goldman Sachs,jo@gs.com,Guessed,Entry,Finance,,"
        "New York,New York,United States\n")
    stats = importer.import_contacts(conn, p)
    assert stats["added"] == 2
    rows = {r["first_name"]: r for r in conn.execute(
        "select c.*, f.name as firm from contacts c join firms f on f.id = c.firm_id").fetchall()}
    assert rows["Kevin"]["firm"] == "Clearlake" and rows["Kevin"]["email_status"] == "valid"
    assert rows["Kevin"]["profile_url"] == "http://www.linkedin.com/in/kevin"
    assert rows["Jo"]["firm"] == "Goldman Sachs" and rows["Jo"]["email_status"] == "unchecked"
    assert rows["Jo"]["office"] == "NY" and rows["Kevin"]["office"] == "LA"
