# -*- coding: utf-8 -*-
"""Validate required plugin files exist before packaging."""

from __future__ import annotations

import os
import sys

REQUIRED = [
    "metadata.txt",
    "__init__.py",
    "plugin.py",
    "icon.png",
]


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    missing = [
        name for name in REQUIRED if not os.path.exists(os.path.join(root, name))
    ]
    if missing:
        print("Missing required files: {}".format(", ".join(missing)))
        return 1
    print("Plugin structure OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
