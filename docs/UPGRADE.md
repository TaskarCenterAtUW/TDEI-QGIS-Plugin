# Upgrade strategy

## Plugin semantic versioning

`MAJOR.MINOR.PATCH` in `metadata.txt`.

## Configuration migrations

`config/migrations.py` applies ordered migrations until `CONFIG_VERSION`.

When changing settings schema:

1. Bump `CONFIG_VERSION` in `defaults.py`
2. Append a migration `(version, callable)`
3. Never remove keys without a migration that rewrites them

## QGIS upgrades

- Raise `qgisMinimumVersion` only when required APIs demand it
- Put version forks in `core/compatibility/`
- Prefer `qgis.PyQt` over binding-specific imports

## API versioning

Mappers live under `api/v1/`. Introduce `api/v2/` for breaking Gateway changes
and select the mapper from configuration — do not branch UI code on API version.

## Compatibility notes

| Area | Notes |
|------|--------|
| Supported QGIS | 3.28 – 3.99 |
| Python | QGIS-bundled 3.9+ |
| PyQt | Via `qgis.PyQt` |
| Deprecated | Avoid `QgsMapLayerRegistry` (pre-3); use `QgsProject` |
| Vector export | `QgsVectorFileWriter.writeAsVectorFormat` — revisit for 4.x APIs inside compat layer |
