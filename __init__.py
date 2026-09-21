"""
Mail Adapters.

Each adapter handles a specific email provider (Gmail, IMAP, etc.).
"""

from typing import Dict, Type

# Registry of available adapters
_adapters: Dict[str, Type] = {}


def register_adapter(name: str, adapter_class: Type):
    """Register an adapter by name."""
    _adapters[name] = adapter_class


def get_adapter(name: str) -> Type:
    """Get adapter class by name."""
    if name not in _adapters:
        raise ValueError(f"Unknown adapter: {name}. Available: {list(_adapters.keys())}")
    return _adapters[name]


# Import and register adapters
try:
    from .gmail import GmailAdapter
    register_adapter("gmail", GmailAdapter)
except ImportError:
    pass  # Gmail dependencies not installed
