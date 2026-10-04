import { createClient } from "redis";

export type Publish = (channel: string, message: string) => Promise<void>;

// api -> agent notifications. The DB row is the source of truth; this is only a nudge.
export const APPROVALS_CHANNEL = "friday:approvals";
export const CALENDAR_CHANNEL = "friday:calendar";

const READY_WAIT_MS = 2000;

// Connects on first publish, so importing the app (tests, /health) never needs Redis.
export function createRedisPublisherFromEnv(env: NodeJS.ProcessEnv = process.env): Publish {
  let client: ReturnType<typeof createClient> | undefined;
  let connecting: Promise<unknown> | undefined;

  return async (channel, message) => {
    if (!client) {
      client = createClient({
        url: env.REDIS_URL ?? "redis://localhost:6379",
        // Set in prod (ElastiCache AUTH). Local compose redis has no password.
        password: env.REDIS_AUTH_TOKEN,
        // Fail the publish instead of queueing it while Redis is down.
        disableOfflineQueue: true,
      });
      // node-redis throws on unhandled 'error' events; reconnect is automatic.
      client.on("error", () => {});
      connecting = client.connect().catch(() => {});
    }
    if (!client.isReady) {
      await Promise.race([connecting, new Promise((resolve) => setTimeout(resolve, READY_WAIT_MS))]);
    }
    if (!client.isReady) throw new Error("redis not ready");
    await client.publish(channel, message);
  };
}
