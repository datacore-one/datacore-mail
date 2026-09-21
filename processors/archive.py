"""
Archive Processor.

Simply archives emails without creating org entries.
Useful for newsletters, notifications, etc.
"""

from pathlib import Path
from typing import Any, Dict, Optional

from ..adapters.gmail import Email


class ArchiveProcessor:
    """
    Archive processor - marks emails as processed without creating entries.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize archive processor.

        Args:
            config: Processor configuration from mail.yaml
        """
        self.config = config
        self.auto_archive = config.get("auto_archive", True)

    def process(self, email: Email, space_path: Path) -> Optional[str]:
        """
        Process email by marking it for archival.

        Args:
            email: Email to process
            space_path: Path to the space directory

        Returns:
            None (no org entry created)
        """
        # Archive processor doesn't create org entries
        # The main module will handle the actual archiving
        return None
