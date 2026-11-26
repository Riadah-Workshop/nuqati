FROM node:26-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
# Exactly the versions in the committed lock file; the build fails if the lock file and package.json disagree.
RUN npm ci --no-audit --no-fund
COPY . .
ENV VITE_API_BASE_URL=""
ARG VITE_MAPTILER_API_KEY
ENV VITE_MAPTILER_API_KEY=${VITE_MAPTILER_API_KEY}
RUN npm run build
FROM caddy:2-alpine
COPY --from=build /src/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile
EXPOSE 80
