# Production Installation on a Plesk Server

This document captures the concrete server setup for the Moodle test-environment
provisioner running on `testsystem.moodle-an-hochschulen.de`
(Plesk Obsidian on Ubuntu 22.04). It explains how the components fit together,
the issues that were encountered during initial deployment, and the daily
operating commands.

> All paths assume the production checkout at
> `/opt/boost-union-envs/backend/` and the Plesk subscription
> `focused-cray.92-205-184-244.plesk.page`, which also serves the alias
> `testsystem.moodle-an-hochschulen.de`.

---

## 1. How the setup works

```
                   Internet
                      │  HTTPS
                      ▼
   ┌─────────────────────────────────────────────┐
   │  Plesk nginx (port 443, vhost SSL)          │
   │   include /etc/nginx/plesk.conf.d/vhosts/   │
   │           boost_union_testsystem/*.conf     │
   └────────────┬────────────────────────────────┘
                │  proxy_pass to 127.0.0.1:<random_port>/public/
                ▼
   ┌─────────────────────────────────────────────┐
   │  moodle-docker container                     │
   │   moodlehq/moodle-php-apache:8.3             │
   │   /var/www/html  (Moodle source)             │
   │   /var/www/html/public/  (Moodle 5+ webroot) │
   └─────────────────────────────────────────────┘
```

Per Moodle test environment (one infrastructure × one Moodle version) the
provisioner emits:

1. A docker-compose project under
   `example_pwd/<infra>/moodles/<version>/` that boots Moodle, MariaDB and
   the surrounding services.
2. A small nginx snippet
   `example_pwd/.nginx/testenvs/<infra>-<version>.conf` that proxies the public
   subpath `/<infra>/<version>/` to the container.
3. An `index.html` overview page that links to every running environment.

The `.nginx/` directory is **symlinked** into Plesk's include directory
(`/etc/nginx/plesk.conf.d/vhosts/boost_union_testsystem`), so adding or removing
a test environment is picked up by a simple `nginx -s reload`.

### Moodle 5.x specifics

Moodle 5.1 moved its web entrypoint from the source root to
`moodle/public/`. The provisioner detects this via
`uses_public_webroot(version)` and:

- Mounts the source directory into the container at `/var/www/html`.
- Lets the proxy snippet `proxy_pass` directly to the container's
  `/public/` subpath, so the external URL stays at `/<infra>/<version>/`
  and Moodle never has to emit `./public/` relative redirects.

### Reverse proxy overrides in `config.php`

`moodle-docker`'s `config.docker-template.php` builds
`$CFG->wwwroot` from `MOODLE_DOCKER_WEB_HOST + ":<port>"`, which is wrong when
running behind a Plesk reverse proxy on a subpath. When
`proxied: yes` is set in `env.prod.yml`, the build step now appends an
override block to the generated `moodle/config.php` just before
`require_once(__DIR__ . '/lib/setup.php');`:

```php
// boost-union-envs override: correct external wwwroot when behind reverse proxy
$CFG->wwwroot     = 'https://testsystem.moodle-an-hochschulen.de/<infra>/<version>';
$CFG->sslproxy    = true;
$CFG->reverseproxy = true;
```

This makes Moodle generate correct absolute URLs and trust the
`X-Forwarded-Proto: https` header from the upstream nginx.

---

## 2. Server prerequisites

- Plesk Obsidian with a subscription pointing at the public hostname
  (`testsystem.moodle-an-hochschulen.de`).
- Docker + Docker Compose v2 installed system-wide.
- A dedicated system user `boost-union-testing` (group `psacln`) that owns
  the checkout under `/opt/boost-union-envs/backend/` and runs Docker.
- Python 3.11+ with the project's `.venv` populated via
  `poetry install` (see [installation.md](installation.md)).
- Let's Encrypt certificates for the Plesk subscription (used directly by
  Plesk's nginx; the provisioner only references the chain/key paths for
  template completeness).

### IPv6 binding (one-time fix)

The subscription was originally bound only to the public IPv4. Nginx then
failed to answer the AAAA address of the `testsystem` alias. The fix is to
re-bind the subscription to *both* the IPv4 and the IPv6 address that resolve
for the hostname:

```bash
sudo plesk bin subscription \
  -u focused-cray.92-205-184-244.plesk.page \
  -ip 92.205.184.244,2a00:1169:116:8290::
```

After this, `nginx -T` lists `listen [::]:443 ssl` for the vhost and the
domain resolves cleanly over IPv6.

---

## 3. `env.prod.yml`

The production environment file selected by `config.yml`:

```yaml
working_dir: "./example_pwd"
# implicitly truthy, yes or no is sufficient here
proxied: yes
nginx:
  base_url: "testsystem.moodle-an-hochschulen.de"
  cert_chain_path: "/etc/letsencrypt/live/testsystem.moodle-an-hochschulen.de/fullchain.pem"
  cert_key_path: "/etc/letsencrypt/live/testsystem.moodle-an-hochschulen.de/privkey.pem"
  overview_page_path: "/var/www/vhosts/testsystem.moodle-an-hochschulen.de/httpdocs"
  # path to which you softlinked the created $working_dir/.nginx
  softlinked_nginx_config_path: "/etc/nginx/plesk.conf.d/vhosts/boost_union_testsystem"
```

