# Moodle Provisioner — test environments for Moodle plugins

Creates and manages isolated Moodle test environments for plugins of
*Moodle an Hochschulen e.V.* (Boost Union and others): pick a plugin, a git
reference and one or more Moodle versions, and get running Moodle instances
in Docker. Includes a web frontend with user management, automatic
stop/cleanup of idle instances and email notifications.

This repository is the **backend** (Python: FastAPI API, CLI, maintenance
scripts). The frontend lives in
[`bmbrands/moodle-provisioner-frontend`](https://github.com/bmbrands/moodle-provisioner-frontend)
and is checked out inside this folder as `moodle-provisioner-frontend/`.

## Documentation

The documentation is in [`docs/`](docs/index.md) (MkDocs; `mkdocs serve -a 127.0.0.1:8001`):

| | Local (dev) | nucky (acceptance) | Plesk (production) |
|:--|:--|:--|:--|
| Day-to-day | [working/dev](docs/working/dev.md) | [working/acceptance](docs/working/acceptance.md) | [working/production](docs/working/production.md) |
| How it is set up | [setup/dev](docs/setup/dev.md) | [setup/acceptance](docs/setup/acceptance.md) | [setup/production](docs/setup/production.md) |

- Configuration: [configuration files](docs/configuration/config-files.md),
  [working directory `example_pwd`](docs/configuration/working-directory.md)
- Reference: [architecture](docs/reference/architecture.md),
  [lifecycle & email](docs/reference/lifecycle-and-email.md),
  [authentication](docs/reference/authentication.md), [CLI](docs/reference/cli.md)

## Quick start (local)

```bash
conda create -n boost-union-envs python=3.11 && conda activate boost-union-envs
pip install poetry && poetry install && pip install fastapi 'uvicorn[standard]' httpx
./boost-union-envs init
python -m uvicorn theme_boost_union_test_envs.ui.api.server:create_app --factory --reload --port 8000
# second terminal
cd moodle-provisioner-frontend && npm install && npm run dev
```

Details, including the first admin account: [docs/setup/dev.md](docs/setup/dev.md).

## Motivation

"Moodle an Hochschulen e.V." needed a central test server for developing the
"Boost Union" theme and its other plugins across the ever-changing Moodle
versions.

## License

Free software: GPL-3.0-only.

The base of this application was created with the
[ppw](https://zillionare.github.io/python-project-wizard) tool.
