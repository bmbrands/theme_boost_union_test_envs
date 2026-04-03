from packaging import version as pkg_version

# Moodle 5.1 moved the web-servable files into a "public/" subdirectory.
# This helper determines whether the given version uses that layout.
MOODLE_PUBLIC_WEBROOT_MIN_VERSION = pkg_version.parse("5.1")


def uses_public_webroot(moodle_version: str) -> bool:
    """Return True if the given Moodle version uses the public/ web root layout (>= 5.1)."""
    return pkg_version.parse(moodle_version) >= MOODLE_PUBLIC_WEBROOT_MIN_VERSION
