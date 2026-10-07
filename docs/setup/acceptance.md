# Setup: nucky (acceptance)

How the acceptance server is put together, and how to rebuild it from
scratch. For daily use see [Working with: nucky](../working/acceptance.md).

## Overview

| | |
|:--|:--|
| Host | `nucky`, Intel NUC, Debian 13, `ssh root@192.168.2.17` (LAN) |
| Public URL | `https://catachrestic-francoise-indomitably.ngrok-free.dev` (ngrok → port 80) |
| Environment file | `env.nucky.yml`, selected with `BOOST_UNION_ENV=env.nucky.yml` |
| Branch | `production` of both repositories (cloned over HTTPS, read-only) |
| Server config in git | [`deploy/nucky/`](https://github.com/bmbrands/theme_boost_union_test_envs/tree/production/deploy/nucky) |

```
Internet ──► ngrok (screen session) ──► nginx :80 ─┬─ /                → /var/www/html → frontend/dist
                                                   ├─ /api, /docs      → uvicorn 127.0.0.1:8000
                                                   └─ /<env>/<ver>/    → Moodle container 127.0.0.1:<port>
```

## Layout

```
/opt/boost-union-envs/
├── backend/            git clone theme_boost_union_test_envs (production)
│   ├── deploy/nucky/   deploy.sh, systemd unit, cron, MailHog compose
│   └── example_pwd/    working directory (live state, not in git)
├── frontend/           git clone moodle-provisioner-frontend (production)
│   └── dist/           built SPA (rebuilt on every deploy)
├── venv/               Python virtualenv used by the service and cron
├── deploy.sh           → symlink to backend/deploy/nucky/deploy.sh
└── state-backup/       manual backups (old deploy.sh, old config.yml, …)
```

## Services

| Service | How it runs | Starts at boot |
|:--|:--|:--|
| `boost-union-api` | systemd, `/etc/systemd/system/boost-union-api.service` (from `deploy/nucky/`), uvicorn on `127.0.0.1:8000`, runs as root | yes |
| `nginx` | Debian package; vhost `/etc/nginx/sites-enabled/boost-union` | yes |
| `docker` | Docker CE (official repo) | yes |
| `cron` | reaper every 15 min via `/etc/cron.d/boost-union-reap` (from `deploy/nucky/`) | yes |
| MailHog | Docker container `mailhog` (from `deploy/nucky/mailhog/`), SMTP `127.0.0.1:1025`, UI `http://192.168.2.17:8025` | yes (`restart: unless-stopped`) |
| ngrok | `ngrok http 80`, started by hand in a `screen` session | **no** |

## Files outside `/opt`

| Path | Content | Managed by |
|:--|:--|:--|
| `/etc/systemd/system/boost-union-api.service` | API unit; sets `BOOST_UNION_ENV=env.nucky.yml` | `deploy.sh` (copied from the repo when changed) |
| `/etc/cron.d/boost-union-reap` | reaper schedule | `deploy.sh` |
| `/etc/boost-union-api.env` | secrets: `SESSION_SECRET`, `SESSION_COOKIE_SECURE`, `BOOTSTRAP_ADMIN_*` | by hand, `chmod 600`; template `deploy/nucky/boost-union-api.env.example` |
| `/etc/nginx/sites-enabled/boost-union` | → `example_pwd/.nginx/192.168.2.25.conf` (outer vhost rendered from `nucky_production_nginx.conf`; the file name dates from an earlier IP) | the app (rendered by `init`) |
| `/etc/nginx/conf.d/boost-union/testenvs` | → `example_pwd/.nginx/testenvs/` (one `.conf` per Moodle instance) | the app |
| `/var/www/html` | → `/opt/boost-union-envs/frontend/dist` | symlink, once |
| `/var/log/boost-union-reap.log` | reaper output | cron |

## Rebuild from scratch

On a fresh Debian 13 host, as root.

### 1. Packages and Docker

```bash
apt-get update
apt-get install -y ca-certificates curl gnupg git python3 python3-venv python3-pip nodejs npm nginx screen

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian ${VERSION_CODENAME} stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl disable --now apache2 2>/dev/null || true     # nginx owns port 80
```

### 2. Code and Python

```bash
mkdir -p /opt/boost-union-envs && cd /opt/boost-union-envs
git clone --branch production https://github.com/bmbrands/theme_boost_union_test_envs.git backend
git clone --branch production https://github.com/bmbrands/moodle-provisioner-frontend.git frontend

python3 -m venv venv
./venv/bin/pip install --upgrade pip wheel
./venv/bin/pip install docker fire gitpython loguru dependency-injector pyyaml \
    rich requests mergedeep jinja2 bcrypt itsdangerous fastapi 'uvicorn[standard]' httpx

ln -s /opt/boost-union-envs/backend/deploy/nucky/deploy.sh /opt/boost-union-envs/deploy.sh
```

Check `base_url` in `backend/env.nucky.yml`: it must be the public host name
(the ngrok domain), without scheme.

### 3. Secrets

```bash
cp backend/deploy/nucky/boost-union-api.env.example /etc/boost-union-api.env
chmod 600 /etc/boost-union-api.env
vi /etc/boost-union-api.env          # SESSION_SECRET=$(openssl rand -hex 32), admin email/password
```

### 4. Working directory and nginx

```bash
cd /opt/boost-union-envs/backend
BOOST_UNION_ENV=env.nucky.yml /opt/boost-union-envs/venv/bin/python -m theme_boost_union_test_envs init
ls example_pwd/.nginx/                       # <base_url>.conf  testenvs/

mkdir -p /etc/nginx/conf.d/boost-union
ln -snf /opt/boost-union-envs/backend/example_pwd/.nginx/testenvs /etc/nginx/conf.d/boost-union/testenvs
ln -snf /opt/boost-union-envs/backend/example_pwd/.nginx/<base_url>.conf /etc/nginx/sites-enabled/boost-union
rm -f /etc/nginx/sites-enabled/default
ln -snf /opt/boost-union-envs/frontend/dist /var/www/html
nginx -t && systemctl enable --now nginx
```

### 5. Deploy (installs the service and cron, builds the frontend)

```bash
/opt/boost-union-envs/deploy.sh all
systemctl enable boost-union-api
```

On first start the API creates the admin from `BOOTSTRAP_ADMIN_*` (see
[Authentication](../reference/authentication.md)).

### 6. MailHog and ngrok

```bash
cd /opt/boost-union-envs/backend
docker compose -f deploy/nucky/mailhog/docker-compose.yml up -d

screen -S ngrok
ngrok http 80          # with the reserved domain configured in ngrok's config; detach with Ctrl-A D
```

### 7. Verify

```bash
curl -s -o /dev/null -w 'frontend %{http_code}\n' http://localhost/
curl -s -o /dev/null -w 'api      %{http_code}\n' http://localhost/api/auth/me   # 401 = API up, not logged in
BOOST_UNION_ENV=env.nucky.yml /opt/boost-union-envs/venv/bin/python scripts/reap_instances.py --dry-run
```

Then sign in on the public URL, configure **Admin Settings → Lifecycle** and
**Email** (MailHog: `127.0.0.1:1025`, security *None*).

## Background

The original deployment (Apache first, then nginx; the path-based proxy
details) is recorded in the [nucky deploy log](../archive/nucky-deploy-log.md).
