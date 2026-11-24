// Shapes shared by the API and the page (safe to import from client components).

/** Largest number of people one run may ask for (also enforced by the database). */
export const MAX_PER_RUN = 1000;

export type RunStatus = "running" | "stopping" | "stopped" | "done" | "auto_stopped" | "error";

export type Run = {
  id: number;
  status: RunStatus;
  requested_count: number;
  sent_count: number;
  message: string | null;
  started_at: string;
  ended_at: string | null;
  /** Extra: true when the run ended (or, if still going, started) today in Los Angeles time. */
  isToday: boolean;
};

export type RunState = {
  run: Run | null;
  sentToday: number;
  dailyLimit: number;
  remainingToday: number;
  senderReady: boolean;
  needsReauth: boolean;
  /** The Railway sender has checked in within the last 2 minutes. */
  senderOnline: boolean;
  /** People emailed so far (all time). */
  peopleSent: number;
  /** People picked to email who haven't been emailed yet. */
  peopleLeft: number;
  /** Set while the sender runs in practice mode: every email goes to this inbox instead. */
  practiceInbox: string | null;
};

export function isActive(run: Run | null | undefined): boolean {
  return run?.status === "running" || run?.status === "stopping";
}
