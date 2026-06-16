# Server install guide (Debian 13)

Install the Boost Union test environments stack on a fresh Debian 13 host.
You are expected to be **logged in on the target server as `root`** (or via
`sudo -i`). All commands below are intended to be run **on the server
itself**.

The end result of this guide is:

- nginx on port 80 serving the React SPA, the FastAPI backend, and every
  Moodle test environment as `http://<host>/<infra>/<version>/`.
- A `boost-union-api` systemd unit running uvicorn on `127.0.0.1:8000`.
- Docker CE for the per-Moodle compose stacks.

The screenshots / examples use the host nucky (`192.168.2.25`); replace that
value with your own host or IP.

---

## 1. Prerequisites

- Fresh Debian 13 (Trixie) install, root shell.
- Outbound HTTPS to GitHub, the Docker apt repo, npm and Debian mirrors.
- Inbound TCP/80 reachable from your client (LAN or via reverse tunnel).

```bash
uname -a
cat /etc/debian_version          # 13.x
whoami                           # root
```

---

## 2. Base packages

```bash
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    ca-certificates curl gnupg rsync git \
    python3 python3-venv python3-pip \
    nodejs npm \
    nginx
```

Verify:

```bash
python3 --version          # 3.11+
node --version             # v20.x
npm --version              # 9.x or newer
nginx -v
```

---

## 3. Install Docker CE (official repo)

```bash
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg \
     -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/debian ${VERSION_CODENAME} stable" \
  > /etc/apt/sources.list.d/docker.list

apt-get update -qq
apt-get install -y -qq \
    docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin

docker --version
docker compose version
systemctl is-active docker          # active
```

---

## 4. Clone the backend

The backend is the Python FastAPI app on branch `feature/fastapi`.

```bash
mkdir -p /opt/boost-union-envs
cd /opt/boost-union-envs

git clone --branch feature/fastapi --depth 1 \
    https://github.com/bmbrands/theme_boost_union_test_envs.git backend

cd backend
# Per-host settings live in env.nucky.yml; keep it editable but ignored:
git update-index --skip-worktree env.nucky.yml 2>/dev/null || true
# Live testbed state managed by the app itself:
echo /example_pwd/ >> .git/info/exclude
```

### 4.1 Configure the host environment

Edit [`env.nucky.yml`](../env.nucky.yml) and set `base_url` to your host
or IP (or rename the file to match your host and update the reference in
`config.yml`). Minimum content for an HTTP-only LAN/ngrok deployment:

```yaml
working_dir: "./example_pwd"
proxied: yes
nginx:
  base_url: "192.168.2.25"
  scheme: "http"
  template: "nucky_production_nginx.conf"
  cert_chain_path: ""
  cert_key_path: ""
  overview_page_path: "/"
  softlinked_nginx_config_path: ""
```

Then point [`config.yml`](../config.yml) at it:

```bash
sed -i 's|^environment:.*|environment: "env.nucky.yml"|' \
    /opt/boost-union-envs/backend/config.yml
```

---

## 5. Clone and build the frontend

```bash
cd /opt/boost-union-envs

git clone --branch dev --depth 1 \
    https://github.com/bmbrands/moodle-provisioner-frontend.git frontend

cd frontend
npm install --no-audit --no-fund
npx vite build                # emits dist/

# nginx serves the SPA from /var/www/html:
ln -snf /opt/boost-union-envs/frontend/dist /var/www/html
```

---

## 6. Python virtualenv + backend dependencies

`pyproject.toml` is Poetry-based, but Poetry is not required at runtime —
the backend's transitive deps install fine with plain `pip` into a venv:

```bash
cd /opt/boost-union-envs
python3 -m venv venv
./venv/bin/pip install --upgrade pip wheel -q
./venv/bin/pip install -q \
    docker fire gitpython loguru dependency-injector pyyaml \
    rich requests mergedeep jinja2 \
    fastapi 'uvicorn[standard]' httpx \
    bcrypt itsdangerous
```

> `bcrypt` and `itsdangerous` are required by the authentication layer
> (password hashing and signed session cookies). If you upgrade an existing
> deployment that predates auth, install them into the venv and restart:
> `/opt/boost-union-envs/venv/bin/pip install bcrypt itsdangerous && systemctl restart boost-union-api`.

Smoke-test the import:

```bash
cd /opt/boost-union-envs/backend
/opt/boost-union-envs/venv/bin/python \
    -c 'from theme_boost_union_test_envs.ui.api.server import app; print(app.title)'
# -> Boost Union Test Environments API
```

---

## 7. systemd unit for the FastAPI backend

```bash
cat >/etc/systemd/system/boost-union-api.service <<'EOF'
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
EOF

systemctl daemon-reload
systemctl enable --now boost-union-api
systemctl is-active boost-union-api    # active

# Loopback smoke-test:
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/api/infrastructures
# -> 200
```

The backend binds to `127.0.0.1` only; outside access goes through nginx.

---

## 8. Render the outer nginx vhost

The vhost is rendered from
[`templates/nucky_production_nginx.conf`](../theme_boost_union_test_envs/cross_cutting/templates/nucky_production_nginx.conf)
by the application:

