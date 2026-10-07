# Architecture

## Components

```
                     Browser
                        │
          ┌─────────────┴──────────────┐      (local dev: Vite on :5173
          │  nginx (server) / Vite     │       proxies /api to :8000)
          └──┬───────────┬──────────┬──┘
             │ /         │ /api     │ /<env>/<version>/
             ▼           ▼          ▼
     React SPA      FastAPI      Moodle stack (moodle-docker compose:
     (dist/)        uvicorn      webserver, db, mailpit, …) on a random
                    :8000        local port
                       │
                       ├── docker compose up/stop/down  ──► Moodle stacks
                       ├── writes nginx snippets + reload ──► nginx
                       └── reads/writes ──► working directory (example_pwd/)

     cron ──► scripts/reap_instances.py   (lifecycle: auto-stop, cleanup, warning email)
     cron ──► scripts/run_moodle_cron.py  (Moodle cron for running instances; Plesk)
```

| Component | Code | Notes |
|:----------|:-----|:------|
| REST API | `theme_boost_union_test_envs/ui/api/` | FastAPI app (`server.py`), routers in `routes/`. Session-cookie auth, see [Authentication](authentication.md). |
| CLI | `./boost-union-envs`, `theme_boost_union_test_envs/ui/cli/` | The original interface; same core as the API. See [CLI](cli.md). |
| Core / domain | `core.py`, `domain/` | Infrastructures, Moodle containers, git checkout, lifecycle rules, notifications. |
| Cross-cutting | `cross_cutting/` | Configuration, `infrastructure.yaml` parser, templates (nginx, docker), users, settings store, mailer, logging. |
| Frontend | `moodle-provisioner-frontend/src/` | `services/api.ts` is the only place that calls the backend. |
| Reaper | `scripts/reap_instances.py` | See [Lifecycle & email](lifecycle-and-email.md). |
| Moodle cron runner | `scripts/run_moodle_cron.py` | Calls `admin/cron.php` of every running instance. |

## Concepts

- An **infrastructure** (called *environment* in the UI) is one plugin at one
  git reference, e.g. `boost_union` @ `MOODLE_501_STABLE`. Its plugin source is
  cloned once and bind-mounted into every Moodle of that infrastructure.
- A **Moodle instance** (called *container* in the UI) is one Moodle version
  inside an infrastructure, with its own compose project, database, ports and
  admin password.
- Instance states: `CREATED` (built, never started) → `STARTED` ⇄ `STOPPED`
  → destroyed. Transitions are recorded in `infrastructure.yaml`
  (`started_at`, `stopped_at`).

## Two URL modes

Selected by `proxied` in the active `env.*.yml` (see
[Configuration files](../configuration/config-files.md)):

- **`proxied: no`** (local): every Moodle is reached directly on
  `http://localhost:<random port>`. No nginx involved.
- **`proxied: yes`** (nucky, Plesk): everything goes through nginx on 80/443.
  Each Moodle is reached at `/<infrastructure>/<version>/`; the backend writes
  one nginx `location` snippet per instance into `example_pwd/.nginx/testenvs/`
  and reloads nginx. Inside the container an Apache `Alias` and a patched
  `$CFG->wwwroot` make Moodle accept the sub-path. The full request path is
  explained (in Dutch) in [Request flow](request-flow-nl.md).

## Lifecycle of an instance (API)

1. `POST /api/infrastructures` clones the plugin, downloads Moodle (cached in
   `.moodles/`), renders `.env` / `local.yml` from the templates, runs
   `docker compose create` and writes the nginx snippet.
2. Start runs `docker compose up`, installs the Moodle database, activates the
   theme and generates test data (`smartdata.php`).
3. Stop / start keep the data; destroy removes containers and files;
   teardown removes the whole infrastructure.
4. The reaper stops and cleans up instances automatically when the
   [lifecycle policy](lifecycle-and-email.md) says so.
