import { db } from "./db";
import { dailyLimit, senderEmail } from "./env";
import type { Run, RunState } from "./types";

/**
 * Everything the page needs, in one round trip.
 *
 * sentToday counts sends with status 'sent' or 'bounced' whose sent_at falls on today's date in
 * Los Angeles. The range below is equivalent to
 *   (sent_at at time zone 'America/Los_Angeles')::date = (now() at time zone 'America/Los_Angeles')::date
 * but written so the index on sends(sent_at) can be used.
 */
export async function getRunState(): Promise<RunState> {
  const sql = db();
  const sender = senderEmail();
  const [row] = await sql<
    {
      run: Run | null;
      sent_today: number;
      token_status: string | null;
      sender_online: boolean | null;
      people_sent: number;
      people_left: number;
      worker_info: { practice_mode?: boolean; practice_inbox?: string } | null;
    }[]
  >`
    with day as (
      select
        (date_trunc('day', now() at time zone 'America/Los_Angeles') at time zone 'America/Los_Angeles') as start_at,
        ((date_trunc('day', now() at time zone 'America/Los_Angeles') + interval '1 day') at time zone 'America/Los_Angeles') as end_at
    )
    select
      (
        select json_build_object(
          'id', r.id,
          'status', r.status,
          'requested_count', r.requested_count,
          'sent_count', r.sent_count,
          'message', r.message,
          'started_at', r.started_at,
          'ended_at', r.ended_at,
          'isToday', coalesce(r.ended_at, r.started_at) >= day.start_at
        )
        from runs r
        order by r.id desc
        limit 1
      ) as run,
      (
        select count(*)::int
        from sends s
        where s.status in ('sent', 'bounced')
          and s.sent_at >= day.start_at
          and s.sent_at < day.end_at
      ) as sent_today,
      (
        select t.status
        from google_tokens t
        where lower(t.email) = ${sender}
      ) as token_status,
      (
        -- The sending server writes a heartbeat every few seconds while it's alive.
        select now() - (a.value->>'at')::timestamptz < interval '2 minutes'
        from app_state a
        where a.key = 'worker_heartbeat'
      ) as sender_online,
      (
        select count(*)::int
        from contacts c
        where c.status in ('sent', 'followup1', 'followup2', 'replied', 'meeting', 'closed')
      ) as people_sent,
      (
        select count(*)::int
        from contacts c
        where c.selected and c.status in ('new', 'ready')
          and c.email not in (select email from suppression)
      ) as people_left,
      (
        select a.value
        from app_state a
        where a.key = 'worker_info'
      ) as worker_info
    from day
  `;

  const limit = dailyLimit();
  const sentToday = row?.sent_today ?? 0;
  const tokenStatus = row?.token_status ?? null;
  return {
    run: row?.run ?? null,
    sentToday,
    dailyLimit: limit,
    remainingToday: Math.max(0, limit - sentToday),
    senderReady: tokenStatus === "ok",
    needsReauth: tokenStatus === null || tokenStatus === "needs_reauth",
    senderOnline: row?.sender_online === true,
    peopleSent: row?.people_sent ?? 0,
    peopleLeft: row?.people_left ?? 0,
    practiceInbox: row?.worker_info?.practice_mode ? (row.worker_info.practice_inbox ?? null) : null,
  };
}
