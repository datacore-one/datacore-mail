"""The one mail rules file, and where each space keeps its account config.

All rules live in `0-personal/.datacore/module-data/mail/rules.yaml`, outside
the module (owner, 2026-09-29). /mails (processors/classifier.py) and the
nightly triage (lib/email_scanner.py) both load it here, so they cannot drift
apart again. Rules for a team mailbox sit in that file's `spaces:` section,
keyed by the space folder name, and apply only to that space's accounts.

The module's own rules.base.yaml is the generic example: it applies only when
no rules file exists (a fresh install).

Account config (mail.yaml) sits in `<space>/.datacore/module-data/mail/`; the
older `<space>/.datacore/mail.yaml` is still found when the new one is absent.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

MODULE_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = MODULE_ROOT / "rules.base.yaml"
RULES_REL = Path(".datacore") / "module-data" / "mail" / "rules.yaml"
ACCOUNTS_REL = Path(".datacore") / "module-data" / "mail" / "mail.yaml"
LEGACY_ACCOUNTS_REL = Path(".datacore") / "mail.yaml"


def data_root() -> Path:
    env = os.environ.get("DATACORE_ROOT") or os.environ.get("DATA_DIR")
    return Path(env) if env else MODULE_ROOT.parents[2]


def rules_file(root: Optional[Path] = None) -> Path:
    """The rules file in force: the personal one, else the module's generic example."""
    f = Path(root or data_root()) / "0-personal" / RULES_REL
    return f if f.exists() else EXAMPLE


def load_rules(path: Optional[str | Path] = None, space: Optional[str] = None,
               root: Optional[Path] = None) -> Dict[str, Any]:
    """Load the one rules file (or `path`), with `space`'s section applied when given."""
    p = Path(path) if path else rules_file(root)
    rules = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    spaces = rules.pop("spaces", None) or {}
    if space and spaces.get(space):
        rules = deep_merge(rules, spaces[space])
    return rules


def deep_merge(base: Dict, override: Dict) -> Dict:
    """Merge override into base; lists are extended, not replaced."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = deep_merge(result[key], val)
        elif key in result and isinstance(result[key], list) and isinstance(val, list):
            result[key] = result[key] + val
        else:
            result[key] = val
    return result


def account_config(space_dir: Path) -> Optional[Path]:
    """A space's mail.yaml: beside the rules in module-data, else the older location."""
    for rel in (ACCOUNTS_REL, LEGACY_ACCOUNTS_REL):
        f = Path(space_dir) / rel
        if f.exists():
            return f
    return None
