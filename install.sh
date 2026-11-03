#!/usr/bin/env bash
# Telepítés: sudo bash install.sh USER   (pl. sudo bash install.sh accofil)
set -euo pipefail
user="${1:?usage: sudo bash install.sh USER}"
here="$(cd "$(dirname "$0")" && pwd)"
DEBIAN_FRONTEND=noninteractive apt-get -qq install -y vnstat >/dev/null
install -d /opt/qbit-space-gate /etc/qbit-space-gate
install -m 755 "$here/qbit_space_gate.py" "$here/qbit_traffic_guard.py" /opt/qbit-space-gate/
if [[ ! -f /etc/qbit-space-gate/config.toml ]]; then
    install -m 640 -o root -g "$user" "$here/config.example.toml" /etc/qbit-space-gate/config.toml
    echo "Fill in /etc/qbit-space-gate/config.toml, then:"
    echo "  systemctl enable --now qbit-space-gate@$user qbit-traffic-guard@$user.timer"
fi
install -m 644 "$here"/deploy/*.service "$here"/deploy/*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now vnstat >/dev/null
