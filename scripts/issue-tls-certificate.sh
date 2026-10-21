#!/usr/bin/env sh
set -eu

docker compose --profile production up --build -d nginx
docker compose --profile production --profile certificates run --rm certbot
docker compose --profile production restart nginx
echo "Certificate issued and Nginx restarted with HTTPS."
