# api

Node.js + TypeScript backend (Fastify). Talks to the frontend via HTTP + WebSocket, and to `agent` via Redis — never direct HTTP calls to `agent`.

## Run standalone

```
npm install
npm run dev
```

Health check: `GET http://localhost:3001/health`

## Dashboard endpoints

全部都要帶 `Authorization: Bearer <DASHBOARD_TOKEN>`。伺服器沒設 `DASHBOARD_TOKEN`
時一律回 503（fail closed），因為 prod 的 api 是公開可連的。

| Method | Path | 作用 |
|---|---|---|
| GET | `/approvals?status=pending` | 列出待批准項目（status 可填 pending / approved / skipped） |
| GET | `/research/queries?limit=20` | Research agent 最近的查詢紀錄（limit 1–100） |
| POST | `/approvals/:id/approve` | 批准；只有 pending 的才會變，重複按回 409 |
| POST | `/approvals/:id/skip` | 略過 |
| GET | `/calendar/events` | agent 從 iCloud 同步回來、還沒結束的事件 |
| GET | `/calendar/intents` | 處理中或最近 10 分鐘內完成的句子和結果 |
| POST | `/calendar/intents` | 送一句話給 Calendar agent，body 是 `{"text": "..."}`（1–500 字，每分鐘最多 10 次） |

approve / skip 寫完 DB 之後，會往 Redis channel `friday:approvals` 發
`{"approval_id":2,"status":"approved"}` 通知 agent。DB 才是準則，Redis 只是提醒：
Redis 掛掉時批准仍然成立，回應裡 `notified` 會是 `false`。

```
curl -H "Authorization: Bearer $DASHBOARD_TOKEN" http://localhost:3001/approvals
```

`POST /calendar/intents` 只把句子存進 `calendar_intents` 並往 Redis channel
`friday:calendar` 發提醒，回 202。api **不呼叫 LLM、不碰 iCloud，也沒有這兩者的 key**：
agent 把句子變成事件草稿並建立待批准項目，批准後才由 agent 寫進 iCloud。

## Database migrations

Schema 用 `migrations/` 底下的編號 SQL 檔管理（`0001_xxx.sql`、`0002_xxx.sql`…），
api 跟 agent 共用同一份。runner 會把套過的檔名記在 `schema_migrations` 表，
每個檔案只套一次，套用時包在 transaction 裡，失敗就整個 rollback。

```
npm run migrate:dev        # 本機（docker compose 起來後，在 api 容器內或本機直接跑）
node dist/migrate.js       # production image 內（透過 ECS exec）
```

新增 migration：在 `migrations/` 加一個新編號的 `.sql`，**不要改已經套過的檔案**。

## Typecheck

```
npm run typecheck
```

## Test

單元/整合測試用 Node.js 內建的 test runner（`node --test`）+ `tsx` 直接跑
TypeScript，不另外引入 vitest/jest 這類工具鏈，理由：

- 這個服務的 endpoint 不多，用內建 test runner 已經夠用，不需要多一層
  esbuild/vite 依賴。
- `/db-check` 依賴外部的 RDS，測試用依賴注入（`buildApp({ createDbClient })`）
  換成假的 client 物件來驗證錯誤處理分支（連線逾時、查詢失敗、收尾失敗），
  不需要 mock `pg` 這個 npm module，也不需要真的起一個本地 Postgres。

```
npm test          # 跑一次
npm run test:watch  # 檔案變動時自動重跑
```
