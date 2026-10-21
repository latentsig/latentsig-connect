#!/usr/bin/env sh
set -eu

docker compose --profile production --profile certificates run --rm certbot renew --webroot -w /var/www/certbot --quiet
docker compose --profile production exec -T nginx nginx -s reload
echo "Certificate renewal check completed and Nginx reloaded."
