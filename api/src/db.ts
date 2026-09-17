import fs from "node:fs";
import path from "node:path";
import { Client } from "pg";

// Narrow interface (just what callers need) so tests can inject a fake
// client instead of mocking the "pg" module or hitting a real database.
export interface DbClientLike {
  connect(): Promise<unknown>;
  query(sql: string, values?: unknown[]): Promise<{ rows: Array<Record<string, unknown>> }>;
  end(): Promise<void>;
}

export interface DbConnectionConfig {
  host?: string;
  port: number;
  user?: string;
  password?: string;
  database?: string;
  connectionTimeoutMillis: number;
  ssl: { rejectUnauthorized: boolean; ca?: string } | false;
}

// Pure function (no fs access) so it's trivially testable with plain objects.
// caCertPem is passed in by the caller rather than read here.
export function buildDbConfigFromEnv(
  env: NodeJS.ProcessEnv = process.env,
  caCertPem?: string,
): DbConnectionConfig {
  return {
    host: env.DB_HOST,
    port: Number(env.DB_PORT ?? 5432),
    user: env.DB_USER,
    password: env.DB_PASSWORD,
    database: env.DB_NAME,
    connectionTimeoutMillis: 5000,
    ssl: resolveSsl(env, caCertPem),
  };
}

// Verify against the RDS CA when we have it; fall back to unverified TLS
// when we don't. DB_SSL=disable is for the local compose Postgres, which
// has no TLS at all.
function resolveSsl(env: NodeJS.ProcessEnv, caCertPem?: string): DbConnectionConfig["ssl"] {
  if (env.DB_SSL === "disable") return false;
  return caCertPem ? { ca: caCertPem, rejectUnauthorized: true } : { rejectUnauthorized: false };
}

const RDS_CA_BUNDLE_PATH = path.join(process.cwd(), "certs", "rds-global-bundle.pem");

export function readRdsCaBundle(): string | undefined {
  try {
    return fs.readFileSync(RDS_CA_BUNDLE_PATH, "utf-8");
  } catch {
    return undefined;
  }
}

export function createDbClientFromEnv(): DbClientLike {
  return new Client(buildDbConfigFromEnv(process.env, readRdsCaBundle()));
}
