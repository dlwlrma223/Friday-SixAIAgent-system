import { createHash, timingSafeEqual } from "node:crypto";
import type { FastifyReply, FastifyRequest } from "fastify";

function digest(value: string): Buffer {
  return createHash("sha256").update(value).digest();
}

// Hash both sides so the comparison is constant-time regardless of length.
export function tokenMatches(presented: string, expected: string): boolean {
  return timingSafeEqual(digest(presented), digest(expected));
}

// Fails closed: with no token configured the dashboard routes stay locked,
// because the api is reachable from the internet in prod.
export function requireDashboardToken(expected: string | undefined) {
  return async (req: FastifyRequest, reply: FastifyReply) => {
    if (!expected) {
      return reply.code(503).send({ status: "error", message: "dashboard token not configured" });
    }
    const header = req.headers.authorization ?? "";
    const presented = header.startsWith("Bearer ") ? header.slice(7) : "";
    if (!presented || !tokenMatches(presented, expected)) {
      return reply.code(401).send({ status: "error", message: "unauthorized" });
    }
  };
}
