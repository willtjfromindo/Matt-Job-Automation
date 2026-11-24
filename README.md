# Outreach

Sends personalized networking emails from one person's Gmail to people in investment banking,
private equity and venture capital. The sender's only screen is a one-page website: sign in once,
pick a number (default 200, max 1,000 a day), press **Send** or **Stop**.

The full plan is in [PLAN.md](PLAN.md).

## What's where

| Folder / file | What it is | Runs on |
|---|---|---|
| `web/` | The one-page website (sign in, Send, Stop) | Vercel |
| `worker.py`, `outreach/` | The sender: sends one email every 25–40 s, follow-ups, reads replies/bounces | Railway |
| `cli.py`, `outreach/` | Tools to load firms and contacts, write the emails, build the send order | Will's laptop |
| `templates/` | The email templates (9 first emails + 2 follow-ups + fallback sentence) | — |
| `data/firms.csv` | The target firms (banks, PE, VC) | — |
| `supabase/migrations/` | Database tables | Supabase |
| `tests/` | Automatic tests (`.venv/bin/python -m pytest tests`) | — |

## How an email gets made

1. **Import** a contact CSV from a data provider (Apollo, Clay, ...). Only target titles
   (analyst / associate / VP / principal) at listed firms in the U.S. are kept; bank contacts
   must be in LA, New York, SF or Chicago.
2. **Pick** 20 people per firm (per office at big firms): 8 junior, 8 mid, 4 senior. People
   who went to the sender's school or worked at one of their past employers are picked first
   (the app reads both from the sender's profile). Everyone else is kept as a backup.
3. **Order**: one numbered list repeating Junior, Junior, Mid, Mid, Senior, moving to the next
   firm each time. Those shared-school and shared-employer people go first.
4. **Write**: the template for their career path and level, with one sentence written for that
   person by the AI (OpenAI or Claude). The sentence may only use facts saved on the person's
   record and facts about the sender. Automatic checks reject anything that can't be traced back
   to those facts; after two failed tries the plain fallback sentence is used instead.
5. **Send**: the sender presses Send. Follow-ups that are due go first (same thread, after 5 and
   then 7 business days), then the next people in the list.
6. **Track**: replies stop follow-ups; bounces and "please remove me" replies block that address
   forever. A run stops itself if more than 5% of its people can't be reached at any address.

### Guessed emails

Most contacts come from firms' own team pages, which don't show emails, so their address is a
guess built from the firm's email format (`cli.py guess-emails`). Each person has up to 3
likely formats (first.last, flast, first), best first; a firm format confirmed from public
examples goes first with one backup.

- **A bounce means try the next guess.** The inbox check runs every 3 minutes while sending.
  When a guess bounces, that address is blocked and the same email goes to the person's next
  guess. A run doesn't finish until its last guess has gone 15 minutes without bouncing.
- **It learns each firm's format.** Once a format has reached someone at a firm, the next person
  there starts with it. If a proven format bounces for one person, they've probably left, so no
  more guesses are made for them.
- **Daily bounce cap.** After 10 bounces in one day (`MAX_BOUNCES_PER_DAY`) the run pauses until
  tomorrow. Lots of bounces can get a Google account flagged; keep this low.
- Only one address is ever tried at a time, and only after the previous one bounced, so nobody
  gets the email twice. Firms whose mail servers accept every address never bounce, so a wrong
  guess there is silently lost.

## Safety switches

- **Practice mode is on by default.** Every email goes to `PRACTICE_INBOX` instead of the real
  person until `PRACTICE_MODE=false` is set on Railway. `python cli.py reset-practice` undoes
  practice sends.
- Only emails in `ALLOWED_EMAILS` can sign in to the website.
- The block list is checked before every single email.
- If the sender crashes mid-email, that person is never emailed again automatically
  (`python cli.py pending` shows them).
- The Google permission is stored encrypted; nobody ever sees the sender's password.

---

## Setting this up with your own email (start here if the app isn't yours)

This app sends email as one person, and **nothing about that person is written into the code**.
Their name, school, sign-off and opening sentence are settings; the facts the AI is allowed to
use come from a profile file built from their own resume. So making it yours is mostly filling
in settings. Here's all of it, in order. Then do the normal [Setup](#setup-one-time) below.

**Before you start, you need:** a Google account you're happy to send from (a plain `@gmail.com`
works), a Supabase account (free), a Vercel account (free), a Railway account (about $5 a month),
a Google Cloud account (free), and an OpenAI or Anthropic API key (a few dollars).

