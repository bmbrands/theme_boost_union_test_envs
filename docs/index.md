# Moodle Provisioner (Boost Union test environments)

A system for creating and managing isolated Moodle test environments for
plugins of *Moodle an Hochschulen e.V.* (Boost Union and friends). Users pick
a plugin, a git reference (branch, tag, pull request or commit) and one or
more Moodle versions; the system builds fully configured Moodle instances with
that plugin installed, each in its own Docker stack.

## The pieces

| Part | Repository | What it is |
|:-----|:-----------|:-----------|
| **Backend** | `bmbrands/theme_boost_union_test_envs` (this repo) | Python. A FastAPI REST API (`/api`), the original CLI (`./boost-union-envs`), and maintenance scripts (lifecycle reaper, Moodle cron runner). |
| **Frontend** | `bmbrands/moodle-provisioner-frontend` | React + TypeScript + Vite single-page app that talks to `/api`. Checked out *inside* the backend folder as `moodle-provisioner-frontend/` (ignored by the backend repo). |
| **Moodle stacks** | created at runtime | One [moodle-docker](https://github.com/moodlehq/moodle-docker) compose project per Moodle instance (web server, database, mail catcher, …). |
| **Working directory** | not in git (`example_pwd/`) | All runtime state: environments, users, settings, audit log, generated nginx config. See [Working directory](configuration/working-directory.md). |

See [Architecture](reference/architecture.md) for how they fit together.

## Three locations

| | Local (dev) | nucky (acceptance) | Plesk (production) |
|:--|:--|:--|:--|
| Purpose | Development on your own machine | Acceptance testing of the `production` branch before it goes live | The live system used by testers |
| Host | your Mac | `nucky`, `root@192.168.2.17` (LAN) | `testsystem.moodle-an-hochschulen.de` |
| Public URL | `http://127.0.0.1:5173` | `https://catachrestic-francoise-indomitably.ngrok-free.dev` (ngrok) | `https://testsystem.moodle-an-hochschulen.de` |
| Environment file | `env.local.yml` | `env.nucky.yml` | `env.prod.yml` |
| Moodle URLs | `http://localhost:<port>` | `https://<host>/<env>/<version>/` | `https://<host>/<env>/<version>/` |

Code moves in one direction: **local → push `production` → deploy on nucky →
accept → deploy on Plesk**.

## Where to go next

- **Working with** a location (day-to-day: run, deploy, logs, tests):
  [local](working/dev.md) · [nucky](working/acceptance.md) · [Plesk](working/production.md)
- **Setup** of a location (how it is installed and wired, rebuilding it from scratch):
  [local](setup/dev.md) · [nucky](setup/acceptance.md) · [Plesk](setup/production.md)
- **Configuration**: [configuration files](configuration/config-files.md) and the
  [working directory (`example_pwd`)](configuration/working-directory.md)
- **Features**: [lifecycle automation & email](reference/lifecycle-and-email.md),
  [authentication & users](reference/authentication.md), [CLI](reference/cli.md)
