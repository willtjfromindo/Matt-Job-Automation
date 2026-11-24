# Outreach — Implementation Plan (V1)

Goal: help the sender (UCLA econ, Bain intern) start real conversations with people in investment
banking, private equity, and venture capital. The system builds a contact list, writes a short
personal email for each person using only facts we can prove, and sends from the sender's own
UCLA email when he presses "Send" on a one-page website.

Success is measured in replies and meetings per 100 contacts, not emails sent.

---

## 1. Ground rules (apply to every step)

1. **Nothing gets made up.** Every personal line in an email must point to a real fact: either
   from the sender's approved fact list or from a saved field on the recipient's record. If there is
   no real connection, the email stays plain and professional.
2. **Finding people and emailing people are separate steps.** A contact only gets emailed after
   it has passed: email check → draft → automatic checks. A personal sentence that fails the
   checks is replaced by a plain, safe sentence.
3. **Practice mode for testing.** Before the sender goes live, the sender runs in a hidden
   practice mode that sends everything to Will's test address instead of real people.
4. **the sender never shares his password.** He signs in to Google himself; the app keeps only the
   permission token, encrypted in the database.
5. **Anyone who says stop, bounces, or isn't interested is blocked for good.**

---

## 2. Tech choices

| Piece | Choice | Why |
|---|---|---|
| Website | Next.js on **Vercel** (free) | The one page the sender uses, from any laptop |
| Sign-in | Google sign-in, locked to the sender's UCLA address | One sign-in logs him in *and* gives send permission |
| Database | **Supabase** Postgres (free) | Contacts, send order, drafts, runs, block list |
| Sender | Python 3.12 worker on **Railway** (~$5/month) | Runs all day, even when laptops are closed |
| AI | OpenAI (default; key added later) or Claude, structured JSON output | Writes the one personal sentence + returns evidence for each claim |
| Email | Gmail API (UCLA mail runs on Google, `g.ucla.edu`) | Sends from his real inbox, threads follow-ups, reads replies |
| Contact data | CSV export from a people-data provider (e.g. Apollo) | Scraping LinkedIn breaks its rules and gets accounts banned |

---

## 3. The website (the only thing the sender sees)

**Before sign-in:** one centered "Sign in with Google" button.

**After sign-in:** one page, nothing else.

```
            ┌────────────────────────────┐
            │   Number of people  [ 200 ]│   default 200, min 1, max 1000
            │                            │
            │        [   Send   ]        │
            │        [   Stop   ]        │
            │                            │
            │   Sent 37 of 200           │   small text, not a button
            └────────────────────────────┘
```

- **Send:** starts sending to the next N people in the send order (section 6.8).
  Disabled while a run is going.
- **Stop:** stops after the email currently being sent. Nothing is lost; the next Send picks
  up where it left off.
- **Number of people:** per day. Default 200, max 1,000. If he presses Send again the same
  day, the total for the day still can't pass 1,000.
- **Spacing:** a random wait of 25–40 seconds between emails. 200 emails ≈ 1 h 50 min;
  1,000 ≈ 9 hours.
- Closing the page doesn't stop sending; the server keeps going until done or Stop.
- Design: clean, calm, lots of white space, one accent color, works on phone and laptop,
  dark mode.

---

## 4. Sign-in, done once

- the sender clicks "Sign in with Google" and picks his UCLA account.
- One Google screen asks to allow: his email address, sending email, reading replies. He
  clicks Allow. That one step both logs him in and gives the sender permission.
- The app keeps a long-lasting permission token (encrypted in Supabase). The Railway sender
  uses it, so he never has to grant access again.
- Only the sender's address (plus Will's, for testing) can sign in. Anyone else is turned away.
- **Catch:** Google cuts off unapproved apps' tokens after 7 days. Two fixes:
  1. Best: create the Google app inside UCLA's Google organization as an "internal" app, so
     there's no 7-day limit and no Google review. Needs the sender's UCLA account to be allowed to
     create a Google Cloud project.
  2. Otherwise: he signs in again once a week (the page asks him when needed) until/unless we
     get Google's approval, which takes a few weeks.

---

## 5. Folder layout