### 1. Your email address, in four places

| Where | Setting | Set it to |
|---|---|---|
| Vercel (the website) | `ALLOWED_EMAILS` | Your address. Only addresses on this list can sign in |
| Vercel | `SENDER_EMAIL` | Your address — the account the emails come from |
| Railway (the sender) | `SENDER_EMAIL` | The same address |
| Railway | `PRACTICE_INBOX` | Your address. While practice mode is on, every email lands here instead of with a real person |
| Your laptop, in `.env` | `SENDER_EMAIL`, `PRACTICE_INBOX` | The same again |

On a Google Workspace account (your own company or school domain), also set
`GOOGLE_HOSTED_DOMAIN` on Vercel to that domain, like `yourcompany.com`. On a plain
`@gmail.com`, delete that setting.

### 2. Who you are, in four more settings

These are the only places your details appear in an email. Set them in `.env` on your laptop
**and** on Railway (the sender uses them for follow-ups):

| Setting | Where it shows up | Example |
|---|---|---|
| `SENDER_NAME` | The name above the sign-off, and the name on the email itself | `Alex Rivera` |
| `SENDER_SCHOOL` | The subject line: "… Student Interested in Your Path to Blackstone" | `UCLA` |
| `SENDER_TAGLINE` | The line under your name | `UCLA Economics \| Class of 2027` |
| `SENDER_INTRO` | The one sentence that opens every first email, right before the personal line | `I'm a UCLA Economics senior graduating in June 2027, and I recently interned at Example Consulting.` |

**Leave one of these empty and nothing gets sent.** You'll get a clear error instead, which is
on purpose: better a loud stop than an email signed by nobody.

### 3. Your resume, and the facts the AI may use

The AI writes one sentence per email and is only allowed to use facts it has been given about
you. Those come from your resume:

```
.venv/bin/python cli.py profile data/your_resume.pdf
```

That writes `data/sender_profile.json`. **Open it and read it.** Every sentence the AI writes is
checked against this file, and anything that isn't in it gets thrown away, so a wrong fact here
is the one thing that can put a wrong fact in an email. While you're in there:

- `facts` — short true statements about you. Delete any you'd rather not mention.
- `schools` and `employers` — with the spellings people actually use, so the app can spot someone
  who went to your school or worked where you worked. Those people get emailed first.
- `extra_allowed_words` — other words tied to those, like what your school's students call
  themselves (UCLA → `Bruin`). Without this the checker treats an unknown capitalised word as
  made up and rejects the sentence.

Then point `RESUME_PATH` in `.env` at your resume file, because the emails say "I've attached my
resume".

### 4. Read the templates before you send anything

The 12 files in `templates/` are the actual emails, and they're worth five minutes of your time.
Your name, school, tagline and opening sentence fill themselves in from the settings above, so
what's left to decide is the wording of the ask ("I'd be grateful for 15 minutes…").

**Keep the curly-brace words exactly as they are** — `{first_name}`, `{firm}`,
`{personal_line}`, `{sender_name}`, `{sender_school}`, `{sender_tagline}`, `{sender_intro}`.
They get swapped for real text when the email is written; delete one by accident and the email
breaks. `templates/README.txt` explains every one of them and which file is used for whom.

### 5. Who you're emailing

`data/firms.csv` is the target list: firm name, whether it's a bank, private equity or venture
capital, and the firm's website domain. Put your own firms in it, then load it:

```
.venv/bin/python cli.py firms data/firms.csv
```

### 6. Google sign-in without a school or company account

Step 2 of the setup below says to make the app "Internal", which is the nice option: no Google
review, and you stay signed in. **"Internal" only exists if you sign in with a Google Workspace
account and pick that organisation when you create the project.** A plain `@gmail.com` can't.

On a personal Gmail:

- Choose **External** and leave the app in **Testing**. Don't submit it for review — you don't
  need to, because you're the only user.
