import { NextResponse, type NextRequest } from "next/server";
import { appUrl } from "./env";

export function json(data: unknown, status = 200): NextResponse {
  return NextResponse.json(data, { status, headers: { "Cache-Control": "no-store" } });
}

export function jsonError(message: string, status: number): NextResponse {
  return json({ error: message }, status);
}

/** Base URL for redirects and the OAuth redirect URI: APP_URL when set, else the request origin. */
export function baseUrl(req: NextRequest): string {
  return appUrl() ?? req.nextUrl.origin;
}

/**
 * CSRF guard for POSTs: when APP_URL is set, the Origin header must be present and its host must
 * match APP_URL's host.
 */
export function originAllowed(req: NextRequest): boolean {
  const configured = appUrl();
  if (!configured) return true;
  const origin = req.headers.get("origin");
  if (!origin) return false;
  try {
    return new URL(origin).host === new URL(configured).host;
  } catch {
    return false;
  }
}

/** Redirect to the home page with a short error code the page turns into a friendly message. */
export function redirectHome(req: NextRequest, params: Record<string, string> = {}): NextResponse {
  const url = new URL("/", baseUrl(req));
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  return NextResponse.redirect(url, 303);
}
