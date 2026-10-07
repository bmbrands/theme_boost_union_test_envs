# Working directory (`example_pwd`)

All runtime state lives in one directory, configured as `working_dir` in the
active `env.*.yml` — `./example_pwd` inside the backend checkout on every
location. It is **not in git** (`.gitignore`) and differs per location: your
local `example_pwd/` has nothing to do with the one on nucky or Plesk.

!!! danger "Back it up, keep it private"
    This directory is the system's database. It contains password hashes, the
    session signing key, the SMTP password and every Moodle's admin password.
    Never commit it; back it up before risky changes (on nucky:
    `/opt/boost-union-envs/state-backup/`).

## Overview

```
example_pwd/
├── infrastructure.yaml        state of all environments and Moodle instances
├── users.yaml                 user accounts (secret)
├── settings.yaml              admin settings: lifecycle policy, email/SMTP (secret)
├── plugins.yaml               plugin catalog as edited in Admin Settings
├── audit.yaml                 audit log (last 2000 entries)
├── .session_secret            cookie signing key, if SESSION_SECRET is not set (secret)
├── index.html                 legacy HTML overview page (CLI era)
├── .moodle-docker/            moodle-docker clone + template copies (created by init)
├── .moodles/                  download cache: Moodle source archives, smartdata.php
├── .nginx/                    generated nginx config (used when proxied)
│   ├── <base_url>.conf        outer vhost (nucky/Plesk)
│   └── testenvs/<env>-<version>.conf   one proxy snippet per Moodle instance
└── <environment>/             one directory per environment (infrastructure)
    ├── <install_folder>/      plugin checkout, e.g. theme/boost_union or mod/bookit
    └── moodles/<version>/     one moodle-docker compose project per Moodle version
        ├── .env               ports, admin password, PHP image, web host
        ├── local.yml          mounts the plugin checkout (+ proxy overrides)
        ├── apache-prefix.conf Apache Alias for the sub-path (proxied only)
        ├── bin/, *.yml        copied from .moodle-docker
        └── moodle/            Moodle source; config.php (patched when proxied)
```

| Entry | Created by | Edit by hand? |
|:--|:--|:--|
| `infrastructure.yaml` | the app, on every action | only to repair state; stop the API first |
| `users.yaml` | first API start (bootstrap admin), then the Users dialog | no — use the UI |
| `settings.yaml` | Admin Settings → Lifecycle / Email | possible (see below); the UI rewrites it |
| `plugins.yaml` | first catalog read (from `supported-plugins.yml`), then Admin Settings → Plugin Catalog | no — use the UI |
| `audit.yaml` | UI actions | no |
| `.session_secret` | first API start | delete to log everybody out |
| `.moodle-docker/`, `.moodles/`, `.nginx/` | `boost-union-envs init` | `.moodle-docker/local.yml` after template changes |
| `<environment>/` | creating an environment | no — delete via the UI or CLI |

## `infrastructure.yaml`

The state database, keyed by environment name:

```yaml
dollhouse:
  plugin: boost_union
  git_ref:
    type: BRANCH                 # BRANCH | TAG | COMMIT | PR
    reference: MOODLE_501_STABLE
  created_at: '2026-09-29 12:53:50'           # UTC
  last_modified_at: '2026-09-29 13:34:52'     # UTC
  created_by:                                 # owner; receives deletion warnings
    id: user-7ae830eaaa1b
    name: Admin User
    email: admin@example.org
  moodles:
    5.1.0:
      status: STARTED                         # CREATED | STARTED | STOPPED
      url: http://localhost:56539
      www_port: '56539'
      db_port: '56540'
      admin_pw: …                             # Moodle "admin" password
      created_at: '2026-09-29T14:54:05.471898'
      started_at: '2026-09-29 13:34:52'       # UTC, set on every start
      stopped_at: …                           # UTC, set on every stop
      deletion_warning_sent_for: '2026-10-01T12:55:10Z'   # last warned deadline
```

The lifecycle reaper uses `started_at` / `stopped_at` to compute the auto-stop
and auto-delete times (falling back to `last_modified_at` / `created_at` for
older records). Environments created with the CLI have no `created_by`.

## `settings.yaml`

Holds a single `values` mapping. Two sections are owned by dedicated screens
and API routes:

```yaml
values:
  lifecycle:                     # Admin Settings → Lifecycle   (PUT /api/lifecycle)
    auto_stop_enabled: true
    max_runtime_minutes: 480
    daily_stop_time: '18:00'     # UTC, '' = off
    auto_cleanup_enabled: true
    stopped_retention_days: 7
    cleanup_empty_infrastructures: true
  email:                         # Admin Settings → Email       (PUT /api/email)
    smtp:
      host: smtp.example.org
      port: 587
      security: starttls         # starttls | ssl | none
      username: …
      password: …                # stored in plain text; file mode 600
      from_address: noreply@example.org
      from_name: Moodle Provisioner
      timeout_seconds: 15
    portal_url: ''               # '' = derived from env.*.yml
    timezone: Europe/Berlin
    deletion_warning:
      enabled: true
      hours_before: 24
      subject: …                 # Jinja2 template
      body: …
```

Meaning of every value: [Lifecycle & email](../reference/lifecycle-and-email.md).
Missing sections mean "defaults", and the defaults switch all automation off.
Other keys under `values` (e.g. `github_webhook_secret`,
`default_moodle_version`) are left over from an earlier settings mock-up and
are not used.

The file is written atomically and with mode `600`. If you edit it by hand,
keep valid YAML; the reaper reads it on every run and the API on every
request, so no restart is needed.

## `users.yaml`, `.session_secret`, `audit.yaml`

See [Authentication](../reference/authentication.md). `audit.yaml` is trimmed
to the most recent 2000 entries.

## `plugins.yaml`

The effective plugin catalog: every plugin from `supported-plugins.yml`
(with admin edits such as *inactive*) plus plugins added in the UI.
Deleting the file restores the defaults on the next read.

## Legacy files

- `index.html` — overview page generated for the CLI; the SPA replaced it.
- `infra_owners.yaml` (present on nucky) — an earlier owner mapping. Owners
  are now stored in `infrastructure.yaml` (`created_by`); the file is unused.

## Resetting

Local only — this deletes all environments and accounts:

```bash
# remove all Moodle stacks first (UI, or for each environment:)
./boost-union-envs teardown <environment>
# then
rm -rf example_pwd
./boost-union-envs init
```

Partial resets:

- log everybody out: delete `.session_secret` (or change `SESSION_SECRET`)
- new bootstrap admin: stop the API, delete `users.yaml`, start with
  `BOOTSTRAP_ADMIN_*` set
- default plugin catalog: delete `plugins.yaml`
- default lifecycle/email settings: remove the section from `settings.yaml`
