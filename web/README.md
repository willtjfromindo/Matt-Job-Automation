# Outreach — website

The one page the sender uses: sign in with Google, pick a number, press **Send** or **Stop**.

The website does only two things:

1. Signs the user in with Google and stores an encrypted Gmail refresh token in `google_tokens`.
2. Creates and stops rows in `runs`. The Python worker (Railway) does the actual sending.

Stack: Next.js (App Router, TypeScript), `postgres` (porsager) for the database, `jose` for the
session cookie, Google OAuth done by hand with `fetch`. No other auth library.

## Environment variables

Copy `.env.example` to `.env.local` for local work. On Vercel, set them under
Project Settings → Environment Variables.

| Name | Required | What it is |
|---|---|---|
| `DATABASE_URL` | yes | Postgres URL. On Supabase use the **transaction pooler** URL (port `6543`). |
| `GOOGLE_CLIENT_ID` | yes | OAuth client ID (see Google Cloud setup below). |
| `GOOGLE_CLIENT_SECRET` | yes | OAuth client secret. |
| `APP_URL` | yes | Public URL, no trailing slash, e.g. `https://outreach.vercel.app`. The redirect URI is `${APP_URL}/api/auth/callback`, and POSTs must come from this host. |
| `SESSION_SECRET` | yes | ≥ 32 characters. Signs the session cookie. `openssl rand -base64 48` |
| `TOKEN_ENCRYPTION_KEY` | yes | Base64 of exactly 32 random bytes. **Must be the same value the worker uses.** `openssl rand -base64 32` |
| `ALLOWED_EMAILS` | yes | Comma-separated, case-insensitive list of who may sign in (the sender + Will). |
| `SENDER_EMAIL` | yes | The account the worker sends from. Send is only allowed when this account has a token with status `ok`. |
| `DAILY_LIMIT` | no | Max emails per day (Los Angeles time) across all runs. Default `1000`. |
| `GOOGLE_HOSTED_DOMAIN` | no | e.g. `g.ucla.edu`. Passed to Google as the `hd` hint so the account picker prefers that domain. Not a security check — `ALLOWED_EMAILS` is. |
| `DEV_LOGIN` | no | `1` enables `GET /api/auth/dev-login?email=...` for local testing. Ignored when `NODE_ENV=production`. Never set it on Vercel. |

## Local development

Needs Node 20.9+ and a Postgres with the schema loaded.

```bash
cd web
npm install
cp .env.example .env.local      # then fill in the secrets

# Load the schema into your local database (once):
psql "$DATABASE_URL" -f ../supabase/migrations/0001_init.sql

npm run dev                      # http://localhost:3000
```

Without Google credentials you can still sign in locally: set `DEV_LOGIN=1` and open
`http://localhost:3000/api/auth/dev-login?email=<an address in ALLOWED_EMAILS>`.

Send stays disabled ("Sending paused: please sign in again") until `SENDER_EMAIL` has a
`google_tokens` row with status `ok`. To fake one locally:

```sql
insert into google_tokens (email, encrypted_refresh_token, status) values ('<SENDER_EMAIL>', 'fake', 'ok');
```

Scripts:

| Command | Does |
|---|---|
| `npm run dev` | Dev server |
| `npm run build` | Production build (also type-checks) |
| `npm run lint` | ESLint |
| `npm run typecheck` | `tsc --noEmit` (run after a build or dev run, which generate the route types) |
| `npm test` | Token-encryption round-trip tests (`node --test`, no extra packages) |

## How it works

### Sign-in (`/api/auth/*`)

- `GET /api/auth/login` sends the user to Google asking for `openid email profile`,
  `gmail.send` and `gmail.readonly`, with `access_type=offline` and `prompt=select_account`.
  `?consent=1&login_hint=<email>` switches to `prompt=consent`, which makes Google show the
  "Allow" screen and issue a fresh refresh token.
