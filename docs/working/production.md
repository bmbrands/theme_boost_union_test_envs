# Working with: Plesk (production)

The live system at `https://testsystem.moodle-an-hochschulen.de`. Only
deploy what has been accepted on [nucky](acceptance.md). How it is set up:
[Setup: Plesk](../setup/production.md).

!!! warning
    Production has no `deploy.sh` in git yet; the steps below follow the
    commands used on the server so far. Verify them on the server and turn
    them into a `deploy/plesk/deploy.sh` (see the setup page).

## Deploy

```bash
# 1. As the operator user: update both checkouts and build the frontend
sudo -i -u boost-union-testing
cd /opt/boost-union-envs/backend  && git pull --ff-only
cd /opt/boost-union-envs/frontend && git checkout -- dist && git pull --ff-only
npm install --no-audit --no-fund && npx vite build
exit

# 2. As root: publish the frontend and restart the API
cd /var/www/vhosts/focused-cray.92-205-184-244.plesk.page
rm -rf site1 && cp -a /opt/boost-union-envs/frontend/dist site1
chown -R boost-union-testing site1
systemctl restart boost-union-api
```

If `pyproject.toml` changed, install new dependencies into
`/opt/boost-union-envs/venv` first (same package list as in
[Setup: nucky](../setup/acceptance.md#2-code-and-python)).

## Check

```bash
systemctl is-active boost-union-api
curl -s -o /dev/null -w '%{http_code}\n' https://testsystem.moodle-an-hochschulen.de/            # 200
curl -s -o /dev/null -w '%{http_code}\n' https://testsystem.moodle-an-hochschulen.de/api/auth/me  # 401 = API up
```

## Logs

```bash
journalctl -u boost-union-api -f -n 100
tail -f /var/log/boost-union-cron.log                      # Moodle cron runner (every 5 min)
tail -f /var/log/boost-union-reap.log                      # reaper, once installed
tail -f /var/www/vhosts/system/testsystem.moodle-an-hochschulen.de/logs/proxy_error_log   # Plesk nginx
```

## Using the CLI

The CLI runs as the operator user:

```bash
sudo -i -u boost-union-testing
cd /opt/boost-union-envs/backend
./boost-union-envs list
./boost-union-envs setup second-test boost_union branch MOODLE_501_STABLE
./boost-union-envs build second-test 5.1.0
./boost-union-envs start second-test 5.1.0
```

The result is at `https://testsystem.moodle-an-hochschulen.de/second-test/5.1.0/`.
See [CLI](../reference/cli.md). Environments created with the CLI have no
owner in the UI.

## Settings

Lifecycle and email settings are edited in the UI (**Admin Settings**) and
stored in `example_pwd/settings.yaml` on the server. Use the real SMTP server
here and send a test before enabling deletion warnings. See
[Lifecycle & email](../reference/lifecycle-and-email.md).

Troubleshooting: see [Setup: Plesk](../setup/production.md#troubleshooting-from-the-original-installation).
