# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Network Weather, Inc.
"""Put the repo root on sys.path so tests can `import rxd` from anywhere."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
