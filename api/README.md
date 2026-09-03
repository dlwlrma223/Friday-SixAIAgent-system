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
