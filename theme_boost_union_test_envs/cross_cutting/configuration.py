import sys
from pathlib import Path
from typing import Any, cast

import yaml
from packaging import version

from ..exceptions import BoostUnionTestEnvValueError

# Core related keys in config
PWD = "working_dir"

# Repo related keys in config
REPO = "repos"
BU = "boost_union"
MDL_DKR = "moodle_docker"
URL = "url"

# Proxy related keys in env file
NGINX = "nginx"
WWW_BASE = "base_url"
CERT_PATH = "cert_chain_path"
PKEY_PATH = "cert_key_path"
HTML_PATH = "overview_page_path"
PROXY = "proxied"
SOFTLINKED_DIR = "softlinked_nginx_config_path"
TEMPLATE = "template"
SCHEME = "scheme"
DEFAULT_PRODUCTION_TEMPLATE = "plesk_production_nginx.conf"


class ApplicationConfigManager:
    def __init__(
        self,
        config: dict[Any, Any],
        moodle_versions_to_php_versions: dict[Any, Any],
        environment_file: Path,
    ) -> None:
        # for some reason, the passed arguments 'config' and 'moodle_versions_to_php_versions' are not of type providers.Configuration anymore, which makes saving it and accessing all elements with the dot notation not possible

        # reading environment-related configs from yaml
        with environment_file.open("r") as env:
            # don't forget, it's python: no need to forward_declare before
            environment = yaml.safe_load(env)

        # converting the int/str values from the read yaml into actual version types
        self.moodle_versions_to_php_versions = {
            version.parse(str(moodle_ver)): [
                version.parse(str(ver)) for ver in php_vers
            ]
            for moodle_ver, php_vers in moodle_versions_to_php_versions.items()
        }

        # just exposing the values that are actual of value for cross cutting
        # concerns
        # path related settings
        self.working_dir = self.get_path(environment[PWD])
        self.infra_yaml = self.working_dir / "infrastructure.yaml"
        # nginx related settings
        self.nginx_dir = self.working_dir / ".nginx/"
        self.softlinked_nginx_path = Path(environment[NGINX][SOFTLINKED_DIR])
        self.base_url = environment[NGINX][WWW_BASE]
        # implicitly truthy as python transforms yes and no
        self.is_proxied = environment[PROXY]
        # if we are setting up new test environments behind a proxy, the
        # overview page path is needed so the docroot is known. SSL cert
        # paths are only required by templates that actually terminate TLS
        # in nginx (e.g. plesk); hosts that put TLS in front (e.g. ngrok
        # in front of `nucky`) may leave them empty.
        if self.is_proxied and not environment[NGINX][HTML_PATH]:
            raise BoostUnionTestEnvValueError(
                "overview_page_path must be set when proxied is enabled"
            )
        # do not try to provide a default here, no sensible option left
        self.cert_chain_path = environment[NGINX][CERT_PATH]
        self.cert_key_path = environment[NGINX][PKEY_PATH]
        # which production nginx template the overview vhost should be
        # generated from. Backwards compatible: defaults to the plesk one.
        self.production_nginx_template = (
            environment[NGINX].get(TEMPLATE) or DEFAULT_PRODUCTION_TEMPLATE
        )
        # scheme used in stored Moodle URLs when the deployment is proxied.
        # Defaults to https for backwards compatibility (plesk + letsencrypt).
        # Set to "http" for setups without TLS (e.g. nucky on the LAN).
        self.scheme = environment[NGINX].get(SCHEME) or "https"
        # default to working_dir/index.html; allows for debugging it
        self.overview_page_path = (
            self.working_dir
            if not environment[NGINX][HTML_PATH]
            else Path(environment[NGINX][HTML_PATH])
        )
        self.overview_page_index = self.overview_page_path / "index.html"
        # moodle related settings
        self.moodle_cache_dir = self.working_dir / ".moodles/"
        self.moodle_docker_dir = self.working_dir / ".moodle-docker"
        self.moodle_docker_repo_url = config[REPO][MDL_DKR][URL]
        # boost union related settings
        self.boost_union_base_directory_name = "theme/boost_union"
        self.boost_union_repo_url = config[REPO][BU][URL]

    def get_path(self, path_name: str) -> Path:
        return Path(path_name).resolve()


def config() -> ApplicationConfigManager:
    # hacky, but hides implementation detail about the singleton and allows us
    # to avoid the circular dependency issues if each import is directly
    # embedded into the services
    from ..app import Application

    # sometimes mypy is just a funny thing.
    return cast(
        ApplicationConfigManager, Application().cross_cutting_concerns.config_manager()
    )
