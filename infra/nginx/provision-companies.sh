#!/usr/bin/env bash
# Every company created in the staff console gets nginx + HTTPS for <slug>.core.versnq.in on its
# own, within about 2 minutes. Runs on the HOST as root from core-provision-companies.timer.
# (Same idea as AMS's provision-tenants.sh: the backend container can't and mustn't drive the
# host's nginx/certbot, so this loop reads the company list and makes the server catch up.)
#
# Done when a company has both its certificate and its nginx file. Failures are remembered in
# /var/lib/core-provision/<slug>.fail and retried after an hour, at most 3 times, because
# Let's Encrypt rate-limits repeated failures. Delete that file to retry at once.
set -uo pipefail

cd /opt/core || exit 1
COMPOSE=(docker compose -f docker-compose.prod.yml --env-file .env.prod)
STATE=/var/lib/core-provision
MAX_TRIES=3
RETRY_AFTER=3600
mkdir -p "$STATE"

slugs=$("${COMPOSE[@]}" exec -T postgres psql -U postgres -d versnq -v ON_ERROR_STOP=1 -tA \
    -c "SELECT slug FROM tenants ORDER BY created_at" 2>/dev/null | tr -d '\r') || exit 0
[ -z "$slugs" ] && exit 0

while read -r slug; do
    [ -z "$slug" ] && continue
    echo "$slug" | grep -Eq '^[a-z0-9]([a-z0-9-]*[a-z0-9])?$' || { echo "[provision] skip invalid slug: $slug"; continue; }
    host="${slug}.core.versnq.in"
    if [ -e "/etc/letsencrypt/live/${host}/fullchain.pem" ] && \
       [ -e "/etc/nginx/sites-enabled/core-company-${slug}.conf" ]; then
        rm -f "$STATE/${slug}.fail"
        continue
    fi

    tries=0; last=0
    if [ -f "$STATE/${slug}.fail" ]; then
        read -r tries last < "$STATE/${slug}.fail" || true
        [ "${tries:-0}" -ge "$MAX_TRIES" ] && continue
        [ $(( $(date +%s) - ${last:-0} )) -lt "$RETRY_AFTER" ] && continue
    fi

    echo "[provision] setting up ${host}"
    if out=$(bash /opt/core/infra/nginx/add-company.sh "$slug" </dev/null 2>&1); then
        echo "[provision] OK: ${host}"
        rm -f "$STATE/${slug}.fail"
    else
        echo "$out" | tail -8
        echo "$(( ${tries:-0} + 1 )) $(date +%s)" > "$STATE/${slug}.fail"
        echo "[provision] FAILED (try $(( ${tries:-0} + 1 )) of ${MAX_TRIES}): ${host}"
    fi
done <<< "$slugs"
