# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""The documentation must describe the version the code declares.

A tag is only allowed on a commit whose version matches (CI checks the tag against
mt7921u.__version__), so tying these checks to __version__ means the release commit cannot
carry a CHANGELOG without its section or a README that still names the previous release.
"""

import re
from pathlib import Path

import mt7921u as m

ROOT = Path(__file__).resolve().parent.parent


def test_changelog_has_a_dated_section_for_the_declared_version():
    changelog = (ROOT / "CHANGELOG.md").read_text()
    pattern = rf"^## \[{re.escape(m.__version__)}\] - \d{{4}}-\d{{2}}-\d{{2}}$"
    assert re.search(pattern, changelog, re.M), f"CHANGELOG.md lacks a dated section for {m.__version__}"
    assert f"[{m.__version__}]: https://" in changelog, "CHANGELOG.md lacks the compare link"


def test_readme_names_the_declared_version_as_current():
    readme = (ROOT / "README.md").read_text()
    assert f"Current release {m.__version__}" in readme


def test_publishing_checklist_lists_the_declared_version():
    publishing = (ROOT / "docs" / "PUBLISHING.md").read_text()
    assert f"`{m.__version__}`" in publishing, "docs/PUBLISHING.md does not mention the release"
