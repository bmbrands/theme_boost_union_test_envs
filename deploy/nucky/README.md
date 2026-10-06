# nucky (acceptance server) deployment

Files here are the source of truth for the server setup on nucky
(`root@192.168.2.17`, public via ngrok).

| File | Installed as |
|---|---|
| `deploy.sh` | `/opt/boost-union-envs/deploy.sh` (symlink) |
| `boost-union-api.service` | `/etc/systemd/system/boost-union-api.service` (installed by `deploy.sh`) |
| `boost-union-reap.cron` | `/etc/cron.d/boost-union-reap` (installed by `deploy.sh`) |
| `boost-union-api.env.example` | template for `/etc/boost-union-api.env` (secrets, not in git) |
| `mailhog/docker-compose.yml` | MailHog test mail catcher (container `mailhog`, restarts with docker) |

Deploy after pushing to `production`:

```bash
ssh root@192.168.2.17 /opt/boost-union-envs/deploy.sh all
```

Services that must be running: `boost-union-api`, `nginx`, `docker`, `cron`
(all enabled at boot) and `ngrok http 80` (started by hand in `screen`).

The active environment file is chosen with `BOOST_UNION_ENV=env.nucky.yml`
(set in the unit and the cron file), so `config.yml` stays unmodified.
Runtime state (`example_pwd/`: infrastructure, users, plugins, settings incl.
lifecycle + email) is not in git.

## Test email (MailHog)

All mail can be caught by MailHog instead of being delivered:

```bash
cd /opt/boost-union-envs/backend
docker compose -f deploy/nucky/mailhog/docker-compose.yml up -d
```

In the frontend, Admin Settings → Email: host `127.0.0.1`, port `1025`,
security `None`, no username/password. Read the mail at
http://192.168.2.17:8025 (LAN only).