```bash
cd /opt/boost-union-envs/backend
/opt/boost-union-envs/venv/bin/python - <<'PY'
from theme_boost_union_test_envs.app import bootstrap
container = bootstrap()
container.template_engine().overview_nginx_config()
PY
ls example_pwd/.nginx/         # -> 192.168.2.25.conf  testenvs/
```

> If `bootstrap()` is not exposed in your build, you can call
> `TemplateEngine.overview_nginx_config()` from the running backend by
> creating one infrastructure via the API — that triggers the same render.

---

## 9. Wire nginx

```bash
mkdir -p /etc/nginx/conf.d/boost-union

# Per-Moodle proxy snippets (the app writes one .conf per env in here):
ln -snf /opt/boost-union-envs/backend/example_pwd/.nginx/testenvs \
        /etc/nginx/conf.d/boost-union/testenvs

# Outer vhost:
ln -snf /opt/boost-union-envs/backend/example_pwd/.nginx/<host>.conf \
        /etc/nginx/sites-enabled/boost-union
#   replace <host> with the file actually rendered, e.g. 192.168.2.25.conf

rm -f /etc/nginx/sites-enabled/default
nginx -t                                 # syntax: ok
systemctl enable --now nginx
systemctl reload nginx
```

If Apache is installed, disable it (it would fight nginx for port 80):

```bash
systemctl disable --now apache2 2>/dev/null || true
```

---

## 10. Permissions for nginx reload

The backend reloads nginx after writing per-env snippets, by calling
`systemctl reload nginx` (with `nginx -s reload` as fallback). Because the
service runs as `root` this just works. If you later switch the unit to a
non-root user, grant that user passwordless sudo for the reload command, or
use a polkit rule.

---

## 11. End-to-end verification

```bash
# Frontend
curl -s -o /dev/null -w 'frontend: %{http_code}\n' http://localhost/

# API
curl -s -o /dev/null -w 'api:      %{http_code}\n' http://localhost/api/infrastructures

# Swagger UI
curl -s -o /dev/null -w 'docs:     %{http_code}\n' http://localhost/docs
```

All three should return `200`.

### Create a real Moodle env to confirm the path-based proxy works

```bash
# 1. Create
curl -sS -X POST http://localhost/api/infrastructures \
  -H 'content-type: application/json' \
  -d '{"name":"smoke","git_ref":"MOODLE_501_STABLE",
       "git_ref_type":"branch","moodle_versions":["5.1.4"]}'

# 2. Start it
curl -sS -X POST http://localhost/api/infrastructures/smoke/5.1.4/start

# 3. Verify the env vars inside the container:
docker exec smoke-5_1_4-webserver-1 sh -c \
  'echo HOST=$MOODLE_DOCKER_WEB_HOST PORT="$MOODLE_DOCKER_WEB_PORT"'
# -> HOST=<host>/smoke/5.1.4 PORT=          (PORT must be empty!)

# 4. Reach Moodle through nginx (no port in URL):
curl -sS -o /dev/null -w '%{http_code} -> %{redirect_url}\n' \
  http://localhost/smoke/5.1.4/
# -> 200 ->        (Moodle install page; no redirect)
```

---

## 12. Optional: expose to the internet via ngrok

Because everything is on port 80, a single tunnel is sufficient:

```bash
ngrok http 80
```

The ngrok URL covers the SPA, the API, the Swagger UI **and** all Moodle
environments — there are no hardcoded ports anywhere in the public URLs.

---

## 13. Day-to-day operations

- Restart backend after code changes:
  ```bash
  systemctl restart boost-union-api
  ```
- Tail backend logs:
  ```bash
  journalctl -u boost-union-api -f -n 100
  ```
- Re-deploy from git:
  ```bash
  /opt/boost-union-envs/deploy.sh           # both backend and frontend
  /opt/boost-union-envs/deploy.sh backend   # only API
  /opt/boost-union-envs/deploy.sh frontend  # only SPA
  ```
  The script does `git pull --ff-only`, restarts `boost-union-api`, and
  re-runs `npx vite build` for the frontend. If `pyproject.toml` changed
  it reinstalls the pip deps into `/opt/boost-union-envs/venv`.

---

## 14. Where things live

| Path | Purpose |
|:-----|:--------|
| `/opt/boost-union-envs/backend` | Python backend git clone (`feature/fastapi`) |
| `/opt/boost-union-envs/frontend` | Frontend git clone (`dev`); built `dist/` is symlinked into `/var/www/html` |
| `/opt/boost-union-envs/venv` | Python virtualenv |
| `/opt/boost-union-envs/backend/example_pwd/` | Live testbed state (not in git) |
| `/opt/boost-union-envs/backend/example_pwd/.nginx/` | Rendered nginx configs (outer vhost + per-env snippets) |
| `/var/www/html` | Symlink → `frontend/dist` |
| `/etc/systemd/system/boost-union-api.service` | uvicorn unit |
| `/etc/nginx/sites-enabled/boost-union` | Symlink → rendered outer vhost |
| `/etc/nginx/conf.d/boost-union/testenvs` | Symlink → per-Moodle proxy snippets |

---

## See also

- [serverlog.md](serverlog.md) — narrative log of the original nucky deploy,
  with rationale and section 10 covering the path-based reverse proxy
  internals.
- [request-flow-nl.md](request-flow-nl.md) — Dutch walk-through of how a
  single request flows through nginx → Apache → Moodle.
- [installation.md](installation.md) — local-dev install (macOS / Linux).
