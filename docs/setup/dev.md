# Setup: local (dev)

How the development setup on your own machine is put together, and how to
create it from scratch. For daily use see [Working with: local](../working/dev.md).

## Layout

```
~/www/theme_boost_union_test_envs/          backend repo  (branch production)
├── config.yml                              environment: "env.local.yml"
├── env.local.yml                           proxied: no, base_url: localhost
├── example_pwd/                            working directory (not in git)
└── moodle-provisioner-frontend/            frontend repo (branch production,
                                            ignored by the backend repo)
```

| Part | How it runs | Address |
|:-----|:------------|:--------|
| Backend API | `uvicorn … --reload` in a terminal | `http://localhost:8000` (Swagger: `/docs`) |
| Frontend | `npm run dev` (Vite) | `http://127.0.0.1:5173`, proxies `/api` → `:8000` (`vite.config.ts`) |
| Moodle instances | Docker Desktop | `http://localhost:<random port>` |
| nginx | not used | — |
| Reaper / cron | not scheduled; run by hand | — |

Both repositories use the `origin` remote on `git@github.com:bmbrands/…` and the
`production` branch.

## Prerequisites

- Docker Desktop (Docker + Compose v2)
- Git, Node.js 20+ and npm
- Miniconda (or another way to get Python 3.11) and Poetry

## From scratch

### 1. Clone both repositories

```bash
mkdir -p ~/www && cd ~/www
git clone --branch production git@github.com:bmbrands/theme_boost_union_test_envs.git
cd theme_boost_union_test_envs
git clone --branch production git@github.com:bmbrands/moodle-provisioner-frontend.git
```

### 2. Python environment

```bash
conda create -n boost-union-envs python=3.11
conda activate boost-union-envs
pip install poetry
poetry install
# The API dependencies are not (yet) declared in pyproject.toml:
pip install fastapi 'uvicorn[standard]' httpx
```

The environment lives at
`/opt/homebrew/Caskroom/miniconda/base/envs/boost-union-envs`; the VS Code
launch configurations in `.vscode/launch.json` point there.

!!! note
    Use Python 3.11 or 3.12. The pinned `fire` version does not work on
    Python 3.13 (`ModuleNotFoundError: pipes`).

### 3. Configuration

The defaults in the repo are the local ones; nothing needs to change:

- `config.yml` → `environment: "env.local.yml"`
- `env.local.yml` → `working_dir: "./example_pwd"`, `proxied: no`

See [Configuration files](../configuration/config-files.md) for all options.

### 4. Initialise the working directory (once)

```bash
./boost-union-envs init
```

This creates `example_pwd/` with the moodle-docker clone (`.moodle-docker/`),
the Moodle download cache (`.moodles/`), `.nginx/` and an empty
`infrastructure.yaml`. See [Working directory](../configuration/working-directory.md).

### 5. Frontend dependencies

```bash
cd moodle-provisioner-frontend
npm install
```

### 6. First start and admin account

Start the backend once with a bootstrap admin (only used while `users.yaml`
does not exist yet):

```bash
export BOOTSTRAP_ADMIN_EMAIL="you@example.org"
export BOOTSTRAP_ADMIN_PASSWORD="a-temporary-password"
python -m uvicorn theme_boost_union_test_envs.ui.api.server:create_app --factory --reload --port 8000
```

Then start the frontend (`npm run dev`), sign in and change the password. See
[Authentication](../reference/authentication.md).

## Optional: catch email locally

To test notification email without sending real mail, run MailHog in Docker
and point **Admin Settings → Email** at it (host `127.0.0.1`, port `1025`,
security *None*):

```bash
docker run -d --name mailhog -p 127.0.0.1:1025:1025 -p 127.0.0.1:8025:8025 mailhog/mailhog:v1.0.1
```

Mail shows up at `http://localhost:8025`.
