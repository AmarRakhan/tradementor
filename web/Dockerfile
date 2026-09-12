FROM node:22-bookworm-slim

WORKDIR /app
ENV NODE_ENV=production

COPY package.json package-lock.json ./
RUN npm ci --include=dev

COPY . .
RUN apt-get update \
  && apt-get install -y --no-install-recommends ffmpeg \
  && ffmpeg -hide_banner -loglevel error -y \
    -i public/portfolio-impact-bull-bear-master.mp4 \
    -vf "reverse,fps=30,scale=1280:720:flags=lanczos,setsar=1" \
    -an -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p \
    -g 6 -keyint_min 6 -sc_threshold 0 -movflags +faststart \
    public/portfolio-impact-bull-bear-master-reverse.mp4 \
  && apt-get purge -y --auto-remove ffmpeg \
  && rm -rf /var/lib/apt/lists/*
RUN npm run build

ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "exec ./node_modules/.bin/vinext start --host 0.0.0.0 --port ${PORT:-8080}"]
