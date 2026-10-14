---
name: deploy
description: Deploy the Moodle Provisioner to nucky (acceptance, phase2) or prepare a Plesk (production) update. Use after committing and pushing, or when the user asks to deploy, update a server, or check that a server is running.
---

# Deploy

Always commit and push first. Run `ssh` with the sandbox disabled.

## nucky (acceptance, branch `phase2`)

```bash
ssh root@192.168.2.17 /opt/boost-union-envs/deploy.sh all      # or backend | frontend
```

`deploy.sh` pulls (`--ff-only`), installs the systemd unit / cron file from
`deploy/nucky/` when they changed, restarts `boost-union-api`, and rebuilds the
frontend (it discards the previous local `dist/` build first).

Verify:

```bash
ssh root@192.168.2.17 'systemctl is-active boost-union-api nginx docker cron;
  git -C /opt/boost-union-envs/backend log --oneline -1; git -C /opt/boost-union-envs/frontend log --oneline -1;
  curl -s -o /dev/null -w "api %{http_code}\n" http://127.0.0.1:8000/api/auth/me;   # 401 = up
  cd /opt/boost-union-envs/backend && BOOST_UNION_ENV=env.nucky.yml /opt/boost-union-envs/venv/bin/python scripts/reap_instances.py --dry-run'
curl -s -o /dev/null -w "public %{http_code}\n" -H "ngrok-skip-browser-warning: 1" https://catachrestic-francoise-indomitably.ngrok-free.dev/
```

Public URL down → ngrok is not running (`screen -ls`, `curl 127.0.0.1:4040/api/tunnels`); the user restarts it.

## Plesk (production, branch `production`)

`sudo` needs a password, so **the user runs the root/operator steps**. You may
only inspect, read-only:

```bash
ssh bas@244.184.205.92.host.secureserver.net 'G="git -c safe.directory=*"; for d in /opt/boost-union-envs/backend /opt/boost-union-envs/frontend; do $G -C $d log --oneline -1; $G -C $d status -sb | head -3; done'
```

Give the user these steps (adapt to what changed):

```bash
sudo -i -u boost-union-testing
cd /opt/boost-union-envs/backend && git pull --ff-only
# frontend changed:
cd /opt/boost-union-envs/frontend && git checkout -- dist && git pull --ff-only && npm install --no-audit --no-fund && npx vite build
exit
# frontend changed: publish the build
cd /var/www/vhosts/focused-cray.92-205-184-244.plesk.page && rm -rf site1 && cp -a /opt/boost-union-envs/frontend/dist site1 && chown -R boost-union-testing site1
sudo systemctl restart boost-union-api
```

Plesk keeps local edits in `config.yml` and `env.prod.yml`; never overwrite them.
See `docs/working/production.md` and `docs/setup/production.md`.
