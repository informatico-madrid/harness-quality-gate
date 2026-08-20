# H2. Valores no deterministas: tiempo, duraciones, redondeos

**Diff real** (`run_l1__mutmut_35`, superviviente hoy):

```diff
-        duration_sec=round(duration, 3),
+        duration_sec=round(duration, None),
```

**Por qué sobrevive**: `duration` viene de `time.monotonic()` y el test no
puede assertar un valor exacto, así que asserta `duration_sec >= 0` (truthy
débil). `round(x, None)` devuelve `int` en vez de `float` con 3 decimales —
es observable, pero solo si controlas el reloj.

**Receta — congelar el reloj**:

```python
def test_duration_redondeo_exacto(adapter, monkeypatch):
    ticks = iter([100.0, 101.23456])             # t0 y t1
    monkeypatch.setattr(time, "monotonic", lambda: next(ticks))
    # mocks de los _run_* como en H1 ...
    result = adapter.run_l1(repo, env)
    assert result.duration_sec == 1.235          # mata round(_, None) → 1
    assert isinstance(result.duration_sec, float)
```

Elige un delta cuyo redondeo a 3 decimales NO sea igual al entero ni al valor
sin redondear (1.23456 → 1.235 ≠ 1 ≠ 1.23456). Lo mismo aplica a
`datetime.now`, `uuid4`, `tempfile`, `random`: **inyectar o monkeypatchear,
nunca assertar "aproximadamente"**. `pytest.approx` con tolerancia ancha es
un criadero de mutantes aritméticos.

**Trampa de razonamiento — `timezone.utc → None` NO es equivalente "en máquinas
UTC".** Diff típico: `datetime.now(datetime.timezone.utc)` → `datetime.now(None)`.
Es tentador declarar esto equivalente ("en un servidor en UTC el reloj de pared
es el mismo, así que da igual"). Es **falso**: `datetime.now(None)` produce un
objeto **naive** (sin `tzinfo`) mientras que `datetime.now(timezone.utc)` produce
uno **aware**; `.isoformat()` de un naive NUNCA lleva el sufijo `+00:00`/`Z`,
sea cual sea la zona horaria de la máquina que ejecuta el test. Es observable
en **cualquier** entorno, no solo en no-UTC — no hace falta viajar de zona
horaria ni congelar el reloj con un valor "raro": basta con assertar que la
cadena termina en `+00:00` o `Z` (o que `datetime.fromisoformat(...).tzinfo is
not None`). Caso real (rompehielos, `finalise_calibration`, 2026-07-04): un
agente declaró este mutante "indistinguible en máquinas UTC" — razonamiento
igual de plausible y de falso que el `isinstance([], list)` del caso de
`psalm_taint_adapter` (regla de oro #3): en ambos casos, **probarlo habría
tardado menos que escribirlo**. Antes de aceptar cualquier "es igual en mi
entorno", ejecuta los dos objetos y compara `.tzinfo` o el string exacto.
