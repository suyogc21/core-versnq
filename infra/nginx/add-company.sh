#!/usr/bin/env bash
# Host nginx + HTTPS for one Core company: <slug>.core.versnq.in. Run on the server as root
# when a company is created in the staff console (DNS: the *.core A record covers it).
#
#   /opt/core/infra/nginx/add-company.sh <slug>
set -euo pipefail

SLUG="${1:?usage: add-company.sh <slug>}"
[[ "$SLUG" =~ ^[a-z0-9-]+$ ]] || { echo "slug: lowercase letters, digits and - only"; exit 1; }
HOST="${SLUG}.core.versnq.in"
CERTBOT_EMAIL="${CERTBOT_EMAIL:-admin@versnq.in}"
NAME="core-company-${SLUG}.conf"
CONF="/etc/nginx/sites-available/${NAME}"

cat > "$CONF" <<CONFEOF
server {
    listen 80;
    listen [::]:80;
    server_name ${HOST};
    client_max_body_size 12m;
    # browsers use HTTPS only for a year (go-live G-3); not includeSubDomains: other versnq.in sites
    add_header Strict-Transport-Security "max-age=31536000" always;

    # the API goes straight to the backend (one hop, so it sees the visitor's address)
    location /api/v1/ {
        proxy_pass http://127.0.0.1:8100;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }
    # call recordings from the phone app (calls step C1) may be up to 50 MB
    location ~ ^/api/v1/calls/[^/]+/recording\$ {
        client_max_body_size 55m;
        proxy_pass http://127.0.0.1:8100;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300s;
    }
    location / {
        proxy_pass http://127.0.0.1:3100;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
CONFEOF

ln -sf "$CONF" "/etc/nginx/sites-enabled/${NAME}"
nginx -t && systemctl reload nginx
certbot --nginx -d "${HOST}" --non-interactive --agree-tos -m "${CERTBOT_EMAIL}" --redirect
echo "${HOST} is live over HTTPS."
