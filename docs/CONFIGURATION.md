# Configuration

All environment-specific values are configurable. Defaults live in
`config/defaults.py`.

## Environments

| Key | Default Gateway API | Default User-management API |
|-----|---------------------|-----------------------------|
| `development` | `https://api-dev.tdei.us/api/v1` | `https://portal-api-dev.tdei.us/api/v1` |
| `staging` | `https://api-stage.tdei.us/api/v1` | `https://portal-api-stage.tdei.us/api/v1` |
| `production` | `https://api.tdei.us/api/v1` | `https://portal-api.tdei.us/api/v1` |

URLs are editable under **Settings → Environments** (one tab per environment).
Overrides are stored as `env.<key>.api_base_url` and
`env.<key>.user_management_api_base_url` (empty → built-in preset).

**Active environment** is switched from the **status bar** (click the env name).
Switching environments **signs the user out** so tokens are not reused across
hosts.

Project groups load from user-management:

`GET {user_management_api_base_url}/project-group-roles/{user_id}`

Datasets / OSW continue to use the gateway API host.

## Persisted keys (QSettings root `tdei_plugin/`)

- `environment`
- `env.<development|staging|production>.api_base_url`
- `env.<development|staging|production>.user_management_api_base_url`
- `custom_api_base_url`, `custom_user_management_api_base_url` (legacy)
- `request_timeout_seconds`, `download_timeout_seconds`, `job_timeout_seconds`
- `log_level`, `ui.show_toasts`, `ui.toast_duration_ms`
- `feature.dataset_load`, `feature.jobs`, …
- `basemap.provider` — `openstreetmap` (default), `google_roadmap`,
  `google_satellite`, or `none`
- `config_version` (schema migrations)
- `secure/*` — token material (obfuscated; cleared on logout)

## Basemap

Basemaps are **XYZ tile layers** built into QGIS 3. Tiles stream over the
network while you pan/zoom — there is **no offline map download** and **no**
extra plugin dependency (QuickMapServices is not required).

| Provider | Notes |
|----------|--------|
| OpenStreetMap | Default; appropriate for most use |
| Google Maps / Satellite | Optional; requires network; review Google Maps ToS |
| None | Do not add a basemap |

When you **Download** a dataset or job output, the plugin ensures the saved
basemap sits under TDEI dataset layers.

## Project layers vs local cache

The plugin **coexists** in the user’s current QGIS project. It does **not**
create a dedicated QGIS user profile or replace the project file.

| Store | Location | Role |
|-------|----------|------|
| Project layers | Layer tree group **TDEI** (stamped `tdei_root`) | Mapped tab, Zoom |
| Disk cache | `{QGIS profile}/tdei_osw_cache/<environment>/<id>/` | Survives crashes; Sync / Download reuse (per env) |
| Tags | Group property + `tdei_tags.json` per cache folder | Mapped search; restored by Sync |

**Sync** (header, top-right): verifies the cache, ensures the `TDEI` root group
exists, and remaps all usable cached packages into the open project without
re-downloading. Use this after a crash or an unsaved project when Mapped is empty
but cache folders remain.

**Switching QGIS projects:** Mapped / Zoom follow whatever is in the newly opened
project. In-flight Sync or Download will not add layers into the wrong project
(files stay in cache). Use Sync again if you want cache packages in the new
project. Saving the QGIS project (`.qgz`) is still recommended so layers persist
without needing Sync. Tags are also written to each cache folder so they survive
even when the project was not saved.

## Feature flags

```
feature.dataset_load
feature.dataset_refresh
feature.jobs
feature.experimental_map
```

## Secrets

Never put tokens or passwords in source, `.ui` files, or layer names.
See [AUTHENTICATION.md](AUTHENTICATION.md).
