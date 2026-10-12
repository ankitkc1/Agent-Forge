# syntax=docker/dockerfile:1.7
# AgentForge workbench: static build served by an unprivileged nginx that also proxies /api to the
# control plane, so the browser talks to a single origin (no CORS, streaming builds unbuffered).

FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY tsconfig.json tsconfig.app.json tsconfig.node.json vite.config.ts eslint.config.js index.html ./
COPY public ./public
COPY src ./src
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    AGENTFORGE_WEB_OUT_DIR=dist
RUN npm run build

FROM nginx:1.28-alpine AS runtime
RUN addgroup -S agentforge && adduser -S -G agentforge -u 10001 agentforge \
    && mkdir -p /var/cache/nginx /var/run /tmp/nginx \
    && chown -R agentforge:agentforge /var/cache/nginx /var/run /tmp/nginx /usr/share/nginx/html
COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=build --chown=agentforge:agentforge /app/dist /usr/share/nginx/html
USER agentforge
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
CMD ["nginx", "-g", "daemon off;"]
