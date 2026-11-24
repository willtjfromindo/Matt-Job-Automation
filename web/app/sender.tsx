"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { MAX_PER_RUN, isActive, type RunState } from "@/lib/types";
import { MinusIcon, PlusIcon } from "./icons";
import styles from "./page.module.css";

const DEFAULT_COUNT = 200;
const STEP = 10;
const POLL_ACTIVE_MS = 3_000;
const POLL_IDLE_MS = 15_000;
const nf = new Intl.NumberFormat("en-US");

type Tone = "muted" | "active" | "error";

/** Whole numbers only; anything else (empty, decimals, negatives) is null. */
function parseCount(text: string): number | null {
  const t = text.trim();
  return /^\d{1,6}$/.test(t) ? Number(t) : null;
}

function maxAllowed(state: RunState | null): number {
  return Math.max(0, Math.min(MAX_PER_RUN, state?.remainingToday ?? MAX_PER_RUN));
}

function startingCount(state: RunState | null): number {
  const max = maxAllowed(state);
  return max >= 1 ? Math.min(DEFAULT_COUNT, max) : DEFAULT_COUNT;
}

class ApiError extends Error {}

async function postRun(body: object): Promise<RunState> {
  const res = await fetch("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (res.status === 401) {
    window.location.reload();
    throw new ApiError("Please sign in again.");
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(data?.error ?? "Something went wrong. Please try again.");
  return data as RunState;
}

export default function Sender({ initial, senderEmail }: { initial: RunState | null; senderEmail: string | null }) {
  const [state, setState] = useState<RunState | null>(initial);
  const [countText, setCountText] = useState(() => String(startingCount(initial)));
  const [pending, setPending] = useState<"start" | "stop" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [offline, setOffline] = useState(false);
  const [pollTick, setPollTick] = useState(0);
  // Bumped around every button press so a poll that started earlier can't overwrite fresher data.
  const seq = useRef(0);

  const run = state?.run ?? null;
  const loaded = state !== null;
  const active = isActive(run);
  const limitReached = !!state && state.remainingToday <= 0;
  const locked = active || limitReached; // number field can't be changed
  const max = maxAllowed(state);
  const count = parseCount(countText);
  const countValid = count !== null && count >= 1 && count <= max;

  const applyState = useCallback((next: RunState) => {
    setState(next);
    setOffline(false);
    if (!isActive(next.run)) {
      // Keep the number within what's still allowed today.
      const nextMax = maxAllowed(next);
      setCountText((text) => {
        const c = parseCount(text);
        return c !== null && nextMax >= 1 && c > nextMax ? String(nextMax) : text;
      });
    }
  }, []);

  const refresh = useCallback(async () => {
    const mine = seq.current;
    try {
      const res = await fetch("/api/run", { cache: "no-store" });
      if (res.status === 401) {
        window.location.reload();
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as RunState;
      if (mine === seq.current) applyState(data);
    } catch {
      if (mine === seq.current) setOffline(true);
    }
  }, [applyState]);

  // Poll every 3 s while sending, every 15 s otherwise (skipped while the tab is hidden).
  useEffect(() => {
    const timer = window.setTimeout(
      async () => {
        if (document.visibilityState === "visible") await refresh();
        setPollTick((n) => n + 1);
      },
      // If the first load failed, try again quickly.
      active || !loaded ? POLL_ACTIVE_MS : POLL_IDLE_MS,
    );
    return () => window.clearTimeout(timer);
  }, [active, loaded, pollTick, refresh]);

  // Catch up as soon as the tab is shown again.
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [refresh]);

  // Error messages fade after a few seconds.
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 6_000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const canSend = !!state && state.senderReady && !active && pending === null && countValid;
  const canStop = run?.status === "running" && pending === null;

  async function act(kind: "start" | "stop", optimistic: RunState, body: object) {
    const before = state;
    seq.current += 1;
    setNotice(null);
    setPending(kind);
    setState(optimistic);
    let failed = false;
    try {
      applyState(await postRun(body));
    } catch (err) {
      failed = true;
      setState(before);
      setNotice(err instanceof ApiError ? err.message : "Couldn't reach the server. Please try again.");
    } finally {
      seq.current += 1;
      setPending(null);
    }
    if (failed) void refresh();
  }

  function onSend(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!canSend || !state || count === null) return;
    void act(
      "start",
      {
        ...state,
        run: {
          id: -1,
          status: "running",
          requested_count: count,
          sent_count: 0,
          message: null,
          started_at: new Date().toISOString(),
          ended_at: null,
          isToday: true,
        },
      },
      { action: "start", count },
    );
  }

  function onStop() {
    if (!canStop || !state || !run) return;
    void act("stop", { ...state, run: { ...run, status: "stopping" } }, { action: "stop" });
  }

  function step(direction: 1 | -1) {
    const c = count ?? startingCount(state);
    const next = direction === 1 ? c - (c % STEP) + STEP : c % STEP === 0 ? c - STEP : c - (c % STEP);
    setCountText(String(Math.min(Math.max(next, 1), Math.max(max, 1))));
  }

  function normalize() {
    const n = Number(countText);
    if (countText.trim() === "" || !Number.isFinite(n) || n < 1) {
      setCountText(String(startingCount(state)));
    } else if (max >= 1 && n > max) {
      setCountText(String(max));
    } else if (!Number.isInteger(n)) {
      setCountText(String(Math.max(1, Math.round(n))));
    }
  }

  // ---- The one line of status text -------------------------------------------------------
  let line: ReactNode;
  let tone: Tone = "muted";
  const reauthHref = `/api/auth/login?consent=1${senderEmail ? `&login_hint=${encodeURIComponent(senderEmail)}` : ""}`;

  if (notice) {
    line = notice;
    tone = "error";
  } else if (!state) {
    line = offline ? "Can't reach the server. Trying again…" : "Loading…";
  } else if (!state.senderReady) {
    line = (
      <>
        Sending paused: please <a href={reauthHref}>sign in again</a>
      </>
    );
    tone = "error";
  } else if (run && active && !state.senderOnline) {
    line = `Waiting for the sending server to come back… ${nf.format(run.sent_count)} of ${nf.format(run.requested_count)} sent`;
    tone = "error";
  } else if (run && active) {
    const sent = nf.format(run.sent_count);
    const total = nf.format(run.requested_count);
    line = run.status === "stopping" ? `Stopping… ${sent} of ${total} sent` : `Sent ${sent} of ${total}`;
    tone = "active";
  } else if (limitReached) {
    line = `Daily limit reached — ${nf.format(state.sentToday)} sent today`;
  } else if (!countValid) {
    line = `Choose a number from 1 to ${nf.format(max)}`;
    tone = "error";
  } else if (run && run.isToday && run.status !== "running" && run.status !== "stopping") {
    const sent = nf.format(run.sent_count);
    const extra = run.message ? ` — ${run.message}` : "";
    if (run.status === "done") line = `Done — ${sent} sent`;
    else if (run.status === "stopped") line = run.sent_count > 0 ? `Stopped after ${sent}` : "Stopped";
    else if (run.status === "auto_stopped") line = `Paused automatically after ${sent}${extra}`;
    else line = `Stopped by a problem after ${sent}${extra}`;
    if (run.status === "auto_stopped" || run.status === "error") tone = "error";
  } else {
    line = state.sentToday > 0 ? `Ready — ${nf.format(state.remainingToday)} left today` : "Ready";
  }
  if (offline && state && !notice) {
    line = "Can't reach the server. Trying again…";
    tone = "error";
  }

  const progress = run && active && run.requested_count > 0 ? Math.min(1, run.sent_count / run.requested_count) : 0;
  const indeterminate = active && (run?.sent_count ?? 0) === 0;

  return (
    <section className={styles.card} aria-label="Send emails">
      <form onSubmit={onSend} noValidate>
        <label htmlFor="count" className={styles.label}>
          Number of people
        </label>
        <div className={styles.stepper}>
          <button
            type="button"
            className={styles.stepButton}
            onClick={() => step(-1)}
            disabled={locked || (count !== null && count <= 1)}
            aria-label={`${STEP} fewer`}
          >
            <MinusIcon />
          </button>
          <input
            id="count"
            name="count"
            className={styles.count}
            type="number"
            inputMode="numeric"
            min={1}
            max={Math.max(1, max)}
            step={1}
            value={countText}
            onChange={(e) => setCountText(e.target.value)}
            onBlur={normalize}
            disabled={locked}
            aria-invalid={!countValid && !locked}
            aria-describedby="status-line"
            autoComplete="off"
          />
          <button
            type="button"
            className={styles.stepButton}
            onClick={() => step(1)}
            disabled={locked || (count !== null && count >= max)}
            aria-label={`${STEP} more`}
          >
            <PlusIcon />
          </button>
        </div>

        <div className={styles.actions}>
          <button type="submit" className={styles.primary} disabled={!canSend}>
            {pending === "start" ? "Starting…" : "Send"}
          </button>
          <button type="button" className={styles.secondary} onClick={onStop} disabled={!canStop}>
            {run?.status === "stopping" ? "Stopping…" : "Stop"}
          </button>
        </div>
      </form>

      <div className={styles.statusArea}>
        <p id="status-line" className={styles.status} data-tone={tone} role="status">
          {line}
        </p>
        <div
          className={styles.progress}
          data-visible={active}
          data-indeterminate={indeterminate}
          role="progressbar"
          aria-label="Sending progress"
          aria-hidden={!active}
          aria-valuemin={0}
          aria-valuemax={run?.requested_count ?? 0}
          aria-valuenow={active ? (run?.sent_count ?? 0) : 0}
        >
          <div
            className={styles.progressFill}
            style={indeterminate ? undefined : { transform: `scaleX(${progress})` }}
          />
        </div>
      </div>

      {state && (
        <footer className={styles.facts}>
          <dl className={styles.counts}>
            <div>
              <dt>Emailed</dt>
              <dd>{nf.format(state.peopleSent)}</dd>
            </div>
            <div>
              <dt>Left to email</dt>
              <dd>{nf.format(state.peopleLeft)}</dd>
            </div>
          </dl>
          {senderEmail && (
            <p className={styles.from}>
              Sending from <strong>{senderEmail}</strong>
            </p>
          )}
          {state.practiceInbox && (
            <p className={styles.practice}>
              Practice mode: every email goes to <strong>{state.practiceInbox}</strong>
            </p>
          )}
        </footer>
      )}
    </section>
  );
}
