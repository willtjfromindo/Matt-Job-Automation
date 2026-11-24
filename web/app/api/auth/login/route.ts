import { NextResponse, type NextRequest } from "next/server";
import { buildAuthUrl } from "@/lib/google";
import { baseUrl, redirectHome } from "@/lib/http";
import { newState, setStateCookie } from "@/lib/oauth-state";

// GET /api/auth/login                      -> normal Google sign-in (account picker)
// GET /api/auth/login?consent=1&login_hint=x -> forces the "Allow" screen so Google issues a new
//                                               refresh token
export async function GET(req: NextRequest) {
  const consent = req.nextUrl.searchParams.get("consent") === "1";
  const hint = req.nextUrl.searchParams.get("login_hint")?.trim() ?? "";
  const loginHint = /^[^\s@]{1,128}@[^\s@]{1,128}$/.test(hint) ? hint : undefined;

  let url: string;
  const state = newState();
  try {
    url = buildAuthUrl({ baseUrl: baseUrl(req), state, consent, loginHint });
  } catch (err) {
    console.error("[auth/login]", err);
    return redirectHome(req, { error: "server" });
  }

  const res = NextResponse.redirect(url, 302);
  res.headers.set("Cache-Control", "no-store");
  setStateCookie(res, state, consent);
  return res;
}
