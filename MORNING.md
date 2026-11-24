# Morning notes (Oct 6)

## Done overnight
- **Website** (`web/`): Google sign-in, number box (default 200, max 1,000), Send, Stop, one
  status line. Warns if the sending server is down or Google sign-in expired.
- **Sender** (`worker.py`): one email every 25–40 seconds (random), Stop works mid-run, daily
  cap of 1,000, follow-ups after 5 and 7 more business days in the same thread, replies stop
  follow-ups, bounces and "remove me" replies are blocked forever, auto-stop above 5% bounces,
  never emails the same person twice even if it crashes or two copies run.
- **Contact tools** (`cli.py`): import provider CSVs, keep only target titles and cities,
  pick 20 per firm (per office at big firms), 8/8/4, UCLA/Bain first, build the
  2 junior → 2 mid → 1 senior order rotating firms, write each email.
- **Emails**: all 9 templates use your Kevin/Clearlake email. The AI rewrites only the
  "I was interested in your path…" sentence, using facts it can quote from the person's record.
  If it can't, a plain safe sentence is used (`templates/fallback_line.txt`).
- **Tested**: 58 automatic tests pass. Full local run: website Send → sender → 5 emails, then
  Stop at 5 of 50. Full-size run: 174 firms, 4,350 fake people → 3,680 picked and ordered.
- **Practice mode is on**: until you switch it off, every email goes to your own inbox.

## Needs you
1. **PE firm list is short: 55 of 300.** The full 2026 PEI 300 needs a free sign-up at
   privateequityinternational.com. Once you have it, add the rows to `data/firms.csv` and run
   `python cli.py firms`. (A copy of the full list turned up on a random file site; it looked
   like an unauthorized copy, so it wasn't used. I also didn't use PEI's older free 2021 list.)
   Banks (25) and VC (100) are complete. Sources are in `data/firms_sources.md`.
   - The bank list is ranked by 2025 U.S. M&A deal value. It includes Allen & Co and M. Klein,
     which have very few analysts; Houlihan Lokey is the obvious swap.
2. **OpenAI key** → put it in `.env` (`OPENAI_API_KEY=`). Not needed on Railway.
3. **Accounts and deploy**: Supabase, Google Cloud sign-in setup, Vercel, Railway. Steps are in
   `README.md` under "Setup". I didn't create anything in your accounts; say the word and I can
   do the Supabase/Vercel/Railway parts with their command-line tools (you're logged in).
4. **Contact data**: provider exports (Apollo/Clay). For the personal sentence to be specific,
   the CSV needs Education and Past Employers columns.
5. **the sender's resume**: didn't come through last night. Optional; his email already gives the
   key facts.

## Good to know
- Run `python cli.py doctor` to see what's set up and what isn't.
- Nothing is committed to git yet.
- While researching firms, a helper sent your UCLA email to sec.gov once, as the contact
  address that SEC's website asks automated visitors for. It wasn't repeated.
- The Gmail and Google Calendar connectors for Claude need authorizing in your claude.ai
  connector settings if you want me to use them (not needed for this app).
- A local test database is running in Docker (`matt-outreach-pg`); stop it with
  `docker stop matt-outreach-pg`.
