# Working with: local (dev)

Day-to-day development on your own machine. How it is set up:
[Setup: local](../setup/dev.md).

## Start

```bash
# Terminal 1 — backend (auto-reloads on Python changes)
cd ~/www/theme_boost_union_test_envs
. ~/conda_profile && conda activate boost-union-envs
python -m uvicorn theme_boost_union_test_envs.ui.api.server:create_app --factory --reload --port 8000

# Terminal 2 — frontend (hot reload)
cd ~/www/theme_boost_union_test_envs/moodle-provisioner-frontend
npm run dev
```

Open `http://127.0.0.1:5173`. The API docs (Swagger) are at
`http://localhost:8000/docs`. Docker Desktop must be running for anything that
builds or starts a Moodle.

Moodle instances you create locally are reachable at
`http://localhost:<port>`; the port is shown in the UI and in
`example_pwd/infrastructure.yaml`.

## Tests and checks

```bash
# Backend (from the backend root, conda env active)
python -m pytest tests

# Frontend
cd moodle-provisioner-frontend
npm run lint
npm run build          # vite build → dist/
```

!!! note
    `npx tsc -b` currently reports errors in unused `components/ui/*` files
    (missing optional Radix packages) and in `App.tsx`
    (`setIsDetailsModalOpen`). They predate the current work; `vite build`
    succeeds regardless. Check that you don't add new ones.

Running Behat/PHPUnit inside a Moodle instance: see
[Moodle tests](../reference/moodle-tests.md). Debugging the backend in VS Code:
see [Debugging](../reference/debugging.md).

## Lifecycle and email locally

The reaper is not scheduled locally. Run it by hand, preferably as a dry run:

```bash
python scripts/reap_instances.py --dry-run
python scripts/reap_instances.py --dry-run --now 2026-10-08T12:00:00   # pretend it is later
```

Without `--dry-run` it really stops and deletes local instances. For email,
use a local MailHog (see [Setup: local](../setup/dev.md#optional-catch-email-locally)).

## Documentation

```bash
mkdocs serve -a 127.0.0.1:8001     # port 8000 is taken by the API
```

The navigation lives in `mkdocs.yml`.

## Commit, push, release

Both repositories work directly on the `production` branch.

1. **Frontend:** the built `dist/` is committed. Run `npm run build` before
   committing so `dist/` matches `src/`, then commit and push:
   ```bash
   cd moodle-provisioner-frontend
   npm run build
   git add -A src dist && git commit && git push
   ```
2. **Backend:** run the tests, commit and push:
   ```bash
   python -m pytest tests && git commit && git push
   ```
3. **Deploy to acceptance** and test there:
   [Working with: nucky](acceptance.md#deploy).
4. After acceptance, deploy to production:
   [Working with: Plesk](production.md#deploy).

## Local data

Everything you do locally ends up in `example_pwd/` (not in git): users,
environments, settings, audit log. Deleting an environment in the UI removes
its containers and files. To start over completely, see
[Working directory](../configuration/working-directory.md#resetting).
