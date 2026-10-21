#!/bin/sh
set -eu

domain="${PUBLIC_DOMAIN:-connect.latentsig.com}"
case "$domain" in
  ''|*[!A-Za-z0-9.-]*|.*|*.) echo "PUBLIC_DOMAIN must be a DNS hostname" >&2; exit 1 ;;
esac

if [ -s "/etc/letsencrypt/live/$domain/fullchain.pem" ] && [ -s "/etc/letsencrypt/live/$domain/privkey.pem" ]; then
  source_config=/etc/nginx/tls.conf
else
  source_config=/etc/nginx/bootstrap.conf
fi

sed "s/__PUBLIC_DOMAIN__/$domain/g" "$source_config" > /etc/nginx/conf.d/default.conf
