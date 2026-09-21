"""One line per message, per disposition — the record triage never kept.

WHY. Until 2026-09-17 the only mail log was run-level: `audit.jsonl` recorded
"scanned 123, archived 65, processed 23, errors 0" and not one message
identity. So the question a person actually asks — "what happened to this
email?" — had no answer anywhere. Worse, there was no `trashed` counter at
all, so a trashed message was folded into the same totals as an archived one
and the log positively implied nothing had been deleted.

That mattered when correspondence went missing and nothing could say whether
triage had touched it, or when, or why.

WHERE. At the ADAPTER, which is the chokepoint every disposition passes
through, rather than in the scanner. A record written in the scanner only
covers the scanner's own path; a record written here covers any caller,
including an agent reaching for `adapter.archive()` on its own initiative.

WHAT. Sender and subject are kept, not just the message id, because a bare id
cannot answer the question that prompted this. The log lives under
`.datacore/state/`, which .gitignore excludes, so it never leaves the machine.
Failure to log is never fatal: losing the record must not also lose the action.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


def _log_path() -> Path:
    root = Path(os.environ.get('DATACORE_ROOT', Path.home() / 'Data'))
    return root / '.datacore' / 'state' / 'mail' / 'messages.jsonl'


def record(account: str, message_id: str, action: str, ok: bool, **extra) -> None:
    """Append one disposition record. Never raises."""
    try:
        entry = {
            'ts': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'account': account,
            'message_id': message_id,
            'action': action,
            'ok': bool(ok),
        }
        for key, value in extra.items():
            if value is not None:
                entry[key] = value if isinstance(value, (int, float, bool)) else str(value)[:400]
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception:  # noqa: BLE001 -- a lost record must not lose the action
        pass


def history(message_id: str) -> list[dict]:
    """Every recorded disposition for one message, oldest first."""
    path = _log_path()
    if not path.exists():
        return []
    out = []
    with path.open(encoding='utf-8') as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get('message_id') == message_id:
                out.append(entry)
    return out


def search(term: str, limit: int = 20) -> list[dict]:
    """Records whose sender or subject contains `term`, newest first.

    The question this exists for is "what happened to the mail from X", which
    nobody can ask with a message id they do not have.
    """
    path = _log_path()
    if not path.exists():
        return []
    needle = term.lower()
    hits = []
    with path.open(encoding='utf-8') as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            haystack = f"{entry.get('sender', '')} {entry.get('subject', '')}".lower()
            if needle in haystack:
                hits.append(entry)
    return list(reversed(hits))[:limit]


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Ask what happened to a message.')
    ap.add_argument('term', help='sender or subject text, or a message id')
    ap.add_argument('--limit', type=int, default=20)
    a = ap.parse_args()
    rows = history(a.term) or search(a.term, a.limit)
    if not rows:
        print(f'no recorded disposition matching {a.term!r}')
        print(f'(log: {_log_path()})')
    for row in rows:
        print(f"{row['ts']}  {row['action']:<10} ok={row['ok']!s:<5} "
              f"{row.get('sender', '')[:40]:<40} {row.get('subject', '')[:50]}")
