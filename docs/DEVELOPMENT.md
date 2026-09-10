# Development

## Setup

1. Clone/copy into QGIS `python/plugins/tdei`
2. Enable **Plugin Reloader** (optional) for faster iteration
3. No virtualenv pip deps required for runtime

## Conventions

- Type hints on public APIs
- Business logic outside `ui/`
- User-facing strings via `self.tr(...)` where widgets inherit `QWidget`
- Log via `logging.logger.get_logger` — never log tokens/passwords
- Map overlays (`MapSearchBar`, map chrome, sticky `MainWindow`) stay on the
  canvas viewport; keep size policies tight so they do not fill the map

## Scripts

```bash
python3 scripts/build_plugin.py      # validate structure
python3 scripts/package_plugin.py    # write dist/tdei.zip
```

### Packaging notes

`scripts/package_plugin.py` zips the plugin as top-level `tdei/` and excludes
`.git`, `tests`, `legacy`, `help`, `dist`, caches, and local env files.

```bash
python3 scripts/package_plugin.py --output ~/Desktop/tdei.zip
```

Install in QGIS via **Plugins → Install from ZIP**. On a new machine, users must
**sign in** before map search (no session is shipped in the ZIP).

## Map search & add dataset area

| Piece | Location |
|-------|----------|
| Controller | `qgis/map_search.py` |
| Overlay UI | `ui/dialogs/map_search_bar.py` |
| Map chrome | `ui/dialogs/map_chrome.py` |
| Area generation | `features/osw/generate_dataset_area.py` (concave hull) |
| Metadata helpers | `features/osw/metadata.py` (`raw_has_valid_dataset_area`, …) |
| Service | `DatasetService.add_dataset_area(..., raw=)` |

Metadata for edit-metadata comes from the **datasets API response**, not from
requiring a local `metadata.json` for the PATCH content. OSW layers are still
needed to compute the hull (download only if not cached).

## Adding a feature

1. Add `features/<name>/service.py` (+ models if needed)
2. Register in `ServiceContainer` if it needs DI
3. Add `ui/<name>/page.py` and register in `MainWindow` navigation
4. Gate with `feature.<name>` in settings when useful

## Compatibility

Isolate QGIS/Qt differences in `core/compatibility/`. Prefer
`qgis.PyQt` imports (QGIS-supported), not raw `PyQt5`/`PyQt6`.
