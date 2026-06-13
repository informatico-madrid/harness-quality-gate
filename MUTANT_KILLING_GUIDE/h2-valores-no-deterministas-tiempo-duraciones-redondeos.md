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
