# Deploying Vectron Management

From a repository to a public HTTPS URL a prospect can open on their own phone.
Written to be followed top to bottom, once, without improvising.

The demo instance this produces holds **fictional data only** (`seed_demo`). No
customer's real data goes near it — that comes after the rest of the hardening
in `docs/briefs/11-security-hardening.md` lands.

> **No secret appears in this file, in the repository, or in the Dockerfile.**
> Only variable *names*. Values are typed into the platform's own settings
> screen, and nowhere else.

---

## 0. What you need first

| | Why |
|---|---|
| A domain name (or a subdomain) | The QR labels are printed with it. A platform-generated URL works, but it changes if you move platforms — and the stickers do not. |
| A PostgreSQL 16 database | Managed (Railway, Neon, Supabase) or on the server. |
| SMTP credentials | Gmail with an **app password**, or Resend. Without this, PDFs by email do not leave. |
| A generated `SECRET_KEY` | `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` |

---

## 1. Environment variables

Set these on the platform. The production profile **refuses to start** if a
required one is missing — that is deliberate: a startup error naming the
variable is cheaper than a site that appears to work and is subtly wrong.

### Required

| Variable | What it is | Getting it wrong looks like |
|---|---|---|
| `DJANGO_SETTINGS_MODULE` | `config.settings_prod`. Already set by the Dockerfile — only set it by hand if you deploy without Docker. | Development settings in production: `DEBUG` behaviour, no HTTPS redirect. |
| `SECRET_KEY` | Signs sessions and CSRF tokens. 50+ random characters. | Anyone who learns it can forge a session cookie. Rotating it logs everyone out — which is also the emergency response. |
| `DATABASE_URL` | `postgresql://user:password@host:5432/dbname`. On Supabase use the **session pooler** host, not the direct one (the direct host is IPv6-only). | The container exits on the migration step. |
| `ALLOWED_HOSTS` | The hostnames this deployment answers to, comma-separated: `cmms.midominio.com`. | Every request answers `400 Bad Request`. |
| `CSRF_TRUSTED_ORIGINS` | The same hosts **with scheme**: `https://cmms.midominio.com`. Comma-separated. | Pages load, but every login and every form fails with a CSRF error. |
| `SITE_URL` | The public base URL, **https only**, no trailing slash. This is what gets printed inside every QR label. | Stickers glued to machines that resolve to nothing. They cannot be edited — only reprinted. |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | SMTP. Port 587 with `EMAIL_USE_TLS=True`, or 465 with SSL. | Startup refuses if `EMAIL_HOST` is empty (silence is the worst email failure). |
| `DEFAULT_FROM_EMAIL` | The From address. Must be one the provider has verified. | The provider rejects the message with "sender refused". |

### Required behind a reverse proxy — which means almost always

| Variable | Set it to |
|---|---|
| `TRUST_PROXY_SSL_HEADER` | `True` on Railway, Render, Fly, or behind nginx/Caddy — anywhere TLS is terminated in front of the app. |

TLS almost never terminates inside the container. The proxy handles HTTPS and
forwards a plain HTTP request, so Django believes the request is insecure and
`SECURE_SSL_REDIRECT` redirects it to HTTPS — to the same proxy, forever. **A
"too many redirects" error on first load is this variable, every time.**

Leave it off only if the app is directly exposed with its own certificate:
trusting `X-Forwarded-Proto` when a client can set it themselves defeats every
secure-cookie rule at once.

### Optional

| Variable | Default | When to change it |
|---|---|---|
| `SECURE_HSTS_SECONDS` | `3600` | Raise it once HTTPS has been stable: `86400` → `2592000` → `31536000`. See §9. |
| `WEB_CONCURRENCY` | `3` | gunicorn workers. Roughly `2 × CPU + 1`; lower it on a 512 MB instance. |
| `GUNICORN_TIMEOUT` | `120` | Seconds before a stuck worker is killed. PDFs with photos are slow. |
| `LOG_LEVEL` | `INFO` | `DEBUG` while hunting something specific — it logs every SQL query. |
| `EMAIL_TIMEOUT` | `20` | Seconds to wait for SMTP. |
| `N8N_WEBHOOK_URL`, `N8N_WEBHOOK_TOKEN` | empty | Phase 2. Empty means nothing is emitted and the app is unaffected. |
| `BACKUP_RETENTION_DAYS` | `14` | Days of dumps `scripts/backup.sh` keeps. |
| `MEDIA_ROOT_PATH` | unset | Set to `/app/media` so backups include uploaded photos and documents. |

---

## 2. Deploy

The deploy unit is the `Dockerfile` in the repository root. It applies
migrations and then starts gunicorn; CI builds it and boots it against a real
database on every push, so if CI is green the image runs.

### Option A — Railway (fastest to a public HTTPS URL)

1. **New Project → Deploy from GitHub repo**, pick `cmms-saas`. Railway detects
   the `Dockerfile` and builds it. No `railway.toml` needed.
2. **Add a PostgreSQL database** to the project. Railway injects `DATABASE_URL`.
3. **Variables** → add every required variable from §1, plus
   `TRUST_PROXY_SSL_HEADER=True`. Leave `PORT` alone; Railway sets it and the
   entrypoint reads it.
