---
name: local-ui-test
description: Run the Moodle Provisioner API and frontend locally and check a UI change in the built-in browser, including admin-only screens. Use to visually verify frontend changes before committing.
---

# Local UI test

1. Create `.claude/launch.json` (delete it afterwards):

```json
{
  "version": "0.0.1",
  "configurations": [
    { "name": "api", "runtimeExecutable": "/opt/homebrew/Caskroom/miniconda/base/envs/boost-union-envs/bin/python",
      "runtimeArgs": ["-m", "uvicorn", "theme_boost_union_test_envs.ui.api.server:create_app", "--factory", "--port", "8000"], "port": 8000 },
    { "name": "frontend", "runtimeExecutable": "npm",
      "runtimeArgs": ["--prefix", "moodle-provisioner-frontend", "run", "dev", "--", "--open=false"], "port": 5173 }
  ]
}
```

2. `preview_start` api, then frontend; open `http://localhost:5173`.
3. Log in with a local test account the user has given in chat (localhost
   only). The local `bas@sonsbeekmedia.nl` account is a *tester*: for admin
   screens back up `example_pwd/users.yaml` to the scratchpad, change its
   role to `admin`, restart the API, and **restore the backup afterwards**.
4. Prefer `find` + `ref` clicks over coordinates; screenshots can lag a render —
   take another one or read values with `javascript_tool` before concluding.
5. Clean up: `preview_stop` both servers, restore `users.yaml` /
   `settings.yaml` backups, remove `.claude/launch.json`.

Never log in on the ngrok or production URLs.
