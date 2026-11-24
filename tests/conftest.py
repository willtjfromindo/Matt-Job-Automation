import os
import sys
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from outreach import db  # noqa: E402

TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgres://postgres:dev@localhost:54329/outreach_test")


# The templates print the sender's own details, which come from the environment. One made-up
# sender for every test, so no real person's details are needed to run the suite.
SENDER = {
    "SENDER_NAME": "Alex Rivera",
    "SENDER_SCHOOL": "UCLA",
    "SENDER_TAGLINE": "UCLA Economics | Class of 2027",
    "SENDER_INTRO": ("I'm a UCLA Economics senior graduating in June 2027, and I recently "
                     "interned at Example Consulting."),
}


@pytest.fixture(autouse=True)
def _sender_env(monkeypatch):
    for key, value in SENDER.items():
        monkeypatch.setenv(key, value)


@pytest.fixture(scope="session")
def _database():
    admin = psycopg.connect(TEST_DB.rsplit("/", 1)[0] + "/postgres", autocommit=True)
    admin.execute("drop database if exists outreach_test")
    admin.execute("create database outreach_test")
    admin.close()
    yield TEST_DB


@pytest.fixture
def conn(_database):
    c = db.connect(_database)
    c.execute("drop schema public cascade; create schema public;")
    c.commit()
    db.migrate(c)
    yield c
    c.close()
