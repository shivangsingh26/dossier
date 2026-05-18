"""dossier-sdk — agentic job search system.

Version is read dynamically from the installed package metadata (pyproject.toml).
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("dossier-sdk")
except PackageNotFoundError:
    # Package not installed (e.g. running from source without editable install)
    __version__ = "0.0.0+dev"
