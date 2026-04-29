# Server Deployment Log — nucky (192.168.2.25)

Target: Debian 13 (`nucky`), accessed as `root@192.168.2.25` over SSH (key-based,
no password).
Goal: Run the Python FastAPI backend (branch `feature/fastapi`) and serve the
React frontend (branch `dev`) via the system Apache on port 80.

## Layout on the server

| Path | Purpose |
|:-----|:--------|
| `/opt/boost-union-envs/backend` | Python backend `git clone` of branch `feature/fastapi` |
| `/opt/boost-union-envs/frontend` | Frontend `git clone` of branch `dev` (built in place; `dist/` served by Apache) |
| `/opt/boost-union-envs/venv` | Python virtualenv (system Python 3.13) |
| `/opt/boost-union-envs/deploy.sh` | Helper: `git pull` + restart for `backend` / `frontend` / `all` |
| `/var/www/html` | Symlink → `/opt/boost-union-envs/frontend/dist` |
| `/etc/systemd/system/boost-union-api.service` | systemd unit for `uvicorn` |
| `/etc/nginx/sites-enabled/boost-union` | Symlink → rendered vhost (`example_pwd/.nginx/192.168.2.25.conf`) |
| `/etc/nginx/conf.d/boost-union/testenvs` | Symlink → per-Moodle proxy snippets (`example_pwd/.nginx/testenvs/`) |

Apache listens on port 80, serves the SPA from `/var/www/html`, falls back to
`index.html` for client-side routes, and reverse-proxies `/api/`, `/docs` and
`/openapi.json` to `http://127.0.0.1:8000` where uvicorn runs the FastAPI app
`theme_boost_union_test_envs.ui.api.server:app`.

> **Note (cutover):** the host webserver is now **nginx**, configured for the
> single-port "nucky" layout described in section 8 below. Apache is still
> installed but disabled. The nginx setup is what makes it possible to
> publish the entire stack through a single ngrok tunnel.

## End URLs

- Frontend SPA: <http://192.168.2.25/>
- API: <http://192.168.2.25/api/infrastructures>
- Swagger UI: <http://192.168.2.25/docs>

---

## 1. Connectivity check

```bash
ssh -o StrictHostKeyChecking=accept-new root@192.168.2.25 \
    "uname -a && cat /etc/debian_version && whoami"
# -> Linux nucky 6.12.74+deb13+1-amd64 ... Debian 13.4, user: root
```

## 2. Install base system packages

```bash
ssh root@192.168.2.25 "set -e; export DEBIAN_FRONTEND=noninteractive; \
    apt-get update -qq && \
    apt-get install -y -qq ca-certificates curl gnupg rsync apache2 \
                            python3 python3-venv python3-pip git"

ssh root@192.168.2.25 "python3 --version && which apache2 && which rsync && which git"
# Python 3.13.5
# /usr/sbin/apache2  /usr/bin/rsync  /usr/bin/git
```

## 3. Install Docker CE (official Docker apt repository)

```bash
ssh root@192.168.2.25 'set -e
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg \
     -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/debian ${VERSION_CODENAME} stable" \
  > /etc/apt/sources.list.d/docker.list
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
                       docker-buildx-plugin docker-compose-plugin'

ssh root@192.168.2.25 "docker --version && docker compose version && systemctl is-active docker"
# Docker version 29.4.1
# Docker Compose version v5.1.3
# active
```

## 4. Clone the backend from GitHub

The backend is a `git clone` of <https://github.com/bmbrands/theme_boost_union_test_envs>
branch `feature/fastapi`. The repo is public, so HTTPS clone needs no auth on
the server (no SSH deploy key required).

```bash
ssh root@192.168.2.25 "set -e
mkdir -p /opt/boost-union-envs
git clone --branch feature/fastapi --depth 1 \
    https://github.com/bmbrands/theme_boost_union_test_envs.git \
    /opt/boost-union-envs/backend

# Runtime files that must not be tracked by the working tree:
cd /opt/boost-union-envs/backend
# env.local.yml is committed, but holds host-specific values on the server
# (base_url: 192.168.2.25). Tell git to keep the local copy:
git update-index --skip-worktree env.local.yml
# example_pwd/ contains live testbed state managed by the app itself:
echo /example_pwd/ >> .git/info/exclude"
```

