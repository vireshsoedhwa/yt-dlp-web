# Frontend Dockerfile — single multi-stage file for dev and prod.
# Select with: docker build --target dev .  (or prod)
# Compose files use `build.target` to pick the right stage.

# --- Stage: deps (shared base) ---
FROM node:22-alpine AS deps

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

# --- Stage: dev (Vite dev server with HMR) ---
# Source is mounted at runtime via docker-compose volumes in dev mode.
# COPY . . is included so the image is also usable standalone.
FROM deps AS dev

COPY . .

EXPOSE 3000
CMD ["npm", "run", "dev"]

# --- Stage: builder (compile static assets) ---
FROM deps AS builder

COPY . .
RUN npm run build

# --- Stage: prod (nginx serving built assets) ---
FROM nginx:alpine AS prod

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx-frontend.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]