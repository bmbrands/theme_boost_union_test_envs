# CLI

The original command-line interface. It uses the same core as the API and the
same working directory, so environments created on the command line show up in
the UI (without an owner) and vice versa.

```bash
./boost-union-envs <command> [arguments]          # with the conda env / venv active
python -m theme_boost_union_test_envs <command>   # equivalent
```

On servers, run from the backend root with the venv Python and the right
environment file, e.g. on nucky:
`BOOST_UNION_ENV=env.nucky.yml /opt/boost-union-envs/venv/bin/python -m theme_boost_union_test_envs list`.

## Commands

| Command | Arguments | What it does |
|:--|:--|:--|
| `init` | — | One-time: create the working directory, clone moodle-docker, copy templates, render the outer nginx vhost. |
| `list` | — | Print `infrastructure.yaml` (environments, versions, status, URLs, passwords). |
| `list-testable-plugins` | — | Plugins from `supported-plugins.yml`. |
| `setup` | `<env> <plugin> <ref type> <ref>` | Create an environment: clone the plugin at a `branch`, `tag`, `commit` or `pr`. |
| `build` | `<env> <version>…` | Download Moodle (cached), render compose files, `docker compose create`, write the nginx snippet. Status `CREATED`. |
| `start` | `<env> [<version>…]` | Start; on first start install the database, activate the theme, generate test data. Status `STARTED`. |
| `stop` | `<env> [<version>…]` | Stop, keep data. Status `STOPPED`. |
| `restart` | `<env> [<version>…]` | Restart the containers only. |
| `destroy` | `<env> [<version>…]` | Remove containers and files of those versions. |
| `teardown` | `<env>` | Destroy all versions and remove the environment, plugin checkout included. |

Without versions, `start`, `stop`, `restart` and `destroy` act on all versions
of the environment.

## Examples

```bash
./boost-union-envs init                                         # once per working directory

./boost-union-envs setup my-test boost_union branch MOODLE_501_STABLE
./boost-union-envs build my-test 4.5.2 5.1.0
./boost-union-envs start my-test 4.5.2 5.1.0
./boost-union-envs list                                         # URLs and admin passwords

./boost-union-envs setup pr-review boost_union pr 42            # a pull request
./boost-union-envs setup release boost_union tag v4.5-r3        # a tag

./boost-union-envs stop my-test
./boost-union-envs destroy my-test 4.5.2
./boost-union-envs teardown my-test
```

Moodle's admin user is `admin`; the password is in `list` / the UI.

## What start does inside the container

```bash
. ./.env && bin/moodle-docker-compose up -d
. ./.env && bin/moodle-docker-wait-for-db
. ./.env && bin/moodle-docker-compose exec webserver php admin/cli/install_database.php \
    --agree-license --fullname="<env> - <version>" --shortname="<env> - <version>" \
    --adminpass=<generated> --adminemail="admin@example.com"
. ./.env && bin/moodle-docker-compose exec webserver php admin/cli/cfg.php --name=theme --set=boost_union
. ./.env && bin/moodle-docker-compose exec webserver php smartdata.php     # public/smartdata.php for Moodle ≥ 5.1
```

## Generated files per instance

`<env>/moodles/<version>/.env`:

| Variable | Value |
|:--|:--|
| `COMPOSE_PROJECT_NAME` | `<env>-<version>` with dots as underscores, e.g. `my-test-5_1_0` |
| `MOODLE_ADMIN_PASSWORD` | random |
| `MOODLE_DOCKER_DB` | `pgsql` |
| `MOODLE_DOCKER_WWWROOT` | absolute path to the Moodle source |
| `MOODLE_DOCKER_WEB_HOST` | `localhost`, or `<base_url>/<env>/<version>` when proxied |
| `MOODLE_DOCKER_WEB_PORT`, `MOODLE_DOCKER_DB_PORT` | random free ports |
| `MOODLE_DOCKER_PHP_VERSION` | newest compatible PHP image (see `moodle-versions-to-supported-php-versions.yaml`) |

`local.yml` bind-mounts the plugin checkout into the container
(`/var/www/html/<install_folder>`, or `/var/www/html/public/<install_folder>`
for Moodle ≥ 5.1) and, when proxied, adds the Apache alias and the
`MOODLE_DOCKER_WEB_PORT=""` override. The full directory layout is described in
[Working directory](../configuration/working-directory.md).
