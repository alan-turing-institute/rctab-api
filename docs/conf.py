"""Configuration file for the Sphinx documentation builder."""
from importlib import metadata
from unittest.mock import MagicMock

import databases
import pydantic
import sphinx_rtd_theme

# pylint: disable=invalid-name

# Patch settings base class to avoid having to set env vars

pydantic.BaseSettings = MagicMock()  # type: ignore
databases.Database = MagicMock()  # type: ignore
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
