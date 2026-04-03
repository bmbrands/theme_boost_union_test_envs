# Installation

## Prerequisites

- **Python 3.11+**
- **Docker** and **Docker Compose**
- **Git**
- **Conda** (recommended for Python version management)

### Why Conda?

Conda ensures you have the exact Python version (3.11) regardless of your system Python. It isolates the project's dependencies in a virtual environment without interfering with other Python projects.

## Setup

```bash
# 1. Clone the repository
git clone git://github.com/eloquenza/theme_boost_union_test_envs

# 2. Create and activate the conda environment
conda create -n boost-union-envs python=3.11
conda activate boost-union-envs

# 3. Install Poetry (Python package manager)
pip install poetry

# 4. Install project dependencies
poetry install

# 5. Deactivate when done
conda deactivate
```

Afterwards, you can run:

```bash
./boost-union-envs
```

This will present you with a help screen describing all available commands.

The next time you want to run the application, activate the conda environment first:

```bash
conda activate boost-union-envs
```

## Configuration

Edit `env.local.yml` to set your working directory and Nginx settings:

```yaml
working_dir: "./my_testbed"
proxied: no
nginx:
  base_url: "localhost"
  cert_chain_path: ""
  cert_key_path: ""
  overview_page_path: ""
  softlinked_nginx_config_path: ""
```

Set `proxied: yes` for production servers with Nginx reverse proxy and HTTPS (requires cert paths).

## Environment Configuration (`env.local.yml` / `env.prod.yml`)

The tool supports **two environment configurations** that control how and where test environments are deployed. Which file is active is determined by a single line in `config.yml`:

```yaml
# config.yml
environment: "env.local.yml"
```

Change this value to switch environments:

```yaml
environment: "env.prod.yml"
```

### How It Works Internally

1. `app.py` reads the `environment` key from `config.yml` and resolves it to a file path
2. That path is injected into `ApplicationConfigManager` (in `cross_cutting/configuration.py`)
3. `ApplicationConfigManager` parses the YAML and exposes settings like `working_dir`, `base_url`, `is_proxied`, certificate paths, etc.

All downstream code (template engine, nginx config generation, Docker environment files) uses these settings — it never reads the environment file directly.

### `env.local.yml` — Local Development

Used for running test environments on your own machine (the default):

```yaml
working_dir: "./example_pwd"
proxied: no
nginx:
  base_url: "localhost"
  cert_chain_path: ""
  cert_key_path: ""
  overview_page_path: ""
  softlinked_nginx_config_path: ""
```

- `proxied: no` — Moodle is accessed directly via `localhost:<port>`
- No certificates or Nginx reverse proxy needed
- `overview_page_path` and `softlinked_nginx_config_path` can be empty

### `env.prod.yml` — Production Server

Used for deploying test environments behind an Nginx reverse proxy with HTTPS (e.g. on a Plesk server):

```yaml
working_dir: "./example_pwd"
proxied: yes
nginx:
  base_url: "focused-cray.92-205-184-244.plesk.page"
  cert_chain_path: "/etc/letsencrypt/live/.../fullchain.pem"
  cert_key_path: "/etc/letsencrypt/live/.../privkey.pem"
  overview_page_path: "/var/www/vhosts/.../httpdocs"
  softlinked_nginx_config_path: "/etc/nginx/plesk.conf.d/vhosts/boost_union"
```

- `proxied: yes` — Enables reverse proxy mode with `plesk_production_nginx.conf` template
- `base_url` — The public hostname; Moodle URLs become `https://base_url/infra/version`
- `cert_chain_path` / `cert_key_path` — TLS certificate paths (e.g. Let's Encrypt)
- `overview_page_path` — Where the auto-generated `index.html` overview page is placed
- `softlinked_nginx_config_path` — Path where the generated nginx configs are symlinked so Nginx picks them up

### Key Differences

| Setting | `env.local.yml` | `env.prod.yml` |
|:--------|:-----------------|:----------------|
| `proxied` | `no` | `yes` |
| URL format | `http://localhost:<random_port>` | `https://base_url/infra/version` |
| Nginx template | `moodle_nginx.conf` (local) | `plesk_production_nginx.conf` |
| TLS certificates | Not needed | Required |
| Overview page | Local `index.html` in working dir | Copied to `overview_page_path` on server |
