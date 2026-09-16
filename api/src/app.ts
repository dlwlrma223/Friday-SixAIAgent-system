import fs from "node:fs";
import path from "node:path";
import Fastify, { type FastifyInstance } from "fastify";
import cors from "@fastify/cors";
import rateLimit from "@fastify/rate-limit";
import { Client } from "pg";

// Narrow interface (just what /db-check needs) so tests can inject a fake
// client instead of mocking the "pg" module or hitting a real database.
export interface DbClientLike {
  connect(): Promise<unknown>;
  query(sql: string): Promise<{ rows: Array<Record<string, unknown>> }>;
  end(): Promise<void>;
}

export interface DbConnectionConfig {
  host?: string;
  port: number;
  user?: string;
  password?: string;
  database?: string;
  connectionTimeoutMillis: number;
  ssl: { rejectUnauthorized: boolean; ca?: string };
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
    // Verify against the RDS CA when we have it; fall back to unverified TLS
    // (local/test envs without the cert file) so the connection still works.
    ssl: caCertPem ? { ca: caCertPem, rejectUnauthorized: true } : { rejectUnauthorized: false },
  };
}

const RDS_CA_BUNDLE_PATH = path.join(process.cwd(), "certs", "rds-global-bundle.pem");

function readRdsCaBundle(): string | undefined {
  try {
    return fs.readFileSync(RDS_CA_BUNDLE_PATH, "utf-8");
  } catch {
    return undefined;
  }
}

function defaultCreateDbClient(): DbClientLike {
  return new Client(buildDbConfigFromEnv(process.env, readRdsCaBundle()));
}

export interface BuildAppOptions {
  // Lets tests inject a fake DB client instead of a real pg.Client.
  createDbClient?: () => DbClientLike;
}

// Split out from index.ts so tests can use Fastify's inject() without
// binding a real port or triggering a real DB connection on import.
export function buildApp(options: BuildAppOptions = {}): FastifyInstance {
  const createDbClient = options.createDbClient ?? defaultCreateDbClient;
  const app = Fastify({ logger: true });

  // Allowlist instead of origin:true — once we add mutating endpoints
  // (approvals, calendar writes), reflecting any origin would be unsafe.
  const allowedOrigins = (
    process.env.CORS_ORIGIN ?? "http://localhost:5173,http://localhost:8080"
  )
    .split(",")
    .map((o) => o.trim())
    .filter(Boolean);

  app.register(cors, { origin: allowedOrigins });

  // /db-check is public and unauthenticated; without a limit it's an easy
  // way to exhaust RDS connections. Global limit for everything else.
  app.register(rateLimit, { max: 60, timeWindow: "1 minute" });

  app.get("/health", async () => {
    return { status: "ok" };
  });

  // Phase 1 smoke test: proves the deployed api can actually reach RDS,
  // not just that the container is running.
  app.get("/db-check", { config: { rateLimit: { max: 10, timeWindow: "1 minute" } } }, async (_req, reply) => {
    const client = createDbClient();

    let connected = false;
    try {
      await client.connect();
      connected = true;
      const result = await client.query("SELECT now() AS server_time");
      return { status: "ok", server_time: result.rows[0].server_time };
    } catch (err) {
      app.log.error(err);
      return reply.code(503).send({ status: "error", message: "database unreachable" });
    } finally {
      // Only end() a connection that actually connected, and never let an
      // end() failure mask the original error or crash the response.
      if (connected) {
        await client.end().catch((endErr) => app.log.error(endErr));
      }
    }
  });

  return app;
}