```
matt-outreach-app/
  README.md
  web/                      website (Vercel)
    app/page.tsx            the one page
    app/api/auth/...        Google sign-in, saves the token
    app/api/run/            start, stop, status
  worker/                   sender (Railway)
    main.py                 waits for Send, sends one email every 25–40 s, checks Stop
    gmail.py                send, refresh token, read replies and bounces
    inbox_sync.py           marks replies, bounces, opt-outs
    followups.py            puts due follow-ups into the queue
  pipeline/                 run by Will on his laptop to prepare contacts
    import_contacts.py      provider CSV → clean → seniority → quotas
    verify_emails.py        email check
    build_profile.py        resume → the sender's fact list
    evidence.py             find real connections, tiers A–E
    draft.py                AI writes the personal sentence
    qa.py                   automatic checks
    build_order.py          builds the round-robin send order
    stats.py                replies / meetings report
  supabase/migrations/      database tables
  templates/                9 email templates (IB/PE/VC × junior/mid/senior), Will edits these
  data/
    firms.csv               425 firms
    sender_profile.json    the sender's approved facts
```

---

## 6. How each part works

### 6.1 Firm list
- Target 425 firms: top 100 VC by AUM, the PEI 300 private equity list, and the top 25
  investment banks by league tables. **Status:** `data/firms.csv` has 25 banks, 100 VC and
  55 PE (the full PEI 300 needs a free PEI sign-up; see MORNING.md). Will/the sender review
  the CSV before anything runs.
- Firms that do more than one (e.g. a bank with a PE arm) list each career path separately.

### 6.2 Who to contact at each firm
- **20 people per firm**, split 8 junior / 8 mid / 4 senior (40/40/20).
- **Big firms with several offices:** 20 people *per office* in LA, New York, SF, and Chicago
  (up to 80 per firm), when that many can be found.
- **Banks:** only people in LA, New York, SF, or Chicago offices.
- **Who first:** UCLA grads and ex-Bain people are picked first to fill each quota. If there
  aren't enough, fill the rest with anyone in a matching role.
- Senior means VP / Principal level, not partners or MDs.

| Path | Junior | Mid | Senior |
|---|---|---|---|
| IB | Analyst | Associate | VP |
| PE | Analyst | Associate | Senior Associate / VP |
| VC | Investment Analyst | Associate | Senior Associate / Principal |

**Math:** 100 VC + 300 PE + 25 banks = 425 firms × 20 = 8,500. About 20 big banks with all 4
offices add 60 each = +1,200. Total ≈ 9,700 people. At 200/day ≈ 49 sending days; at
1,000/day ≈ 10.

### 6.3 Getting contacts
- Pull CSVs from the data provider per firm, filtered by the titles above and the 4 cities
  (banks) or U.S. (PE/VC).
- Importer throws out duplicates, wrong titles, wrong locations, and missing emails; extras
  beyond the quota are kept as backups.

### 6.4 Email check
- Format check + "does this domain accept mail" check (free, built in).
- Optional paid checker (NeverBounce / ZeroBounce); only "valid" goes forward. Strongly
  recommended at this volume, since bounces hurt the sender's inbox reputation.

### 6.5 the sender's fact list
- Starts from the facts in the sender's own email (UCLA senior, Economics, two summers at
  Bain & Company in Southeast Asia, consulting + banking exposure, focused on investing).
- Optionally, the sender's resume (PDF or text) adds more facts.
- AI turns it into a structured list: school, major, employers (exact names, e.g.
  "Bain & Company", not "Bain Capital"), clubs, activities, hobbies, hometown and cities,
  interests.
- the sender reviews and edits the list. Only facts in this file can ever appear in an email.

### 6.6 Finding real connections (tiers)
Checked in order; the first match wins. Each match saves the exact field and text it came from.

| Tier | Connection | How it's found |
|---|---|---|
| A | UCLA | "UCLA" / "University of California, Los Angeles" in their education |
| B | Bain or other shared employer | Exact employer match (Bain & Company ≠ Bain Capital) |
| C | Shared hobby/activity | the sender's hobbies matched against their listed interests/bio |
| D | Something specific about their career path | AI picks one concrete fact from their bio, with a quote |
| E | Firm/role reason only | No personal claim; plain professional email |

A–C are found with simple matching code (no AI), so they can't be invented. D uses AI but must
quote the source text exactly.

