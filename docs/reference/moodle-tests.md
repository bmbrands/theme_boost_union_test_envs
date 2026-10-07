# Running Behat & PHPUnit Tests

Each Moodle test environment is a full moodle-docker stack, so you can run Behat and PHPUnit tests directly inside the containers. All commands use the `bin/moodle-docker-compose` wrapper, which automatically loads the correct `.env` for that environment.

## Prerequisites

1. The environment must be **started** (`boost-union-envs start <infra> <version>`)
2. You must `cd` into the Moodle version directory and `source .env` first

## Behat Tests

```bash
# 1. Navigate to the Moodle version directory
cd example_pwd/iterinaire/moodles/5.1.3

# 2. Load the environment variables
source .env

# 3. Initialize the Behat test environment (required once, or after config changes)
bin/moodle-docker-compose exec -u www-data webserver php admin/tool/behat/cli/init.php

# 4. Run all Boost Union Behat tests
bin/moodle-docker-compose exec -u www-data webserver php admin/tool/behat/cli/run.php \
  --tags=@theme_boost_union

# 5. Run a specific feature file
bin/moodle-docker-compose exec -u www-data webserver php admin/tool/behat/cli/run.php \
  --tags=@theme_boost_union \
  --feature=/var/www/html/public/theme/boost_union/tests/behat/theme_boost_union_feelsettings.feature
```

!!! note
    For Moodle < 5.1, the feature file path uses `/var/www/html/theme/boost_union/tests/behat/...` (without `public/`).

## Viewing Behat Faildump

When Behat tests fail, screenshots and HTML dumps are saved. You can access them via the running webserver:

```
http://localhost:<www_port>/local/moodledocker/faildump/
```

For example, with the iterinaire 5.1.3 instance (port 63133):

```
http://localhost:63133/local/moodledocker/faildump/
```

You can find the `www_port` in the `.env` file (`MOODLE_DOCKER_WEB_PORT`) or in the `infrastructure.yaml`.

## PHPUnit Tests

```bash
# 1. Navigate and source the environment (same as Behat)
cd example_pwd/iterinaire/moodles/5.1.3
source .env

# 2. Initialize PHPUnit (required once)
bin/moodle-docker-compose exec -u www-data webserver php admin/tool/phpunit/cli/init.php

# 3. Run all Boost Union PHPUnit tests
bin/moodle-docker-compose exec -u www-data webserver vendor/bin/phpunit \
  --testsuite theme_boost_union_testsuite

# 4. Run a specific test file
bin/moodle-docker-compose exec -u www-data webserver vendor/bin/phpunit \
  /var/www/html/public/theme/boost_union/tests/example_test.php
```

## Quick Reference

| Action | Command |
|:-------|:--------|
| Init Behat | `bin/moodle-docker-compose exec -u www-data webserver php admin/tool/behat/cli/init.php` |
| Run Behat (all BU) | `...run.php --tags=@theme_boost_union` |
| Run Behat (feature) | `...run.php --tags=@theme_boost_union --feature=/var/www/html/public/theme/boost_union/tests/behat/<file>.feature` |
| Init PHPUnit | `bin/moodle-docker-compose exec -u www-data webserver php admin/tool/phpunit/cli/init.php` |
| Run PHPUnit (suite) | `...vendor/bin/phpunit --testsuite theme_boost_union_testsuite` |
| Faildump | `http://localhost:<www_port>/local/moodledocker/faildump/` |

!!! tip
    `source .env` is essential — without it, `bin/moodle-docker-compose` does not know which Docker project to target.
