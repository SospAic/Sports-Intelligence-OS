FROM node:24-alpine

ENV NEXT_TELEMETRY_DISABLED=1 \
    API_INTERNAL_URL=http://api:8000 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
WORKDIR /workspace

RUN corepack enable && corepack prepare pnpm@11.9.0 --activate

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc .prettierignore /workspace/
COPY packages /workspace/packages
COPY apps/web /workspace/apps/web

RUN --mount=type=cache,id=sio-pnpm-store,target=/pnpm/store \
    pnpm config set store-dir /pnpm/store \
    && pnpm config set fetch-retries 5 \
    && pnpm config set fetch-retry-maxtimeout 120000 \
    && pnpm config set fetch-timeout 300000 \
    && pnpm install --frozen-lockfile \
    && pnpm --filter @sio/web build

# Next.js standalone output does not include .next/static or public assets.
# They must be copied manually into the standalone root.
RUN cp -r apps/web/.next/static apps/web/.next/standalone/apps/web/.next/static \
    && if [ -d apps/web/public ]; then cp -r apps/web/public apps/web/.next/standalone/apps/web/public; fi

EXPOSE 3000
CMD ["node", "apps/web/.next/standalone/apps/web/server.js"]
