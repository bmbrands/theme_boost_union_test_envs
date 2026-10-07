# Moodle 5.x Support — Changes Made

Moodle 5.1 introduced a new directory structure where the web-accessible root moved from `moodle/` to `moodle/public/`. This required changes across several files.

## Summary of Changes (`git diff`)

| File | What changed | Why |
|:-----|:-------------|:----|
| `config.yml` | Changed moodle-docker repo URL from a fork (`eloquenza/moodle-docker`) to the official [`moodlehq/moodle-docker`](https://github.com/moodlehq/moodle-docker) | The official repo now has the changes needed; the fork is no longer required |
| `moodle-versions-to-supported-php-versions.yaml` | Added entries for Moodle **4.4**, **4.5**, **5.0**, and **5.1** with their supported PHP version ranges | These Moodle releases didn't exist when the tool was last updated |
| `domain/moodle_version_utils.py` | **New file** — `uses_public_webroot()` function | Determines if a Moodle version uses `public/` as the webroot (≥ 5.1) |
| `domain/__init__.py` | Added import of `uses_public_webroot` | Makes the helper available to other modules |
| `domain/git.py` | Changed default branch from `master` to `main` | The moodle-docker repo renamed its default branch |
| `cross_cutting/template_engine.py` | `docker_customisation()` now accepts `moodle_version` parameter; dynamically sets the mount path | Moodle ≥ 5.1 mounts theme at `/var/www/html/public/theme/boost_union` instead of `/var/www/html/theme/boost_union` |
| `cross_cutting/templates/local.yml` | Hardcoded path replaced with `$REPLACE_THEME_MOUNT_PATH` placeholder | Allows dynamic mount path based on Moodle version |
| `domain/test_container.py` | `smartdata.php` path now uses `public/` prefix for Moodle ≥ 5.1 | The data generator is a web script and must live in `public/` for Moodle 5.1+ |
| `domain/test_infrastructure.py` | Copies `smartdata.php` to `moodle/public/` for Moodle ≥ 5.1; passes `moodle_version` to `docker_customisation()` | Ensures files end up in the correct webroot |
| `poetry.lock` | Updated dependency versions | Dependency resolution after adding/updating packages |
