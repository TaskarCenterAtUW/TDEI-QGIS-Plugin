# TDEI QGIS Plugin

Production-grade QGIS plugin for the [TDEI](https://tdei.us) OpenSidewalks platform.

## Features

- Sign in to TDEI (development / staging / production / custom API)
- **Map search** — sticky map overlay: find OSW datasets by view or name, color-coded areas, zoom/highlight
- Browse datasets and load OSW packages into QGIS layer groups
- **Add dataset area** — ⋮ menu builds a concave-hull `dataset_area`, patches API metadata, submits edit-metadata
- **Sync** header action restores layers from local cache after a crash
- Submit OpenAPI-defined TDEI jobs from the layer context menu
- Background workers (non-blocking UI), toasts, confirmations, theme

## Requirements

- QGIS **3.28+** (tested design target through 3.x)
- Python bundled with QGIS (3.9+)
- No extra pip packages required

## Install

1. From the plugin root, build a ZIP:

   ```bash
   python3 scripts/package_plugin.py
   ```

   Output: `dist/tdei.zip` (top-level folder `tdei/`). Optional:

   ```bash
   python3 scripts/package_plugin.py --output ~/Desktop/tdei.zip
   ```

2. In QGIS: **Plugins → Manage and Install Plugins → Install from ZIP**
3. Enable **TDEI**

Or copy this folder into your QGIS profile `python/plugins/tdei` and reload.

**Fresh install:** open the plugin and **sign in** first. Until a session exists, the toolbar opens the TDEI sign-in panel (map search needs auth).

## Quick start

1. Open **Plugins → TDEI** (or **Ctrl+Shift+T** / ⌘⇧T)
2. Sign in with your TDEI credentials
3. Use **map search** (map chrome or default toolbar entry when signed in) to find datasets in the current view
4. Or open **Datasets** → **Download** (then **Zoom to map** when ready)
5. For rows with a **red** map icon (no area): **⋮ → Add dataset area**
6. Right-click the dataset group → **TDEI Jobs**
7. After a crash or unsaved project: click **Sync** (header) to rebuild the **TDEI** group from `tdei_osw_cache`

## Documentation

| Doc | Purpose |
|-----|---------|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Layers, DI, map overlays, boundaries |
| [DEVELOPMENT.md](docs/DEVELOPMENT.md) | Local setup, packaging & conventions |
| [CONFIGURATION.md](docs/CONFIGURATION.md) | Environments & settings |
| [AUTHENTICATION.md](docs/AUTHENTICATION.md) | Tokens & session UX |
| [TESTING.md](docs/TESTING.md) | Running tests |
| [UPGRADE.md](docs/UPGRADE.md) | QGIS & config migrations |
| [PRESENTATION.md](docs/PRESENTATION.md) | Stakeholder / demo deck outline |

## License

GNU GPL v2 (or later), consistent with QGIS plugin norms.
# TDEI-QGIS-Plugin
