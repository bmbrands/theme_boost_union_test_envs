---
name: new-moodle-release
description: Add support for a new Moodle release (e.g. 5.3, 5.4) to the provisioner — PHP mapping, moodle-docker update, database requirements, environment-check warnings. Use when a user reports that a new Moodle version fails to install or shows environment warnings.
---

# New Moodle release

## 1. Find the requirements

Moodle 5.1+ keeps the file under `public/`:

```bash
curl -sfL https://raw.githubusercontent.com/moodle/moodle/v<X.Y.0>/public/admin/environment.xml -o env.xml
L=$(grep -n '<MOODLE version="<X.Y>"' env.xml | cut -d: -f1); sed -n "${L},\$p" env.xml | grep -nE '<PHP version|<VENDOR|PHP_SETTING' | head -20
```

Check upstream moodle-docker for a matching "Update default dependencies per
Moodle X.Y requirements" commit (DB image defaults):
`curl -s "https://api.github.com/repos/moodlehq/moodle-docker/commits?per_page=10"`.

## 2. Change the code (on `production` for live fixes, cherry-pick to `phase2`)

- `moodle-versions-to-supported-php-versions.yaml`: add `X.Y: [min, max]`
  (newest is used).
- PHP ini settings Moodle recommends go in
  `theme_boost_union_test_envs/cross_cutting/templates/php-moodle.ini`
  (mounted into every webserver container via `local.yml`).

## 3. Update the moodle-docker clone in each working directory

- Local / Plesk (git clone): `cd example_pwd/.moodle-docker && git pull --ff-only origin main`
- nucky (plain copy): clone upstream into a temp dir, back up the folder to
  `/opt/boost-union-envs/state-backup/`, `rsync -a --exclude .git <tmp>/ <dir>/`.

Existing environments keep their own copy; environments built with the old
database must be recreated.

## 4. Test end to end

```bash
P=/opt/homebrew/Caskroom/miniconda/base/envs/boost-union-envs/bin/python
$P -m theme_boost_union_test_envs setup tXY boost_union branch main
$P -m theme_boost_union_test_envs build tXY X.Y.0
$P -m theme_boost_union_test_envs start tXY X.Y.0          # expect "Installation completed successfully."
```

Environment check inside the container (copy `envcheck.php` in with `docker cp`):

```php
<?php
define('CLI_SCRIPT', true);
require('/var/www/html/config.php');
require_once($CFG->libdir . '/environmentlib.php');
[$ok, $results] = check_moodle_environment(normalize_version($CFG->release), ENV_SELECT_RELEASE);
echo "Moodle {$CFG->release}, environment ok: " . ($ok ? 'yes' : 'no') . PHP_EOL;
foreach ($results as $r) { if (!$r->getStatus()) { echo " - {$r->getLevel()}: {$r->getPart()} {$r->getInfo()}" . PHP_EOL; } }
```

Also build an older version (e.g. 4.5.x) to check for regressions, test the
proxied path on nucky (`BOOST_UNION_ENV=env.nucky.yml`, curl via
`http://localhost/<env>/<ver>/` and the ngrok URL), then `destroy` + `teardown`
all test environments.