- `GET /api/auth/callback` checks the `state` cookie, swaps the code for tokens, reads the email
  from the `id_token`, and rejects anyone not in `ALLOWED_EMAILS`. If a Gmail box was left
  unticked, the page explains and the next sign-in forces the consent screen.
  - Refresh token returned → encrypted and upserted into `google_tokens` with status `ok`.
  - No refresh token and no `ok` row for that email → sent back through Google with
    `prompt=consent` (so the sender only sees "Allow" when it's actually needed).
  - Then the 30-day session cookie `mo_session` is set.
- `POST /api/auth/logout` clears the cookie (no button in the UI).
- `GET /api/auth/dev-login?email=` — local only, see above.

When the worker finds the token no longer works, it sets `google_tokens.status = 'needs_reauth'`.
The page then shows "Sending paused: please sign in again", whose link goes through the consent
screen and stores a new token.

### Runs (`/api/run`, signed-in only)

- `GET` → `{ run, sentToday, dailyLimit, remainingToday, senderReady, needsReauth }`.
  `run` is the latest row (plus an `isToday` flag the page uses to hide yesterday's result).
  `sentToday` counts `sends` with status `sent` or `bounced` on today's Los Angeles date.
- `POST {action: "start", count}` → `count` must be a whole number from 1 to 1,000 and no more
  than what's left today (400 otherwise); 409 "Please sign in again" if the sender has no working
  token; 409 "Already sending" if a run is already active (the `runs_one_active` index).
- `POST {action: "stop"}` → sets the running run to `stopping`. The worker finishes the current
  email and marks it `stopped`.
- POSTs must carry an `Origin` header whose host matches `APP_URL` (CSRF protection).

The page polls `GET /api/run` every 3 s while a run is active and every 15 s otherwise.

### Token encryption (shared with the worker)

AES-256-GCM. Key = base64-decode(`TOKEN_ENCRYPTION_KEY`) (must be 32 bytes). Stored value =
base64(`iv` (12 bytes) ‖ `ciphertext` ‖ `tag` (16 bytes)). In Python:

```python
raw = base64.b64decode(stored)
token = AESGCM(key).decrypt(raw[:12], raw[12:], None).decode()
```

See `lib/crypto.ts` and `lib/crypto.test.ts`.

## Deploying to Vercel

1. Import the Git repository in Vercel.
2. **Root Directory: `web`**. Framework preset: Next.js (defaults for build/output are fine).
3. Add every variable from the table above for the **Production** environment. Use the Supabase
   **transaction pooler** connection string (port 6543) for `DATABASE_URL`. Do not set `DEV_LOGIN`.
4. Set `APP_URL` to the production URL (e.g. `https://outreach-xyz.vercel.app`, or a custom domain)
   and add `${APP_URL}/api/auth/callback` to the Google OAuth client's redirect URIs.
5. Deploy.

Preview deployments have different URLs, so Google sign-in and POSTs only work on the URL in
`APP_URL`. Use the production URL.

## Google Cloud OAuth setup

1. Go to <https://console.cloud.google.com/> and create a project.
   - **Best:** create it while signed in with the UCLA account, inside the UCLA organization. Then
     the app can be **Internal**, which means no 7-day token expiry and no Google review.
   - If UCLA doesn't allow creating projects, create it with any Google account and use
     **External** (see step 3).
2. **APIs & Services → Library →** enable the **Gmail API**.
3. **Google Auth Platform → Branding / Audience** (the "OAuth consent screen"):
   - App name "Outreach", support email, developer contact email.
   - **Audience / User type:**
     - **Internal** if the project is in the UCLA organization. Only UCLA accounts can sign in.
     - Otherwise **External**, publishing status **Testing**, and add every address in
       `ALLOWED_EMAILS` under **Test users**.
       ⚠️ In Testing mode Google expires refresh tokens after **7 days**. The worker will then mark
       the token `needs_reauth`, and the sender must press "sign in again" on the page about once a
       week (until the app passes Google's verification for the restricted Gmail scope).
4. **Data access / Scopes:** add `openid`, `.../auth/userinfo.email`, `.../auth/userinfo.profile`,
   `https://www.googleapis.com/auth/gmail.send` and `https://www.googleapis.com/auth/gmail.readonly`.
5. **Clients → Create client → Web application:**
   - Authorized redirect URIs:
     - `https://<your-app>.vercel.app/api/auth/callback` (must equal `${APP_URL}/api/auth/callback`)
     - `http://localhost:3000/api/auth/callback` (for local testing with real Google)
   - Authorized JavaScript origins aren't needed.
   - Copy the client ID and secret into `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`.

The first time each person signs in, Google shows one screen asking to allow reading their email
address, sending email, and reading email. They must leave every box ticked.