- Add your own address under **Test users**, or sign-in is refused.
- Google makes you sign in again **every 7 days**. The website tells you when; just sign in
  again. Nothing is lost.

Everything else in that step is the same.

### 7. Your own daily limit

Google caps one account at roughly 500 emails a day on a personal Gmail and 2,000 on a paid
Workspace account. Those are ceilings, not targets.

**Start far lower.** Sending lots of mail to people who didn't ask for it is how accounts get
flagged and suspended, and getting one back is painful. Set `DAILY_LIMIT` to **20-30** on both
Vercel and Railway, watch what bounces for a week, and only then raise it. The app also pauses
for the day after 10 bounces (`MAX_BOUNCES_PER_DAY`) and stops a run if more than 5% of people
can't be reached at any address (`BOUNCE_STOP_RATE`) — leave both switched on.

### 8. Send to yourself before you send to anyone real

`PRACTICE_MODE=true` on Railway sends every email to your own inbox instead of the real person.
Keep it that way until you've read a few of your own emails end to end.
[Testing on your own account](#testing-on-your-own-account-before-the-real-sender) below walks
through it with made-up people, so you never touch a real contact by mistake. When you're happy:
`cli.py reset-practice`, then set `PRACTICE_MODE=false`.

### Where your details live, all in one list

| Thing | What's in it |
|---|---|
| `SENDER_NAME`, `SENDER_SCHOOL`, `SENDER_TAGLINE`, `SENDER_INTRO` | Everything about you that appears in an email |
| `data/sender_profile.json` | The only facts about you the AI may use (built from your resume) |
| `RESUME_PATH` → `data/resume/…` | The file attached to every first email |
| `data/firms.csv` | The firms you're targeting |
| `templates/*.txt` | The wording of the emails — no names, just fill-ins |

None of the last four are in this repository: resumes, profiles and contact files are all
ignored by git, so your details and other people's stay on your own machine.

### One thing to be clear about

This app sends email to strangers who didn't ask to hear from you. That's legal in the US if
you're honest about who you are and you stop when asked, and the app does both: any reply asking
to be removed blocks that address forever. But read your own emails and ask whether you'd be
glad to receive one. Keep the numbers small, make them genuinely personal, and don't use a
school or work account you can't afford to lose.

## Setup (one time)

You need accounts on Supabase, Vercel, Railway (about $5/month) and Google Cloud, an OpenAI API
key, and the contact data provider.

### 1. Database (Supabase)
1. Create a new project (free tier is fine).
2. SQL Editor → paste all of `supabase/migrations/0001_init.sql` → Run.
3. Project Settings → Database → Connection string. Copy two versions:
   - **Session pooler** (port 5432) → for Railway and your laptop. (Railway must use this
     one: the sender holds a lock so two copies can never send at the same time.)
   - **Transaction pooler** (port 6543) → for Vercel.

### 2. Google sign-in (Google Cloud)
1. Go to console.cloud.google.com and create a project. **Try creating it while signed in with
   a UCLA account and picking the UCLA organization.** If that works, you can make the app
   "Internal", which means no Google review and no weekly re-sign-in.
2. APIs & Services → Library → enable **Gmail API**.
3. Google Auth Platform (OAuth consent screen): app name "Outreach".
   - Audience: **Internal** if available. Otherwise **External**, leave it in **Testing**, and
     add your email and the sender's as test users. (In Testing, Google makes people sign in again
     every 7 days; the website will ask when that happens.)
   - Data access → add scopes: `openid`, `email`, `profile`, `.../auth/gmail.send`,
     `.../auth/gmail.readonly`.
4. Clients → Create client → **Web application**. Authorized redirect URIs:
   - `https://YOUR-APP.vercel.app/api/auth/callback`
   - `http://localhost:3100/api/auth/callback` (for running on the laptop)
5. Copy the Client ID and Client secret.

### 3. Shared secret
Make one encryption key and use the same value on Vercel, Railway and your laptop:
```
python3 -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
```

### 4. Website (Vercel)
New Project → import this GitHub repo → **Root Directory: `web`**. Environment variables are
listed in `web/.env.example` (details in [web/README.md](web/README.md)). Start with
`ALLOWED_EMAILS` and `SENDER_EMAIL` set to **your** address for testing.

