import type { NextRequest } from "next/server";
import { isAllowedEmail, isProduction } from "@/lib/env";
import { jsonError, redirectHome } from "@/lib/http";
import { createSessionToken, setSessionCookie } from "@/lib/session";

// Local testing only: GET /api/auth/dev-login?email=x signs in without Google.
// Works only when NODE_ENV !== 'production' AND DEV_LOGIN=1. Anywhere else it is a 404.
export async function GET(req: NextRequest) {
  if (isProduction() || process.env.DEV_LOGIN !== "1") {
    return jsonError("Not found", 404);
  }
  const email = (req.nextUrl.searchParams.get("email") ?? "").trim().toLowerCase();
  if (!email || !isAllowedEmail(email)) {
    return jsonError("That email is not in ALLOWED_EMAILS", 403);
  }
  const res = redirectHome(req);
  setSessionCookie(res, await createSessionToken(email));
  return res;
}
