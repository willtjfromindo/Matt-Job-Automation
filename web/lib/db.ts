import postgres from "postgres";
import { requireEnv } from "./env";

// One small connection per server instance. `prepare: false` keeps it compatible with the
// Supabase transaction pooler (port 6543), which does not support prepared statements.
// Cached on globalThis so dev hot-reloads don't open a new connection each time.
const globalForDb = globalThis as unknown as { __outreachSql?: postgres.Sql };

export function db(): postgres.Sql {
  if (!globalForDb.__outreachSql) {
    globalForDb.__outreachSql = postgres(requireEnv("DATABASE_URL"), {
      prepare: false,
      max: 1,
      idle_timeout: 20,
      connect_timeout: 10,
    });
  }
  return globalForDb.__outreachSql;
}

/** True when `err` is a Postgres unique violation, optionally on a specific constraint/index. */
export function isUniqueViolation(err: unknown, constraint?: string): boolean {
  if (!(err instanceof postgres.PostgresError) || err.code !== "23505") return false;
  return !constraint || err.constraint_name === constraint;
}
