FROM node:22-slim AS base
WORKDIR /app
COPY package*.json ./

# Local docker-compose target: bind mount + tsx watch for hot reload.
FROM base AS dev
RUN npm ci
COPY . .
EXPOSE 3001
CMD ["npm", "run", "dev"]

# Compile-only stage, never run as a container itself.
FROM base AS build
RUN npm ci
COPY . .
RUN npm run build

# ECS deploy target: no devDependencies, no tsx, non-root.
FROM base AS production
RUN npm ci --omit=dev
COPY --from=build /app/dist ./dist
COPY certs ./certs
RUN useradd --system --create-home --shell /usr/sbin/nologin appuser \
  && chown -R appuser:appuser /app
USER appuser
EXPOSE 3001
CMD ["node", "dist/index.js"]
