import Fastify from "fastify";
import cors from "@fastify/cors";

const app = Fastify({ logger: true });

// 只允許本地 dashboard 的來源呼叫 API，不要用 origin: true 反射任意來源。
// 現在只有 /health、風險低，但之後一旦加入會改資料 / 觸發外部效果的
// endpoint（approvals、calendar 寫入等），origin: true 等於允許任何網站
// 用使用者瀏覽器的身份打過來，是必須先收緊的一環。
const allowedOrigins = (
  process.env.CORS_ORIGIN ?? "http://localhost:5173,http://localhost:8080"
)
  .split(",")
  .map((o) => o.trim())
  .filter(Boolean);

await app.register(cors, { origin: allowedOrigins });

app.get("/health", async () => {
  return { status: "ok" };
});

const port = Number(process.env.PORT ?? 3001);

try {
  await app.listen({ port, host: "0.0.0.0" });
} catch (err) {
  app.log.error(err);
  process.exit(1);
}