Then edit `env.local.yml` on the server and set `base_url: "192.168.2.25"` so
the API hands out reachable URLs to LAN clients.

## 5. Clone and build the frontend on the server

The frontend is also a `git clone` and is built directly on `nucky` so the
deploy flow is uniform (`git pull && build`). Node 20 / npm 9 are available
from Debian 13 apt:

```bash
ssh root@192.168.2.25 "set -e
apt-get install -y -qq nodejs npm
git clone --branch dev --depth 1 \
    https://github.com/bmbrands/moodle-provisioner-frontend.git \
    /opt/boost-union-envs/frontend
cd /opt/boost-union-envs/frontend
npm install --no-audit --no-fund
npx vite build              # produces dist/  (skips strict tsc --noEmit step)

# Apache docroot is a symlink to the freshly-built dist/:
ln -snf /opt/boost-union-envs/frontend/dist /var/www/html"
```

## 6. Create Python virtualenv and install backend dependencies

The `pyproject.toml` is Poetry-based, but Poetry is not installed on the
server. The runtime dependencies needed for the FastAPI backend are installed
directly with `pip` into a system-Python virtualenv:

```bash
ssh root@192.168.2.25 "set -e
cd /opt/boost-union-envs
python3 -m venv venv
./venv/bin/pip install --upgrade pip wheel -q
./venv/bin/pip install -q \
    docker fire gitpython loguru dependency-injector pyyaml \
    rich requests mergedeep jinja2 \
    fastapi 'uvicorn[standard]' httpx"
```

Verify the FastAPI app imports cleanly:

```bash
ssh root@192.168.2.25 "cd /opt/boost-union-envs/backend && \
    /opt/boost-union-envs/venv/bin/python \
    -c 'from theme_boost_union_test_envs.ui.api.server import app; print(app.title)'"
# -> Boost Union Test Environments API
```

## 7. systemd unit for the FastAPI backend

`/etc/systemd/system/boost-union-api.service`:

```ini
[Unit]
Description=Boost Union Test Environments FastAPI backend
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/boost-union-envs/backend
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/boost-union-envs/venv/bin/uvicorn theme_boost_union_test_envs.ui.api.server:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
ssh root@192.168.2.25 'systemctl daemon-reload && \
    systemctl enable --now boost-union-api && \
    systemctl is-active boost-union-api'
# -> active

# Smoke-test directly against uvicorn (loopback only):
ssh root@192.168.2.25 'curl -sS -o /dev/null -w "%{http_code}\n" \
    http://127.0.0.1:8000/api/infrastructures'
# -> 200
```

The backend binds to `127.0.0.1` only — it is reachable from the outside
exclusively through the Apache reverse proxy.

## 8. Front-end webserver — nginx (single-port "nucky" layout)

The host webserver is **nginx** (Debian package). Apache is left installed
but disabled. nginx terminates HTTP on port 80 and is the single entry-point
that ngrok can be pointed at. Three things are reverse-proxied through it:

| URL prefix | Backend | Source |
|:-----------|:--------|:-------|
| `/`              | React SPA at `/var/www/html` | symlink → `/opt/boost-union-envs/frontend/dist` |
| `/api/`, `/docs`, `/openapi.json` | FastAPI on `127.0.0.1:8000` | `boost-union-api.service` |
| `/<infra>/<ver>/` | per-Moodle docker container | rendered into `example_pwd/.nginx/testenvs/<infra>-<ver>.conf` by `TemplateEngine.moodle_nginx_config` |

The outer vhost is rendered from
[`theme_boost_union_test_envs/cross_cutting/templates/nucky_production_nginx.conf`](../theme_boost_union_test_envs/cross_cutting/templates/nucky_production_nginx.conf)
by `TemplateEngine.overview_nginx_config()`. The template is selected via
`nginx.template: "nucky_production_nginx.conf"` in [env.nucky.yml](../env.nucky.yml).

