FROM node:22-bookworm-slim

WORKDIR /app
ENV NODE_ENV=production

COPY package.json package-lock.json ./
RUN npm ci --include=dev

COPY . .
RUN npm run build

ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "exec ./node_modules/.bin/vinext start --host 0.0.0.0 --port ${PORT:-8080}"]
