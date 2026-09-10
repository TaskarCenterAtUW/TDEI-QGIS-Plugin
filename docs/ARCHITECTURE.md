# Architecture

## Goals

Long-lived, testable QGIS plugin with clear boundaries between UI, domain,
API, auth, and QGIS integration.

## Package layout

```
tdei/
  plugin.py              # QGIS lifecycle (initGui / unload); toolbar → map search or sign-in
  config/                # QSettings + environments + migrations
  auth/                  # AuthManager, TokenManager, SessionManager
  api/                   # ApiClient, transport, v1 mappers
  core/                  # models, exceptions, workers, compatibility, DI
  features/              # datasets, jobs, osw (use-cases)
  qgis/                  # LayerManager, MapSearchController, context menu, OSW preview
  ui/                    # theme, components, pages, map overlays (search / chrome)
  logging/               # redacting logger
  tests/                 # unit + integration scaffolding
  docs/                  # developer docs
  scripts/               # package / validate
```

## Dependency direction

```
UI pages / map overlays → services (LoginService, DatasetService, JobService)
                       → repositories/API (ApiClient)
                       → transport (urllib)

UI → QGIS services (LayerManager) only via feature services or controllers
Auth UI → LoginService → AuthManager → ApiClient + TokenManager
```

UI widgets contain **no** HTTP calls and **no** token handling.

## Design decisions

1. **Stdlib HTTP (`urllib`)** — avoids third-party deps in the QGIS env.
2. **Constructor DI via `ServiceContainer`** — no DI framework.
3. **Compatibility layer** — QGIS/Qt version checks live in `core/compatibility/`.
4. **Feature modules** — new capabilities add a folder under `features/` + a page.
5. **Refresh tokens** — modeled even though current TDEI `/authenticate` may only
   return an access token; wiring is isolated in `ApiClient.refresh_tokens`.
6. **Token storage** — QSettings with base64 obfuscation (not encryption).
   Documented limitation; tokens never logged or shown in UI.
7. **Legacy prototype** — previous Plugin Builder modules live in `legacy/`
   for reference and are excluded from the release ZIP.

## Main window UX

Sticky **TDEI panel** on the map canvas (not a free-floating `QMainWindow`):

```
Login → App shell (header + sidebar + page container)
Pages: Dashboard | Datasets | Jobs | Settings
```

## Map chrome & map search

Top-right **map chrome** (TDEI / Map search / Close) is mutually exclusive with modes:

| Mode | Behavior |
|------|----------|
| **TDEI panel** | Sticky overlay (~full width); sidebar collapsed on open |
| **Map search** | Sticky left overlay: project group, status, name filter, result list, area polygons |
| **Close** | Hides chrome + both overlays (plugin stays loaded) |

**Toolbar / shortcut** (`Ctrl+Shift+T`): if signed in → map search; if not → TDEI sign-in panel.

Map search (`qgis/map_search.py` + `ui/dialogs/map_search_bar.py`):

- Debounced bbox (and optional name / ignore-extent) → `GET datasets`
- Area indicator: **green** = API `dataset_area` present, **red** = missing
- Click → highlight; double-click → zoom
- Busy state: animated purple left-edge stripe
- Title/hint copy uses a fixed-height block to avoid layout shake

## Add dataset area

Available from **map search** ⋮ and **Datasets** list ⋮ when area is missing:

1. Take full **metadata** from the datasets API list item (`raw.metadata`) — not from a downloaded `metadata.json` alone
2. Build a **concave hull** from local OSW layers (edges/nodes → vertices → `native:concavehull`; convex fallback). Fetch/extract the OSW package only if layers are not already cached
3. Set `dataset_detail.dataset_area` and **PUT** multipart edit-metadata (`metadata/{tdei_dataset_id}`)

Core helpers: `features/osw/generate_dataset_area.py`, `features/osw/metadata.py`, `DatasetService.add_dataset_area`.

## Threading

`Worker` / `WorkerPool` (`QRunnable` + `QThreadPool`) run network and heavy
IO off the UI thread. Results arrive via Qt signals.

**Cache Sync** prepares/unpacks packages in a worker, then adds layers on the
UI thread (`QgsProject` is not thread-safe). Tags are stored both on layer
groups and in `tdei_osw_cache/<id>/tdei_tags.json` so Mapped search survives
project loss; Sync restores groups from cache.

**Map updates** (add layers, hull Processing, highlights) stay on the UI thread.