```bash
ssh root@192.168.2.25 'apt-get install -y -qq nginx'

# Switch backend to env.nucky.yml so URLs become path-based (no port):
ssh root@192.168.2.25 \
  'sed -i "s|^environment:.*|environment: \"env.nucky.yml\"|" \
   /opt/boost-union-envs/backend/config.yml'

# Render the outer vhost into ./example_pwd/.nginx/192.168.2.25.conf:
scp /tmp/render_outer_nginx.py \
    root@192.168.2.25:/opt/boost-union-envs/backend/
ssh root@192.168.2.25 \
  'cd /opt/boost-union-envs/backend && \
   /opt/boost-union-envs/venv/bin/python render_outer_nginx.py && \
   rm render_outer_nginx.py'
```

Wire it into nginx (the include path inside the rendered vhost is
`/etc/nginx/conf.d/boost-union/testenvs/*.conf` — provided by symlink):

```bash
ssh root@192.168.2.25 "set -e
mkdir -p /etc/nginx/conf.d/boost-union
ln -snf /opt/boost-union-envs/backend/example_pwd/.nginx/testenvs \
        /etc/nginx/conf.d/boost-union/testenvs
ln -snf /opt/boost-union-envs/backend/example_pwd/.nginx/192.168.2.25.conf \
        /etc/nginx/sites-enabled/boost-union
rm -f /etc/nginx/sites-enabled/default
nginx -t

# Cutover apache -> nginx
systemctl disable --now apache2
systemctl enable  --now nginx
systemctl restart boost-union-api"
```

The rendered vhost serves the SPA, proxies `/api/` to FastAPI, and (via
`include "/etc/nginx/conf.d/boost-union/testenvs/*.conf";`) picks up every
per-Moodle `.conf` snippet that the Python app writes when a new Moodle
environment is created. Newly-created Moodles are reachable as
`http://192.168.2.25/<infra>/<version>/` — no port number.

> **Existing infrastructures**: `nucky-one` was created under
> `env.local.yml` (proxied=no), so its container's `wwwroot` still contains
> the explicit port (`http://192.168.2.25:47833/`). To migrate it to the
> path-based URL it must be re-created after the env switch.

### Optional: expose to the internet via ngrok

Because everything is on port 80, a single tunnel is enough:

```bash
ssh root@192.168.2.25 'ngrok http 80'
```

The ngrok URL works for the SPA, the API, the Swagger UI **and** any new
Moodle environments — all through the one nginx entry point.

## 8b. (legacy) Apache vhost

Required modules:

```bash
ssh root@192.168.2.25 'a2enmod proxy proxy_http headers rewrite'
```

`/etc/apache2/sites-available/boost-union.conf`:

```apache
<VirtualHost *:80>
    ServerName nucky
    DocumentRoot /var/www/html

    <Directory /var/www/html>
        Options -Indexes +FollowSymLinks
        AllowOverride None
        Require all granted

        # SPA fallback: serve index.html for any path that is not a real file
        RewriteEngine On
        RewriteCond %{REQUEST_URI} !^/api(/|$)
        RewriteCond %{REQUEST_FILENAME} !-f
        RewriteCond %{REQUEST_FILENAME} !-d
        RewriteRule ^ /index.html [L]
    </Directory>

    # Reverse proxy to FastAPI / uvicorn on localhost:8000
    ProxyPreserveHost On
    ProxyRequests Off
    ProxyPass        /api/  http://127.0.0.1:8000/api/
    ProxyPassReverse /api/  http://127.0.0.1:8000/api/
    ProxyPass        /docs  http://127.0.0.1:8000/docs
    ProxyPassReverse /docs  http://127.0.0.1:8000/docs
    ProxyPass        /openapi.json http://127.0.0.1:8000/openapi.json
    ProxyPassReverse /openapi.json http://127.0.0.1:8000/openapi.json

    ProxyTimeout 600

    ErrorLog ${APACHE_LOG_DIR}/boost-union-error.log
    CustomLog ${APACHE_LOG_DIR}/boost-union-access.log combined
</VirtualHost>
```

Activate and reload:

