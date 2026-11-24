import { randomBytes, timingSafeEqual } from "node:crypto";
import type { NextResponse } from "next/server";
import { isProduction } from "./env";

// Short-lived cookie holding the OAuth `state` (CSRF protection) plus whether this attempt
// already forced the consent screen (so the callback never loops back to Google forever).
export const STATE_COOKIE = "mo_oauth_state";

export function newState(): string {
  return randomBytes(32).toString("base64url");
}

export function setStateCookie(res: NextResponse, state: string, consent: boolean): void {
  res.cookies.set(STATE_COOKIE, `${state}.${consent ? 1 : 0}`, {
    httpOnly: true,
    sameSite: "lax", // Google's redirect back is a top-level GET, which lax allows
    secure: isProduction(),
    path: "/api/auth",
    maxAge: 10 * 60,
  });
}

export function clearStateCookie(res: NextResponse): void {
  res.cookies.set(STATE_COOKIE, "", {
    httpOnly: true,
    sameSite: "lax",
    secure: isProduction(),
    path: "/api/auth",
    maxAge: 0,
  });
}

/** Returns whether consent was forced, or null when the state is missing/doesn't match. */
export function checkState(cookieValue: string | undefined, returned: string | null): { consent: boolean } | null {
  if (!cookieValue || !returned) return null;
  const dot = cookieValue.lastIndexOf(".");
  if (dot < 0) return null;
  const expected = Buffer.from(cookieValue.slice(0, dot));
  const actual = Buffer.from(returned);
  if (expected.length !== actual.length || !timingSafeEqual(expected, actual)) return null;
  return { consent: cookieValue.slice(dot + 1) === "1" };
}
