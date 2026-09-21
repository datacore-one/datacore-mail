"""
Mail Processors.

Each processor handles emails differently:
- classifier: AI classification into ACTIONABLE/INFORMATIONAL/IGNORE
- github: GitHub notification processing with context fetching
- accounting: Invoice extraction and accounting updates
- newsletter: Newsletter processing with URL extraction and product relevance
- support: GitHub issue creation
- archive: Just archive, no processing
"""

from typing import Dict, Type

# Registry of available processors
_processors: Dict[str, Type] = {}


def register_processor(name: str, processor_class: Type):
    """Register a processor by name."""
    _processors[name] = processor_class


def get_processor(name: str) -> Type:
    """Get processor class by name."""
    if name not in _processors:
        raise ValueError(f"Unknown processor: {name}. Available: {list(_processors.keys())}")
    return _processors[name]


def list_processors() -> list:
    """List all registered processor names."""
    return list(_processors.keys())


# Import and register processors
try:
    from .classifier import ClassifierProcessor, batch_classify, batch_process, quick_classify
    register_processor("classifier", ClassifierProcessor)
except ImportError:
    pass

try:
    from .github import GitHubProcessor
    register_processor("github", GitHubProcessor)
except ImportError:
    pass

try:
    from .accounting import AccountingProcessor
    register_processor("accounting", AccountingProcessor)
except ImportError:
    pass

try:
    from .archive import ArchiveProcessor
    register_processor("archive", ArchiveProcessor)
except ImportError:
    pass

try:
    from .newsletter import NewsletterProcessor
    register_processor("newsletter", NewsletterProcessor)
except ImportError:
    pass
