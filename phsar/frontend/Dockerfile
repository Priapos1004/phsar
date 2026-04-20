# syntax=docker/dockerfile:1

# ---------- Builder ----------
FROM oven/bun:1.3.11 AS builder

WORKDIR /build

COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

COPY . .

# PUBLIC_API_BASE_URL and PUBLIC_APP_VERSION are both read at runtime via
# $env/dynamic/public — nothing needs to be baked into the build.
RUN bun run build

# Trim dependencies down to what the node runtime needs.
RUN rm -rf node_modules && bun install --frozen-lockfile --production

# ---------- Runtime ----------
FROM node:22-slim AS runtime

ARG PUBLIC_APP_VERSION=dev
ENV NODE_ENV=production \
    PORT=3000 \
    PUBLIC_APP_VERSION=${PUBLIC_APP_VERSION}

# node:22-slim ships with a non-root "node" user at UID 1000 — reuse it
# rather than creating a new user.
WORKDIR /app

COPY --from=builder --chown=node:node /build/build ./build
COPY --from=builder --chown=node:node /build/node_modules ./node_modules
COPY --from=builder --chown=node:node /build/package.json ./

USER node
EXPOSE 3000

CMD ["node", "build"]
