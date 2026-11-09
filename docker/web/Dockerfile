FROM node:22-alpine AS build

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* /app/
RUN npm install
COPY frontend /app
RUN npm run build

FROM nginx:1.31-alpine

COPY docker/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
