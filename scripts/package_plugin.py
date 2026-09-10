# -*- coding: utf-8 -*-
"""Build an installable QGIS plugin ZIP."""

from __future__ import annotations

import argparse
import os
import zipfile

EXCLUDE_DIRS = {
    ".git",
    ".github",
    ".pytest_cache",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    "legacy",
    "graphify-out",
    "help",
    "dist",
    "tests",
}
EXCLUDE_FILES = {
    ".DS_Store",
    ".env",
    ".coverage",
    "pb_tool.cfg",
    "pylintrc",
    "Makefile",
}
EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".qml~")


def should_skip(rel_path: str) -> bool:
    parts = rel_path.replace("\\", "/").split("/")
    if any(part in EXCLUDE_DIRS for part in parts):
        return True
    name = parts[-1]
    if name in EXCLUDE_FILES:
        return True
    if name.startswith(".env"):
        return True
    if name.endswith(EXCLUDE_SUFFIXES):
        return True
    return False


def package(plugin_root: str, output: str, plugin_name: str = "tdei") -> str:
    plugin_root = os.path.abspath(plugin_root)
    output = os.path.abspath(output)
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for dirpath, dirnames, filenames in os.walk(plugin_root):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            for filename in filenames:
                full = os.path.join(dirpath, filename)
                rel = os.path.relpath(full, plugin_root)
                if should_skip(rel):
                    continue
                archive.write(full, os.path.join(plugin_name, rel))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Package TDEI QGIS plugin")
    parser.add_argument(
        "--root",
        default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output zip path (default: dist/tdei.zip)",
    )
    args = parser.parse_args()
    output = args.output or os.path.join(args.root, "dist", "tdei.zip")
    path = package(args.root, output)
    print("Wrote {}".format(path))


if __name__ == "__main__":
    main()