```bash
# Config file shipped via scp from the dev machine (heredoc-over-ssh
# corrupts indentation — always scp Apache configs):
scp /tmp/boost-union.conf \
    root@192.168.2.25:/etc/apache2/sites-available/boost-union.conf

ssh root@192.168.2.25 'a2dissite 000-default >/dev/null 2>&1; \
    a2ensite boost-union >/dev/null && \
    apache2ctl configtest && \
    systemctl reload apache2'
# -> Syntax OK
```

## 9. End-to-end verification

```bash
curl -s -o /dev/null -w "frontend: %{http_code}\n" http://192.168.2.25/
# frontend: 200

curl -s -o /dev/null -w "api: %{http_code}\n"      http://192.168.2.25/api/infrastructures
# api: 200

curl -s -o /dev/null -w "docs: %{http_code}\n"     http://192.168.2.25/docs
# docs: 200

curl -s http://192.168.2.25/api/infrastructures | head -c 200
# {"infrastructures":[{"name":"testme","git_ref_type":"BRANCH", ...}
```

The React app is now live at <http://192.168.2.25/>, talks to FastAPI through
the same origin (no CORS issues), and the Swagger UI is reachable at
<http://192.168.2.25/docs>.

---

## Operational notes

- Restart backend after code changes:
  ```bash
  ssh root@192.168.2.25 'systemctl restart boost-union-api'
  ```
- Tail backend logs:
  ```bash
  ssh root@192.168.2.25 'journalctl -u boost-union-api -f -n 100'
  ```
- Re-deploy from git (run on the server):
  ```bash
  ssh root@192.168.2.25 '/opt/boost-union-envs/deploy.sh'           # both
  ssh root@192.168.2.25 '/opt/boost-union-envs/deploy.sh backend'   # only api
  ssh root@192.168.2.25 '/opt/boost-union-envs/deploy.sh frontend'  # only spa
  ```
  The script does `git pull --ff-only`, restarts `boost-union-api`, and
  re-runs `npx vite build` for the frontend. If `pyproject.toml` changed it
  reinstalls the pip deps into `/opt/boost-union-envs/venv`.
- The backend `WorkingDirectory` is `/opt/boost-union-envs/backend`, and the
  testbed working dir from `env.local.yml` (`./example_pwd`) is therefore
  `/opt/boost-union-envs/backend/example_pwd`. The systemd unit runs as
  `root`, which has access to the Docker socket.

---

## 10. Path-based reverse proxy for Moodle envs (the gory bits)

When the deployment is proxied (`proxied: yes`), each Moodle environment is
served at `http(s)://<base_url>/<infra>/<version>/`. Three pieces have to
agree on that prefix or Moodle will redirect off the path and the request
will fall through to the SPA.

### 10.1 nginx — forward the prefix unchanged

[`templates/moodle_nginx.conf`](../theme_boost_union_test_envs/cross_cutting/templates/moodle_nginx.conf):

```nginx
location /<infra>/<version> {
    # NO trailing slash — forward the original URI as-is so Moodle's
    # $CFG->wwwroot path check (lib/setuplib.php) sees the prefix.
    proxy_pass http://127.0.0.1:<host_port>;
    proxy_set_header Host $http_host;
    ...
}
```

A trailing slash on `proxy_pass` would strip the `/<infra>/<version>` prefix
before forwarding, Moodle would detect a wwwroot mismatch and 303 to the
bare host, which then matches the SPA fallback.

### 10.2 Apache (inside the container) — Alias the prefix to the docroot

The Moodle container's Apache `DocumentRoot` is the bare `/var/www/html` (or
`/var/www/html/public` for Moodle 5.1+). Without help, `/foo/5.1.4/...` 404s.
A small Alias snippet is rendered per-env from
[`templates/apache-prefix.conf`](../theme_boost_union_test_envs/cross_cutting/templates/apache-prefix.conf)
and bind-mounted into the container as
`/etc/apache2/conf-enabled/moodle-prefix.conf`:

```apache
Alias /<infra>/<version> /var/www/html/public
<Directory /var/www/html/public>
    Options FollowSymLinks
    AllowOverride All
    Require all granted
</Directory>
```

