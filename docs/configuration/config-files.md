# Configuration files

Static configuration lives in the backend repository. Runtime settings that
administrators change in the UI (lifecycle policy, email) live in the working
directory instead, see [Working directory](working-directory.md#settingsyaml).

| File / variable | What it configures | Differs per location? |
|:--|:--|:--|
| `config.yml` | Which environment file is active; moodle-docker repo; Moodle download settings | no (use `BOOST_UNION_ENV`) |
| `env.local.yml`, `env.nucky.yml`, `env.prod.yml` | Working directory, URL mode, nginx/TLS paths | one file per location |
| `BOOST_UNION_ENV` | Overrides the environment file chosen in `config.yml` | yes |
| `supported-plugins.yml` | The plugins that can be tested (default plugin catalog) | no |
| `moodle-versions-to-supported-php-versions.yaml` | PHP image per Moodle version | no |
| API environment variables | Session secret, cookie security, bootstrap admin, GitHub token | yes (secrets) |
| `moodle-provisioner-frontend/vite.config.ts` | Dev server port and `/api` proxy (local only) | no |

## `config.yml`

```yaml
environment: "env.local.yml"          # the env.*.yml to use (see below)
repos:
  moodle_docker:
    url: "https://github.com/moodlehq/moodle-docker"
adapters:
  moodle:
    downloader:
      url: "https://github.com/moodle/moodle/archive/refs/tags/"   # Moodle source archives
      retries: 5
      retry_timeout: 15
```

Keep the committed value `env.local.yml`. Servers select their own file with
`BOOST_UNION_ENV` instead of editing `config.yml`, so `git pull` never
conflicts.

`config.yml` is read from the **current directory** and the environment file
is resolved relative to the backend directory, so always run the API, the CLI
and the scripts from the backend root.

### `BOOST_UNION_ENV`

```bash
BOOST_UNION_ENV=env.nucky.yml python -m theme_boost_union_test_envs list
```

Set in the systemd unit and the cron file on nucky
(`deploy/nucky/boost-union-api.service`, `deploy/nucky/boost-union-reap.cron`).
Production still uses an edited `config.yml` (see
[Setup: Plesk](../setup/production.md)).

## Environment files (`env.*.yml`)

| Key | Meaning |
|:--|:--|
| `working_dir` | The working directory, relative to the backend root. Always `./example_pwd` in practice. |
| `proxied` | `no`: Moodles on `http://localhost:<port>`. `yes`: Moodles behind nginx on `/<env>/<version>/`; the backend writes nginx snippets and patches `config.php`. |
| `nginx.base_url` | Public host name, **without scheme**. Used in Moodle's `wwwroot`, in links and in the name of the rendered outer vhost (`<base_url>.conf`). |
| `nginx.scheme` | `http` or `https` for stored Moodle URLs when proxied (default `https`). |
| `nginx.template` | Template for the outer vhost in `cross_cutting/templates/` (default `plesk_production_nginx.conf`; nucky uses `nucky_production_nginx.conf`). |
| `nginx.cert_chain_path`, `nginx.cert_key_path` | TLS files, only used by templates that terminate TLS themselves (Plesk). Empty when TLS is in front (ngrok). |
| `nginx.overview_page_path` | Where the legacy HTML overview page (`index.html`) is written. Required when proxied. On nucky it points into the working directory so it never overwrites the SPA. |
| `nginx.softlinked_nginx_config_path` | Where nginx expects the per-instance snippets (the symlink to `example_pwd/.nginx/testenvs` or `.nginx`). |

The files in the repo:

| File | Used on | Notable values |
|:--|:--|:--|
| `env.local.yml` | local | `proxied: no`, `base_url: localhost` |
| `env.nucky.yml` | nucky | `proxied: yes`, `base_url: <ngrok domain>`, `scheme: https`, `template: nucky_production_nginx.conf` |
| `env.prod.yml` | Plesk | `proxied: yes`, Plesk certificate and include paths. The repo copy has the old host name; the server has `testsystem.moodle-an-hochschulen.de`. |
| `env.local-nginx-test.yml` | testing the proxied code path locally | dummy values |

## `supported-plugins.yml`

The plugins users can choose, by name:

```yaml
boost_union:
  url: "https://github.com/moodle-an-hochschulen/moodle-theme_boost_union"
  install_folder: "theme/boost_union"      # path inside the Moodle source
```

This is the default plugin catalog. Admins can deactivate entries or add extra
plugins in **Admin Settings → Plugin Catalog**; those changes are stored in
`example_pwd/plugins.yaml`, not in this file.

## `moodle-versions-to-supported-php-versions.yaml`

Maps Moodle versions (only the breakpoints) to the oldest and newest supported
`moodlehq/moodle-php-apache` image tag; the newest is used:

```yaml
5.1:   [8.3, 8.4]
5.0:   [8.3, 8.3]
```

Add an entry when a new Moodle major/minor version or PHP requirement appears.

## API environment variables

| Variable | Default | Purpose |
|:--|:--|:--|
| `SESSION_SECRET` | random, persisted in `example_pwd/.session_secret` | Signs session cookies. Set a stable value on servers. |
| `SESSION_COOKIE_SECURE` | `false` | `true` when served over HTTPS (nucky via ngrok, Plesk). |
| `BOOTSTRAP_ADMIN_EMAIL` | `admin@localhost` | First admin, only while `users.yaml` does not exist. |
| `BOOTSTRAP_ADMIN_PASSWORD` | random (logged once) | Password for that admin; must be changed on first login. |
| `GITHUB_TOKEN` | — | Optional. Authenticates GitHub API calls for branch/tag/PR lists (5000 instead of 60 requests/hour). |
| `BOOST_UNION_ENV` | — | See above. |

On nucky these are in `/etc/boost-union-api.env` (template:
`deploy/nucky/boost-union-api.env.example`). Details:
[Authentication](../reference/authentication.md).

## Templates

`theme_boost_union_test_envs/cross_cutting/templates/` holds the files the
backend renders: nginx vhosts (`nucky_production_nginx.conf`,
`plesk_production_nginx.conf`), the per-instance proxy snippet
(`moodle_nginx.conf`), the moodle-docker overrides (`local.yml`, `.env`
values, `apache-prefix.conf`) and the overview page (`index.html.j2`).

!!! note
    `local.yml` and the other moodle-docker templates are copied into
    `example_pwd/.moodle-docker/` once, by `init`. After changing them, copy
    them there again (see [Setup: Plesk → troubleshooting](../setup/production.md#troubleshooting-from-the-original-installation)).
