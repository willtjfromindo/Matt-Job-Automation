"""Settings, read from environment variables (or a local .env file)."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

TEMPLATES_DIR = ROOT / "templates"
DATA_DIR = ROOT / "data"
PROFILE_PATH = DATA_DIR / "sender_profile.json"

MODEL = "claude-opus-5-5"
LOCAL_TZ = "America/Los_Angeles"  # what "today" means for the daily limit


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _path(raw: str) -> str:
    """Relative paths are relative to the project folder."""
    raw = raw.strip()
    if not raw:
        return ""
    p = Path(raw)
    return str(p if p.is_absolute() else ROOT / p)


@dataclass(frozen=True)
class Settings:
    database_url: str
    sender_email: str
    sender_name: str
    practice_mode: bool
    practice_inbox: str
    daily_limit: int
    min_gap_seconds: float
    max_gap_seconds: float
    google_client_id: str
    google_client_secret: str
    token_encryption_key: str
    neverbounce_api_key: str
    bounce_stop_rate: float
    bounce_stop_min_sends: int
    followup1_business_days: int
    followup2_business_days: int
    # Guessed emails: how long to wait for a bounce before a guess counts as having worked,
    # and how many bounces in one day pause sending (to protect the sending account).
    bounce_wait_minutes: int = 15
    max_bounces_per_day: int = 10
    # Attached to every first email (the templates say "I've attached my resume"). Blank = none.
    resume_path: str = ""
    # Who the sender is, as the templates print it: see templates/README.txt. Blank stops an
    # email that needs it, rather than sending one signed by nobody.
    sender_school: str = ""
    sender_tagline: str = ""
    sender_intro: str = ""


def load() -> Settings:
    return Settings(
        database_url=os.environ.get("DATABASE_URL", ""),
        sender_email=os.environ.get("SENDER_EMAIL", "").strip().lower(),
        sender_name=os.environ.get("SENDER_NAME", "").strip(),
        sender_school=os.environ.get("SENDER_SCHOOL", "").strip(),
        sender_tagline=os.environ.get("SENDER_TAGLINE", "").strip(),
        sender_intro=os.environ.get("SENDER_INTRO", "").strip(),
        # Practice mode is ON unless explicitly turned off.
        practice_mode=_bool("PRACTICE_MODE", True),
        practice_inbox=os.environ.get("PRACTICE_INBOX", "").strip(),
        daily_limit=int(os.environ.get("DAILY_LIMIT", "1000")),
        min_gap_seconds=float(os.environ.get("MIN_GAP_SECONDS", "25")),
        max_gap_seconds=float(os.environ.get("MAX_GAP_SECONDS", "40")),
        google_client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
        google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
        token_encryption_key=os.environ.get("TOKEN_ENCRYPTION_KEY", ""),
        neverbounce_api_key=os.environ.get("NEVERBOUNCE_API_KEY", ""),
        bounce_stop_rate=float(os.environ.get("BOUNCE_STOP_RATE", "0.05")),
        bounce_stop_min_sends=int(os.environ.get("BOUNCE_STOP_MIN_SENDS", "40")),
        followup1_business_days=int(os.environ.get("FOLLOWUP1_BUSINESS_DAYS", "5")),
        followup2_business_days=int(os.environ.get("FOLLOWUP2_BUSINESS_DAYS", "7")),
        bounce_wait_minutes=int(os.environ.get("BOUNCE_WAIT_MINUTES", "15")),
        max_bounces_per_day=int(os.environ.get("MAX_BOUNCES_PER_DAY", "10")),
        resume_path=_path(os.environ.get("RESUME_PATH", "data/resume/resume.pdf")),
    )
