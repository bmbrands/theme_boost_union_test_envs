# Moodle Provisioner — project guide for Claude

Moodle test-environment provisioner for *Moodle an Hochschulen e.V.* (contract
with Hochschule Hannover, quotation of 26 March 2026, work packages 1–5).
Full documentation: `docs/` (MkDocs, nav in `mkdocs.yml`) — start at
`docs/index.md`. Read the relevant doc page before changing a location.

## Repositories

| Repo | Path | Notes |
|:--|:--|:--|
| Backend (this repo) | `~/www/theme_boost_union_test_envs` | Python: FastAPI API (`ui/api/`), CLI, `scripts/` (reaper, Moodle cron runner) |
| Frontend | `moodle-provisioner-frontend/` (nested, gitignored by the backend) | React + Vite. **`dist/` is committed**: run `npx vite build` before committing |

Remote: `origin` = `git@github.com:bmbrands/…` only (both repos).

## Branches

- **`production`** — what runs on Plesk. Plesk runs backend `57f44c7` /
  frontend `82c04f0` (no login; Apache basic auth in front, 2 users) plus the
  Moodle 5.3 fix (`6dd801f`, local branch `moodle-5.3`). Only live-system
  fixes go here; cherry-pick them onto `phase2` too.
- **`phase2`** — next release (user management, lifecycle reaper, email,
  security hardening, docs). Runs on nucky. Merged into `production` after
  acceptance.

## Locations

| | Local (dev) | nucky (acceptance) | Plesk (production) |
|:--|:--|:--|:--|
| Access | this Mac | `ssh root@192.168.2.17` | `ssh bas@244.184.205.92.host.secureserver.net` (key; `sudo` needs a password → the user runs root steps) |
| URL | `http://127.0.0.1:5173` | `https://catachrestic-francoise-indomitably.ngrok-free.dev` | `https://testsystem.moodle-an-hochschulen.de` |
| Branch | either | `phase2` | `production` |
| Env file | `env.local.yml` | `env.nucky.yml` via `BOOST_UNION_ENV` | `env.prod.yml` via edited `config.yml` |
| Deploy | — | `ssh root@192.168.2.17 /opt/boost-union-envs/deploy.sh all` | manual, see `docs/working/production.md` |

nucky: ngrok must be started by hand in `screen` after a reboot; MailHog UI
`http://192.168.2.17:8025`; server config lives in `deploy/nucky/`.
Plesk repos are owned by `boost-union-testing`; read them with
`git -c safe.directory=* -C …`.

## Local commands

```bash
P=/opt/homebrew/Caskroom/miniconda/base/envs/boost-union-envs/bin/python   # Python 3.11 conda env
$P -m uvicorn theme_boost_union_test_envs.ui.api.server:create_app --factory --reload --port 8000
npm --prefix moodle-provisioner-frontend run dev        # :5173, proxies /api
$P -m pytest tests                                       # backend tests
$P -m theme_boost_union_test_envs <list|setup|build|start|stop|destroy|teardown> …   # CLI
/opt/homebrew/Caskroom/miniconda/base/envs/boost-union-envs/bin/mkdocs build -d <scratch>/site
```

Run everything from the backend root (`config.yml` is read from the cwd).

## Working agreements

- Talk to the user in Dutch; write code, commits and docs in English.
- After each completed task: commit (both repos as needed), push, and deploy
  `phase2` to nucky. Commit messages explain what and why.
- Match the surrounding code; don't reformat or touch unrelated code.
- Never enter passwords (Plesk sudo, ngrok/production logins) — ask the user.
  Local test logins on localhost are fine. Don't copy credentials into files.
- Force-push / branch resets are blocked by the permission classifier: give
  the user the exact command instead.
- Visual UI checks: run the API + Vite locally (see skill `local-ui-test`).

## Pitfalls (learned the hard way)

- `example_pwd/` is runtime state (users, settings, environments) — not in
  git, different per location. Plugin checkouts under it (e.g.
  `numark-1/mod/bookit`) are foreign repos: never edit them.
- `example_pwd/.moodle-docker/` is the moodle-docker clone used for new
  environments: a git clone on Plesk and locally, a **plain copy** on nucky
  (update it there by cloning upstream to a temp dir and rsyncing over it).
- New Moodle releases need the PHP mapping and an up-to-date moodle-docker
  (Moodle 5.3 requires PostgreSQL 17) — skill `new-moodle-release`.
- `ssh`/network commands need the sandbox disabled.
- The pinned `fire` breaks on Python 3.13; use the 3.11 conda env.
- `npx tsc -b` has pre-existing errors (unused `components/ui/*`, `App.tsx`
  `setIsDetailsModalOpen`); `vite build` is the check that matters.
- `cross_cutting.template_engine` is shadowed by a function of the same name:
  import the module with `importlib` in tests.
- macOS: `aiosmtpd`/`smtplib` hang on `getfqdn()`; the mailer passes its own
  EHLO name. Use MailHog for mail tests.
- `.gitignore` used to ignore `docs/*`; private notes go in
  `docs/archive/private/` (ignored, excluded from the site).

## Open items (phase2, before acceptance)

Cleanup of unused code/files, missing FastAPI/uvicorn/httpx in
`pyproject.toml`, user report "users & their environments", self-service
password change, clarify "email as part of user management", deploy phase2
to Plesk (incl. re-binding Moodle ports to 127.0.0.1), hand over to the
association's GitHub repos.
