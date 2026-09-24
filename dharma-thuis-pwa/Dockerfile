FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/index.html
COPY manifest.webmanifest /usr/share/nginx/html/manifest.webmanifest
COPY sw.js /usr/share/nginx/html/sw.js
COPY icon-192.svg /usr/share/nginx/html/icon-192.svg
COPY icon-512.svg /usr/share/nginx/html/icon-512.svg
EXPOSE 8080
