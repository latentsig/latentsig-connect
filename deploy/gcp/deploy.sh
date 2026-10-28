#!/usr/bin/env bash
set -euo pipefail
umask 077
[[ $EUID == 0 && $# == 3 ]] || { echo 'Usage: sudo deploy.sh SOURCE.tar.gz PUBLIC_DOMAIN BACKUP_BUCKET' >&2; exit 1; }
archive=$(realpath "$1")
domain=$2
bucket=$3
[[ $domain =~ ^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$ && $bucket =~ ^[a-z0-9][a-z0-9.-]+[a-z0-9]$ ]] || { echo 'Invalid domain or bucket name.' >&2; exit 1; }
mountpoint -q /srv/latentsig-connect || { echo 'Run bootstrap.sh first.' >&2; exit 1; }
exec 9>/srv/latentsig-connect/deploy.lock
flock -n 9 || { echo 'Another deployment or backup is running.' >&2; exit 1; }
staging=$(mktemp -d /opt/latentsig-connect-stage.XXXXXX)
trap 'rm -rf "$staging"' EXIT
python3 "$(dirname "$(realpath "$0")")/extract_source.py" "$archive" "$staging"
[[ -f $staging/docker-compose.yml && -f $staging/deploy/gcp/runtime.py ]] || { echo 'Archive root must be the repository root.' >&2; exit 1; }
mkdir -p /opt/latentsig-connect
rsync -a --delete --exclude=.env "$staging/" /opt/latentsig-connect/
cd /opt/latentsig-connect
python3 deploy/gcp/runtime.py environment "$domain"
ln -sfn /srv/latentsig-connect/secrets/production.env .env
printf 'BACKUP_BUCKET=%s\n' "$bucket" > /etc/latentsig-connect.conf
chmod 600 /etc/latentsig-connect.conf
export COMPOSE_PROJECT_NAME=latentsig-connect
docker compose --profile production config --quiet
docker compose --profile production up --build --wait --wait-timeout 240 -d
python3 deploy/gcp/runtime.py admins
bash deploy/gcp/operations.sh install-timers
echo 'Stack started. Run issue-tls after DNS points at this VM.'
