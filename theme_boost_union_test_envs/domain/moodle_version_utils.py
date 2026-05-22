from packaging import version as pkg_version

# Moodle 5.1 moved the web-servable files into a "public/" subdirectory.
# This helper determines whether the given version uses that layout.
MOODLE_PUBLIC_WEBROOT_MIN_VERSION = pkg_version.parse("5.1")

# Starting with the moodlehq/moodle-php-apache:8.4 image (used by Moodle 5.2+),
# the image ships a /system-docker-entrypoint.d/10-wwwroot.sh entrypoint that
# auto-detects /var/www/html/public and exports
# APACHE_DOCUMENT_ROOT=/var/www/html/public. For older images (e.g. :8.3 used
# by Moodle 5.1) the DocumentRoot stays at /var/www/html and we must proxy
# requests into the public/ subpath ourselves.
MOODLE_IMAGE_AUTO_PUBLIC_DOCROOT_MIN_VERSION = pkg_version.parse("5.2")


def uses_public_webroot(moodle_version: str) -> bool:
    """Return True if the given Moodle version uses the public/ web root layout (>= 5.1)."""
    return pkg_version.parse(moodle_version) >= MOODLE_PUBLIC_WEBROOT_MIN_VERSION


def image_auto_serves_public_webroot(moodle_version: str) -> bool:
    """Return True if the moodle-docker image for this Moodle version auto-sets
    APACHE_DOCUMENT_ROOT to /var/www/html/public (i.e. Moodle >= 5.2)."""
    return (
        pkg_version.parse(moodle_version)
        >= MOODLE_IMAGE_AUTO_PUBLIC_DOCROOT_MIN_VERSION
    )
