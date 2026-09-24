FROM debian:bookworm-slim AS assets
RUN apt-get update && apt-get install -y --no-install-recommends librsvg2-bin && rm -rf /var/lib/apt/lists/*
WORKDIR /assets
COPY icon.svg /assets/icon.svg
RUN rsvg-convert -w 192 -h 192 /assets/icon.svg > /assets/icon-192.png \
 && rsvg-convert -w 512 -h 512 /assets/icon.svg > /assets/icon-512.png

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/index.html
COPY manifest.webmanifest /usr/share/nginx/html/manifest.webmanifest
COPY sw.js /usr/share/nginx/html/sw.js
COPY offline.html /usr/share/nginx/html/offline.html
COPY --from=assets /assets/icon-192.png /usr/share/nginx/html/icon-192.png
COPY --from=assets /assets/icon-512.png /usr/share/nginx/html/icon-512.png
EXPOSE 8080
