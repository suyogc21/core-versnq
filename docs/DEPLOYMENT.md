# Versnq Core — deployment (the shared server)

Core runs on the same server as AMS (`222.167.207.64`, hostname `versnq.in`), **in its own space**: its own folder, containers, database, Redis, files and ports. AMS, the website, n8n and suyogsalgo are never touched. The one thing they share is the host nginx, which Core adds its own files to.

| | AMS | Core |
|---|---|---|
| Folder | `/opt/ams` | `/opt/core` |
| Containers | `ams-*` | `core-*` (postgres, redis, backend, worker, frontend, frontend-admin) |
| Ports (127.0.0.1 only) | 3000, 3001, 8000 | 3100 (app), 3101 (staff console), 8100 (API) |
| Addresses | `<company>.ams.versnq.in`, `admin.versnq.in` | `<company>.core.versnq.in`, `admincore.versnq.in` |
| nginx files | `ams-*`, `admin.versnq.in.conf`, `api.ams…` | `admincore.versnq.in.conf`, `core-company-<slug>.conf` |

```
browser ──https──> host nginx ──> <slug>.core.versnq.in   /api/v1 → 127.0.0.1:8100 (backend)
                                                          the rest → 127.0.0.1:3100 (app)
                                  admincore.versnq.in     /platform → 127.0.0.1:8100
                                                          the rest → 127.0.0.1:3101 (staff console)
backend + worker ──> core postgres, core redis (internal only)
```

API calls go **straight from nginx to the backend**, so rate limits and audit rows see each visitor's own address (nginx sets `X-Forwarded-For $remote_addr`, overwriting whatever the visitor sent).

## One time: DNS (GoDaddy) — done Nov 13

| Type | Name | Value |
|---|---|---|
| A | `*.core` | `222.167.207.64` |
| A | `admincore` | `222.167.207.64` |

## One time: get the code

GitHub repo `suyogc21/core-versnq` is private, so the server pulls with its own **read-only deploy key**:

```bash
ssh-keygen -t ed25519 -N "" -C "core-deploy@versnq.in" -f /root/.ssh/core_deploy
cat >> /root/.ssh/config <<'EOF'
Host github-core
  HostName github.com
  User git
  IdentityFile /root/.ssh/core_deploy
  IdentitiesOnly yes
EOF
cat /root/.ssh/core_deploy.pub   # GitHub → repo → Settings → Deploy keys → Add (read-only)
git clone git@github-core:suyogc21/core-versnq.git /opt/core
```

## One time: secrets

```bash
cd /opt/core && cp .env.prod.example .env.prod && chmod 600 .env.prod
# fill every empty value with a fresh secret (commands at the top of the file)
```

`.env.prod` lives only on the server. Never commit it; never paste it into chat.

## Start, or update after a `git push`

```bash
cd /opt/core
git pull
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
docker compose -f docker-compose.prod.yml ps
curl -s http://127.0.0.1:8100/health
```

The backend applies database migrations when it starts. The worker (sequences, reminders, mailbox sync, webhooks, WhatsApp health) starts with it.

## One time: nginx + HTTPS for the staff console

```bash
cp /opt/core/infra/nginx/admincore.versnq.in.conf /etc/nginx/sites-available/
ln -sf /etc/nginx/sites-available/admincore.versnq.in.conf /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
certbot --nginx -d admincore.versnq.in --non-interactive --agree-tos -m admin@versnq.in --redirect
```

## One time: the first Versnq staff account

```bash
cd /opt/core
docker compose -f docker-compose.prod.yml exec backend python -m app.platform.cli create-staff
```

Sign in at `https://admincore.versnq.in` (the authenticator app is required for staff; there are no demo shortcuts in production). Company users get an emailed sign-in code instead, on each new browser (Decision #45).

## Demo companies (invented data)

With `ALLOW_DEMO_DATA=true` in `.env.prod`, after the first staff account exists:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec backend python -m app.platform.demo --server
for s in brightlane acme bluewave; do /opt/core/infra/nginx/add-company.sh $s; done
```

It adds Brightlane Software (B2B SaaS), Acme Academy (EdTech) and Bluewave Realty (real estate, AED), prints every demo sign-in and one shared password **once**. There is no demo staff account on the server. Demo sign-ins need only the password: their invented `*.demo` addresses can't receive the emailed sign-in code, so none is sent (anyone who turned on the authenticator app uses it). Each company is walled off from the others, including real ones.

## Each new company (automatic)

Create the company in the staff console. Within about 2 minutes, `https://<slug>.core.versnq.in` works: a timer on the server (`core-provision-companies.timer`, every 2 min) finds companies without HTTPS and runs `infra/nginx/add-company.sh` for them. The `*.core` DNS record already points here.

- Watch it: `journalctl -u core-provision-companies -n 30`
- A failure is retried after an hour, at most 3 times (Let's Encrypt limits repeated failures). To retry at once: `rm /var/lib/core-provision/<slug>.fail`
- By hand, if ever needed: `/opt/core/infra/nginx/add-company.sh <slug>`

One time, to install the timer:
```bash
cp /opt/core/infra/nginx/core-provision-companies.{service,timer} /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now core-provision-companies.timer
```

## What works on the server today, and what waits

| Works | Waits on |
|---|---|
| Everything in the app, staff console, sign-in with 2FA | — |
| Sending/receiving email through a **connected mailbox** (Gmail / Google Workspace / Zoho / any IMAP+SMTP, with an app password) | — |
| WhatsApp **Chrome extension** for reps' own WhatsApp (load `extension/dist`; set its address to the company's `https://<slug>.core.versnq.in`) | — |
| Company WhatsApp number | Meta Business verification; then `WHATSAPP_SENDER=meta` |
| Copy-in addresses, company-wide sending | Amazon SES; then `INBOUND_EMAIL_LIVE=true` |
| Invite, password-reset and sign-in code emails | Sent from `support@versnq.in` (`SYSTEM_SMTP_*` in `.env.prod`, the same Zoho mailbox AMS uses) |
| Payment links | Razorpay / Stripe keys |

## Backups (nightly)

```bash
cp /opt/core/infra/backup/core-backup.cron /etc/cron.d/core-backup
/opt/core/infra/backup/core-backup.sh        # run once now to check
```

Every night at 02:30: the database (`db-<date>.dump`, `pg_dump` custom format) and uploaded files (`files-<date>.tgz`) into `/opt/core-backups`, kept 14 days. Log: `/var/log/core-backup.log`.

Restore the database (stops nothing else):
```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T postgres \
  pg_restore -U postgres -d versnq --clean --if-exists < /opt/core-backups/db-<date>.dump
```

**Still to do:** a copy off this server (another machine or storage), so a lost server doesn't lose the backups too.

## Not set up yet (the parked go-live work)

- A backup copy off the server (above).
- Error monitoring, log rotation, 2FA recovery codes (see `docs/OWNER-TODO.md`).

## Useful

```bash
cd /opt/core
docker compose -f docker-compose.prod.yml logs -f backend worker     # what's happening
docker compose -f docker-compose.prod.yml restart backend worker
docker compose -f docker-compose.prod.yml down                       # stops Core only; data kept
```

Never run `docker system prune --volumes` on this server: it would delete AMS's and Core's data.
