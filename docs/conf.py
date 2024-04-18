"""Configuration file for the Sphinx documentation builder."""

import os
from importlib import metadata
from unittest.mock import patch

import sphinx_rtd_theme

# pylint: disable=invalid-name

# Set mandatory env vars
os.environ["SESSION_EXPIRE_TIME_MINUTES"] = "1"
os.environ["SESSION_SECRET"] = "don't use this in production"
os.environ["CLIENT_ID"] = "00000000-0000-0000-0000-000000000000"
os.environ["CLIENT_SECRET"] = "this is a secret"
os.environ["TENANT_ID"] = "00000000-0000-0000-0000-000000000000"
os.environ["DB_HOST"] = "localhost"
os.environ["DB_PASSWORD"] = "notarealpassword"
os.environ["DB_USER"] = "the_username"

with patch("databases.Database"):
    # pylint: disable=wrong-import-position
    import rctab

# pylint: enable=wrong-import-position

# General configuration

project = "rctab-api"
author = "The Alan Turing Institute's Research Computing Team"
# pylint: disable=redefined-builtin
copyright = f"2023, {author}"
# pylint: enable=redefined-builtin

version = metadata.version(rctab.__package__)
release = version

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- General configuration

extensions = [
    "sphinx.ext.duration",
    "sphinx.ext.doctest",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "myst_parser",
]

# -- Options for HTML output

html_theme = "sphinx_rtd_theme"
html_theme_path = [sphinx_rtd_theme.get_html_theme_path()]
html_static_path = ["_static"]

html_logo = "RCTab-hex.png"


def setup(app):  # type: ignore
    """Tasks to perform during app setup."""
    app.add_css_file("css/custom.css")


# -- Options for autosummary extension

autosummary_generate = True

# -- Options for MyST

myst_heading_anchors = 5
