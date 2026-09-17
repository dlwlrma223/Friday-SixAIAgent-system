# api

Node.js + TypeScript backend (Fastify). Talks to the frontend via HTTP + WebSocket, and to `agent` via Redis — never direct HTTP calls to `agent`.

## Run standalone

```
npm install
npm run dev
```

Health check: `GET http://localhost:3001/health`

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

- 這個服務目前只有兩個 endpoint，用內建 test runner 已經夠用，不需要多一層
  esbuild/vite 依賴。
- `/db-check` 依賴外部的 RDS，測試用依賴注入（`buildApp({ createDbClient })`）
  換成假的 client 物件來驗證錯誤處理分支（連線逾時、查詢失敗、收尾失敗），
  不需要 mock `pg` 這個 npm module，也不需要真的起一個本地 Postgres。

```
npm test          # 跑一次
npm run test:watch  # 檔案變動時自動重跑
```
