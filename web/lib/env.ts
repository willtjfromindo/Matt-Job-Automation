// Small helpers for reading configuration. Read lazily so `next build` works without secrets.

export class ConfigError extends Error {}

export function requireEnv(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new ConfigError(`Missing environment variable ${name}`);
  return value;
}

export function isProduction(): boolean {
  return process.env.NODE_ENV === "production";
}

/** Public base URL without a trailing slash, e.g. https://outreach.vercel.app (null when unset). */
export function appUrl(): string | null {
  const value = process.env.APP_URL?.trim();
  return value ? value.replace(/\/+$/, "") : null;
}

export function allowedEmails(): Set<string> {
  return new Set(
    (process.env.ALLOWED_EMAILS ?? "")
      .split(",")
      .map((e) => e.trim().toLowerCase())
      .filter(Boolean),
  );
}

export function isAllowedEmail(email: string): boolean {
  return allowedEmails().has(email.trim().toLowerCase());
}

export function senderEmail(): string {
  return requireEnv("SENDER_EMAIL").toLowerCase();
}

export function dailyLimit(): number {
  const n = Number(process.env.DAILY_LIMIT ?? "");
  return Number.isInteger(n) && n > 0 ? n : 1000;
}