4. **Settings → Networking → Generate Domain** (or add your own, §3).
   Set `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` and `SITE_URL` to match, then
   redeploy so they take effect.
5. **Settings → Volumes** → mount a volume at `/app/media`. Skip this and every
   redeploy silently deletes the uploaded photos (see §10).

### Option B — a VPS you control

```bash
git clone https://github.com/Cristhianmancipe96/cmms-saas.git
cd cmms-saas
docker build -t vectron:latest .

# Variables live in a root-owned file, mode 600, OUTSIDE the repository.
sudo install -m 600 /dev/null /etc/vectron.env
sudo nano /etc/vectron.env        # one KEY=value per line, from §1

docker run -d --name vectron --restart unless-stopped \
  --env-file /etc/vectron.env \
  -p 127.0.0.1:8000:8000 \
  -v /srv/vectron/media:/app/media \
  -v /srv/vectron/backups:/app/backups \
  vectron:latest
```

`-p 127.0.0.1:8000:8000` binds to loopback only: the container is reachable
through the reverse proxy and not from the internet directly.

Then put Caddy in front — it obtains and renews the certificate on its own.
`/etc/caddy/Caddyfile`:

```
cmms.midominio.com {
    reverse_proxy 127.0.0.1:8000
}
```

Caddy sets `X-Forwarded-Proto` itself and strips any incoming copy, which is
what makes `TRUST_PROXY_SSL_HEADER=True` safe here.

---

## 3. Domain and HTTPS

1. Point an `A` record (VPS: the server's IP) or a `CNAME` (Railway: the value
   it shows you) at the deployment.
2. Wait for DNS to propagate — `nslookup cmms.midominio.com` should answer.
3. The certificate is automatic on Railway; Caddy issues it on first request.
4. Confirm the padlock in a browser **before** touching HSTS (§9). HSTS makes a
   broken certificate un-bypassable for as long as its window lasts.
5. Update `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` and `SITE_URL` to the final
   domain and redeploy. **Do this before printing any label.**

---

## 4. First boot

Migrations run by themselves in the entrypoint. What is left is the data.

> **Running a one-off command.** Every command from here on is written in its
> VPS form, `docker exec -it vectron <command>`. On Railway, open a shell into
> the container first (`railway ssh`) and then run the command on its own,
> without the prefix.

