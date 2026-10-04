import type { FastifyInstance } from "fastify";
import { protectRoutes } from "./auth.js";
import { withDb, type DbClientLike } from "./db.js";

export interface CalendarRouteOptions {
  createDbClient: () => DbClientLike;
  dashboardToken?: string;
}

export interface NewEventInput {
  title: string;
  starts_at: string;
  ends_at: string;
  all_day: boolean;
  location: string | null;
  notes: string | null;
}

const MAX_TITLE = 200;
const MAX_LOCATION = 200;
const MAX_NOTES = 2000;
// Must carry an explicit offset or Z: a bare local time would silently mean UTC here.
const ISO_WITH_ZONE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,3})?)?(Z|[+-]\d{2}:\d{2})$/;
const MAX_YEARS_AHEAD = 5;
const DISPLAY_TZ = process.env.CALENDAR_TZ ?? "Asia/Hong_Kong";

function optionalText(value: unknown, max: number, field: string): string | null {
  if (value === undefined || value === null || value === "") return null;
  if (typeof value !== "string") throw new Error(`${field} must be a string`);
  const text = value.trim();
  if (text.length > max) throw new Error(`${field} must be at most ${max} characters`);
  return text || null;
}

function parseTime(value: unknown, field: string): Date {
  if (typeof value !== "string" || !ISO_WITH_ZONE.test(value)) {
    throw new Error(`${field} must be an ISO 8601 time with a timezone, e.g. 2026-11-01T09:00:00+08:00`);
  }
  const time = new Date(value);
  if (Number.isNaN(time.getTime())) throw new Error(`${field} is not a real date`);
  return time;
}

// Throws an Error whose message is safe to return to the client.
export function validateNewEvent(body: unknown, now: Date = new Date()): NewEventInput {
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    throw new Error("body must be a JSON object");
  }
  const input = body as Record<string, unknown>;

  if (typeof input.title !== "string" || !input.title.trim()) throw new Error("title is required");
  const title = input.title.trim();
  if (title.length > MAX_TITLE) throw new Error(`title must be at most ${MAX_TITLE} characters`);

  const startsAt = parseTime(input.starts_at, "starts_at");
  const endsAt = parseTime(input.ends_at, "ends_at");
  if (endsAt < startsAt) throw new Error("ends_at must not be before starts_at");

  const dayMs = 24 * 60 * 60 * 1000;
  if (startsAt.getTime() < now.getTime() - dayMs) throw new Error("starts_at is in the past");
  if (startsAt.getTime() > now.getTime() + MAX_YEARS_AHEAD * 366 * dayMs) {
    throw new Error(`starts_at must be within ${MAX_YEARS_AHEAD} years`);
  }

  if (input.all_day !== undefined && typeof input.all_day !== "boolean") {
    throw new Error("all_day must be true or false");
  }

  return {
    title,
    starts_at: startsAt.toISOString(),
    ends_at: endsAt.toISOString(),
    all_day: input.all_day === true,
    location: optionalText(input.location, MAX_LOCATION, "location"),
    notes: optionalText(input.notes, MAX_NOTES, "notes"),
  };
}

function describe(event: NewEventInput): string {
  const format = (iso: string) =>
    new Date(iso).toLocaleString("zh-HK", {
      timeZone: DISPLAY_TZ,
      dateStyle: "medium",
      ...(event.all_day ? {} : { timeStyle: "short" }),
    });
  const lines = [
    `時間：${format(event.starts_at)} 至 ${format(event.ends_at)}${event.all_day ? "（全天）" : ""}`,
  ];
  if (event.location) lines.push(`地點：${event.location}`);
  if (event.notes) lines.push(`備註：${event.notes}`);
  return lines.join("\n");
}

// Calendar routes for the dashboard. Creating an event here only files a
// request; the agent writes to iCloud after the approval is granted.
export async function calendarRoutes(app: FastifyInstance, opts: CalendarRouteOptions): Promise<void> {
  const { createDbClient } = opts;

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

  app.post("/calendar/events", { bodyLimit: 16 * 1024 }, async (req, reply) => {
    let event: NewEventInput;
    try {
      event = validateNewEvent(req.body);
    } catch (err) {
      return reply.code(400).send({ status: "error", message: (err as Error).message });
    }

    const created = await withDb(createDbClient, async (db) => {
      // Both rows or neither: a request without its approval could never be decided.
      await db.query("BEGIN");
      try {
        const approval = await db.query(
          `INSERT INTO approvals (agent_id, title, detail)
           VALUES ((SELECT id FROM agents WHERE name = 'calendar'), $1, $2)
           RETURNING id`,
          [`新增行事曆事件：${event.title}`, describe(event)],
        );
        const approvalId = approval.rows[0].id;
        // requested_by stays NULL: this request came from me on the dashboard.
        const request = await db.query(
          `INSERT INTO calendar_event_requests
             (title, starts_at, ends_at, all_day, location, notes, approval_id)
           VALUES ($1, $2, $3, $4, $5, $6, $7)
           RETURNING id, status`,
          [event.title, event.starts_at, event.ends_at, event.all_day, event.location, event.notes, approvalId],
        );
        await db.query("COMMIT");
        return { request_id: request.rows[0].id, approval_id: approvalId, status: request.rows[0].status };
      } catch (err) {
        await db.query("ROLLBACK").catch(() => {});
        throw err;
      }
    });

    // 202: accepted, but nothing is on the calendar until the approval is granted.
    return reply.code(202).send(created);
  });
}
