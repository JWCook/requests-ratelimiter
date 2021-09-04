"""Config file for Sphinx documentation"""
# flake8: noqa: E402
import sys
from os.path import dirname, join

# Add project path so we can import our package
sys.path.insert(0, '..')
from requests_ratelimiter import __version__

DOCS_DIR = dirname(__file__)
PACKAGE_DIR = join(dirname(DOCS_DIR), 'requests_ratelimiter')

# General information about the project.
copyright = '2021, Jordan Cook'
exclude_patterns = ['_build']
master_doc = 'index'
needs_sphinx = '4.0'
project = 'requests_ratelimiter'
source_suffix = ['.rst', '.md']
templates_path = ['_templates']
version = release = __version__

# Sphinx extensions
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.autosummary',
    'sphinx.ext.intersphinx',
    'sphinx.ext.napoleon',
    'sphinx_autodoc_typehints',
    'sphinx_copybutton',
    'myst_parser',
]
myst_enable_extensions = ['colon_fence']

# Enable automatic links to other projects' Sphinx docs
intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
    'requests': ('https://requests.readthedocs.io/en/master/', None),
}

# napoleon settings
napoleon_google_docstring = True
napoleon_include_init_with_doc = True
numpydoc_show_class_members = False

# copybutton settings: Strip prompt text when copying code blocks
copybutton_prompt_text = r'>>> |\.\.\. |\$ '
copybutton_prompt_is_regexp = True

# Disable autodoc's built-in type hints, and use sphinx_autodoc_typehints extension instead
autodoc_typehints = 'none'

# HTML general settings
html_show_sphinx = False
pygments_style = 'friendly'
pygments_dark_style = 'material'

# HTML theme settings
html_theme = 'furo'
html_theme_options = {
    'sidebar_hide_name': True,
}
