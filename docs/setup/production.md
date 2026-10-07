# Setup: Plesk (production)

How the production server is put together. For daily use see
[Working with: Plesk](../working/production.md).

!!! warning "Verify against the server"
    This page is compiled from the original Plesk installation notes and the
    server's shell history; it has not been re-checked on the server since.
    Items marked **(verify)** should be confirmed and this page corrected.
    Unlike nucky, the production server configuration is **not yet in git**
    (there is no `deploy/plesk/`).

## Overview

| | |
|:--|:--|
| Public URL | `https://testsystem.moodle-an-hochschulen.de` |
| Server | Plesk Obsidian on Ubuntu 22.04 (Python 3.10) |
| Plesk subscription | `focused-cray.92-205-184-244.plesk.page`, alias `testsystem.moodle-an-hochschulen.de`; bound to `92.205.184.244` and `2a00:1169:116:8290::` |
| Environment file | `env.prod.yml`, selected in `config.yml` on the server (local edit) |
| TLS | Let's Encrypt, managed by Plesk |
| Operator user | `boost-union-testing` (group `psacln`), owns the checkouts |

```
Internet ──► Plesk nginx :443 (testsystem vhost) ─┬─ /                 → site1/ (copy of frontend/dist)
                                                  ├─ /api              → uvicorn 127.0.0.1:8000  (additional nginx directives)
                                                  └─ /<env>/<ver>/     → Moodle container 127.0.0.1:<port>
                                                                         (snippets included from plesk.conf.d)
```

## Layout

```
/opt/boost-union-envs/
├── backend/        git clone theme_boost_union_test_envs (production), owner boost-union-testing
│   └── example_pwd/   working directory (live state, not in git)
├── frontend/       git clone moodle-provisioner-frontend (production)
├── venv/           Python 3.10 virtualenv used by the API service
└── testdeploy      helper used by boost-union-testing during deploys (not in git; verify content)
```

## Services and wiring

| Part | Where / how |
|:--|:--|
| API | systemd `boost-union-api.service` (same unit as the original nucky one: `uvicorn theme_boost_union_test_envs.ui.api.server:app` on `127.0.0.1:8000`, `WorkingDirectory=/opt/boost-union-envs/backend`, runs as root). Environment chosen via `config.yml` (verify whether `BOOST_UNION_ENV` is set). |
| Frontend | Built in `/opt/boost-union-envs/frontend`, then **copied** to the domain's document root `/var/www/vhosts/focused-cray.92-205-184-244.plesk.page/site1` (`cp -a dist site1`; a symlink was tried and replaced by a copy). |
| `/api` proxy | Plesk *Additional nginx directives* for `testsystem.moodle-an-hochschulen.de`, stored in `/var/www/vhosts/system/testsystem.moodle-an-hochschulen.de/conf/vhost_nginx.conf` and `vhost_ssl_nginx.conf`: proxy `/api` to `127.0.0.1:8000` (verify exact content). Edit via Plesk (*Apache & nginx Settings*), not in Plesk's generated `nginx.conf`. |
| Moodle sub-paths | `/etc/nginx/plesk.conf.d/vhosts/boost_union_testsystem` → symlink to `example_pwd/.nginx`; Plesk's nginx includes the per-instance snippets from there. `env.prod.yml` → `softlinked_nginx_config_path` must point at this path (the repo copy still says `…/boost_union`, verify). |
| Basic auth | An `.htpasswd` in the subscription root was added before the application had its own login (verify whether it is still active). |
| Moodle cron | root crontab, every 5 minutes: `scripts/run_moodle_cron.py >> /var/log/boost-union-cron.log`. |
| Lifecycle reaper | not installed yet, see below. |
| Docker | Docker CE + Compose v2, system-wide. |

### `env.prod.yml` on the server

```yaml
working_dir: "./example_pwd"
proxied: yes
nginx:
  base_url: "testsystem.moodle-an-hochschulen.de"
  cert_chain_path: "/etc/letsencrypt/live/testsystem.moodle-an-hochschulen.de/fullchain.pem"
  cert_key_path: "/etc/letsencrypt/live/testsystem.moodle-an-hochschulen.de/privkey.pem"
  overview_page_path: "/var/www/vhosts/testsystem.moodle-an-hochschulen.de/httpdocs"
  softlinked_nginx_config_path: "/etc/nginx/plesk.conf.d/vhosts/boost_union_testsystem"
```

The `env.prod.yml` committed in the repo still has the old Plesk host
(`focused-cray…plesk.page`). Update the repo copy to match the server.

### Proxy specifics

With `proxied: yes` the build step patches each instance's `moodle/config.php`
(`$CFG->wwwroot = 'https://testsystem…/<env>/<version>'`, `sslproxy`,
`reverseproxy`) and the per-instance nginx snippet proxies to the container's
`/public/` for Moodle 5.1+. See [Request flow](../reference/request-flow-nl.md)
and [Moodle 5.x](../reference/moodle5.md).

## Bringing lifecycle automation and email to production

Work packages 3 and 5 run on nucky. To enable them on Plesk:

1. Deploy the current `production` branch (backend and frontend).
2. Prefer `BOOST_UNION_ENV` over a locally edited `config.yml`: add
   `Environment=BOOST_UNION_ENV=env.prod.yml` to the unit, `systemctl
   daemon-reload && systemctl restart boost-union-api`, then
   `git checkout -- config.yml`.
3. Add the reaper to root's crontab (or `/etc/cron.d/boost-union-reap`, as on
   nucky):
   ```cron
   */15 * * * * cd /opt/boost-union-envs/backend && BOOST_UNION_ENV=env.prod.yml /opt/boost-union-envs/venv/bin/python scripts/reap_instances.py >> /var/log/boost-union-reap.log 2>&1
   ```
4. In the UI: **Admin Settings → Email** with the SMTP server provided by the
   association, send a test; then **Lifecycle** with production values
   (automation stays off until you enable it).
5. Consider adding `deploy/plesk/` (unit, cron, deploy script, nginx
   directives) like `deploy/nucky/`, so the server can be rebuilt from git.

## Troubleshooting from the original installation

**`Permission denied` on `moodle/config.php`** — the container's `www-data`
cannot read root-owned files (usually after editing with `sudo`):

```bash
sudo chown boost-union-testing:psacln example_pwd/<env>/moodles/<version>/moodle/config.php
sudo chmod 644 example_pwd/<env>/moodles/<version>/moodle/config.php
```

**Browser keeps redirecting to `/<env>/<version>/public/`** — a cached 301
from before the proxy fix. Use a private window or clear site data.

**Snippet exists but the URL 404s** — check the include symlink and reload:

```bash
ls -l /etc/nginx/plesk.conf.d/vhosts/boost_union_testsystem
sudo nginx -t && sudo nginx -s reload
```

**New instances 404 inside the container (stale `.moodle-docker/local.yml`)** —
the per-instance `local.yml` is rendered from the copy in
`example_pwd/.moodle-docker/`, which is seeded only once by `init`. After
template changes, re-seed it and rebuild affected instances:

```bash
cd /opt/boost-union-envs/backend
sudo cp theme_boost_union_test_envs/cross_cutting/templates/local.yml example_pwd/.moodle-docker/local.yml
grep REPLACE_PROXY_OVERRIDES example_pwd/.moodle-docker/local.yml
```

**IPv6 not answering** — the subscription must be bound to both addresses:

```bash
sudo plesk bin subscription -u focused-cray.92-205-184-244.plesk.page -ip 92.205.184.244,2a00:1169:116:8290::
```