For a **demo instance** (this is the legitimate use of `--force`: `DEBUG` is
False, and the flag says "yes, I know, this database is meant to hold demo
data"):

```bash
docker exec -it vectron python manage.py seed_demo --force
```

It prints four usernames and their passwords **once**. Copy them now; they are
generated on every run and are stored nowhere. Running the command again is
safe — it creates nothing new and simply renews the passwords.

For a **real company**, do not seed. Create the first administrator instead:

```bash
docker exec -it vectron python manage.py createsuperuser
```

---

## 5. Verify email, end to end

```bash
docker exec -it vectron python manage.py send_test_email --to tucorreo@dominio.com
```

It prints the backend, the server and the sender — never the password — and
either delivers a message or fails with a Spanish diagnosis of which variable
is wrong. Run it **before** the smoke test: the application is fail-safe about
email on purpose, so a broken SMTP configuration produces no error anywhere
else, and step 4 below would just quietly not arrive.

---

## 6. Smoke test — five steps, on the deployed URL

Do this on the real domain, with a phone that is **not** on the office wifi.
Anything that fails here fails for a prospect too.

| # | Step | What proves it worked |
|---|---|---|
| 1 | Open `https://cmms.midominio.com` and log in as `sabana.admin`. | Padlock in the address bar, dashboard with numbers — not dashes. `http://` must bounce to `https://` on its own. |
| 2 | **Equipos → FLW-01 → Etiqueta**. Print the label on paper. | The QR encodes `https://cmms.midominio.com/...`, not `localhost`. Check the printed URL with your eyes before continuing. |
| 3 | Scan that paper with the phone, on mobile data, logged out. Then log in on the phone as `sabana.tecnico` and scan again. | Logged out: only the plate. Logged in: the live record. This is the step the whole deployment exists for. |
| 4 | Open a work order, **Terminar** it, then email the PDF from the report screen. | The message arrives at a real inbox with the PDF attached. Check the spam folder the first time. |
| 5 | Back on the laptop as `sabana.admin`: **Tablero**, then **Auditoría**. | The numbers moved, and every step above is listed with who did it and when. |

The full sales demo — the six-step, five-minute script — is in the README under
*Try it in five minutes*. This is the shorter version that only asks: does the
deployment work.

---

## 7. Confirm the security profile on the instance itself

```bash
docker exec -it vectron python manage.py check --deploy
```

Expected, exactly: `System check identified no issues (0 silenced).`

A warning here means a variable is missing on this instance even though CI is
green — CI checks the profile, this checks the deployment. The same check runs
as a test (`apps/core/tests/test_deploy_profile.py`), so it can only regress
here through configuration.

---

## 8. The daily job

Preventive work orders are created by a command, not by a background worker:

```bash
python manage.py generate_work_orders
```

Run it once a day, early. On Railway: a **Cron Schedule** service in the same
project (`0 10 * * *` UTC = 05:00 in Bogotá) running that command. On a VPS,
the host's crontab:

```bash
0 5 * * * docker exec vectron python manage.py generate_work_orders >> /var/log/vectron-scheduler.log 2>&1
```

It is idempotent — running it twice, or retrying after a crash, creates
nothing new.

---

## 9. Turning HSTS up

HSTS tells browsers to refuse plain HTTP for this domain for N seconds, and
**it cannot be called back**: a browser that received `max-age=31536000` will
refuse the site for a year even if the certificate breaks. So it starts at one
hour and is raised only once HTTPS has been boring for a few days.

`SECURE_HSTS_SECONDS`: `3600` → `86400` → `2592000` → `31536000`. One step at a
time, waiting between them. It applies to subdomains too, so make sure no
subdomain of this domain is still served over plain HTTP.

Only after a year's max-age has been served for a while does submitting the
domain at [hstspreload.org](https://hstspreload.org) make sense.

---

## 10. Backups and restore

### Daily backup

`scripts/backup.sh` takes a compressed `pg_dump` and, if `MEDIA_ROOT_PATH` is
set, a tarball of the uploaded files. It reads the same `DATABASE_URL` the
application uses, so it cannot dump the wrong database by accident.

The image has `/app/backups` ready and owned by the application user. Mount a
volume there (`-v /srv/vectron/backups:/app/backups`) or the dumps disappear
with the container.

```bash
# VPS — 03:15 every day, in the host's crontab:
15 3 * * * docker exec -e MEDIA_ROOT_PATH=/app/media vectron /app/scripts/backup.sh /app/backups >> /var/log/vectron-backup.log 2>&1
```

Keep a copy **off the server**. A backup that lives on the machine it is backing
up is not a backup; `rclone`, `scp` to another host, or the platform's own
snapshot feature all qualify. On a managed database (Railway, Supabase) the
provider already takes daily snapshots — this script is what gives you a copy
they do not control.

Old dumps are pruned after `BACKUP_RETENTION_DAYS` (14 by default).

### Restore — the part that matters

```bash
# 1. See what you have.
ls -lh backups/

# 2. Restore. DESTRUCTIVE: it drops and rebuilds every table in the database
#    DATABASE_URL points at. Read that variable twice before running this.
RESTORE_CONFIRM=si ./scripts/restore.sh backups/vectron-db-20260816-031500.dump

# 3. Uploaded files, if they were backed up too.
tar -xzf backups/vectron-media-20260816-031500.tar.gz -C /srv/vectron/media

# 4. Verify — do not skip this.
docker exec -it vectron python manage.py showmigrations | tail -5
```

`RESTORE_CONFIRM=si` is required on purpose: the difference between "restore
the staging copy" and "wipe production" is one environment variable.

**To rehearse without risk**, point `DATABASE_URL` at an empty scratch database
and restore into that. This is exactly what the `backup-restore` job in
`.github/workflows/ci.yml` does on every push: it seeds a database, dumps it,
destroys the schema, restores it and counts the rows back. If that job is
green, these instructions worked today — not the day someone wrote them.

---

## 11. Logs

Everything goes to stdout: Django's own logs, gunicorn's access log, and the
application's warnings — including "no se pudo entregar el evento a n8n". Read
them with `railway logs` or `docker logs -f vectron`.

Lines are `timestamp LEVEL logger message`. There is no PII and there are no
credentials in them by design, which is what makes a log safe to paste into a
chat when asking for help.

Error tracking (Sentry) is phase 3; the place it will be wired is marked in
`config/settings.py`.

---

## 12. Known limits of this deployment

Honest list. None of these blocks selling with fictional data; all of them
matter before a real customer's data arrives.

1. **Uploads need a volume.** On a platform with an ephemeral filesystem, no
   volume at `/app/media` means every redeploy deletes the photos — and the
   work orders that reference them will show broken images, not an error.
2. **One instance.** Migrations run at container start, so two replicas
   starting at once would race. Scale out only after moving migrations to a
   release step.
3. **The rest of hardening is pending**: login lockout, rate limiting, password
   policy, `pip-audit` in CI, and the Ley 1581 retention/deletion policy. They
   are specified in `docs/briefs/11-security-hardening.md` and are required
   before any real customer data is loaded.
4. **Media is served by Django**, through an authenticated view — correct, and
   slower than a CDN. That is the right trade: the files are tenant data.
5. **No staging environment.** Changes go from a laptop to production. A second
   deployment of the same image with its own database is cheap when it starts
   being worth it.

---

## 13. Rolling back

```bash
# VPS: redeploy the previous image
docker stop vectron && docker rm vectron
docker run -d --name vectron ... vectron:<tag-anterior>
```

On Railway, **Deployments → the previous one → Redeploy**.

A rollback undoes code, **not migrations**. If the release included a migration
that dropped or rewrote data, the previous code will meet a database it does
not recognise, and §10's restore is the real path back. Which is the argument
for taking a backup immediately before any deploy that carries a migration.
