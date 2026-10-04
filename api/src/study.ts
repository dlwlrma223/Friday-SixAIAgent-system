import type { FastifyInstance } from "fastify";
import { protectRoutes } from "./auth.js";
import { validateIntent } from "./calendar.js";
import { withDb, type DbClientLike } from "./db.js";
import { STUDY_CHANNEL, type Publish } from "./pubsub.js";

export interface StudyRouteOptions {
  createDbClient: () => DbClientLike;
  publish: Publish;
  dashboardToken?: string;
}

function parseId(raw: string): number | undefined {
  return /^[1-9]\d{0,8}$/.test(raw) ? Number(raw) : undefined;
}

// Study routes for the dashboard. The api only records the goal; the agent does
// the research and the planning, and holds the keys for both.
export async function studyRoutes(app: FastifyInstance, opts: StudyRouteOptions): Promise<void> {
  const { createDbClient, publish } = opts;

  protectRoutes(app, opts.dashboardToken);

  app.get("/study/goals", async () => {
    const rows = await withDb(createDbClient, async (db) => {
      const result = await db.query(
        `SELECT g.id, g.request_text, g.title, g.status, g.error, g.total_weeks,
                g.created_at, g.completed_at,
                (SELECT count(*)::int FROM study_modules m WHERE m.goal_id = g.id) AS modules
           FROM study_goals g
          ORDER BY g.id DESC
          LIMIT 10`,
      );
      return result.rows;
    });
    return { goals: rows };
  });

  app.get<{ Params: { id: string } }>("/study/goals/:id", async (req, reply) => {
    const id = parseId(req.params.id);
    if (id === undefined) {
      return reply.code(400).send({ status: "error", message: "invalid goal id" });
    }
    const found = await withDb(createDbClient, async (db) => {
      const goal = await db.query(
        `SELECT id, request_text, title, status, error, overview, facts, total_weeks, sources,
                created_at, completed_at
           FROM study_goals WHERE id = $1`,
        [id],
      );
      if (!goal.rows[0]) return undefined;
      const modules = await db.query(
        `SELECT id, position, title, summary, topics, est_hours, week, source_ids,
                materials_status, materials_error
           FROM study_modules WHERE goal_id = $1 ORDER BY position`,
        [id],
      );
      return { goal: goal.rows[0], modules: modules.rows };
    });
    if (!found) return reply.code(404).send({ status: "error", message: "goal not found" });
    return found;
  });

  // Each goal costs several searches and model calls on the agent side.
  app.post(
    "/study/goals",
    { bodyLimit: 4 * 1024, config: { rateLimit: { max: 5, timeWindow: "1 minute" } } },
    async (req, reply) => {
      let text: string;
      try {
        text = validateIntent(req.body);
      } catch (err) {
        return reply.code(400).send({ status: "error", message: (err as Error).message });
      }

      const goal = await withDb(createDbClient, async (db) => {
        const result = await db.query(
          "INSERT INTO study_goals (request_text) VALUES ($1) RETURNING id, status",
          [text],
        );
        return result.rows[0];
      });

      // The row is saved; the agent's periodic sweep picks it up even if Redis is down.
      let notified = true;
      try {
        await publish(STUDY_CHANNEL, JSON.stringify({ goal_id: goal.id }));
      } catch (err) {
        notified = false;
        app.log.error(err);
      }
      return reply.code(202).send({ goal_id: goal.id, status: goal.status, notified });
    },
  );

  // Ask the agent to write cards and questions for one module.
  app.post<{ Params: { id: string } }>(
    "/study/modules/:id/materials",
    { config: { rateLimit: { max: 10, timeWindow: "1 minute" } } },
    async (req, reply) => {
      const id = parseId(req.params.id);
      if (id === undefined) {
        return reply.code(400).send({ status: "error", message: "invalid module id" });
      }
      const outcome = await withDb(createDbClient, async (db) => {
        // Anything but an in-flight request can be queued (a ready module is rewritten),
        // so a double click can't queue it twice.
        const updated = await db.query(
          `UPDATE study_modules SET materials_status = 'pending', materials_error = NULL
            WHERE id = $1 AND materials_status <> 'pending'
            RETURNING id, materials_status`,
          [id],
        );
        if (updated.rows[0]) return { module: updated.rows[0] };
        const existing = await db.query("SELECT materials_status FROM study_modules WHERE id = $1", [id]);
        return { existing: existing.rows[0]?.materials_status as string | undefined };
      });
      if (!outcome.module) {
        return outcome.existing === undefined
          ? reply.code(404).send({ status: "error", message: "module not found" })
          : reply.code(409).send({ status: "error", message: `materials already ${outcome.existing}` });
      }

      let notified = true;
      try {
        await publish(STUDY_CHANNEL, JSON.stringify({ module_id: id }));
      } catch (err) {
        notified = false;
        app.log.error(err);
      }
      return reply.code(202).send({ module_id: id, materials_status: "pending", notified });
    },
  );

  app.get<{ Params: { id: string } }>("/study/modules/:id/materials", async (req, reply) => {
    const id = parseId(req.params.id);
    if (id === undefined) {
      return reply.code(400).send({ status: "error", message: "invalid module id" });
    }
    const found = await withDb(createDbClient, async (db) => {
      const module = await db.query(
        `SELECT id, title, materials_status, materials_error, materials_sources
           FROM study_modules WHERE id = $1`,
        [id],
      );
      if (!module.rows[0]) return undefined;
      const cards = await db.query(
        "SELECT id, front, back FROM study_cards WHERE module_id = $1 ORDER BY position",
        [id],
      );
      // The correct answer is not sent here: it comes back when an answer is submitted.
      const questions = await db.query(
        "SELECT id, question, options FROM study_questions WHERE module_id = $1 ORDER BY position",
        [id],
      );
      return { module: module.rows[0], cards: cards.rows, questions: questions.rows };
    });
    if (!found) return reply.code(404).send({ status: "error", message: "module not found" });
    return found;
  });

  app.post<{ Params: { id: string } }>(
    "/study/questions/:id/answer",
    { bodyLimit: 1024 },
    async (req, reply) => {
      const id = parseId(req.params.id);
      if (id === undefined) {
        return reply.code(400).send({ status: "error", message: "invalid question id" });
      }
      const chosen = (req.body as { chosen_index?: unknown } | null)?.chosen_index;
      if (typeof chosen !== "number" || !Number.isInteger(chosen) || chosen < 0 || chosen > 3) {
        return reply.code(400).send({ status: "error", message: "chosen_index must be 0, 1, 2 or 3" });
      }

      const result = await withDb(createDbClient, async (db) => {
        const question = await db.query(
          "SELECT correct_index, explanation FROM study_questions WHERE id = $1",
          [id],
        );
        const row = question.rows[0];
        if (!row) return undefined;
        const correct = row.correct_index === chosen;
        await db.query(
          "INSERT INTO study_attempts (question_id, chosen_index, is_correct) VALUES ($1, $2, $3)",
          [id, chosen, correct],
        );
        return { correct, correct_index: row.correct_index, explanation: row.explanation };
      });
      if (!result) return reply.code(404).send({ status: "error", message: "question not found" });
      return result;
    },
  );
}