### 5. Sender (Railway)
New Project → Deploy from GitHub repo (root of the repo; `railway.json` sets the start command).
Add the variables from `.env.example` (DATABASE_URL = Session pooler). Keep
`PRACTICE_MODE=true`, `SENDER_EMAIL` and `PRACTICE_INBOX` = your address. Railway doesn't need
the AI key.

### 6. Your laptop
```
cd matt-outreach-app
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env        # then fill in DATABASE_URL, OPENAI_API_KEY, ...
.venv/bin/python cli.py init
.venv/bin/python cli.py firms data/firms.csv
```

## Getting contacts ready

```
.venv/bin/python cli.py profile data/resume.pdf     # optional: the sender's facts from his resume
                                                     # (review data/sender_profile.json after)
.venv/bin/python cli.py guess-emails                 # team-page people -> data/imports/ready/
.venv/bin/python cli.py import data/imports/ready/*.csv
.venv/bin/python cli.py prepare                      # check emails, pick, order, write emails
.venv/bin/python cli.py preview 10                   # read the next 10 emails that will go out
```

Contact CSVs: the importer understands common column names (First Name, Last Name, Title,
Company, Email, Email Status, City, State, Country, LinkedIn URL, ...). For the personal
sentence to say something specific, the CSV also needs **Education**, **Past Employers** and
ideally **Headline/Bio** columns. Without them everything still works, but most people get the
plain fallback sentence and UCLA/Bain people can't be found. Clay (or Apollo's enrichment) can
add those columns.

Re-run `prepare` any time after importing more people; people already emailed keep their place.

## Testing on your own account (before the real sender)

1. Make a test list: `.venv/bin/python cli.py fake-contacts` then
   `.venv/bin/python cli.py import data/imports/fake_contacts.csv` and
   `.venv/bin/python cli.py prepare --fallback-only`.
2. Open the website, sign in with your UCLA account, set the number to 5, press Send.
3. All 5 emails arrive in your inbox (practice mode), 25–40 seconds apart. Try Stop.
4. Reply to one of them: within ~5 minutes of the next send (or 30 min idle) it's marked replied.
5. Clean up: `.venv/bin/python cli.py reset-practice`, and delete the fake people
   (`delete from contacts where email like '%@example.com';` in Supabase SQL editor).

## Final step: connect the real sender's email

1. Vercel: add the sender's address to `ALLOWED_EMAILS` and set `SENDER_EMAIL` to it. Redeploy.
2. Railway: set `SENDER_EMAIL` to the sender's address. Keep `PRACTICE_MODE=true` and
   `PRACTICE_INBOX` = your address for now.
3. the sender opens the website, signs in with his UCLA account, clicks Allow.
4. He sends 1 email: it should arrive in **your** inbox, from **his** address.
5. `.venv/bin/python cli.py reset-practice`, then on Railway set `PRACTICE_MODE=false`.
   From now on, Send emails real people.

## Every day

- the sender: open the site, check the number, press Send.
- Will (as needed): import more contacts and run `prepare` so the list stays ahead;
  `python cli.py stats` for reply and meeting rates; `python cli.py meeting someone@firm.com`
  when a meeting is booked; `python cli.py block someone@firm.com` to never email someone.

## Commands

| Command | What it does |
|---|---|
| `doctor` | Check that everything is set up (settings, templates, database, sign-in, sender) |
| `init` | Create the database tables |
| `firms [path]` | Load the firm list (default `data/firms.csv`) |
| `profile [resume]` | Build the sender's fact list from his resume, or show the current one |
| `import FILE...` | Import provider CSVs |
| `prepare [--limit N] [--fallback-only]` | verify + select + order + draft |
| `verify [--paid]`, `select`, `order`, `draft` | The steps of `prepare`, one at a time |
| `preview [N]` | Show the next N emails |
| `stats` | Replies and meetings by tier, path, level, office, firm |
| `meeting EMAIL` / `block EMAIL` | Mark a meeting / never email this address |
| `reset-practice` | Undo practice sends |
| `pending`, `resolve ID sent/failed` | Handle an email interrupted by a crash |
| `fake-contacts` | Make made-up people for testing |
