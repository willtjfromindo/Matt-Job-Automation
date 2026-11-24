import base64
import os

import pytest

from outreach import classify, crypto, evidence, guess, qa, templates
from outreach import profile as profile_mod

# A made-up sender, in the shape `cli.py profile` writes. The real one lives in
# data/sender_profile.json and never ships with the code.
PROFILE = {
    "name": "Alex Rivera",
    "facts": [
        {"id": "school", "text": "Senior at UCLA studying Economics"},
        {"id": "consulting_banking", "text": "Has exposure to both consulting and banking"},
        {"id": "investing", "text": "Increasingly focused on investing"},
    ],
    "schools": [{"name": "UCLA", "aliases": ["UCLA", "University of California, Los Angeles",
                                             "UCLA Anderson"]}],
    "employers": [{"name": "Bain & Company",
                   "aliases": ["Bain & Company", "Bain and Company", "Bain"],
                   "exclude": ["Bain Capital", "Bain Capital Ventures"]}],
    "hobbies": [],
    "extra_allowed_words": ["Bruin", "Bruins"],
}


def test_default_profile_has_no_facts():
    """Nothing about the sender may be claimed until their own profile file exists."""
    assert profile_mod.DEFAULT_PROFILE["facts"] == []
    assert profile_mod.DEFAULT_PROFILE["schools"] == []


@pytest.mark.parametrize("title,path,expected", [
    ("Investment Banking Analyst", "IB", "junior"),
    ("Analyst, M&A", "IB", "junior"),
    ("Associate", "PE", "mid"),
    ("Senior Associate", "PE", "senior"),
    ("Senior Associate", "IB", "mid"),
    ("Vice President", "IB", "senior"),
    ("Principal", "VC", "senior"),
    ("Investment Analyst", "VC", "junior"),
    ("Managing Director", "IB", None),
    ("Partner", "VC", None),
    ("Summer Analyst", "IB", None),
    ("Executive Assistant", "PE", None),
    ("Wealth Management Associate", "IB", None),
    ("Associate General Counsel", "PE", None),
    ("Sales & Trading Analyst", "IB", None),
    ("Software Engineer", "VC", None),
])
def test_seniority(title, path, expected):
    assert classify.seniority(title, path) == expected


@pytest.mark.parametrize("city,expected", [
    ("Los Angeles", "LA"), ("Santa Monica, CA", "LA"), ("New York, NY", "NY"),
    ("San Francisco Bay Area", "SF"), ("Menlo Park", "SF"), ("Chicago, Illinois", "Chicago"),
    ("Houston, TX", "Other"), ("Lafayette, Louisiana", "Other"),
])
def test_office(city, expected):
    assert classify.office(city) == expected


def test_career_path_for_multi_path_firm():
    assert classify.career_path(["PE", "VC"], "Associate, Venture Growth") == "VC"
    assert classify.career_path(["PE", "VC"], "Associate") == "PE"


def test_crypto_round_trip():
    key = base64.b64encode(os.urandom(32)).decode()
    sealed = crypto.encrypt("1//refresh-token", key)
    assert crypto.decrypt(sealed, key) == "1//refresh-token"
    with pytest.raises(ValueError):
        crypto.encrypt("x", base64.b64encode(b"short").decode())


def test_evidence_ucla_and_bain():
    rec = {"education": "B.A. Economics, University of California, Los Angeles; MBA, Wharton"}
    ev = evidence.find(rec, PROFILE)
    assert ev.tier == "A" and "University of California, Los Angeles" in ev.quote
    rec = {"past_employers": "Bain Capital; Goldman Sachs"}
    assert evidence.find(rec, PROFILE).tier == ""          # Bain Capital is not Bain & Company
    rec = {"past_employers": "Goldman Sachs | Bain & Company"}
    ev = evidence.find(rec, PROFILE)
    assert ev.tier == "B" and ev.quote == "Bain & Company"
    assert evidence.flags({"education": "UCLA Anderson"}, PROFILE) == (True, False)


