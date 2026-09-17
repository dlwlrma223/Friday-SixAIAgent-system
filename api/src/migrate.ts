import fs from "node:fs";
import path from "node:path";
import { createDbClientFromEnv, type DbClientLike } from "./db.js";

// Any stable bigint works; it just has to be the same for every runner.
const MIGRATION_LOCK_ID = 7_412_019;

export interface MigrationFile {
  name: string;
  sql: string;
}

export function loadMigrationFiles(dir: string): MigrationFile[] {
  if (!fs.existsSync(dir)) return [];
  return fs
    .readdirSync(dir)
    .filter((f) => f.endsWith(".sql"))
    // Filenames are zero-padded (0001_...) so lexical order is apply order.
    .sort()
    .map((name) => ({ name, sql: fs.readFileSync(path.join(dir, name), "utf-8") }));
}

export interface MigrateResult {
  applied: string[];
  skipped: string[];
}

export async function runMigrations(
  client: DbClientLike,
  files: MigrationFile[],
  log: (msg: string) => void = () => {},
): Promise<MigrateResult> {
  await client.query(`
    CREATE TABLE IF NOT EXISTS schema_migrations (
      name TEXT PRIMARY KEY,
      applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
  `);

  // Two runners at once (e.g. two ECS tasks starting) must not both apply.
  await client.query("SELECT pg_advisory_lock($1)", [MIGRATION_LOCK_ID]);
  const applied: string[] = [];
  const skipped: string[] = [];
  try {
    const done = await client.query("SELECT name FROM schema_migrations");
    const doneNames = new Set(done.rows.map((r) => String(r.name)));

    for (const file of files) {
      if (doneNames.has(file.name)) {
        skipped.push(file.name);
        continue;
      }
      log(`applying ${file.name}`);
      await client.query("BEGIN");
      try {
        await client.query(file.sql);
        await client.query("INSERT INTO schema_migrations (name) VALUES ($1)", [file.name]);
        await client.query("COMMIT");
      } catch (err) {
        await client.query("ROLLBACK");
        throw new Error(`migration ${file.name} failed: ${(err as Error).message}`);
      }
      applied.push(file.name);
    }
  } finally {
    await client.query("SELECT pg_advisory_unlock($1)", [MIGRATION_LOCK_ID]);
  }
  return { applied, skipped };
}

// CLI entry: `npm run migrate:dev` locally, `node dist/migrate.js` in the
// production container (via ECS exec).
async function main(): Promise<void> {
  const dir = path.join(process.cwd(), "migrations");
  const files = loadMigrationFiles(dir);
  const client = createDbClientFromEnv();
  await client.connect();
  try {
    const result = await runMigrations(client, files, (m) => console.log(m));
    console.log(`applied: ${result.applied.length}, already applied: ${result.skipped.length}`);
  } finally {
    await client.end();
  }
}

const isDirectRun =
  process.argv[1] !== undefined && path.resolve(process.argv[1]) === path.resolve(new URL(import.meta.url).pathname);
if (isDirectRun) {
  main().catch((err) => {
    console.error(err.message ?? err);
    process.exit(1);
  });
}
