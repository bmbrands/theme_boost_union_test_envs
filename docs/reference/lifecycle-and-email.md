# Lifecycle automation & email

The **reaper** (`scripts/reap_instances.py`) runs from cron every 15 minutes.
It stops instances that run too long, deletes instances that stay stopped too
long, and emails owners before their instance is deleted. Everything is
**off by default**: nothing happens until an administrator enables it.

| Location | Scheduled? | Email goes to |
|:--|:--|:--|
| Local | no, run by hand | local MailHog, if configured |
| nucky | `/etc/cron.d/boost-union-reap` | MailHog (`http://192.168.2.17:8025`) |
| Plesk | not yet, see [Setup: Plesk](../setup/production.md#bringing-lifecycle-automation-and-email-to-production) | the association's SMTP server |

## Lifecycle policy

Edited in **Admin Settings → Lifecycle** (administrators only; every user can
read it). Stored in `example_pwd/settings.yaml` → `values.lifecycle`.

| Setting | Default | Meaning |
|:--|:--|:--|
| `auto_stop_enabled` | `false` | Stop long-running instances. Stopping keeps the data. |
| `max_runtime_minutes` | `480` | Stop an instance this long after it was last started. |
| `daily_stop_time` | `""` (off) | `HH:MM` in **UTC**. Also stop at the first occurrence of this time *after* the instance was started. |
| `auto_cleanup_enabled` | `false` | Delete idle instances, **including their data**. |
| `stopped_retention_days` | `7` | Delete an instance this many days after it was stopped. Instances that were created but never started count as stopped. |
| `cleanup_empty_infrastructures` | `true` | When all instances of an environment are due, tear down the whole environment (plugin checkout included). |

Rules:

- **Auto-stop time** = the earlier of *started + max runtime* and the next
  daily stop time after the start. An instance started at 17:00 with a daily
  stop at 16:00 runs until 16:00 the next day (or until its max runtime).
- **Auto-delete time** = *stopped + retention*. Starting the instance again
  resets it.
- The reaper runs every 15 minutes, so actions happen up to 15 minutes after
  the computed time.

The UI shows each instance's next **Auto stop** (running) or **Auto delete**
(stopped) time below its creation date, with a help popover that explains the
current policy. The API exposes the same values: `GET /api/lifecycle` and the
`auto_stop_at` / `auto_delete_at` fields (UTC) of `GET /api/infrastructures`.

## Email

Edited in **Admin Settings → Email** (administrators only). Stored in
`example_pwd/settings.yaml` → `values.email`.

### SMTP

| Setting | Notes |
|:--|:--|
| Host, port, security | `starttls` (587), `ssl` (465) or `none` (25 / MailHog 1025). |
| Username, password | Leave empty when no login is needed. The password is write-only in the UI and stored in plain text in `settings.yaml` (mode `600`). |
| Sender address and name | The `From:` header. |
| Provisioner URL | Link used in emails; empty = derived from the active `env.*.yml` (`scheme://base_url`). |
| Time zone | IANA name for dates in emails, default `Europe/Berlin`. |

**Send test** sends the deletion warning, filled with sample data (but the
real provisioner URL), to any address, using the values currently in the form
— also before saving. SMTP errors are shown in the notification.

### Deletion warning

| Setting | Default | Meaning |
|:--|:--|:--|
| Enabled | off | Send warnings at all. Only effective when auto-cleanup is on and SMTP is configured. |
| Hours before deletion | `24` | When to warn. If the deletion is already closer when the instance is stopped, the warning goes out on the next reaper run. |
| Subject, message | see the UI | Plain-text templates (Jinja2 syntax). |

Placeholders (the tab lists them and inserts them on click):

| Placeholder | Example |
|:--|:--|
| `{{ user_name }}`, `{{ user_email }}` | owner of the environment |
| `{{ environment }}`, `{{ moodle_version }}` | `my-feature-test`, `5.0.2` |
| `{{ instance_url }}` | the Moodle URL |
| `{{ portal_url }}`, `{{ server_name }}` | the provisioner URL and its host name |
| `{{ deletion_date }}`, `{{ stopped_since }}` | `8 Oct 2026, 14:30 CEST` |
| `{{ retention_days }}`, `{{ hours_before }}` | policy values |

Templates are rendered in a sandbox; an unknown placeholder is rejected when
saving, and the live preview shows the error while typing.

Each stop cycle is warned about **once**: the deadline that was warned about
is stored on the instance (`deletion_warning_sent_for` in
`infrastructure.yaml`). Starting and stopping again gives a new deadline and a
new warning. The recipient is the environment's owner (`created_by`);
environments without an owner (e.g. created with the CLI) are skipped and
logged.

## Running the reaper by hand

From the backend root (on servers with the venv Python and `BOOST_UNION_ENV`):

```bash
python scripts/reap_instances.py --dry-run                          # what would happen now
python scripts/reap_instances.py --dry-run --now 2026-10-08T12:00   # … at another moment (UTC)
python scripts/reap_instances.py                                    # really do it
```

Output (also in `/var/log/boost-union-reap.log` on servers):

```
2026-10-06 12:55:42  stop dollhouse/5.1.0 (running for 0:31:08 (> 30m max runtime))
2026-10-06 12:55:42  send deletion warning for numark-1/5.1.6 (deletion due 2026-10-07T12:55:10Z)
2026-10-06 12:55:43  deletion warning sent to owner@example.org for numark-1/5.1.6
2026-10-06 12:55:43  done: stopped=1 destroyed=0 torn_down=0 notified=1 failures=0 (planned 2)
```

The exit code is non-zero if any action failed. One failing instance never
stops the others from being processed.

## Code

| File | Role |
|:--|:--|
| `domain/lifecycle.py` | Policy, deadline computation (`compute_deadlines`), planning (`plan_actions`, pure) and execution. |
| `domain/notifications.py` | Email settings, templates, placeholder context, the reaper's notifier. |
| `cross_cutting/mailer.py` | SMTP client. |
| `cross_cutting/settings_store.py` | Atomic per-section access to `settings.yaml`. |
| `ui/api/routes/lifecycle.py`, `ui/api/routes/email.py` | API for the Admin Settings tabs. |
| `tests/test_lifecycle.py`, `tests/test_notifications.py`, `tests/test_admin_settings.py` | Tests. |