def test_fill_template_and_followup():
    _, subject, body = templates.render_first(
        {"career_path": "PE", "seniority": "mid", "first_name": "Kevin", "title": "Associate"},
        "Clearlake", "I was interested in your path before joining Clearlake.")
    assert subject == "UCLA Student Interested in Your Path to Clearlake"
    assert body.startswith("Hi Kevin,")
    assert ("interned at Example Consulting. I was interested in your path before joining "
            "Clearlake.") in body
    assert body.rstrip().endswith("Alex Rivera\nUCLA Economics | Class of 2027")
    assert "{" not in body
    _, fsub, fbody = templates.render_followup(1, {"first_name": "Kevin", "first_subject": subject},
                                               "Clearlake")
    assert fsub == f"Re: {subject}" and "Kevin" in fbody


def test_fill_rejects_unknown_and_missing_fields():
    with pytest.raises(templates.TemplateError):
        templates.fill("Hi {nickname}", {"first_name": "A"})
    with pytest.raises(templates.TemplateError):
        templates.fill("On the {team} team", {"first_name": "A", "team": None})
    assert templates.fill("Hi\n{personal_line}\nBye", {"personal_line": ""}) == "Hi\nBye\n"


RECORD = {
    "firm": "Clearlake", "first_name": "Kevin", "last_name": "Lee", "title": "Associate",
    "past_employers": "Evercore; Morgan Stanley Equity Research",
    "education": "UCLA, B.A. Business Economics",
    "headline_or_bio": "Associate at Clearlake. Previously equity research and investment banking.",
}


def good_result(**over):
    r = {
        "personal_line": ("As a fellow Bruin, I was interested in your path across equity research "
                          "and investment banking before joining Clearlake, as I've similarly had "
                          "exposure to both consulting and banking."),
        "tier": "A",
        "sender_fact_ids": ["school", "consulting_banking"],
        "recipient_claims": [
            {"claim": "went to UCLA", "source_field": "education", "quote": "UCLA"},
            {"claim": "research and banking", "source_field": "headline_or_bio",
             "quote": "Previously equity research and investment banking"},
        ],
    }
    r.update(over)
    return r


def test_qa_passes_good_line():
    assert qa.check(good_result(), RECORD, PROFILE, "A", "UCLA") == []


def test_qa_catches_made_up_quote():
    bad = good_result(recipient_claims=[{"claim": "x", "source_field": "past_employers",
                                         "quote": "Lazard"}])
    assert any("quote not found" in i for i in qa.check(bad, RECORD, PROFILE, "A", "UCLA"))


def test_qa_catches_invented_name():
    bad = good_result(personal_line=("As a fellow Bruin, I was interested in your time at Lazard "
                                     "before joining Clearlake, as I've similarly had exposure to "
                                     "consulting and banking."))
    issues = qa.check(bad, RECORD, PROFILE, "A", "UCLA")
    assert any("Lazard" in i for i in issues)


def test_qa_catches_unknown_fact_and_tier_mismatch():
    bad = good_result(sender_fact_ids=["rowing"], tier="D")
    issues = qa.check(bad, RECORD, PROFILE, "A", "UCLA")
    assert any("rowing" in i for i in issues)
    assert any("tier" in i for i in issues)


def test_qa_tier_a_must_mention_school():
    bad = good_result(personal_line=("I was interested in your path across equity research and "
                                     "investment banking before joining Clearlake, as I've "
                                     "similarly had exposure to both."))
    assert any("school" in i for i in qa.check(bad, RECORD, PROFILE, "A", "UCLA"))


def test_qa_banned_and_questions_and_duplicates():
    bad = good_result(personal_line=good_result()["personal_line"][:-1] + "?")
    assert any("question" in i for i in qa.check(bad, RECORD, PROFILE, "A", "UCLA"))
    same = good_result()["personal_line"]
    assert any("identical" in i for i in qa.check(good_result(), RECORD, PROFILE, "A", "UCLA", [same]))