### 6.7 Writing and checking the emails
- **Templates:** a `templates/` folder holds 9 templates, one per career path × level:

  |  | Junior | Mid | Senior |
  |---|---|---|---|
  | IB | `ib_junior.txt` | `ib_mid.txt` | `ib_senior.txt` |
  | PE | `pe_junior.txt` | `pe_mid.txt` | `pe_senior.txt` |
  | VC | `vc_junior.txt` | `vc_mid.txt` | `vc_senior.txt` |

  Each has a subject line and body with fill-ins: `{first_name}`, `{firm}`, `{team}`,
  `{title}`, `{personal_line}`. All 9 start from Will's email to Kevin at Clearlake; Will
  edits them per path and level.
- Names, firm, team, and title are filled straight from the record (no AI).
- `{personal_line}` is the only part the AI writes, replacing "I was interested in your path
  across public-markets research and investment banking before joining Clearlake, as I've
  similarly had exposure to both consulting and banking and am increasingly focused on
  investing." with a sentence for that person: one sentence based on the tier A–E
  evidence. Tier E gets no personal line (the sentence is dropped cleanly).
- Drafts are made **ahead of time** on Will's laptop (`cli.py prepare`), so the sender never
  waits on the AI. Will runs this before each big push; it stays ~1,000 ahead of the send order.
- AI returns JSON: the personal line, the sender-facts used, and for each claim about the
  recipient: the claim, which field it came from, and the exact quote.
- Follow-ups: `followup_1.txt` and `followup_2.txt` (placeholders, Will edits).
- **Automatic checks** reject a draft if:
  - a quote doesn't appear word-for-word in the recipient's saved record;
  - a the sender fact isn't in his approved list;
  - a tier A/B connection is claimed but not backed by the record (or vice versa);
  - names, firm, or title don't match the record;
  - leftover placeholders like `[Name]`, too long, more than one ask, or banned phrases
    ("I hope this finds you well", "I came across your profile", etc.);
  - it's near-identical to another email at the same firm.
- Failed sentences get one automatic rewrite; if they fail again, the plain sentence in
  `templates/fallback_line.txt` is used instead (the person still gets a good email).
- No human approval step in the website. Will spot-checks a sample after each drafting batch.

### 6.8 Send order (round-robin)
Built ahead of time as one numbered list:
- Every slot follows the repeating pattern **Junior, Junior, Mid, Mid, Senior**.
- For each slot, take the next firm in rotation (Firm 1 → … → Firm 425 → Firm 1) that still
  has someone of that level left, and take that firm's next person of that level.
- UCLA and Bain people go to the front of each firm's line.
- Result: never more than 2 of one level in a row, and a firm doesn't come up again until the
  rotation loops back.
- Example start: J (Firm 1), J (Firm 2), M (Firm 3), M (Firm 4), S (Firm 5), J (Firm 6) …

### 6.9 Sending
When the sender presses Send with N:
1. The website creates a "run" for N people in the database.
2. The Railway sender picks it up, takes the next person on the send order, checks the block
   list, sends, waits a random 25–40 seconds, repeats.
3. Before every email it checks for Stop.
4. Due follow-ups go out first and count toward N.
5. Done when N are sent, Stop is pressed, or the daily total hits 1,000.

### 6.10 Replies, bounces, opt-outs
Between sends, the sender checks the sender's inbox:
- Reply in the thread → "replied", no more follow-ups.
- Bounce notice → blocked.
- Reply with "unsubscribe", "remove me", "not interested", "stop" etc. → blocked.
- If bounces pass ~5% in a run, the run stops itself to protect his inbox.

### 6.11 Follow-ups
- No reply after 5 business days → follow-up 1. No reply 7 business days later →
  follow-up 2. Then closed. Same thread, shorter, same checks.

### 6.12 Results
- No dashboard for the sender. Will runs `stats.py` (or opens Supabase) to see reply and meeting
  rates by tier, career path, seniority, and firm.
- Meetings are marked by hand in Supabase for now.

---

## 7. Data model (Supabase)

**firms**: id, name, career_paths, rotation_position, active.

**contacts**: id, first_name, last_name, firm_id, career_path, title, team, focus (industry /
sector), seniority (junior / mid / senior), office (LA / NY / SF / Chicago / other), location,
timezone, years_at_firm, email, email_status, profile_url, education, past_employers,
interests, headline_or_bio, source (which import file), UCLA_connection, Bain_connection,
other_connection, personalization_tier (A–E), personalization_source, personalization_fact,
send_order, status, follow_up_count, last_contacted_at, follow_up_date, gmail_thread_id,
created_at.