### 10.3 Moodle wwwroot — strip the bound port

`config.docker-template.php` builds:

```php
$CFG->wwwroot = "http://" . MOODLE_DOCKER_WEB_HOST
              . (MOODLE_DOCKER_WEB_PORT ? ":" . MOODLE_DOCKER_WEB_PORT : "");
```

For the path-based layout `MOODLE_DOCKER_WEB_HOST` already contains the
prefix (`192.168.2.25/<infra>/<version>`) and there is no port in the
public URL. We override `MOODLE_DOCKER_WEB_PORT=""` at runtime via the env
section of the per-env `local.yml` so the port branch is skipped. The
**compose-time** `${MOODLE_DOCKER_WEB_PORT}` from `.env` (used to bind
`<host_port>:80`) is unaffected because it is resolved before the override
takes effect.

### 10.4 Code wiring

All three pieces are emitted by
[`TemplateEngine.docker_customisation`](../theme_boost_union_test_envs/cross_cutting/template_engine.py)
when `config().is_proxied` is true:

- writes `apache-prefix.conf` into the per-env directory,
- expands `$REPLACE_PROXY_OVERRIDES` in
  [`templates/local.yml`](../theme_boost_union_test_envs/cross_cutting/templates/local.yml)
  with the bind-mount + `MOODLE_DOCKER_WEB_PORT: ""` override.

`Template.safe_substitute` is used (not `substitute`) so any stray
`$tokens` in YAML comments don't blow up the build.

After writing a per-env nginx conf, `_reload_nginx_if_available()` runs
`systemctl reload nginx` (with `nginx -s reload` fallback) so newly written
include-globs become active without manual intervention.

### 10.5 Bind on 0.0.0.0, strip bind-ip from URLs

`environment_file()` sets `MOODLE_DOCKER_WEB_PORT="0.0.0.0:<freeport>"`
(otherwise moodle-docker-compose prepends `127.0.0.1:` and the container
isn't reachable from the LAN). When the API surfaces a URL,
`TestContainer.get_access_info()` strips the `bind_ip:` prefix so users
never see `0.0.0.0:`.

### 10.6 New config keys (env.nucky.yml)

Added in [`configuration.py`](../theme_boost_union_test_envs/cross_cutting/configuration.py):

| Key | Default | Notes |
|:----|:--------|:------|
| `nginx.template`         | `plesk_production_nginx.conf` | Selects the outer-vhost template. `nucky` uses [`nucky_production_nginx.conf`](../theme_boost_union_test_envs/cross_cutting/templates/nucky_production_nginx.conf). |
| `nginx.scheme`           | `https`                       | Stored in Moodle URLs. Set to `http` for nucky (no TLS in nginx). |
| `cert_chain_path` / `cert_key_path` | (still required by parser, may be empty) | Validation relaxed: only `overview_page_path` is required when proxied. |

The active config on the server is [`env.nucky.yml`](../env.nucky.yml)
(selected via `environment: env.nucky.yml` in
[`config.yml`](../config.yml)).

### 10.7 Smoke test for a fresh env

```bash
# create
curl -sS -X POST http://192.168.2.25/api/infrastructures \
  -H 'content-type: application/json' \
  -d '{"name":"mont-test","git_ref":"MOODLE_501_STABLE",
       "git_ref_type":"branch","moodle_versions":["5.1.4"]}'

# start
curl -sS -X POST http://192.168.2.25/api/infrastructures/mont-test/5.1.4/start

# verify
ssh root@192.168.2.25 \
  "docker exec mont-test-5_1_4-webserver-1 sh -c \
   'echo HOST=\$MOODLE_DOCKER_WEB_HOST PORT=\"\$MOODLE_DOCKER_WEB_PORT\"'"
# -> HOST=192.168.2.25/mont-test/5.1.4 PORT=

curl -sS -o /dev/null -w '%{http_code} -> %{redirect_url}\n' \
  http://192.168.2.25/mont-test/5.1.4/
# -> 200 ->         (Moodle install page; no redirect)
```

