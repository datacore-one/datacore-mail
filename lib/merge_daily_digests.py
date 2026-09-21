#!/usr/bin/env python3
"""Merge duplicate "Daily News Digest - <date>" entries in an org file.

The newsletter processor's `aggregate_daily_news` action creates a NEW digest
heading per processing batch instead of appending to the day's existing one, so
a day that gets processed three times ends up with three digests, each holding a
different slice of the day's links. Observed 2026-08-05: Aug 03 x2, Aug 04 x2,
Aug 05 x3.

This merges same-day digests into one, unioning their `**Section:**` blocks and
de-duplicating links by URL. Idempotent: a file with one digest per day is left
unchanged.

Usage:
    python3 merge_daily_digests.py --file 0-personal/org/inbox.org            # dry run
    python3 merge_daily_digests.py --file 0-personal/org/inbox.org --execute
    python3 merge_daily_digests.py --file ... --day "Aug 05" --execute
"""
import argparse
import re
import sys
from collections import OrderedDict
from pathlib import Path

HEADING = re.compile(r'^(\*+) TODO Daily News Digest - (.+?)\s*(:[\w:]+:)?\s*$')
LINK = re.compile(r'\[\[([^\]]+)\]\[')
SECTION = re.compile(r'^\*\*(.+?):\*\*\s*$')


def parse_blocks(lines):
    """Yield (start, end, day, level, tags) for each digest heading."""
    out = []
    for i, line in enumerate(lines):
        m = HEADING.match(line)
        if not m:
            continue
        level, day, tags = m.group(1), m.group(2).strip(), m.group(3) or ''
        end = len(lines)
        for j in range(i + 1, len(lines)):
            nxt = lines[j]
            if nxt.startswith('*') and re.match(r'^\*+ ', nxt):
                if len(nxt.split(' ')[0]) <= len(level):
                    end = j
                    break
        out.append((i, end, day, level, tags))
    return out


def body_sections(block_lines):
    """Split a digest body into {section_title: [item lines]}, dropping PROPERTIES."""
    sections, current = OrderedDict(), None
    skipping = False
    for line in block_lines:
        s = line.strip()
        if s == ':PROPERTIES:':
            skipping = True
            continue
        if s == ':END:':
            skipping = False
            continue
        if skipping:
            continue
        m = SECTION.match(line)
        if m:
            current = m.group(1).strip()
            sections.setdefault(current, [])
            continue
        if s.startswith('- '):
            if current is None:
                current = 'Other'
                sections.setdefault(current, [])
            sections[current].append(line.rstrip())
    return sections


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--file', required=True)
    ap.add_argument('--day', help='Only merge this day, e.g. "Aug 05"')
    ap.add_argument('--execute', action='store_true')
    args = ap.parse_args()

    path = Path(args.file).expanduser()
    lines = path.read_text().split('\n')
    blocks = parse_blocks(lines)

    by_day = OrderedDict()
    for b in blocks:
        if args.day and b[2] != args.day:
            continue
        by_day.setdefault(b[2], []).append(b)

    dupes = {d: bs for d, bs in by_day.items() if len(bs) > 1}
    if not dupes:
        print('no duplicate digests found')
        return 0

    drop = set()
    edits = {}
    for day, bs in dupes.items():
        merged, seen = OrderedDict(), set()
        for (start, end, _d, _l, _t) in bs:
            for title, items in body_sections(lines[start + 1:end]).items():
                for it in items:
                    m = LINK.search(it)
                    key = m.group(1) if m else it.strip()
                    if key in seen:
                        continue
                    seen.add(key)
                    merged.setdefault(title, []).append(it)

        keep = bs[0]
        level, tags = keep[3], keep[4]
        rebuilt = [f'{level} TODO Daily News Digest - {day} {tags}'.rstrip(),
                   ':PROPERTIES:', f':CREATED: [{day}]', ':END:', '']
        # Preserve the kept block's own CREATED line verbatim if present.
        for line in lines[keep[0] + 1:keep[1]]:
            if line.strip().startswith(':CREATED:'):
                rebuilt[2] = line.rstrip()
                break
        for title, items in merged.items():
            rebuilt.append(f'**{title}:**')
            rebuilt.extend(items)
            rebuilt.append('')
        edits[keep[0]] = (keep[1], rebuilt)
        for b in bs[1:]:
            drop.add((b[0], b[1]))
        total = sum(len(v) for v in merged.values())
        print(f'{day}: {len(bs)} digests -> 1  ({total} unique links, '
              f'{len(merged)} sections)')

    if not args.execute:
        print('\n(dry run - pass --execute to write)')
        return 0

    out, i = [], 0
    while i < len(lines):
        if i in edits:
            end, rebuilt = edits[i]
            out.extend(rebuilt)
            i = end
            continue
        skipped = False
        for (s, e) in drop:
            if i == s:
                i = e
                skipped = True
                break
        if skipped:
            continue
        out.append(lines[i])
        i += 1

    path.write_text('\n'.join(out))
    print(f'\nwrote {path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
