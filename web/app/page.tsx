import { senderEmail } from "@/lib/env";
import { getRunState } from "@/lib/runs";
import { getSession } from "@/lib/session";
import type { RunState } from "@/lib/types";
import { GoogleG, LogoMark } from "./icons";
import styles from "./page.module.css";
import Sender from "./sender";

// Short codes in the URL (?error=...) mapped to plain-English messages.
const ERROR_MESSAGES: Record<string, string> = {
  not_allowed: "That Google account doesn't have access. Please sign in with your approved account.",
  permissions:
    "Outreach needs every permission on Google's screen to send and track your emails. Please sign in again and tick all the boxes.",
  cancelled: "Sign-in was cancelled.",
  state: "Your sign-in timed out. Please try again.",
  google: "Google sign-in didn't go through. Please try again.",
  unverified: "That Google account's email address isn't verified.",
  no_refresh: "Google didn't give lasting permission. Please try again.",
  server: "Something went wrong on our side. Please try again in a minute.",
};

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function Home(props: PageProps<"/">) {
  const session = await getSession();

  if (!session) {
    const query = await props.searchParams;
    const code = first(query.error);
    const message = code ? (ERROR_MESSAGES[code] ?? "Something went wrong. Please try again.") : null;
    const login = new URLSearchParams();
    if (first(query.consent) === "1") login.set("consent", "1");
    const hint = first(query.login_hint);
    if (hint && /^[^\s@]{1,128}@[^\s@]{1,128}$/.test(hint)) login.set("login_hint", hint);
    const qs = login.toString();
    const href = qs ? `/api/auth/login?${qs}` : "/api/auth/login";

    return (
      <main className={styles.main}>
        <section className={`${styles.card} ${styles.signIn}`} aria-labelledby="title">
          <LogoMark size={48} />
          <h1 id="title" className={styles.title}>
            Outreach
          </h1>
          <p className={styles.subtitle}>Sign in with your UCLA Google account to get started.</p>
          {message && (
            <p className={styles.alert} role="alert">
              {message}
            </p>
          )}
          <a className={styles.google} href={href}>
            <GoogleG />
            <span>Sign in with Google</span>
          </a>
        </section>
      </main>
    );
  }

  let initial: RunState | null = null;
  try {
    initial = await getRunState();
  } catch (err) {
    console.error("[page] loading run state", err);
  }
  let sender: string | null = null;
  try {
    sender = senderEmail();
  } catch {
    // Not configured; the sign-in-again link just won't pre-fill the account.
  }

  return (
    <main className={styles.main}>
      <div className={styles.stack}>
        <header className={styles.brand}>
          <LogoMark size={28} />
          <h1 className={styles.brandName}>Outreach</h1>
        </header>
        <Sender initial={initial} senderEmail={sender} />
      </div>
    </main>
  );
}
