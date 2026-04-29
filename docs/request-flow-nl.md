# Hoe een request naar `http://192.168.2.25/mont-test/5.1.4/` werkt

Hieronder loop ik de hele keten door, in de volgorde waarin het request reist.

---

## 0. Vertrekpunt — de URL

```
http://192.168.2.25/mont-test/5.1.4/
└── host ──┘└─ infra ─┘└─ver┘
```

`192.168.2.25` is `nucky` (Debian 13). Poort 80, want `http://`. Geen
poortnummer in de URL — dat is precies het hele punt van deze opzet.

---

## 1. TCP verbinding op poort 80 → **nginx** op de host

Op nucky luistert maar één proces op poort 80: **nginx** (Debian package,
`systemctl is-active nginx`). Apache is geïnstalleerd maar uitgeschakeld
(`systemctl disable apache2`).

De vhost die nginx laadt is een symlink:

```
/etc/nginx/sites-enabled/boost-union
   → /opt/boost-union-envs/backend/example_pwd/.nginx/192.168.2.25.conf
```

Die `192.168.2.25.conf` is **niet handgeschreven** — hij is gegenereerd
door de Python backend uit het template
[`nucky_production_nginx.conf`](../theme_boost_union_test_envs/cross_cutting/templates/nucky_production_nginx.conf)
(geselecteerd via `nginx.template:` in [env.nucky.yml](../env.nucky.yml)).
De rendering gebeurt door
[`TemplateEngine.overview_nginx_config()`](../theme_boost_union_test_envs/cross_cutting/template_engine.py).

In die outer-vhost staat onderaan een `include`-regel:

```nginx
include /etc/nginx/conf.d/boost-union/testenvs/*.conf;
```

Die directory is óók een symlink:

```
/etc/nginx/conf.d/boost-union/testenvs
   → /opt/boost-union-envs/backend/example_pwd/.nginx/testenvs/
```

Dus: **elke** `.conf` die de Python app daar neerzet (één per
Moodle-omgeving) wordt automatisch onderdeel van de nginx-config.

### Welke locations matcht nginx?

Voor onze URL zijn er drie kandidaten in volgorde van specificiteit:

| Location | Backend |
|:---|:---|
| `location /api/`, `/docs`, `/openapi.json` | proxy naar `127.0.0.1:8000` (FastAPI) |
| `location /mont-test/5.1.4` (uit `mont-test-5.1.4.conf`) | proxy naar `127.0.0.1:<random_port>` (Moodle container) |
| `location /` | static files uit `/var/www/html` (de SPA) |

Onze URL begint met `/mont-test/5.1.4`, dus de **tweede** location wint.
Die location ziet er — gerenderd uit
[`templates/moodle_nginx.conf`](../theme_boost_union_test_envs/cross_cutting/templates/moodle_nginx.conf)
— zo uit:

```nginx
location /mont-test/5.1.4 {
    proxy_pass http://127.0.0.1:47833;   # let op: GEEN trailing slash
    proxy_set_header Host $http_host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    ...
}
```

> **Cruciaal detail**: er staat **geen `/` achter de `proxy_pass` URL**.
> Dat betekent: nginx forward de **volledige originele URI**
> (`/mont-test/5.1.4/`) ongewijzigd door naar de upstream. Mét slash zou
> nginx het prefix afknippen en alleen `/` doorsturen — dan zou Moodle
> merken dat zijn `$CFG->wwwroot` niet matcht en een 303-redirect
> terugsturen naar de bare host, en dan zou het request alsnog op de SPA
> uitkomen.

De `47833` is een willekeurige vrije poort die de Python backend bij
creatie kiest (`environment_file()` in `template_engine.py`) en in `.env`
van die Moodle-omgeving zet.

---

## 2. TCP naar `127.0.0.1:47833` → **Apache in de Moodle Docker container**

Die poort is gepubliceerd door `docker compose` van de per-env stack. De
compose-stack zelf is gestart met `bin/moodle-docker-compose` (een wrapper
die in elke env-directory wordt gegenereerd) en gebruikt het master-template
[`templates/local.yml`](../theme_boost_union_test_envs/cross_cutting/templates/local.yml).

In de `.env` van die env staat:

```
MOODLE_DOCKER_WEB_PORT=0.0.0.0:47833
```

→ Docker mapt `0.0.0.0:47833` op de host naar **poort 80 in de container**.
(We binden expliciet op `0.0.0.0` zodat het LAN er ook bij kan;
moodle-docker-compose zou anders `127.0.0.1:` voorzetten.)

In de container draait een Apache (httpd) die **moodle-docker** standaard zo
configureert: `DocumentRoot /var/www/html` (of `/var/www/html/public` voor
Moodle 5.1+).

Maar… Apache krijgt nu een request voor `/mont-test/5.1.4/` binnen, terwijl
zijn DocumentRoot gewoon `/var/www/html` is. Default zou dat een **404**
geven.

### De fix: een `Alias` per env

Bij het aanmaken van de env schrijft
[`TemplateEngine.docker_customisation()`](../theme_boost_union_test_envs/cross_cutting/template_engine.py)
een klein snippet uit
[`templates/apache-prefix.conf`](../theme_boost_union_test_envs/cross_cutting/templates/apache-prefix.conf):

