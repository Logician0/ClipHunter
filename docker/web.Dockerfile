FROM node:22-bookworm-slim

WORKDIR /app
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
ARG CLIPHUNTER_API_ORIGIN=http://api:3101
ENV CLIPHUNTER_API_ORIGIN=${CLIPHUNTER_API_ORIGIN} NEXT_TELEMETRY_DISABLED=1
RUN npm run build
RUN npm prune --omit=dev
EXPOSE 3000
CMD ["node", "node_modules/next/dist/bin/next", "start", "--hostname", "0.0.0.0", "-p", "3000"]
