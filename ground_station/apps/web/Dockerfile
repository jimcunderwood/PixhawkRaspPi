FROM node:20-bookworm-slim AS build

WORKDIR /workspace/ground_station/apps/web

COPY ground_station/shared /workspace/ground_station/shared
COPY ground_station/packages /workspace/ground_station/packages
COPY ground_station/apps/web/package*.json ./

RUN npm install --no-audit --no-fund

COPY ground_station/apps/web ./

RUN npm run build

FROM node:20-bookworm-slim AS runtime

WORKDIR /app

ENV GROUND_STATION_HOST=0.0.0.0
ENV GROUND_STATION_PORT=80
ENV GROUND_STATION_SHELL_LABEL=web
ENV COMPANION_BASE_URL=

COPY --from=build /workspace/ground_station/apps/web /app

EXPOSE 80

CMD ["node", "server.mjs"]
