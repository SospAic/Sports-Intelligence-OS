FROM node:24-alpine

ENV NEXT_TELEMETRY_DISABLED=1 \
    API_INTERNAL_URL=http://api:8000
WORKDIR /workspace

RUN corepack enable && corepack prepare pnpm@11.9.0 --activate

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc .prettierignore /workspace/
COPY packages /workspace/packages
COPY apps/web /workspace/apps/web

RUN pnpm install --frozen-lockfile \
    && pnpm --filter @sio/web build

EXPOSE 3000
CMD ["pnpm", "--filter", "@sio/web", "start"]