> The `softlinked_nginx_config_path` value is the symlink target — Plesk
> actually includes everything under
> `/etc/nginx/plesk.conf.d/vhosts/boost_union_testsystem/`, which is the
> symlink itself pointing at `…/example_pwd/.nginx`.

---

## 4. Code changes that landed for the Plesk deployment

The following project files were updated to make
`./boost-union-envs build` reproducibly produce a working Plesk-fronted
environment without manual server patching.

| File | Change |
|:--|:--|
| `theme_boost_union_test_envs/cross_cutting/templates/moodle_nginx.conf` | Added a `location = /$REPLACE_LOCATION { return 301 …/; }` no-trailing-slash redirect and rewrote the proxy block to `proxy_pass http://127.0.0.1:$REPLACE_PORT/$REPLACE_PROXY_SUBPATH;` with `Host`, `X-Forwarded-Host`, `X-Forwarded-Proto https`, `X-Real-IP`, `X-Forwarded-For`, `proxy_read_timeout 1000s`, `proxy_redirect default`. |
| `theme_boost_union_test_envs/cross_cutting/template_engine.py` | `moodle_nginx_config()` imports `uses_public_webroot(moodle_version)` and substitutes `REPLACE_PROXY_SUBPATH = "public/"` for Moodle 5.1+, `""` otherwise. |
| `theme_boost_union_test_envs/domain/test_infrastructure.py` | After copying `config.docker-template.php` to `moodle/config.php`, when `config().is_proxied` is true the new `_append_proxy_overrides_to_config_php()` helper injects the `wwwroot` / `sslproxy` / `reverseproxy` block (idempotent via a `// boost-union-envs override` sentinel). |

Together these changes mean that running

```bash
./boost-union-envs build <infra> <version>
```

on the production server produces a directly-working subpath reverse proxy
setup; no manual edits to `config.php` or `.nginx/testenvs/*.conf` are
needed.

---

## 5. Daily operation

The provisioner runs as the dedicated `boost-union-testing` system user
inside the project's Poetry-managed virtual environment.

### Open a shell as the operator user

```bash
sudo -i -u boost-union-testing
cd /opt/boost-union-envs/backend
testdeploy
```

### Create / build / start an environment

```bash
# 1. Scaffold a new infrastructure with a fresh boost_union checkout
./boost-union-envs setup second-test boost_union branch MOODLE_501_STABLE

# 2. Build the docker-compose project and nginx snippet for a Moodle version
./boost-union-envs build second-test 5.1.0

# 3. Bring up the Moodle container, reload nginx, append to overview page
./boost-union-envs start second-test 5.1.0
```

Result: `https://testsystem.moodle-an-hochschulen.de/second-test/5.1.0/` will
serve the Moodle 5.1.0 install/home page within seconds.

### Inspect / tear down

```bash
./boost-union-envs status                           # list running envs
./boost-union-envs stop  second-test 5.1.0          # stop the container
./boost-union-envs teardown second-test             # remove the infrastructure
```

### Reload nginx manually (rarely needed)

```bash
sudo nginx -t && sudo nginx -s reload
```

---

## 6. Where things live on the server

| Purpose | Path |
|:--|:--|
| Project checkout | `/opt/boost-union-envs/backend/` |
| Active env file (`env.prod.yml`) selected via `config.yml` | `/opt/boost-union-envs/backend/config.yml` |
| Working directory (per-infrastructure scaffolding) | `/opt/boost-union-envs/backend/example_pwd/<infra>/` |
| Per-Moodle docker-compose project | `…/example_pwd/<infra>/moodles/<version>/` |
| Generated `config.php` | `…/example_pwd/<infra>/moodles/<version>/moodle/config.php` |
| Generated nginx snippet | `…/example_pwd/.nginx/testenvs/<infra>-<version>.conf` |
| Plesk include (symlink) | `/etc/nginx/plesk.conf.d/vhosts/boost_union_testsystem` → `…/example_pwd/.nginx` |
| Overview page | `/var/www/vhosts/focused-cray.92-205-184-244.plesk.page/httpdocs/index.html` |
| TLS certificates (managed by Plesk) | `/etc/letsencrypt/live/focused-cray.92-205-184-244.plesk.page/` |

---

## 7. Troubleshooting

**`Permission denied` on `moodle/config.php`**
The container's `www-data` cannot read root-owned files. Ownership must match
the rest of the Moodle tree:

```bash
sudo chown boost-union-testing:psacln \
  example_pwd/<infra>/moodles/<version>/moodle/config.php
sudo chmod 644 example_pwd/<infra>/moodles/<version>/moodle/config.php
```

This typically happens only if you edited `config.php` via `sudo`. A fresh
`./boost-union-envs build` produces correctly-owned files.

**Browser still redirects to `/<infra>/<version>/public/`**
This is a cached `301 Permanent Redirect` from before the proxy fix landed.
Reload in an incognito window or clear site data for the host. The server
itself returns `200 OK` for the bare `/<infra>/<version>/` URL.

**Nginx snippet exists but URL still 404s**
Check that the include symlink resolves and reload nginx:

```bash
ls -l /etc/nginx/plesk.conf.d/vhosts/boost_union_testsystem
sudo nginx -t && sudo nginx -s reload
```

**Let's Encrypt rate limit**
The Plesk subscription uses Let's Encrypt; the production certificate is
renewed by Plesk. Manual renewals via `certbot` are rate-limited to a few
per week per domain — wait or use the Plesk UI ("Let's Encrypt"
extension → Renew).