**drafts**: id, contact_id, kind (first / follow-up 1 / follow-up 2), subject, body, evidence
(JSON), qa_result, qa_issues.

**runs**: id, requested_count, sent_count, status (running / stopped / done / auto-stopped),
started_at, ended_at.

**sends**: id, run_id, contact_id, draft_id, sent_at, gmail_message_id, practice_mode.

**suppression**: email, reason (opted out / bounced / not interested / manual), added_at.
Checked before every send, no exceptions.

**google_tokens**: email, encrypted_refresh_token, scopes, updated_at.

**Contact status flow**

```
new → verified → drafted → ready (passed checks) → sent
    → follow-up 1 → follow-up 2 → closed (no reply)
sent / follow-up → replied → meeting → closed
any → blocked (bounced, opted out, bad email, failed checks twice)
```

---

## 8. Build order

| # | Step | Done when |
|---|---|---|
| 1 | Supabase tables, Railway + Vercel projects | Empty app deploys |
| 2 | 425-firm list | CSV reviewed by Will/the sender |
| 3 | Contact importer + quotas + office rule | Sample CSV imports with 8/8/4 per firm/office |
| 4 | Email check | Bad addresses get marked and skipped |
| 5 | the sender's fact list from resume | the sender approves his fact file |
| 6 | Connection finder (tiers A–E) | Test records land in the right tier with evidence |
| 7 | Templates + email writer | Right template per path/level; personal line has evidence |
| 8 | Automatic checks | Planted fake claims are caught |
| 9 | Send order builder | Pattern J, J, M, M, S holds; firms rotate |
| 10 | Google sign-in + token storage, **tested with Will's account** | Will signs in once; sender can send |
| 11 | Sender: runs, 25–40 s spacing, Stop, daily 1,000 limit | Practice run of 20 from Will's account to a test inbox works |
| 12 | Reply / bounce / opt-out tracking | Test reply and test bounce update status |
| 13 | Follow-ups | Follow-up lands in same thread on schedule |
| 14 | The one-page website | Sign in, Send, Stop, count all work, looks good |
| 15 | Full end-to-end test on Will's account | Everything works with fake contacts and test inboxes |
| 16 | **Final step: connect the real sender's email** | the sender signs in once with his UCLA account; one test email to Will arrives from his inbox |
| 17 | First real run (small, e.g. 50) | Sent; Will reads every email that went out |
| 18 | Measure ~2 weeks, improve the emails, then full campaign | Daily runs at the sender's chosen number |

Steps 1–15 are built and tested entirely on Will's account and test data. the sender's email is
connected only at step 16, once everything else works. Nothing can reach a real contact until
then.

**Time estimate for steps 1–14 (Claude's build time):**

| Part | Hours |
|---|---|
| Setup: database, Vercel, Railway | 1 |
| 425-firm list | 1.5 |
| Importer, quotas, email check | 1.5 |
| Fact list, connection finder, templates, AI writer, checks | 3 |
| Send order builder | 0.5 |
| Google sign-in + token storage | 1.5 |
| Sender: runs, spacing, Stop, replies, bounces, follow-ups | 2.5 |
| One-page website | 1.5 |
| End-to-end testing | 2 |
| **Total** | **~15** |

Spread over 2–3 days, because some steps wait on Will/the sender (accounts, API keys, resume,
Google sign-in). Gathering contacts from the data provider is separate.

---

## 9. What we need from Will / the sender

1. the sender's resume (optional now; his email already gives the key facts).
2. Approval of the 425-firm list.
3. A paid people-data provider account (e.g. Apollo).
4. An OpenAI API key (or Anthropic) — a few cents per email.
5. Accounts on Vercel, Supabase, Railway (~$5/month for Railway).
6. the sender to try creating a Google Cloud project with his UCLA account (decides whether the
   7-day sign-in limit applies, see section 4).

---

## 10. Risks

- **Volume.** Will chose 200/day default, 1,000/day max, 25–40 s apart. Google allows ~2,000
  a day for school accounts, but many cold emails fast can get the account flagged. The
  auto-stop on bounces (6.10) and a paid email checker reduce this. If Google ever shows a
  warning, lower the number.
- **Weekly re-sign-in** if the Google app can't be internal to UCLA (section 4).
- **Data provider quality.** Provider emails are often stale; expect 5–15% bounces without a
  paid checker.
- **Supabase free tier** pauses after a week of no use; daily sending keeps it awake.
