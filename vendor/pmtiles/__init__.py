# -*- coding: utf-8 -*-
"""Vendored PMTiles v3 reader (BSD-3-Clause, Protomaps LLC).

Source: https://github.com/protomaps/PMTiles (python/pmtiles)
Used to stream OSW previews when GDAL has no PMTiles driver.
"""

from .reader import MemorySource, MmapSource, Reader
from .tile import Compression, TileType

__all__ = [
    "Compression",
    "MemorySource",
    "MmapSource",
    "Reader",
    "TileType",
]
