# api

Node.js + TypeScript backend (Fastify). Talks to the frontend via HTTP + WebSocket, and to `agent` via Redis — never direct HTTP calls to `agent`.

## Run standalone

```
npm install
npm run dev
```

Health check: `GET http://localhost:3001/health`

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
