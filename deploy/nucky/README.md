# nucky (acceptance server) deployment files

Source of truth for the server configuration of nucky (`root@192.168.2.17`,
public via ngrok). Full documentation:
[Setup: nucky](../../docs/setup/acceptance.md) and
[Working with: nucky](../../docs/working/acceptance.md).

| File | Installed as |
|:--|:--|
| `deploy.sh` | `/opt/boost-union-envs/deploy.sh` (symlink) |
| `boost-union-api.service` | `/etc/systemd/system/boost-union-api.service` (installed by `deploy.sh` when changed) |
| `boost-union-reap.cron` | `/etc/cron.d/boost-union-reap` (installed by `deploy.sh` when changed) |
| `boost-union-api.env.example` | template for `/etc/boost-union-api.env` (secrets, not in git) |
| `mailhog/docker-compose.yml` | MailHog test mail catcher (container `mailhog`) |

Deploy after pushing to `production`:

```bash
ssh root@192.168.2.17 /opt/boost-union-envs/deploy.sh all
```
