# Usage

## CLI Usage & Examples

### Syntax

```bash
./boost-union-envs <command> [arguments]
```

### Complete Workflow Example

```bash
# 1. Initialize testbed (one-time only)
./boost-union-envs init

# 2. Create an infrastructure for Boost Union's main branch
./boost-union-envs setup my-test branch main

# 3. Build Moodle 4.5.2 and 5.1.0 containers
./boost-union-envs build my-test 4.5.2 5.1.0

# 4. Start both containers
./boost-union-envs start my-test 4.5.2 5.1.0

# 5. Test manually in your browser:
#    → Moodle 4.5.2: http://localhost:<port1>  (see infrastructure.yaml for actual port)
#    → Moodle 5.1.0: http://localhost:<port2>
#    → Admin login: admin / <generated_password>

# 6. Stop when done
./boost-union-envs stop my-test 4.5.2 5.1.0

# 7. Destroy individual containers
./boost-union-envs destroy my-test 4.5.2

# 8. Tear down the entire infrastructure
./boost-union-envs teardown my-test
```

### Testing a Pull Request

```bash
./boost-union-envs setup pr-review pr 42
./boost-union-envs build pr-review 5.0.0
./boost-union-envs start pr-review 5.0.0
```

### Testing a Specific Tag

```bash
./boost-union-envs setup release-test tag v4.5-r3
./boost-union-envs build release-test 4.5.2 5.1.0
./boost-union-envs start release-test 4.5.2 5.1.0
```

### Listing All Infrastructures

```bash
./boost-union-envs list
```

Outputs the contents of `infrastructure.yaml` — shows all infrastructures, their git refs, Moodle versions, status, URLs, ports, and admin passwords.

## Step-by-Step: What Each Command Does

### 1. `init` — One-Time Testbed Setup

Creates the working directory structure and clones the shared moodle-docker repository.

**Actions performed:**

