import type { NextRequest } from "next/server";
import { jsonError, originAllowed, redirectHome } from "@/lib/http";
import { clearSessionCookie } from "@/lib/session";

// POST /api/auth/logout -> clears the session cookie and goes back to the sign-in page.
// (No button for this in the UI; kept for completeness.)
export async function POST(req: NextRequest) {
  if (!originAllowed(req)) return jsonError("Request not allowed", 403);
  const res = redirectHome(req);
  clearSessionCookie(res);
  return res;
}
