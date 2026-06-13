# 2. Qué muta mutmut (para saber qué buscar en el diff)

| Operador | Original → Mutado | Qué necesita el test para matarlo |
|---|---|---|
| Números | `n` → `n + 1` (`0`→`1`, `600`→`601`) | Asersión sobre el valor EXACTO donde se usa |
| Strings | `"key"` → `"XXkeyXX"` | Asersión de igualdad exacta del string / clave |
| Comparación | `<` ↔ `<=`, `>` ↔ `>=`, `==` ↔ `!=` | Caso de frontera exacto (§4.2) |
| Booleanos | `True` ↔ `False`, `and` ↔ `or`, `not x` → `x` | Casos donde cada operando decide solo |
| `in` / `is` | `in` ↔ `not in`, `is` ↔ `is not` | Caso positivo Y negativo |
| Flujo | `break` ↔ `continue`, `return x` → `return None` | Contar iteraciones / assert del retorno |
| Defaults | `def f(x=10)` → `def f(x=11)` | Llamar SIN el argumento (§4.5) |
| Kwargs en llamadas | `f(timeout=600)` → `f(timeout=601)` / quitar kwarg | `assert_called_once_with(...)` con TODOS los kwargs |
| Aritmética | `+` ↔ `-`, `*` ↔ `/`, `+=` ↔ `=` | Valores no simétricos, >1 iteración (§4.6) |

Catálogo completo: `node_mutation.py` en el repo de mutmut (no tocarlo, solo leerlo).

---
