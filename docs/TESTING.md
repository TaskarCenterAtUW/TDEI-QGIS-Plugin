# Testing

## Unit tests (no live API)

From the **parent** of the plugin folder (so `import tdei` resolves), or with
`PYTHONPATH` set to the QGIS `python/plugins` directory:

```bash
cd "$HOME/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins"
python3 -m unittest tdei.tests.unit.test_datasets_parse -v
python3 -m unittest tdei.tests.unit.test_osw_package -v
python3 -m unittest tdei.tests.unit.test_auth_tokens -v
python3 -m unittest tdei.tests.unit.test_environment -v
```

QGIS stubs in `tests/fixtures/qgis_stubs.py` allow auth/config tests without
a running QGIS binary.

## Coverage targets

- Dataset JSON mapping
- OSW zip extraction
- HTTP → domain error mapping
- Token store / expiry / clear
- Environment resolution

## Integration

`tests/integration/` is reserved for gated live-API and QGIS canvas tests.
Do not hit production from CI without explicit credentials fixtures.
