import type { NextRequest } from "next/server";
import { db, isUniqueViolation } from "@/lib/db";
import { json, jsonError, originAllowed } from "@/lib/http";
import { getRunState } from "@/lib/runs";
import { getSession } from "@/lib/session";
import { MAX_PER_RUN } from "@/lib/types";

const fmt = (n: number) => n.toLocaleString("en-US");

// GET /api/run -> { run, sentToday, dailyLimit, remainingToday, senderReady, needsReauth }
export async function GET() {
  const session = await getSession();
  if (!session) return jsonError("Please sign in", 401);
  try {
    return json(await getRunState());
  } catch (err) {
    console.error("[api/run GET]", err);
    return jsonError("Couldn't load the status. Please try again.", 500);
  }
}

// POST /api/run { action: 'start', count } | { action: 'stop' }
export async function POST(req: NextRequest) {
  if (!originAllowed(req)) return jsonError("Request not allowed", 403);
  const session = await getSession();
  if (!session) return jsonError("Please sign in", 401);

  let body: { action?: unknown; count?: unknown };
  try {
    body = await req.json();
  } catch {
    return jsonError("Invalid request", 400);
  }

  try {
    if (body.action === "start") return await start(body.count, session.email);
    if (body.action === "stop") return await stop();
    return jsonError("Unknown action", 400);
  } catch (err) {
    console.error("[api/run POST]", err);
    return jsonError("Something went wrong. Please try again.", 500);
  }
}

async function start(count: unknown, email: string) {
  if (typeof count !== "number" || !Number.isInteger(count) || count < 1 || count > MAX_PER_RUN) {
    return jsonError(`Please choose a whole number from 1 to ${fmt(MAX_PER_RUN)}.`, 400);
  }

  const state = await getRunState();
  if (state.remainingToday <= 0) {
    return jsonError(`Daily limit reached — ${fmt(state.sentToday)} sent today.`, 400);
  }
  if (count > state.remainingToday) {
    return jsonError(`You can send to ${fmt(state.remainingToday)} more people today.`, 400);
  }
  if (!state.senderReady) return jsonError("Please sign in again", 409);

  try {
    await db()`
      insert into runs (requested_count, started_by, status)
      values (${count}, ${email}, 'running')
    `;
  } catch (err) {
    if (isUniqueViolation(err, "runs_one_active")) return jsonError("Already sending", 409);
    throw err;
  }
  return json(await getRunState(), 201);
}

async function stop() {
  // The worker sees 'stopping', finishes the email it's on, then marks the run 'stopped'.
  await db()`update runs set status = 'stopping' where status = 'running'`;
  return json(await getRunState());
}
