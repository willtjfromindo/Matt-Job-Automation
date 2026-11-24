import { requireEnv } from "./env";

export const GMAIL_SEND = "https://www.googleapis.com/auth/gmail.send";
export const GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly";
export const SCOPES = ["openid", "email", "profile", GMAIL_SEND, GMAIL_READONLY];

const AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth";
const TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token";

export function redirectUri(baseUrl: string): string {
  return `${baseUrl}/api/auth/callback`;
}

export function buildAuthUrl(opts: {
  baseUrl: string;
  state: string;
  consent: boolean;
  loginHint?: string;
}): string {
  const params = new URLSearchParams({
    client_id: requireEnv("GOOGLE_CLIENT_ID"),
    redirect_uri: redirectUri(opts.baseUrl),
    response_type: "code",
    scope: SCOPES.join(" "),
    access_type: "offline",
    include_granted_scopes: "true",
    // select_account: normal sign-in, no "Allow" screen if already granted.
    // consent: forces the "Allow" screen, which makes Google issue a new refresh token.
    prompt: opts.consent ? "consent" : "select_account",
    state: opts.state,
  });
  if (opts.loginHint) params.set("login_hint", opts.loginHint);
  const hd = process.env.GOOGLE_HOSTED_DOMAIN?.trim();
  if (hd) params.set("hd", hd); // a hint for the account picker only, not a security check
  return `${AUTH_ENDPOINT}?${params.toString()}`;
}

export type TokenResponse = {
  access_token: string;
  expires_in: number;
  id_token?: string;
  refresh_token?: string;
  scope?: string;
  token_type: string;
};

export async function exchangeCode(code: string, baseUrl: string): Promise<TokenResponse> {
  const res = await fetch(TOKEN_ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      code,
      client_id: requireEnv("GOOGLE_CLIENT_ID"),
      client_secret: requireEnv("GOOGLE_CLIENT_SECRET"),
      redirect_uri: redirectUri(baseUrl),
      grant_type: "authorization_code",
    }),
    cache: "no-store",
  });
  const body = (await res.json().catch(() => ({}))) as Partial<TokenResponse> & {
    error?: string;
    error_description?: string;
  };
  if (!res.ok || !body.access_token) {
    throw new Error(`Google token exchange failed: ${res.status} ${body.error ?? ""} ${body.error_description ?? ""}`.trim());
  }
  return body as TokenResponse;
}

export type IdTokenClaims = { email: string; emailVerified: boolean };

/**
 * Reads the email from the id_token.
 *
 * The signature is NOT verified here. That is acceptable because this token came straight from
 * Google's token endpoint over TLS in exchange for our client secret (it was never handed to the
 * browser), so it cannot have been tampered with. We still check the audience and issuer.
 */
export function readIdToken(idToken: string | undefined): IdTokenClaims {
  if (!idToken) throw new Error("Google did not return an id_token");
  const part = idToken.split(".")[1];
  if (!part) throw new Error("Malformed id_token");
  const payload = JSON.parse(Buffer.from(part, "base64url").toString("utf8")) as Record<string, unknown>;

  const aud = payload.aud;
  const clientId = requireEnv("GOOGLE_CLIENT_ID");
  if (aud !== clientId && !(Array.isArray(aud) && aud.includes(clientId))) {
    throw new Error("id_token audience mismatch");
  }
  if (payload.iss !== "https://accounts.google.com" && payload.iss !== "accounts.google.com") {
    throw new Error("id_token issuer mismatch");
  }
  const email = typeof payload.email === "string" ? payload.email.trim().toLowerCase() : "";
  if (!email) throw new Error("id_token has no email");
  const verified = payload.email_verified === true || payload.email_verified === "true";
  return { email, emailVerified: verified };
}

export function hasRequiredScopes(scope: string | undefined): boolean {
  const granted = new Set((scope ?? "").split(/\s+/).filter(Boolean));
  return granted.has(GMAIL_SEND) && granted.has(GMAIL_READONLY);
}
