# 4. Catálogo de técnicas para matar

## 4.1 Asersiones densas (la técnica base de este repo)

Compara la estructura COMPLETA, no campos sueltos. Una mutación de string,
número o clave en cualquier parte del resultado rompe la igualdad.

```python
assert finding == Finding(
    rule_id="PHP.AT.001",
    severity="error",
    message="Mensaje exacto con sus {placeholders}",
    file="src/Foo.php",
    line=42,
)
# y no:  assert finding.line == 42
```

Para dicts/JSON: `assert parsed == {dict literal completo}`.

## 4.2 Fronteras exactas (mata `<` ↔ `<=`, `>` ↔ `>=`)

Tres inputs por cada comparación: **debajo, EXACTAMENTE en el límite, encima**.
El caso del límite exacto es el único que distingue `<` de `<=`.

```python
assert gate(msi=99.99) is False   # debajo
assert gate(msi=100.0) is True    # EN el límite — este mata el mutante
assert gate(msi=100.01) is True   # encima
```

Si no puedes construir el input límite porque un invariante lo impide → es el
equivalente tipo B (§5.2).

## 4.3 Strings exactos: mensajes, logs, claves

- Mensajes de error: `pytest.raises(ValueError, match=re.escape("mensaje exacto"))`
  o `assert str(exc.value) == "..."`.
- Logging: `caplog` con igualdad exacta:
  `assert caplog.records[0].message == "Capa L1 completada: OK"`.
- stdout/stderr: `capsys` y comparar la línea completa.
- Claves de dicts que cruzan una frontera (JSON, argv, env): assert sobre la
  serialización externa, donde `"XXkeyXX"` rompe el contrato.

## 4.4 Spies sobre dependencias (mata kwargs, flags, timeouts, rutas)

Todo lo que la función pasa a `subprocess.run`, a otro adapter o a una librería
es observable vía mock — incluidos los valores que "no afectan al resultado":

```python
mock_run.assert_called_once_with(
    ["phpmd", str(path), "json", RULESET],
    capture_output=True, text=True, timeout=600, check=False,
)
```

Esto mata `timeout=600`→`601`, eliminación de kwargs, mutación de elementos
del argv, etc. **Asersión de la llamada completa, nunca `assert_called()`.**

## 4.5 Defaults de parámetros

Para `def f(x, timeout=600.0)`: ten al menos un test que llame a `f` **sin**
`timeout` y observe el 600.0 (normalmente vía el spy de §4.4 aguas abajo).
Si el default jamás llega a ninguna parte observable → tipo C (§5.3).

## 4.6 Acumuladores y aritmética (`+=` ↔ `=`, `+` ↔ `-`)

- Usa **≥2 iteraciones / ≥2 elementos**: con un solo elemento, `+=` y `=`
  son indistinguibles partiendo de 0.
- Usa **valores asimétricos**: `2 + 2 == 2 * 2`; con `3` y `5` no hay empate.
- Evita `0` y `1` como datos de test en rutas aritméticas (son identidades
  de `+`/`*` y enmascaran mutaciones).

## 4.7 `break` ↔ `continue` y early-returns

El resultado puede ser idéntico, pero el **número de iteraciones no lo es**:

```python
calls = []
def spy(item):
    calls.append(item)
    return item.matches
items = [stub(matches=True), stub(matches=False)]
find_first(items, spy)
assert calls == [items[0]]        # con continue habría 2 llamadas → muere
```

Variantes: iterador que cuenta `next()`, mock con `side_effect` que registra,
o un segundo elemento cuyo procesamiento sería visible (excepción, log).
Si el cuerpo del loop es 100% puro y sin efectos → refactor a `next(...)` /
`any(...)` y el mutante desaparece (§5.1).

## 4.8 Ramas booleanas (`and` ↔ `or`)

Tabla de verdad mínima: un caso donde **solo el primer operando** decide y
otro donde **solo el segundo** decide. Con `(True, True)` y `(False, False)`
ambos operadores dan lo mismo y el mutante sobrevive.

## 4.9 Property-based testing (cuando los ejemplos no llegan)

Para parsers y funciones con muchos inputs, una propiedad con `hypothesis`
mata familias enteras de mutantes aritméticos y de comparación que los
ejemplos puntuales no alcanzan (p. ej. `parse(render(x)) == x`,
monotonicidad, idempotencia). Úsalo con moderación: los tests deben seguir
siendo rápidos, mutmut ejecuta la suite miles de veces.

---
