"""Turn raw titles and cities into seniority levels, offices and career paths."""

import re

# Titles that are never targets: too senior, interns, or non-investing jobs.
EXCLUDE_TITLE = re.compile(
    r"\b("
    r"managing director|md|partner|general partner|managing partner|founder|co-founder|"
    r"chief|ceo|cfo|coo|cio|president|chair(man|woman)?|head of|vice chair|"
    r"intern|internship|summer|"
    r"assistant|administrative|receptionist|office manager|"
    r"compliance|operations|human resources|hr|talent|recruit(er|ing)?|people|"
    r"marketing|communications|investor relations|legal|counsel|paralegal|"
    r"accounting|accountant|controller|tax|audit|fund administration|"
    r"software|engineer|developer|data scientist|data analyst|it|information technology|"
    r"wealth|private bank(ing|er)?|sales|trading|trader|research|equity research|"
    r"asset management|portfolio operations|risk|credit analyst|loan|lending|"
    r"platform|events|design|product"
    r")\b",
    re.I,
)
# "Vice President" contains "President": strip it before the exclusion check.
VP = re.compile(r"\b(vice[- ]president|vp|svp|avp)\b", re.I)

SENIOR = re.compile(
    r"\b(vice[- ]president|vp|svp|principal|director|executive director|senior associate)\b", re.I
)
MID = re.compile(r"\b(associate)\b", re.I)
JUNIOR = re.compile(r"\b(analyst)\b", re.I)


def seniority(title: str, career_path: str) -> str | None:
    """junior / mid / senior, or None if the title isn't a target."""
    t = (title or "").strip()
    if not t:
        return None
    without_vp = VP.sub("", t)
    if EXCLUDE_TITLE.search(without_vp):
        return None
    if re.search(r"\bassociate (director|general counsel|partner)\b", t, re.I):
        return None
    if re.search(r"\bsenior associate\b", t, re.I):
        # In banking a senior associate is still an associate; in PE/VC it's the level below VP.
        return "mid" if career_path == "IB" else "senior"
    if SENIOR.search(t):
        return "senior"
    if MID.search(t):
        return "mid"
    if JUNIOR.search(t):
        return "junior"
    return None


OFFICE_PATTERNS = [
    ("LA", r"los angeles|\bl\.?a\.?\b|santa monica|beverly hills|century city|west hollywood|"
           r"culver city|pasadena|el segundo|manhattan beach|venice|playa vista|marina del rey|"
           r"burbank|sherman oaks|encino"),
    ("NY", r"new york|\bnyc\b|manhattan|brooklyn"),
    ("SF", r"san francisco|\bsf\b|bay area|menlo park|palo alto|redwood city|mountain view|"
           r"san mateo|burlingame|woodside|sausalito|mill valley|oakland|berkeley"),
    ("Chicago", r"chicago|evanston"),
]


def office(*location_parts: str | None) -> str:
    text = " ".join(p for p in location_parts if p).lower()
    for name, pattern in OFFICE_PATTERNS:
        if re.search(pattern, text):
            return name
    return "Other"


TIMEZONES = {
    "LA": "America/Los_Angeles",
    "SF": "America/Los_Angeles",
    "NY": "America/New_York",
    "Chicago": "America/Chicago",
}

US_STATE = re.compile(
    r"\b(united states|usa|u\.s\.|AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|"
    r"MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|"
    r"california|new york|illinois|texas|massachusetts|connecticut|new jersey|florida|"
    r"washington|colorado|georgia|pennsylvania)\b"
)


def in_us(country: str | None, state: str | None, city: str | None) -> bool:
    if not (country or state or city):
        return True  # no location given: keep them (banks still need a known office)
    if country:
        return bool(re.search(r"united states|^us$|^usa$|u\.s\.", country.strip(), re.I))
    return bool(US_STATE.search(" ".join(p for p in (state, city) if p))) or office(city, state) != "Other"


PATH_HINTS = [
    ("VC", re.compile(r"venture|seed|early[- ]stage|growth equity|ventures", re.I)),
    ("PE", re.compile(r"private equity|buyout|merchant banking|private investing|private capital", re.I)),
    ("IB", re.compile(r"investment bank|m&a|mergers|coverage|corporate finance|capital markets|"
                      r"\becm\b|\bdcm\b|leveraged finance|restructuring|advisory|\bibd\b", re.I)),
]


def career_path(firm_paths: list[str], *hints: str | None) -> str:
    """Pick the career path for a person at a firm that may do several."""
    if len(firm_paths) == 1:
        return firm_paths[0]
    text = " ".join(h for h in hints if h)
    for path, pattern in PATH_HINTS:
        if path in firm_paths and pattern.search(text):
            return path
    return firm_paths[0]
