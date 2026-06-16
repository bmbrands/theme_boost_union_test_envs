# Authentication & User Management

The provisioner ships with a small, self-contained authentication layer so the
API and the web UI are not open to the world. It is intentionally simple — no
external identity provider, no database — while still following sensible
security practices.

## Overview

- **Session cookies, not tokens in JS.** After a successful login the backend
  sets a signed, **HTTP-only** cookie (`mp_session`). Because the cookie is not
  readable from JavaScript it is not exposed to XSS-based token theft.
- **Passwords are hashed with bcrypt.** Plain-text passwords are never stored.
- **Admin-managed users.** There is no public sign-up. An administrator creates
  accounts; each new user must change their password on first sign-in.
- **Single organisation.** All users belong to one default organisation
  (`Boost Union`). The concept is kept in the data model for UI compatibility
  but is not multi-tenant.

## Where data lives

Everything is stored in the configured **working directory**
(`working_dir` in your `env.*.yml`, e.g. `./example_pwd`):

| File | Purpose | Notes |
| --- | --- | --- |
| `users.yaml` | The user directory (bcrypt password hashes, roles, status). | Atomic writes; treat as a secret. |
| `.session_secret` | Random key used to sign session cookies. | Auto-generated, `chmod 600`. Delete to invalidate all sessions. |
| `infra_owners.yaml` | Maps each environment to the user who created it. | Drives the "Owner" column in the UI. |

> These files should **not** be committed to source control. Add them to
> `.gitignore` if your working directory lives inside the repo.

## First run / bootstrapping

On startup the backend ensures an initial administrator exists. It reads two
environment variables:

| Variable | Default | Description |
| --- | --- | --- |
| `BOOTSTRAP_ADMIN_EMAIL` | `admin@localhost` | Email of the seeded admin. |
| `BOOTSTRAP_ADMIN_PASSWORD` | _(empty)_ | Password for the seeded admin. |

Behaviour:

- If `BOOTSTRAP_ADMIN_PASSWORD` is set, the admin is created with that password.
- If it is **not** set, a random password is generated and **logged once** at
  startup. Watch the server log for a line like
  `Seeded initial admin '…' from BOOTSTRAP_ADMIN_PASSWORD …`.
- In all cases the seeded admin is flagged `must_change_password`, so the first
  sign-in forces a password change.

Seeding only happens when there are no users yet; on subsequent starts the
existing `users.yaml` is used unchanged.

### Example

```bash
export BOOTSTRAP_ADMIN_EMAIL="you@example.org"
export BOOTSTRAP_ADMIN_PASSWORD="a-strong-temporary-password"
export SESSION_SECRET="$(openssl rand -hex 32)"   # recommended in production

python -m uvicorn \
  theme_boost_union_test_envs.ui.api.server:create_app \
  --factory --reload --port 8000
```

## Configuration reference

| Variable | Default | Description |
| --- | --- | --- |
| `BOOTSTRAP_ADMIN_EMAIL` | `admin@localhost` | Seeded admin email (first run only). |
| `BOOTSTRAP_ADMIN_PASSWORD` | _(random)_ | Seeded admin password (first run only). |
| `SESSION_SECRET` | _(persisted random)_ | Key used to sign session cookies. Set a stable value in production so sessions survive restarts and are consistent across processes. |
| `SESSION_COOKIE_SECURE` | `false` | When truthy, the session cookie is only sent over HTTPS. **Enable this in production.** |

Fixed (non-configurable) parameters:

- Cookie name: `mp_session`
- Cookie attributes: `HttpOnly`, `SameSite=Lax`
- Session lifetime: 8 hours
- Minimum password length: 8 characters
- Brute-force throttle: 5 failed logins per email+IP within 60 seconds → `429`

## Security model

- **Password storage** — bcrypt with per-password salt. Verification is
  constant-time, and login performs a dummy hash comparison for unknown emails
  so response timing does not reveal whether an account exists.
- **Session integrity** — the cookie payload (`{uid, session_version}`) is
  signed and time-stamped with `itsdangerous`. Tampered or expired cookies are
  rejected.
- **Session invalidation** — each user record carries a `session_version`.
  Changing a password (or an admin resetting one) bumps the version, which
  immediately invalidates every previously issued cookie for that user.
- **Forced password change** — users with `must_change_password = true` can
  authenticate but are blocked from all protected endpoints until they set a new
  password. The UI routes them straight to the change-password form.
- **Brute-force protection** — repeated failed logins for the same email+IP are
  throttled with a short lockout window.
- **Admin safety rails** — the API refuses to delete or demote the **last**
  active administrator, and an admin cannot delete or deactivate their own
  account. This prevents accidentally locking everyone out.

## Roles & permissions

Two built-in roles are defined (backend `cross_cutting/roles.py`, mirrored in the
frontend `types/user.ts`):

| Role | Permissions |
| --- | --- |
| **Tester** | View / create / delete environments. |
| **Administrator** | Everything a tester can do, plus host metrics, admin settings, user management, and audit log access. |

Permission checks are resource/action pairs (e.g. `environments:write`,
`users:admin`, `system:admin`). The frontend derives its capability flags
(`canManageUsers`, `canViewMetrics`, …) from the signed-in user's roles, and the
backend independently enforces the same checks — the UI never grants access the
API would deny.

## API endpoints

### Authentication (`/api/auth`)

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `POST` | `/login` | none | Authenticate; sets the session cookie. `401` on bad credentials, `429` when throttled. |
| `POST` | `/logout` | cookie | Clears the session cookie (`204`). |
| `GET` | `/me` | cookie | Returns the current user. `401` if not signed in. |
| `POST` | `/change-password` | cookie | Change own password; re-issues the cookie and invalidates old sessions. |

### User management (`/api/users`) — admin only

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `` | List users. |
| `GET` | `/roles` | List available roles. |
| `POST` | `` | Create a user (forces password change on first login). |
| `PATCH` | `/{user_id}` | Update profile, roles, active status, or reset password. |
| `DELETE` | `/{user_id}` | Delete a user (last-admin / self-delete protected). |

All other application routers (infrastructures, plugins, moodle, audit,
settings, logs) require a valid, fully-activated session.

## How the frontend ties in

- `services/api.ts` exposes `login`, `logout`, `fetchCurrentUser`,
  `changePassword`, and the user-management calls. They send the session cookie
  automatically (`credentials: "include"`).
- `hooks/useAuth.ts` resolves the current session on load, exposes
  `login` / `logout` / `changePassword`, and derives permission flags.
- `components/LoginScreen.tsx` renders the sign-in form and the forced
  password-change form.
- `App.tsx` gates the whole application: it shows a loading state while the
  session resolves, the login screen when unauthenticated, and the
  password-change screen when a change is required.

In development the Vite dev server proxies `/api` to the backend, so the cookie
is treated as same-origin and works without extra configuration.

## Operational notes

- **Resetting everything:** stop the server and delete `users.yaml` (and
  optionally `.session_secret`) from the working directory, then restart to
  re-bootstrap a fresh admin.
- **Rotating the signing key:** change `SESSION_SECRET` (or delete
  `.session_secret`). All existing sessions are invalidated.
- **Production checklist:** set a stable `SESSION_SECRET`, set
  `SESSION_COOKIE_SECURE=true`, serve over HTTPS, and provide a strong
  `BOOTSTRAP_ADMIN_PASSWORD` on first run.
