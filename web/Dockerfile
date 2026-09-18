FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ARG VITE_API_URL=""
ARG VITE_WS_URL=""
ARG VITE_BUILD_SHA="development"
ENV VITE_API_URL=$VITE_API_URL VITE_WS_URL=$VITE_WS_URL VITE_BUILD_SHA=$VITE_BUILD_SHA
RUN npm run build
RUN printf '{"web_build_sha":"%s"}\n' "$VITE_BUILD_SHA" > /app/dist/version.json

FROM caddy:2.9-alpine
COPY --from=build /app/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile
EXPOSE 80
