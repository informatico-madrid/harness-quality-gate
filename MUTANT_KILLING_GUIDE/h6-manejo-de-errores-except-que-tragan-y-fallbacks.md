# H6. Manejo de errores: `except` que tragan y fallbacks

**Código real** (`tool_versions`): `except (RuntimeError, OSError): versions[adapter.name] = "MISSING"`.

Mutantes duros aquí: el string `"MISSING"` → `"XXMISSINGXX"`, y mutaciones del
flujo del handler. Sobreviven porque ningún test fuerza la excepción.

**Receta — provocar el fallo con `side_effect`** y assertar el fallback exacto:

```python
def test_tool_versions_herramienta_rota(adapter):
    adapter.ruff.version = MagicMock(side_effect=OSError("no existe"))
    versions = adapter.tool_versions()
    assert versions["ruff"] == "MISSING"          # exacto, no `in`
```

Cubre cada tipo de excepción del tuple por separado (un test con
`RuntimeError`, otro con `OSError`): si mutmut o un refactor toca el tuple,
algo muere. Y un test donde NO hay excepción que verifique que el fallback
NO se aplicó.
