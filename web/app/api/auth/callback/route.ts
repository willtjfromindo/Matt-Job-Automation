import { NextResponse, type NextRequest } from "next/server";
import { encrypt } from "@/lib/crypto";
import { db } from "@/lib/db";
import { isAllowedEmail } from "@/lib/env";
import { exchangeCode, hasRequiredScopes, readIdToken } from "@/lib/google";
import { baseUrl, redirectHome } from "@/lib/http";
import { STATE_COOKIE, checkState, clearStateCookie } from "@/lib/oauth-state";
import { createSessionToken, setSessionCookie } from "@/lib/session";

export async function GET(req: NextRequest) {
  const res = await handle(req);
  clearStateCookie(res);
  res.headers.set("Cache-Control", "no-store");
  return res;
}

async function handle(req: NextRequest): Promise<NextResponse> {
  const params = req.nextUrl.searchParams;

  // The person pressed "Cancel" on Google's screen, or Google refused.
  const googleError = params.get("error");
  if (googleError) {
    return redirectHome(req, { error: googleError === "access_denied" ? "cancelled" : "google" });
  }

  const state = checkState(req.cookies.get(STATE_COOKIE)?.value, params.get("state"));
  if (!state) return redirectHome(req, { error: "state" });

  const code = params.get("code");
  if (!code) return redirectHome(req, { error: "google" });

  const base = baseUrl(req);
  let tokens;
  let email: string;
  try {
    tokens = await exchangeCode(code, base);
    const claims = readIdToken(tokens.id_token);
    if (!claims.emailVerified) return redirectHome(req, { error: "unverified" });
    email = claims.email;
  } catch (err) {
    console.error("[auth/callback] token exchange", err);
    return redirectHome(req, { error: "google" });
  }

  if (!isAllowedEmail(email)) {
    return redirectHome(req, { error: "not_allowed" });
  }

  // Both Gmail permissions are needed. If a box was left unticked, explain and ask again with
  // the consent screen forced.
  if (!hasRequiredScopes(tokens.scope)) {
    return redirectHome(req, { error: "permissions", consent: "1", login_hint: email });
  }

  try {
    const sql = db();
    if (tokens.refresh_token) {
      const encrypted = encrypt(tokens.refresh_token);
      await sql`
        insert into google_tokens (email, encrypted_refresh_token, scopes, status, updated_at)
        values (${email}, ${encrypted}, ${tokens.scope ?? null}, 'ok', now())
        on conflict (email) do update set
          encrypted_refresh_token = excluded.encrypted_refresh_token,
          scopes = excluded.scopes,
          status = 'ok',
          updated_at = now()
      `;
    } else {
      // Google only sends a refresh token on the first "Allow" (or when consent is forced).
      // If we don't already hold a working one, go back and force the consent screen.
      const existing = await sql`
        select 1 from google_tokens where lower(email) = ${email} and status = 'ok' limit 1
      `;
      if (existing.length === 0) {
        if (state.consent) {
          // Consent was already forced and Google still sent nothing; don't loop.
          return redirectHome(req, { error: "no_refresh", consent: "1", login_hint: email });
        }
        const again = new URL("/api/auth/login", base);
        again.searchParams.set("consent", "1");
        again.searchParams.set("login_hint", email);
        return NextResponse.redirect(again, 302);
      }
    }
  } catch (err) {
    console.error("[auth/callback] saving token", err);
    return redirectHome(req, { error: "server" });
  }

  let session: string;
  try {
    session = await createSessionToken(email);
  } catch (err) {
    console.error("[auth/callback] session", err);
    return redirectHome(req, { error: "server" });
  }
  const res = redirectHome(req);
  setSessionCookie(res, session);
  return res;
}
