# H4. Tablas de verdad incompletas en condiciones compuestas

**Código real**: `passed = mutation_stats.survived == 0 and mutation_stats.timed_out == 0`.

Mutaciones posibles: `and`→`or`, `== 0`→`!= 0` (×2), `0`→`1` (×2). Un test
con `survived=0, timed_out=0` y otro con `survived=5, timed_out=3` deja vivos
varios: con `(0,0)` y `(5,3)`, `and` y `or` dan lo mismo.

**Receta — parametrizar la tabla de verdad mínima**, donde cada operando
decide en solitario:

```python
@pytest.mark.parametrize("survived,timed_out,expected", [
    (0, 0, True),    # ambos OK
    (1, 0, False),   # solo el 1º falla  → mata and→or
    (0, 1, False),   # solo el 2º falla  → mata and→or y ==→!=
    (2, 0, False),   # ≠1: mata 0→1 en la comparación
])
```

Regla general: para `A op B` necesitas los casos donde A y B **discrepan**.
Para cadenas de 3+ condiciones, un caso por operando donde solo él falla.