1. Creates the working directory (`working_dir` from `env.local.yml`)
2. Creates the Moodle cache directory (`.moodles/`)
3. Downloads the [`smartdata.php`](https://raw.githubusercontent.com/andrewnicols/moodle-datagenerator/master/smartdata.php) data generator script into the cache
4. Creates Nginx directories (`.nginx/` and `.nginx/testenvs/`)
5. Generates the overview Nginx config (from `plesk_production_nginx.conf` template)
6. **Clones** [moodle-docker](https://github.com/moodlehq/moodle-docker) into `.moodle-docker/`
7. **Copies template files** (`.env`, `local.yml`, `moodle_nginx.conf`, etc.) into the clone — these contain `$REPLACE_*` placeholders that get filled in during `build`
8. Creates the empty `infrastructure.yaml` state file
9. Generates the HTML overview page

### 2. `setup` — Create an Infrastructure for a Boost Union Git Ref

Clones the Boost Union theme at a specific git reference and prepares a directory to hold Moodle containers.

**Actions performed:**

1. **Clones** the [Boost Union repo](https://github.com/moodle-an-hochschulen/moodle-theme_boost_union) into `<working_dir>/<name>/theme/boost_union/`
   - For **branch/tag**: `git clone --branch <ref>`
   - For **commit**: clone, then `git checkout <sha>`
   - For **PR**: clone, fetch `+refs/pull/*/head:refs/remotes/origin/pr/*`, checkout `pr/<number>`
2. Creates the `moodles/` directory (empty, ready for builds)
3. Records the infrastructure in `infrastructure.yaml`

### 3. `build` — Download Moodle & Prepare Docker Containers

Downloads Moodle source, copies all moodle-docker files, generates configs, and creates Docker containers.

**Actions performed (per version):**

1. **Downloads** `https://github.com/moodle/moodle/archive/refs/tags/v<version>.tar.gz` — skips if already cached in `.moodles/`
2. **Extracts** the archive into `<infra>/moodles/<version>/moodle/`
3. **Copies all moodle-docker files** (`bin/`, `base.yml`, `db.pgsql.yml`, compose fragments, etc.) from `.moodle-docker/` into the version directory
4. **Copies** `config.docker-template.php` → `moodle/config.php`
5. **Copies** `smartdata.php` → `moodle/smartdata.php` (or `moodle/public/smartdata.php` for Moodle ≥ 5.1)
6. **Renders `local.yml`** — replaces `$REPLACE_BOOST_UNION_SOURCE_PATH` and `$REPLACE_THEME_MOUNT_PATH` to bind-mount the Boost Union source into the container
7. **Renders `.env`** — fills in compose project name, Moodle source path, random admin password, random free ports (web + DB), PHP Docker image tag, and web host
8. Runs **`docker compose create`** (via `bin/moodle-docker-compose`)
9. **Generates per-container Nginx config** (in proxied/production mode)
10. Records the moodle entry in `infrastructure.yaml` with status `CREATED`

### 4. `start` — Start Containers & Install Moodle

Starts the Docker containers and runs all Moodle setup commands inside them.

**Docker & Moodle commands executed (in order):**

```bash
# 1. Start all containers and wait for the database
. ./.env && bin/moodle-docker-compose up -d
. ./.env && bin/moodle-docker-wait-for-db

# 2. Install the Moodle database
. ./.env && bin/moodle-docker-compose exec webserver \
  php admin/cli/install_database.php \
    --agree-license \
    --fullname="<infra> - <version>" \
    --shortname="<infra> - <version>" \
    --summary="<infra> - <version>" \
    --adminpass=<generated_password> \
    --adminemail="admin@example.com"

# 3. Set Boost Union as the active theme
. ./.env && bin/moodle-docker-compose exec webserver \
  php admin/cli/cfg.php --name=theme --set=boost_union

# 4. Populate with test data
. ./.env && bin/moodle-docker-compose exec webserver \
  php smartdata.php
# (for Moodle ≥ 5.1: php public/smartdata.php)
```

Updates status to `STARTED` in `infrastructure.yaml`.

### 5. `stop` — Stop Containers

```bash
. ./.env && bin/moodle-docker-compose stop
```

Updates status to `STOPPED`. Data is preserved — `start` would bring them back.

### 6. `restart` — Restart Containers

```bash
. ./.env && bin/moodle-docker-compose restart
```

Container restart only — does **not** re-run Moodle install, theme activation, or data generation.

### 7. `destroy` — Remove Individual Moodle Containers

Tears down Docker containers and removes all files for specific Moodle versions within an infrastructure.

1. `docker compose down` for each version
2. Removes the per-container Nginx config
3. Deletes the entire version directory (`<infra>/moodles/<version>/`)
4. Removes the entry from `infrastructure.yaml`

### 8. `teardown` — Remove Entire Infrastructure

Destroys **all** Moodle containers within the infrastructure, then removes the infrastructure directory entirely (including the Boost Union clone).

## Directory Structure

After running `init`, `setup my-infra branch main`, and `build my-infra 4.5.2 5.1.0`:

```
$working_dir/
├── infrastructure.yaml              # State database (YAML)
├── index.html                       # Auto-generated overview page
│
├── .moodles/                        # Shared download cache
│   ├── smartdata.php                # Test data generator script
│   ├── v4.5.2.tar.gz               # Cached Moodle archives
│   └── v5.1.0.tar.gz
│
├── .moodle-docker/                  # Cloned moodle-docker + template overrides
│   ├── bin/moodle-docker-compose    # Docker Compose wrapper
│   ├── base.yml
│   ├── .env                         # Template (with $REPLACE_* placeholders)
│   ├── local.yml                    # Template (with $REPLACE_* placeholders)
│   └── ...
│
├── .nginx/                          # Generated Nginx configs
│   ├── localhost.conf               # Main overview server config
│   └── testenvs/
│       ├── my-infra-4.5.2.conf     # Reverse proxy for Moodle 4.5.2
│       └── my-infra-5.1.0.conf     # Reverse proxy for Moodle 5.1.0
│
└── my-infra/                        # Your infrastructure
    ├── theme/
    │   └── boost_union/             # Boost Union clone (shared by all versions)
    └── moodles/
        ├── 4.5.2/                   # Moodle 4.5.2 environment
        │   ├── .env                 # Rendered: ports, password, PHP version
        │   ├── local.yml            # Rendered: Boost Union volume mount
        │   ├── bin/moodle-docker-compose
        │   ├── base.yml
        │   └── moodle/              # Extracted Moodle 4.5.2 source
        │       ├── config.php
        │       ├── smartdata.php
        │       └── ...
        └── 5.1.0/                   # Moodle 5.1.0 environment
            ├── .env
            ├── local.yml
            ├── bin/moodle-docker-compose
            └── moodle/
                ├── config.php
                └── public/
                    └── smartdata.php  # ≥5.1: web scripts in public/
```

## The Generated Files Explained

### `.env` — Docker Compose Environment Variables

Each Moodle version gets its own `.env` with unique values:

| Variable | Value | How it's determined |
|:---------|:------|:--------------------|
| `COMPOSE_PROJECT_NAME` | `my-infra-4_5_2` | Infrastructure name + version (dots → underscores) |
| `MOODLE_ADMIN_PASSWORD` | `Kuev6QqfiOPH...` | Random 32-character alphanumeric string |
| `MOODLE_DOCKER_DB` | `pgsql` | Always PostgreSQL |
| `MOODLE_DOCKER_WWWROOT` | `/path/to/moodle/` | Absolute path to the extracted Moodle source |
| `MOODLE_DOCKER_WEB_HOST` | `localhost` | From `env.local.yml` (or `base_url/infra/version` when proxied) |
| `MOODLE_DOCKER_WEB_PORT` | `55516` | Random free port (checked against all existing containers) |
| `MOODLE_DOCKER_DB_PORT` | `55517` | Random free port (different from web port) |
| `MOODLE_DOCKER_PHP_VERSION` | `8.3` | Newest compatible PHP from version mapping YAML |

### `local.yml` — Docker Compose Override

Bind-mounts the shared Boost Union clone into the container's theme directory:

```yaml
version: "2"
services:
  webserver:
    volumes:
      - "/path/to/my-infra/theme/boost_union:/var/www/html/theme/boost_union:cached"
```

For **Moodle ≥ 5.1** (which moved themes into `public/`):

```yaml
      - "/path/to/my-infra/theme/boost_union:/var/www/html/public/theme/boost_union:cached"
```

### `infrastructure.yaml` — State Database

```yaml
my-infra:
  git_ref:
    reference: main
    type: BRANCH
  moodles:
    4.5.2:
      admin_pw: Kuev6QqfiOPHoBUiiuNmToVnkqiQglCo
      db_port: '55517'
      status: STARTED
      url: http://localhost:55516
      www_port: '55516'
    5.1.0:
      admin_pw: xR8mNpQw2kLj7YvH...
      db_port: '55519'
      status: STARTED
      url: http://localhost:55518
      www_port: '55518'
```
