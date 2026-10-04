import type { FastifyInstance } from "fastify";
import { protectRoutes } from "./auth.js";
import { withDb, type DbClientLike } from "./db.js";
import { APPROVALS_CHANNEL, type Publish } from "./pubsub.js";

export interface DashboardRouteOptions {
  createDbClient: () => DbClientLike;
  publish: Publish;
  dashboardToken?: string;
}

const APPROVAL_STATUSES = ["pending", "approved", "skipped"] as const;
type ApprovalStatus = (typeof APPROVAL_STATUSES)[number];

const DEFAULT_LIMIT = 20;
const MAX_LIMIT = 100;

function parseId(raw: string): number | undefined {
  return /^[1-9]\d{0,8}$/.test(raw) ? Number(raw) : undefined;
}

function parseLimit(raw: string | undefined): number | undefined {
  if (raw === undefined) return DEFAULT_LIMIT;
  const limit = parseId(raw);
  return limit !== undefined && limit <= MAX_LIMIT ? limit : undefined;
}

// Read + approve/skip routes the dashboard uses. Everything here needs the token.
export async function dashboardRoutes(app: FastifyInstance, opts: DashboardRouteOptions): Promise<void> {
  const { createDbClient, publish } = opts;

  protectRoutes(app, opts.dashboardToken);

  app.get<{ Querystring: { status?: string } }>("/approvals", async (req, reply) => {
    const status = req.query.status ?? "pending";
    if (!APPROVAL_STATUSES.includes(status as ApprovalStatus)) {
      return reply.code(400).send({ status: "error", message: "status must be pending, approved or skipped" });
    }
    const rows = await withDb(createDbClient, async (db) => {
      const result = await db.query(
        `SELECT a.id, g.name AS agent, a.title, a.detail, a.status, a.created_at, a.resolved_at
           FROM approvals a LEFT JOIN agents g ON g.id = a.agent_id
          WHERE a.status = $1
          ORDER BY a.created_at DESC
          LIMIT 50`,
        [status],
      );
      return result.rows;
    });
    return { approvals: rows };
  });

  app.get<{ Querystring: { limit?: string } }>("/research/queries", async (req, reply) => {
    const limit = parseLimit(req.query.limit);
    if (limit === undefined) {
      return reply.code(400).send({ status: "error", message: `limit must be 1-${MAX_LIMIT}` });
    }
    const rows = await withDb(createDbClient, async (db) => {
      const result = await db.query(
        `SELECT q.id, g.name AS agent, q.query, q.purpose, q.pii_flags, q.status, q.approval_id,
                q.result_count, q.answer_preview, q.error, q.created_at, q.completed_at
           FROM research_queries q LEFT JOIN agents g ON g.id = q.agent_id
          ORDER BY q.created_at DESC
          LIMIT $1`,
        [limit],
      );
      return result.rows;
    });
    return { queries: rows };
  });

  const resolve = (decision: "approved" | "skipped") =>
    async function handler(
      req: { params: { id: string } },
      reply: { code(statusCode: number): { send(payload: unknown): unknown } },
    ) {
      const id = parseId(req.params.id);
      if (id === undefined) {
        return reply.code(400).send({ status: "error", message: "invalid approval id" });
      }

      const outcome = await withDb(createDbClient, async (db) => {
        // Only a pending row can change, so a double click can't resolve it twice.
        const updated = await db.query(
          `UPDATE approvals SET status = $1, resolved_at = now()
            WHERE id = $2 AND status = 'pending'
            RETURNING id, status, resolved_at`,
          [decision, id],
        );
        if (updated.rows[0]) return { approval: updated.rows[0] };
        const existing = await db.query("SELECT status FROM approvals WHERE id = $1", [id]);
        return { existingStatus: existing.rows[0]?.status as string | undefined };
      });

      if (!outcome.approval) {
        return outcome.existingStatus === undefined
          ? reply.code(404).send({ status: "error", message: "approval not found" })
          : reply.code(409).send({ status: "error", message: `approval already ${outcome.existingStatus}` });
      }

      // The decision is already saved; a Redis hiccup must not undo or hide it.
      let notified = true;
      try {
        await publish(APPROVALS_CHANNEL, JSON.stringify({ approval_id: id, status: decision }));
      } catch (err) {
        notified = false;
        app.log.error(err);
      }
      return { approval: outcome.approval, notified };
    };

  app.post<{ Params: { id: string } }>("/approvals/:id/approve", resolve("approved"));
  app.post<{ Params: { id: string } }>("/approvals/:id/skip", resolve("skipped"));
}
