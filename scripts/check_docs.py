#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Check local Markdown links and JSON documentation without network access."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
MARKDOWN_LINK = re.compile(r"!?\[[^]]*\]\(([^)]+)\)")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
SKIP_PARTS = {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv", "build", "dist"}


def markdown_files() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*.md")
        if not SKIP_PARTS.intersection(path.relative_to(ROOT).parts)
    )


def github_anchor(heading: str) -> str:
    heading = re.sub(r"<[^>]+>", "", heading).lower()
    heading = re.sub(r"[^\w\- ]", "", heading, flags=re.UNICODE)
    return heading.replace(" ", "-")


def anchors(path: Path) -> set[str]:
    found = set()
    duplicates: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = HEADING.match(line)
        if not match:
            continue
        base = github_anchor(match.group(1))
        count = duplicates.get(base, 0)
        duplicates[base] = count + 1
        found.add(base if count == 0 else f"{base}-{count}")
    return found


def check_markdown() -> list[str]:
    errors = []
    anchor_cache: dict[Path, set[str]] = {}
    for source in markdown_files():
        for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
            for match in MARKDOWN_LINK.finditer(line):
                target = match.group(1).strip().strip("<>").split(maxsplit=1)[0]
                if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                    continue
                file_part, separator, fragment = target.partition("#")
                destination = (source.parent / unquote(file_part)).resolve()
                try:
                    destination.relative_to(ROOT)
                except ValueError:
                    errors.append(
                        f"{source.relative_to(ROOT)}:{line_number}: link escapes repository"
                    )
                    continue
                if not destination.is_file():
                    errors.append(f"{source.relative_to(ROOT)}:{line_number}: missing {target}")
                    continue
                if separator and destination.suffix.lower() == ".md":
                    available = anchor_cache.setdefault(destination, anchors(destination))
                    if unquote(fragment).lower() not in available:
                        errors.append(
                            f"{source.relative_to(ROOT)}:{line_number}: missing anchor #{fragment} "
                            f"in {destination.relative_to(ROOT)}"
                        )
    return errors


def check_json() -> list[str]:
    errors = []
    for path in sorted((ROOT / "docs").glob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"{path.relative_to(ROOT)}: {exc}")
    return errors


def main() -> int:
    errors = check_markdown() + check_json()
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"documentation ok: {len(markdown_files())} Markdown files, local links, JSON")
    return 0


if __name__ == "__main__":
    sys.exit(main())
