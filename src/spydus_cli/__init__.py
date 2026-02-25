from importlib.metadata import PackageNotFoundError, version

from .client import SpydusClient

try:
    __version__ = version("spydus-cli")
except PackageNotFoundError:
    __version__ = "0.1.0"  # fallback for editable / uninstalled

__all__ = ["SpydusClient", "__version__"]