@pytest.mark.parametrize("line", [
    # Real failures from the first test drafts: evidence pasted into the email.
    'I was drawn to your path from (past_employers: "Evercore") to Clearlake as an Associate at UCLA.',
    "I was glad to see we both studied at 'UCLA' and your time at Evercore before Clearlake stood out.",
    "I was excited to see you also studied at UCLA, and your path from Evercore (equity research) to Clearlake stood out.",
])
def test_qa_catches_pasted_evidence(line):
    issues = qa.check(good_result(personal_line=line), RECORD, PROFILE, "A", "UCLA")
    assert any("quote marks" in i for i in issues)


def test_qa_allows_brackets_in_the_firm_name():
    record = {**RECORD, "firm": "Clearlake (CL)"}
    line = "I was excited to see you also studied at UCLA, and your path from Evercore to Clearlake (CL) stood out."
    issues = qa.check(good_result(personal_line=line), record, PROFILE, "A", "UCLA")
    assert not any("quote marks" in i for i in issues)


def test_qa_keeps_apostrophes():
    line = ("I was excited to see you also studied at UCLA, and Clearlake's growth since your time "
            "at Evercore and Morgan Stanley's research team caught my eye.")
    issues = qa.check(good_result(personal_line=line), RECORD, PROFILE, "A", "UCLA")
    assert not any("quote marks" in i for i in issues)


def test_qa_wants_short_school_and_one_bain():
    long_school = good_result(personal_line=(
        "I was excited to see you also studied at the University of California, Los Angeles, and "
        "your path from Evercore to Clearlake stood out."))
    assert any("write UCLA" in i for i in qa.check(long_school, RECORD, PROFILE, "A", "UCLA"))
    two_bains = good_result(personal_line=(
        "As a fellow Bruin who also spent time at Bain & Company, your move from Bain & Company "
        "and Evercore to Clearlake stood out."))
    assert any("more than once" in i for i in qa.check(two_bains, RECORD, PROFILE, "A", "UCLA"))


@pytest.mark.parametrize("first,last,pattern,expected", [
    ("Jane", "Smith", "{first}.{last}", "jane.smith@firm.com"),
    ("Jane", "Smith", "{f}{last}", "jsmith@firm.com"),
    ("Jane", "Smith", "{first}{l}", "janes@firm.com"),
    ("Jane", "Smith-Lee", "{first}.{last}", None),
    ("José", "Ruiz", "{first}.{last}", None),
    ("Jane", "van Dyke", "{first}.{last}", None),
    ("J.", "Smith", "{first}.{last}", None),
    ("Jane", "O'Neil", "{first}.{last}", None),
    ("Jane", "Smith", "{nickname}", None),
])
def test_build_email(first, last, pattern, expected):
    assert guess.build_email(first, last, pattern, "Firm.com") == expected


def test_qa_degree_dots_are_not_sentences():
    record = {**RECORD, "education": "UCLA, Ph.D. Immunology"}
    line = ("I was glad to see you also earned a Ph.D. at UCLA. Your path from Evercore into "
            "Clearlake caught my attention.")
    result = good_result(personal_line=line, recipient_claims=[
        {"claim": "UCLA PhD", "source_field": "education", "quote": "UCLA, Ph.D. Immunology"}])
    assert "more than two sentences" not in qa.check(result, record, PROFILE, "A", "UCLA")


def test_thin_record_skips_the_ai():
    from outreach import drafter, evidence
    thin = {"firm": "Clearlake", "title": "Principal", "team": "Investment Team"}
    assert drafter.thin_record(thin, evidence.Evidence(tier=""))
    assert not drafter.thin_record({**thin, "past_employers": "Evercore"}, evidence.Evidence(tier=""))
    assert not drafter.thin_record(thin, evidence.Evidence(tier="A", label="UCLA"))


def test_qa_wants_it_simple():
    listy = good_result(personal_line=(
        "I was excited to see you also studied at UCLA. Your path through Evercore, Morgan Stanley, "
        "equity research, and banking into Clearlake caught my attention."))
    assert any("too many details" in i for i in qa.check(listy, RECORD, PROFILE, "A", "UCLA"))
    possessive = good_result(personal_line=(
        "I was excited to see you also studied at UCLA. Your path from Evercore's banking team "
        "into Clearlake particularly caught my attention."))
    assert not any("Evercore" in i for i in qa.check(possessive, RECORD, PROFILE, "A", "UCLA"))
