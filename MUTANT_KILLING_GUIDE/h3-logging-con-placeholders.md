# H3. Logging con placeholders `%`

**Diff real** (`run_l3a__mutmut_13`, superviviente hoy):

```diff
-    logger.info("ruff: %d findings", len(ruff_findings))
+    logger.info("XXruff: %d findingsXX", len(ruff_findings))
```

**Por qué sobrevive**: nadie asserta los logs, o el assert usa `in`, o
`caplog` no captura porque el nivel/logger no está configurado.

**Receta**:

```python
def test_run_l3a_logs(adapter, caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger="harness_quality_gate")  # ¡nivel Y logger!
    # mocks que devuelven 2 findings de ruff ...
    adapter.run_l3a(repo, env)
    assert "ruff: 2 findings" in [r.getMessage() for r in caplog.records]  # mensaje COMPLETO
```

- `r.getMessage()` (mensaje interpolado completo, igualdad contra la lista),
  no `"ruff" in caplog.text` — el `in` sobre `caplog.text` deja vivo el `XX...XX`
  solo si el assert es de fragmento; contra el mensaje completo interpolado, muere.
- Si también muta el argumento (`len(x)` → otra cosa): el mensaje interpolado
  exacto con un conteo ≥2 lo cubre (usa 2 findings, no 0 ni 1 — ver §4.6).
- Mutación del NIVEL (`logger.info` → mutado): asserta `r.levelno == logging.INFO`.
