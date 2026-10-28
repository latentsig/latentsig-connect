#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run as root.' >&2; exit 1; }
[[ $# == 0 || $# == 1 && $1 == --new-disk ]] || { echo 'Usage: bootstrap.sh [--new-disk]' >&2; exit 1; }
disk=/dev/disk/by-id/google-latentsig-connect-data
mountpoint=/srv/latentsig-connect
[[ -b $disk ]] || { echo 'The dedicated data disk is missing.' >&2; exit 1; }
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-v2 python3 curl rsync ca-certificates
systemctl stop docker.service docker.socket || true
mkdir -p "$mountpoint"
filesystem=$(blkid -s TYPE -o value "$disk" || true)
if [[ -z $filesystem ]]; then
  # --new-disk asserts that this disk was just created by the cloud operator.
  [[ -z $(wipefs --no-act --noheadings --output TYPE "$disk") ]] || { echo 'Unrecognized disk signature; refusing to format.' >&2; exit 1; }
  [[ $(lsblk -nr -o NAME "$disk" | wc -l) -eq 1 ]] || { echo 'Disk has partitions; refusing to format.' >&2; exit 1; }
  if [[ ${1:-} != --new-disk ]]; then
    cmp -n "$(blockdev --getsize64 "$disk")" "$disk" /dev/zero >/dev/null || { echo 'Disk is not blank; refusing to format.' >&2; exit 1; }
  fi
  mkfs.ext4 -q -m 0 "$disk"
elif [[ $filesystem != ext4 ]]; then
  echo 'Expected an ext4 data disk; refusing to change it.' >&2; exit 1
fi
uuid=$(blkid -s UUID -o value "$disk")
if mountpoint -q "$mountpoint"; then
  [[ $(findmnt -n -o UUID --target "$mountpoint") == "$uuid" ]] || { echo 'Wrong filesystem mounted at data directory.' >&2; exit 1; }
else
  [[ -z $(find "$mountpoint" -mindepth 1 -maxdepth 1 -print -quit) ]] || { echo 'Data mount directory is not empty.' >&2; exit 1; }
  mount "$disk" "$mountpoint"
fi
python3 - "$uuid" <<'PY'
import pathlib, sys
path = pathlib.Path('/etc/fstab')
lines = path.read_text().splitlines()
entry = f'UUID={sys.argv[1]} /srv/latentsig-connect ext4 defaults 0 2'
existing = [line for line in lines if line.strip() and not line.lstrip().startswith('#') and len(line.split()) > 1 and line.split()[1] == '/srv/latentsig-connect']
if existing and existing != [entry]:
    raise SystemExit('Conflicting fstab entry; refusing to change it.')
if not existing:
    path.write_text('\n'.join(lines + [entry]) + '\n')
PY
mkdir -p /etc/docker /etc/systemd/system/docker.service.d "$mountpoint/docker" "$mountpoint/secrets" /opt/latentsig-connect
chmod 700 "$mountpoint/secrets"
python3 - <<'PY'
import json, pathlib
path = pathlib.Path('/etc/docker/daemon.json')
config = json.loads(path.read_text()) if path.exists() else {}
expected = '/srv/latentsig-connect/docker'
if config.get('data-root', expected) != expected:
    raise SystemExit('Existing Docker data-root differs; refusing to relocate data.')
config['data-root'] = expected
config.setdefault('log-driver', 'json-file')
config.setdefault('log-opts', {'max-size': '10m', 'max-file': '3'})
path.write_text(json.dumps(config) + '\n')
PY
cat > /etc/systemd/system/docker.service.d/data-disk.conf <<'EOF'
[Unit]
RequiresMountsFor=/srv/latentsig-connect
EOF
systemctl daemon-reload
systemctl enable --now docker
echo 'Docker and the persistent data disk are ready.'
