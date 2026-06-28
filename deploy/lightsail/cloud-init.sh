#!/bin/sh
if [ -z "${BASH_VERSION:-}" ]; then
  exec /bin/bash "$0" "$@"
fi
set -Eeuo pipefail

ZEROTIER_NETWORK_ID="${ZEROTIER_NETWORK_ID:-08752e18b1384126}"
RUT241_URL="${RUT241_URL:-http://10.23.48.89}"

export DEBIAN_FRONTEND=noninteractive

hostnamectl set-hostname isaac1-lightsail

apt-get update
apt-get install -y ca-certificates curl python3 python3-pip python3-venv tar

if ! command -v zerotier-cli >/dev/null 2>&1; then
  curl -fsSL https://install.zerotier.com | bash
fi

systemctl enable --now zerotier-one
sleep 3

if ! zerotier-cli listnetworks | grep -q "$ZEROTIER_NETWORK_ID"; then
  zerotier-cli join "$ZEROTIER_NETWORK_ID"
fi

if ! id isaac1 >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /opt/isaac1 --shell /usr/sbin/nologin isaac1
fi

mkdir -p /opt/isaac1/releases /etc/isaac1
chown -R isaac1:isaac1 /opt/isaac1

if [ ! -d /opt/isaac1/venv ]; then
  python3 -m venv /opt/isaac1/venv
  /opt/isaac1/venv/bin/python -m pip install --upgrade pip setuptools wheel
fi

if [ ! -f /etc/isaac1/isaac1.env ]; then
  cat >/etc/isaac1/isaac1.env <<EOF
ISAAC1_RUT241_URL=$RUT241_URL
ISAAC1_CONTROL_TOKEN=replace-this-during-deploy
PYTHONUNBUFFERED=1
EOF
  chmod 600 /etc/isaac1/isaac1.env
  chown root:root /etc/isaac1/isaac1.env
fi

cat >/etc/systemd/system/isaac1-control.service <<'EOF'
[Unit]
Description=ISAAC1 control UI
After=network-online.target zerotier-one.service
Wants=network-online.target
Requires=zerotier-one.service

[Service]
Type=simple
User=isaac1
Group=isaac1
WorkingDirectory=/opt/isaac1/app
EnvironmentFile=/etc/isaac1/isaac1.env
ExecStart=/opt/isaac1/venv/bin/python -m isaac1 control-ui --bind 127.0.0.1 --port 8765
Restart=always
RestartSec=5
PrivateTmp=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

echo "ISAAC1 Lightsail bootstrap complete."
echo "Authorize this node in ZeroTier Central, then deploy the app from the project workstation."
