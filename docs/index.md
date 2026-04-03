# Boost Union Test Environments

A Python-based **Infrastructure-as-Code (IaC) tool** for managing Docker-based Moodle test environments for the [Boost Union](https://github.com/moodle-an-hochschulen/moodle-theme_boost_union) theme. Created by *Moodle an Hochschulen e.V.*

!!! info "In short"
    You give it a Boost Union git reference (branch, tag, PR, or commit) and one or more Moodle version numbers. It builds fully configured, running Moodle instances — each with the Boost Union theme installed, activated, and populated with test data — in a single command.

## How It Works

This tool wraps the standard [moodle-docker](https://github.com/moodlehq/moodle-docker) project and automates everything needed to go from *zero* to *running Moodle with Boost Union* in a few commands. The key concept is:

- An **infrastructure** is a specific version of the Boost Union theme (a git ref) that you want to test.
- Within each infrastructure, you can spin up **multiple Moodle versions** simultaneously — each in its own Docker container with its own port, database, and admin password.
- All Moodle containers within one infrastructure **share the same Boost Union source code** — edit the theme once, see the changes across all Moodle versions instantly.

### High-Level Flow

```
init  →  setup  →  build  →  start  →  [test manually]  →  stop  →  destroy  →  teardown
 │          │         │         │                              │         │           │
 │          │         │         ├─ Docker up + DB wait         │         │           │
 │          │         │         ├─ install_database.php        │         │           │
 │          │         │         ├─ Set theme to boost_union    │         │           │
 │          │         │         └─ Run data generator          │         │           │
 │          │         │                                        │         │           │
 │          │         ├─ Download Moodle source (cached)       │         │           │
 │          │         ├─ Copy moodle-docker into version dir   │         │           │
 │          │         ├─ Generate .env, local.yml, nginx       │         │           │
 │          │         └─ docker compose create                 │         │           │
 │          │                                                  │         │           │
 │          ├─ Clone Boost Union at git ref                    │         │           │
 │          └─ Create moodles/ directory                       │         │           │
 │                                                             │         │           │
 ├─ Clone moodle-docker repo                                   │         │           │
 ├─ Copy template files into clone                             │         │           │
 ├─ Download smartdata.php data generator                      │         │           │
 └─ Create working directories                                 │         │           │
                                                               │         │           │
                                                docker stop ◄──┘         │           │
                                          docker down + rm files ◄───────┘           │
                                              rm entire infrastructure ◄─────────────┘
```

## What It Automates on Top of moodle-docker

The standard [moodle-docker](https://github.com/moodlehq/moodle-docker) gives you a Docker Compose setup for *one* Moodle instance. You still need to manually download Moodle source, configure `.env`, set up volumes, install the database, configure themes, etc.

This tool automates **all of that** and adds multi-version/multi-infrastructure support:

| Task | Standard moodle-docker | This tool |
|:-----|:----------------------|:----------|
| **Moodle source download** | Manual download & extract | Auto-downloads from GitHub, caches on disk in `.moodles/` |
| **Theme volume mount** | Manually edit `local.yml` | Auto-generates `local.yml` with correct mount path (handles Moodle 5.1+ `public/` webroot) |
| **`.env` configuration** | Manually create with ports, PHP version, paths | Auto-generated with random free ports, random admin password, correct PHP Docker image tag |
| **PHP version selection** | Look up docs, set manually | Auto-selected from `moodle-versions-to-supported-php-versions.yaml` |
| **Database installation** | Run `install_database.php` manually | Auto-executed on `start` via `docker exec` |
| **Theme activation** | Log into Moodle admin UI | Auto-set via `admin/cli/cfg.php --name=theme --set=boost_union` |
| **Test data population** | Manual or no test data | Auto-runs `smartdata.php` data generator inside the container |
| **Multiple Moodle versions** | One instance at a time | N versions per infrastructure, each with unique ports |
| **Multiple infrastructures** | Not supported | N infrastructures (different Boost Union branches/PRs) side by side |
| **Reverse proxy (production)** | Not included | Auto-generates per-container Nginx location configs |
| **State tracking** | None | YAML "database" tracking status, URLs, ports, passwords |
| **Overview dashboard** | None | Auto-generated HTML page listing all environments |
