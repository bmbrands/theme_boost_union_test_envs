# Session Log — boost-union-envs

## Environment setup

```bash
# Conda activeren (eenmalig per terminal)
. ~/conda_profile
conda activate boost-union-envs

# Python check
python --version   # 3.11.x
which python       # /opt/homebrew/Caskroom/miniconda/base/envs/boost-union-envs/bin/python
```

## Project commando's (CLI)

```bash
# Werkmap
cd /Users/basbrands/www/theme_boost_union_test_envs

# Testbed opzetten (git clone moodle + theme)
./boost-union-envs setup <naam> branch <branch>
# Voorbeeld:
./boost-union-envs setup iterinaire branch main
./boost-union-envs setup viervijf branch MOODLE_405_STABLE

# Docker containers bouwen
./boost-union-envs build <naam> <versie>
# Voorbeeld:
./boost-union-envs build iterinaire 5.1.3
./boost-union-envs build viervijf 4.5.7

# Containers starten
./boost-union-envs start <naam> <versie>

# Containers stoppen
./boost-union-envs stop <naam> <versie>

# Containers verwijderen
./boost-union-envs destroy <naam> <versie>

# Hele testbed opruimen
./boost-union-envs teardown <naam>

# Overzicht
./boost-union-envs list
```

## Debugging (VS Code)

```bash
# Debugger starten via terminal (VS Code attach config)
python -m debugpy --wait-for-client --listen 5678 -m theme_boost_union_test_envs list
python -m debugpy --wait-for-client --listen 5678 -m theme_boost_union_test_envs stop lebberdobber 5.1.0
```

Bestanden aangemaakt: `__main__.py`, `cli.py`, `.vscode/launch.json`

## Behat tests draaien (in container)

```bash
cd example_pwd/<naam>/moodles/<versie>
source .env

# Behat init (Moodle < 5.1)
bin/moodle-docker-compose exec webserver php admin/tool/behat/cli/init.php

# Behat init (Moodle >= 5.1, public/ webroot)
bin/moodle-docker-compose exec webserver php public/admin/tool/behat/cli/init.php

# Behat tests uitvoeren
bin/moodle-docker-compose exec -u www-data webserver php public/admin/tool/behat/cli/run.php --tags=@theme_boost_union
```

## API server (FastAPI)

```bash
# Starten
python -m uvicorn theme_boost_union_test_envs.ui.api.server:create_app --factory --reload --port 8000

# Testen
curl http://localhost:8000/api/infrastructures
```

Bestanden: `ui/api/server.py`, `ui/api/routes/infrastructures.py`, `ui/api/models/responses.py`

## Documentatie (MkDocs)

```bash
pip install mkdocs-material mkdocstrings[python]
mkdocs serve        # dev server op :8001
mkdocs build        # static site in site/
```

Docs herschreven in `docs/`: index.md, installation.md, usage.md, testing.md, debugging.md, moodle5.md

## Wat we gedaan hebben

1. **Python project geanalyseerd** — dependency-injector, Fire CLI, Jinja2 templates, Docker SDK, GitPython
2. **VS Code debugging opgezet** — `__main__.py` + `cli.py` aangemaakt, launch.json configs
3. **Moodle 5.1+ support** — `public/` webroot detectie, nginx router config, PHP version mapping
4. **Threshold fix 5.0 → 5.1** — `uses_public_webroot()` geeft `True` vanaf 5.1 (niet 5.0)
5. **FastAPI REST API** — `/api/infrastructures` endpoint, Pydantic models, CORS middleware
6. **Frontend gekoppeld** — Vite proxy, `api.ts` service, `App.tsx` laadt echte data
7. **Documentatie herschreven** — Alles van markdown naar MkDocs docs/ structuur
8. **Git branch** — `feature/moodle5-support` met schone commits via interactive rebase

## Git branches

```bash
# Feature branch (4 commits boven main)
git --no-pager log --oneline feature/moodle5-support -6

# Commits:
# 533ed8a feat: add Moodle 5.x support (public/ webroot, updated PHP versions, official moodle-docker)
# 2b68a30 feat: add __main__.py and cli.py for python -m and debugpy support
# 52baa08 docs: rewrite and expand mkdocs documentation
# 9a252f8 feat: add FastAPI REST API for frontend integration  (aparte branch: feature/fastapi)
```

## Belangrijke bestanden gewijzigd

| Bestand | Wat |
|---------|-----|
| `domain/moodle_version_utils.py` | `uses_public_webroot()` threshold 5.1 |
| `cross_cutting/template_engine.py` | Docker config met versie-aware paths |
| `domain/test_container.py` | Webroot prefix logica |
| `domain/test_infrastructure.py` | Build/setup lifecycle |
| `cross_cutting/templates/moodle_nginx_router.conf` | Nginx routing voor 5.1+ |
| `ui/api/` | Hele FastAPI laag (nieuw) |
| `__main__.py`, `cli.py` | Entry points voor debugger |
