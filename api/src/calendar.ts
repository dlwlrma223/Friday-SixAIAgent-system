import type { FastifyInstance } from "fastify";
import { protectRoutes } from "./auth.js";
import { withDb, type DbClientLike } from "./db.js";
import { CALENDAR_CHANNEL, type Publish } from "./pubsub.js";

export interface CalendarRouteOptions {
  createDbClient: () => DbClientLike;
  publish: Publish;
  dashboardToken?: string;
}

const MAX_INTENT_CHARS = 500;

// Throws an Error whose message is safe to return to the client.
export function validateIntent(body: unknown): string {
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    throw new Error("body must be a JSON object");
  }
  const text = (body as Record<string, unknown>).text;
  if (typeof text !== "string" || !text.trim()) throw new Error("text is required");
  // Control characters have no place in a sentence and only confuse the model.
  const cleaned = text.replace(/[\u0000-\u001f\u007f]+/g, " ").trim();
  if (cleaned.length > MAX_INTENT_CHARS) {
    throw new Error(`text must be at most ${MAX_INTENT_CHARS} characters`);
  }
  return cleaned;
}

// Calendar routes for the dashboard. The api never writes to iCloud and never
// calls the LLM: it records what I asked for and lets the agent do the rest.
export async function calendarRoutes(app: FastifyInstance, opts: CalendarRouteOptions): Promise<void> {
  const { createDbClient, publish } = opts;

  protectRoutes(app, opts.dashboardToken);

  app.get("/calendar/events", async () => {
    const rows = await withDb(createDbClient, async (db) => {
      const result = await db.query(
        `SELECT id, calendar_name, title, starts_at, ends_at, all_day, location, synced_at
           FROM calendar_events
          WHERE COALESCE(ends_at, starts_at) >= now()
          ORDER BY starts_at
          LIMIT 200`,
      );
      return result.rows;
    });
    return { events: rows };
  });

  // What is in flight or just finished, so the dashboard can show what became of
  // each sentence. Older rows stay in the table but drop off the screen.
  app.get("/calendar/intents", async () => {
    const rows = await withDb(createDbClient, async (db) => {
      const result = await db.query(
        `SELECT id, text, status, request_id, error, created_at, completed_at
           FROM calendar_intents
          WHERE status = 'pending' OR completed_at > now() - interval '10 minutes'
          ORDER BY id DESC
          LIMIT 5`,
      );
      return result.rows;
    });
    return { intents: rows };
  });

  // Each intent costs one LLM call on the agent side, hence the tighter limit.
  app.post(
    "/calendar/intents",
    { bodyLimit: 4 * 1024, config: { rateLimit: { max: 10, timeWindow: "1 minute" } } },
    async (req, reply) => {
      let text: string;
      try {
        text = validateIntent(req.body);
      } catch (err) {
        return reply.code(400).send({ status: "error", message: (err as Error).message });
      }

      const intent = await withDb(createDbClient, async (db) => {
        const result = await db.query(
          "INSERT INTO calendar_intents (text) VALUES ($1) RETURNING id, status",
          [text],
        );
        return result.rows[0];
      });

      // The row is saved; the agent's periodic sweep picks it up even if Redis is down.
      let notified = true;
      try {
        await publish(CALENDAR_CHANNEL, JSON.stringify({ intent_id: intent.id }));
      } catch (err) {
        notified = false;
        app.log.error(err);
      }
      // 202: accepted, nothing is drafted yet and nothing is on the calendar.
      return reply.code(202).send({ intent_id: intent.id, status: intent.status, notified });
    },
  );
}
