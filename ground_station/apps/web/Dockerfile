FROM node:20-bookworm-slim AS build

WORKDIR /workspace

COPY ground_station/shared ./ground_station/shared
COPY ground_station/packages ./ground_station/packages
COPY ground_station/apps/web/package*.json ./ground_station/apps/web/

WORKDIR /workspace/ground_station/apps/web

RUN npm install --no-audit --no-fund

COPY ground_station/apps/web ./

RUN npm run build

FROM nginx:1.27-alpine AS runtime

ENV COMPANION_BASE_URL=

COPY ground_station/apps/web/docker-entrypoint.sh /docker-entrypoint.d/10-runtime-config.sh
COPY ground_station/apps/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /workspace/ground_station/apps/web/dist /usr/share/nginx/html
RUN chmod +x /docker-entrypoint.d/10-runtime-config.sh

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
