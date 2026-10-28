#!/usr/bin/env bash
set -euo pipefail
umask 077
[[ $EUID == 0 ]] || { echo 'Run as root.' >&2; exit 1; }
cd /opt/latentsig-connect
export COMPOSE_PROJECT_NAME=latentsig-connect
action=${1:-}
if [[ $action == install-timers ]]; then
  for task in renew retention backup; do
    cat > "/etc/systemd/system/latentsig-connect-${task}.service" <<EOF
[Unit]
Description=Latentsig Connect ${task}
Requires=docker.service
After=docker.service network-online.target
RequiresMountsFor=/srv/latentsig-connect
[Service]
Type=oneshot
EnvironmentFile=/etc/latentsig-connect.conf
ExecStart=/bin/bash /opt/latentsig-connect/deploy/gcp/operations.sh ${task}
TimeoutStartSec=1800
EOF
    case $task in renew) time=02:15:00 ;; retention) time=02:45:00 ;; backup) time=03:15:00 ;; esac
    cat > "/etc/systemd/system/latentsig-connect-${task}.timer" <<EOF
[Unit]
Description=Daily Latentsig Connect ${task}
[Timer]
OnCalendar=*-*-* ${time} UTC
RandomizedDelaySec=10m
Persistent=true
[Install]
WantedBy=timers.target
EOF
  done
  systemctl daemon-reload
  systemctl enable --now latentsig-connect-{renew,retention,backup}.timer
  exit
fi
exec 9>/srv/latentsig-connect/deploy.lock
flock -w 1200 9 || { echo 'Deployment or backup lock timed out.' >&2; exit 1; }
case $action in
  issue-tls)
    python3 deploy/gcp/runtime.py check-dns
    sh scripts/issue-tls-certificate.sh
    ;;
  renew)
    # A bootstrap VM can wait for DNS without generating certificate failures.
    docker compose --profile certificates run --rm --no-deps --entrypoint sh certbot -c 'test -d /etc/letsencrypt/live && test -n "$(ls -A /etc/letsencrypt/live)"' >/dev/null 2>&1 || exit 0
    sh scripts/renew-tls-certificate.sh
    ;;
  retention)
    docker compose exec -T backend python -m app.services.storage.retention
    ;;
  backup)
    [[ -n ${BACKUP_BUCKET:-} ]] || { echo 'BACKUP_BUCKET is required.' >&2; exit 1; }
    backup_dir=$(mktemp -d /srv/latentsig-connect/backup.XXXXXX)
    paused=false
    verify_db=
    cleanup() {
      if [[ -n $verify_db ]]; then docker compose exec -T postgres dropdb -U latentsig --if-exists "$verify_db" >/dev/null || true; fi
      if [[ $paused == true ]]; then docker compose --profile production start backend integration-worker >/dev/null; fi
      rm -rf "$backup_dir"
    }
    trap cleanup EXIT
    # Pause application writes so the card archive and database describe one state.
    paused=true
    docker compose stop backend integration-worker >/dev/null
    docker compose exec -T postgres pg_dump -U latentsig -d latentsig -Fc > "$backup_dir/database.dump"
    docker compose exec -T postgres pg_restore --list < "$backup_dir/database.dump" > /dev/null
    docker compose exec -T postgres psql -U latentsig -d latentsig -Atqc 'SELECT count(*) FROM users; SELECT count(*) FROM leads;' > "$backup_dir/expected-counts"
    volume_path() {
      docker volume inspect "latentsig-connect_$1" --format '{{.Mountpoint}}'
    }
    tar -C "$(volume_path private_cards)" -czf "$backup_dir/private-cards.tar.gz" .
    tar -C "$(volume_path letsencrypt)" -czf "$backup_dir/letsencrypt.tar.gz" .
    cp -a /srv/latentsig-connect/secrets "$backup_dir/secrets"
    docker compose --profile production start backend integration-worker >/dev/null
    paused=false
    candidate="latentsig_verify_$(date +%s)_$RANDOM"
    docker compose exec -T postgres createdb -U latentsig "$candidate"
    verify_db=$candidate
    docker compose exec -T postgres pg_restore -U latentsig --no-owner --exit-on-error -d "$verify_db" < "$backup_dir/database.dump"
    docker compose exec -T postgres psql -U latentsig -d "$verify_db" -Atqc 'SELECT count(*) FROM users; SELECT count(*) FROM leads;' > "$backup_dir/restored-counts"
    cmp "$backup_dir/expected-counts" "$backup_dir/restored-counts"
    docker compose exec -T postgres dropdb -U latentsig "$verify_db"
    verify_db=
    stamp=$(date -u +%Y%m%dT%H%M%SZ)
    tar -C "$backup_dir" -czf "$backup_dir/snapshot.tar.gz" database.dump private-cards.tar.gz letsencrypt.tar.gz secrets
    (cd "$backup_dir" && sha256sum snapshot.tar.gz > snapshot.sha256)
    python3 deploy/gcp/upload-backup.py "$BACKUP_BUCKET" "snapshots/$stamp.tar.gz" "$backup_dir/snapshot.tar.gz"
    python3 deploy/gcp/upload-backup.py "$BACKUP_BUCKET" "snapshots/$stamp.sha256" "$backup_dir/snapshot.sha256"
    ;;
  *) echo 'Expected install-timers, issue-tls, renew, retention, or backup.' >&2; exit 1 ;;
esac