```apache
Alias /mont-test/5.1.4 /var/www/html/public
<Directory /var/www/html/public>
    Options FollowSymLinks
    AllowOverride All
    Require all granted
</Directory>
```

Dat bestand wordt via een **bind-mount** in `local.yml` (de
`$REPLACE_PROXY_OVERRIDES` expansie) in de container gemount als:

```
/etc/apache2/conf-enabled/moodle-prefix.conf
```

Apache pikt het bij start op en weet nu: "request voor
`/mont-test/5.1.4/...` → bedien uit `/var/www/html/public`". Apache geeft
het door aan PHP-FPM / mod_php → Moodle's `index.php` draait.

---

## 3. Moodle's interne sanity-check → `$CFG->wwwroot`

In `lib/setuplib.php` controleert Moodle of de URL waarop hij benaderd
wordt overeenkomt met `$CFG->wwwroot`. Komt dat niet overeen → 303 redirect
naar `$CFG->wwwroot` (en dan komt het request weer bij nginx binnen, valt
op `location /`, krijgt de SPA — precies de bug die we eerder hadden).

`$CFG->wwwroot` wordt opgebouwd in `config.docker-template.php`:

```php
$CFG->wwwroot = "http://" . MOODLE_DOCKER_WEB_HOST
              . (MOODLE_DOCKER_WEB_PORT ? ":" . MOODLE_DOCKER_WEB_PORT : "");
```

Voor onze env zet de Python backend in de `environment:` sectie van
`local.yml`:

| Variabele in container | Waarde |
|:---|:---|
| `MOODLE_DOCKER_WEB_HOST` | `192.168.2.25/mont-test/5.1.4` |
| `MOODLE_DOCKER_WEB_PORT` | `""` (leeg!) |

Dus binnen de container: `$CFG->wwwroot = "http://192.168.2.25/mont-test/5.1.4"`.
Dat klopt **exact** met wat de gebruiker intypt → Moodle is tevreden, geen
redirect.

> Belangrijk om te beseffen: de **compose-time**
> `${MOODLE_DOCKER_WEB_PORT}` uit `.env` (waarmee de poort `47833:80`
> gebonden wordt) is wél gevuld. De **runtime** override op `""` werkt
> alleen ín de container, ná dat Docker de port-mapping al heeft opgezet.
> Twee verschillende fases, dezelfde naam — verwarrend maar werkt.

---

## 4. Het antwoord terug

Moodle PHP rendert HTML → Apache stuurt response → nginx ziet de response
(eventueel met `Location:` headers van interne redirects, die kloppen omdat
`$CFG->wwwroot` correct staat) → browser krijgt 200 met de Moodle
install/login pagina.

---

## Samengevat in één diagram

```
Browser
  │  GET http://192.168.2.25/mont-test/5.1.4/
  ▼
nginx  (host nucky, port 80)
  │  vhost: example_pwd/.nginx/192.168.2.25.conf
  │  matches: location /mont-test/5.1.4
  │  proxy_pass http://127.0.0.1:47833   (URI ongewijzigd)
  ▼
Docker port-mapping  0.0.0.0:47833 → container:80
  ▼
Apache  (in moodle webserver container)
  │  Alias /mont-test/5.1.4  →  /var/www/html/public
  │  conf-enabled/moodle-prefix.conf  (bind-mount uit apache-prefix.conf)
  ▼
PHP / Moodle  index.php
  │  $CFG->wwwroot = http://192.168.2.25/mont-test/5.1.4
  │  (MOODLE_DOCKER_WEB_PORT="" → geen poort in URL)
  ▼
HTML response  →  Apache  →  nginx  →  Browser
```

---

## Wie zorgt waarvoor

| Stuk | Gegenereerd door | Template | Wanneer |
|:---|:---|:---|:---|
| Outer nginx vhost | `TemplateEngine.overview_nginx_config()` | `nucky_production_nginx.conf` | bij eerste setup / als de overview verandert |
| Per-Moodle nginx snippet | `TemplateEngine.moodle_nginx_config()` | `moodle_nginx.conf` | bij `create_infrastructure` per versie; gevolgd door `_reload_nginx_if_available()` |
| Apache Alias snippet | `TemplateEngine.docker_customisation()` | `apache-prefix.conf` | bij create, geschreven in env-dir, bind-mounted via `local.yml` |
| Compose `local.yml` met `$REPLACE_PROXY_OVERRIDES` | idem | `local.yml` | idem; `safe_substitute` zodat `${VAR}` in YAML-comments niet ploft |
| `.env` met `MOODLE_DOCKER_WEB_HOST` + `WEB_PORT=0.0.0.0:<vrije_poort>` | `TemplateEngine.environment_file()` | inline | idem |

De FastAPI backend zelf draait in `boost-union-api.service` (uvicorn op
`127.0.0.1:8000`) en wordt door nginx alleen aangesproken voor `/api/`,
`/docs` en `/openapi.json` — die paden zien we nooit in dit verhaal omdat
onze URL met `/mont-test/...` begint.

---

## Zie ook

- [serverlog.md](serverlog.md) — volledige deployment-log van nucky, inclusief
  sectie 10 met de path-based reverse-proxy details (`proxy_pass` zonder
  trailing slash, `MOODLE_DOCKER_WEB_PORT=""` override, etc.).
- [installation.md](installation.md) — installatie-instructies voor lokaal en
  productie.
