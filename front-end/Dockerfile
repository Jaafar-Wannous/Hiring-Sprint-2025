# syntax=docker/dockerfile:1.6

FROM node:20-alpine AS build
WORKDIR /app

ENV NODE_ENV=production \
    NG_CLI_ANALYTICS=false

COPY package*.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist/front-end/browser /usr/share/nginx/html

EXPOSE 80
