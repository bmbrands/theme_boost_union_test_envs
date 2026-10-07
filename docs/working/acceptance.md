# Working with: nucky (acceptance)

nucky runs the `production` branch so changes can be accepted before they go
to the Plesk server. How it is set up: [Setup: nucky](../setup/acceptance.md).

| | |
|:--|:--|
| SSH | `ssh root@192.168.2.17` (LAN) |
| Application | `https://catachrestic-francoise-indomitably.ngrok-free.dev` |
| MailHog (caught email) | `http://192.168.2.17:8025` (LAN only) |
| Swagger | `<application URL>/docs` |

## Deploy

After pushing to `production` (see [Working with: local](dev.md#commit-push-release)):

```bash
ssh root@192.168.2.17 /opt/boost-union-envs/deploy.sh all        # or: backend | frontend
```

`deploy.sh` (from `deploy/nucky/`, so it updates itself) does:

- **backend:** `git pull --ff-only`; reinstalls pip packages if
  `pyproject.toml` changed; installs the systemd unit and the reaper cron file
  when they differ from the repo; restarts `boost-union-api`.
- **frontend:** discards the previous local build in `dist/`, `git pull
  --ff-only`, `npm install`, `npx vite build`. nginx serves `dist/` directly,
  so the new version is live immediately (browsers may need a hard refresh).

Running environments are not touched by a deploy.

## After a reboot

Everything starts by itself except ngrok:

```bash
ssh root@192.168.2.17
screen -S ngrok          # or: screen -r  to re-attach an existing one
ngrok http 80            # detach with Ctrl-A D
```

Check the rest:

```bash
systemctl is-active boost-union-api nginx docker cron
docker ps --filter name=mailhog
curl -s http://127.0.0.1:4040/api/tunnels | head -c 300     # ngrok tunnel URL
```

Moodle containers do **not** restart after a reboot; start them in the UI.

## Logs

```bash
journalctl -u boost-union-api -f -n 100       # API (also visible in the UI: server logs panel)
tail -f /var/log/boost-union-reap.log         # reaper runs every 15 minutes
tail -f /opt/boost-union-envs/backend/example_pwd/.nginx/*.log 2>/dev/null   # nginx, if configured
```

## Lifecycle automation and email

- The policy (auto-stop, cleanup) and the email settings are edited in the UI:
  **Admin Settings → Lifecycle / Email**. They are stored in
  `example_pwd/settings.yaml` and read by the reaper on every run. See
  [Lifecycle & email](../reference/lifecycle-and-email.md).
- nucky uses short test values (e.g. 20 minutes runtime, 1 day retention), so
  instances disappear quickly.
- Email goes to **MailHog** (`127.0.0.1:1025`, security *None*); nothing is
  delivered. Read it at `http://192.168.2.17:8025`.

Preview or force the reaper by hand:

```bash
cd /opt/boost-union-envs/backend
export BOOST_UNION_ENV=env.nucky.yml
/opt/boost-union-envs/venv/bin/python scripts/reap_instances.py --dry-run
/opt/boost-union-envs/venv/bin/python scripts/reap_instances.py --dry-run --now 2026-10-08T12:00:00
```

To pause automation, switch it off in the Lifecycle tab (no need to touch cron).

## Using the CLI on nucky

Always set the environment and use the venv:

```bash
cd /opt/boost-union-envs/backend
BOOST_UNION_ENV=env.nucky.yml /opt/boost-union-envs/venv/bin/python -m theme_boost_union_test_envs list
```

See [CLI](../reference/cli.md).

## Troubleshooting

| Symptom | Check |
|:--|:--|
| Public URL shows nothing | Is ngrok running (`screen -ls`, `curl 127.0.0.1:4040/api/tunnels`)? Does `curl -I http://localhost/` return 200? Then it is the browser: hard refresh / private window / click through the ngrok warning page. |
| UI loads, API calls fail | `systemctl status boost-union-api`, `journalctl -u boost-union-api -n 50`. |
| Moodle URL gives the SPA or 404 | Is the container running (`docker ps`)? Does `example_pwd/.nginx/testenvs/<env>-<version>.conf` exist? `nginx -t && systemctl reload nginx`. See [Request flow](../reference/request-flow-nl.md). |
| Test email fails | Is MailHog up (`docker ps --filter name=mailhog`)? The error from the SMTP server is shown in the toast. |
| Instance stopped/deleted unexpectedly | `/var/log/boost-union-reap.log` lists every action with its reason. |
