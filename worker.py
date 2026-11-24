"""Railway entry point: runs the sender forever, reconnecting to the database if it drops."""

import logging
import os
import sys
import time

import psycopg

from outreach import config, db, gmail, sender

logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("worker")


def main() -> None:
    settings = config.load()
    missing = [name for name, value in (
        ("DATABASE_URL", settings.database_url), ("SENDER_EMAIL", settings.sender_email),
        ("GOOGLE_CLIENT_ID", settings.google_client_id),
        ("GOOGLE_CLIENT_SECRET", settings.google_client_secret),
        ("TOKEN_ENCRYPTION_KEY", settings.token_encryption_key),
    ) if not value]
    if missing:
        sys.exit(f"Missing settings: {', '.join(missing)}")
    log.info("worker starting: sender=%s practice_mode=%s practice_inbox=%s daily_limit=%s",
             settings.sender_email, settings.practice_mode, settings.practice_inbox or "-",
             settings.daily_limit)
    while True:
        try:
            conn = db.connect(settings.database_url)
            # The two URL overrides exist only for local end-to-end tests against a fake Google.
            client = gmail.Gmail(conn, settings,
                                 token_url=os.environ.get("GOOGLE_TOKEN_URL") or gmail.TOKEN_URL,
                                 api=os.environ.get("GMAIL_API_BASE") or gmail.API)
            sender.loop(conn, settings, client)
        except psycopg.OperationalError as e:
            log.warning("database connection lost (%s); reconnecting in 10s", e)
            time.sleep(10)


if __name__ == "__main__":
    main()
