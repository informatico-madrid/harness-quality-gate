---
name: mutation-testing-guide
description: Operational guide for killing mutants with mutmut in Python. Covers techniques (dense assertions, boundary testing, spies), equivalence classification A-I with refactor solutions, and 12 hard cases from real repo survivors. Use when tackling survived mutants, designing test strategies for 100% mutation score, or when mutmut coverage is below target.
keywords: mutmut, mutation testing, equivalent mutants, python testing, test strategies, MSI improvement, survivor classification
origin: harness-quality-gate
---

# Guía para matar mutantes al 100% (mutmut)

Manual operativo para los subagentes que cierran supervivientes de mutmut.
El flujo de ejecución (comandos, caché, coverage, lectura de resultados) está
en MUTATION_TESTING.md y en la cabecera del `Makefile`.
Este documento cubre lo otro: **cómo matar cada mutante y qué hacer cuando
parece equivalente**.

---

## 0. Reglas de oro (no negociables)

1. **Prioridad estricta**: test que mata > refactor que elimina el mutante > pragma.
   El pragma es el ÚLTIMO recurso y exige `# reason:` + `# audited:` (ver §7).
2. **"Equivalente" es una afirmación que hay que PROBAR, no una excusa.**
   Antes de declarar un mutante equivalente, debes haber intentado las
   estrategias de §4 y §5 para su tipo. La mayoría de "equivalentes" son
   tests débiles.
3. **Nunca modificar el código fuente de mutmut** (`.venv/lib/python*/site-packages/mutmut/`).
   Si mutmut se comporta raro (menos mutantes de los esperados, 0 mutantes,
   resultados extraños): desinstalar y reinstalar mutmut ANTES de investigar.
4. **Nunca debilitar el código de producción para matar un mutante.** Un
   refactor que elimina un mutante equivalente debe preservar el comportamiento
   (los 1139 tests deben seguir en verde y coverage en 100%).
5. **Regenerar `.coverage` antes de cada run** (con `mutate_only_covered_lines = true`,
   un coverage viejo manda mutantes a `no_tests`). El `make mutation` ya lo gestiona.
6. Paralelismo: `--max-children 20` (≈ la mitad de los cores). Saturar todos los
   cores deja sin CPU a los hijos y produce timeouts espurios (verificado
   2026-06-12); el Makefile ya usa 20 por defecto.

---

## 1. Bucle de trabajo por superviviente

```bash
# 1. Lista de supervivientes (señal accionable, sin ruido)
mutmut results 2>&1 | grep survived

# 2. Ver el diff exacto de UN mutante
mutmut show harness_quality_gate.config.x_validate__mutmut_5

# 3. Clasificarlo (ver §3 y §5) y escribir/reforzar el test

# 4. Verificar que el test pasa con el código ORIGINAL
.venv/bin/python -m pytest tests/unit/test_config.py -q -x

# 5. Re-ejecutar SOLO ese mutante (o el módulo)
mutmut run harness_quality_gate.config.x_validate__mutmut_5
mutmut run 'harness_quality_gate.config.*'
```

Truco de depuración cuando no entiendes por qué sobrevive: aplica el mutante
en disco, ejecuta el test que debería matarlo y mira qué pasa de verdad:

```bash
mutmut apply <mutant-id>
.venv/bin/python -m pytest tests/unit/test_config.py -q -x   # ¿pasa? → tu assert no toca esa rama
git diff && git checkout -- harness_quality_gate/             # SIEMPRE revertir
```

Si tras matar un mutante el conteo del módulo no baja: caché sucia →
`make clean-mutmut` y relanzar el módulo.

**Regla del test nuevo**: cada test que escribas debe (a) pasar con el código
original y (b) fallar con el mutante aplicado. Si no cumple (b), no has matado
nada — solo has añadido coverage.

---

## 2. Qué muta mutmut (para saber qué buscar en el diff)

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

---

## 3. Triage: clasifica antes de actuar

Por cada `mutmut show`, responde en orden:

1. **¿El cambio es observable desde fuera de la función?**
   (retorno, excepción, efecto sobre un mock, log, archivo, exit code)
   → SÍ en ~90% de los casos: es un **test débil**, ve a §4.
2. **¿El cambio es observable solo "desde dentro"?**
   (nº de iteraciones, valor intermedio, kwarg pasado a una dependencia)
   → Sigue siendo matable con spies/mocks: §4.4 y §4.7.
3. **¿El cambio es genuinamente inobservable bajo CUALQUIER input y CUALQUIER
   doble de test?** → Candidato a equivalente: ve a §5 y busca su tipo.
   Casi siempre hay un refactor que lo elimina.

---

## 4. Catálogo de técnicas para matar

### 4.1 Asersiones densas (la técnica base de este repo)

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
```

### 4.2 Fronteras exactas (mata `<` ↔ `<=`, `>` ↔ `>=`)

Tres inputs por cada comparación: **debajo, EXACTAMENTE en el límite, encima**.
El caso del límite exacto es el único que distingue `<` de `<=`.

```python
assert gate(msi=99.99) is False   # debajo
assert gate(msi=100.0) is True    # EN el límite — este mata el mutante
assert gate(msi=100.01) is True   # encima
```

### 4.3 Strings exactos: mensajes, logs, claves

- Mensajes de error: `pytest.raises(ValueError, match=re.escape("mensaje exacto"))`
- Logging: `caplog` con igualdad exacta: `assert "exacto" in [r.getMessage() for r in caplog.records]`
- stdout/stderr: `capsys` y comparar la línea completa

### 4.4 Spies sobre dependencias (mata kwargs, flags, timeouts, rutas)

```python
mock_run.assert_called_once_with(
    ["phpmd", str(path), "json", RULESET],
    capture_output=True, text=True, timeout=600, check=False,
)
```

**Asersión de la llamada completa, nunca `assert_called()`.**

### 4.5 Defaults de parámetros

Para `def f(x, timeout=600.0)`: ten al menos un test que llame a `f` **sin**
`timeout` y observe el 600.0 (normalmente vía el spy de §4.4 aguas abajo).

### 4.6 Acumuladores y aritmética

- Usa **≥2 iteraciones / ≥2 elementos**: con un solo elemento, `+=` y `=`
  son indistinguibles partiendo de 0.
- Usa **valores asimétricos**: `2 + 2 == 2 * 2`; con `3` y `5` no hay empate.

### 4.7 `break` ↔ `continue` y early-return en loops puros

```python
class IterEspia:
    def __init__(self, items): self.items, self.consumidos = iter(items), 0
    def __iter__(self): return self
    def __next__(self): self.consumidos += 1; return next(self.items)

espia = IterEspia([obj_que_matchea, obj_extra])
buscar_primero(espia)
assert espia.consumidos == 1     # continue habría consumido 2 → muere
```

---

## 5. Taxonomía de (presuntos) equivalentes y solución por tipo

### Tipo A — Equivalente "solo rendimiento" (`break`→`continue`, orden de comprobaciones)

- **Primero**: intenta §4.7 (contar iteraciones/llamadas).
- **Si es puro de verdad**: refactor que elimina la sentencia mutable:
  `for`+`break` → `next((x for x in xs if p(x)), default)` o `any()`/`all()`.

### Tipo B — Frontera inalcanzable (`x > 0` → `x >= 0` con invariante `x != 0`)

¿La función es pública/llamable con el límite aunque "no deba pasar"?
→ llámala con el límite en el test y fija el comportamiento. Ya no es equivalente.

### Tipo C — Default muerto (`d.get(k, X)` cuando `k` siempre existe)

¿Puede faltar la clave en algún input legal?
→ test con la clave AUSENTE que observe `X`. Muerto.

### Tipo D — Código defensivo inalcanzable

Si la rama es inalcanzable de verdad → es código muerto: elimínala o conviértela
en `raise AssertionError(...)` y testea el raise con mocks.

### Tipo E — Constantes de tuning (timeouts, tamaños de buffer)

Si la constante se pasa a una dependencia → §4.4 la mata siempre
(`assert_called_once_with(..., timeout=600, ...)`).

---

## 6. Casos difíciles (con supervivientes reales de este repo)

### H1. Passthrough de argumentos a colaboradores mockeados ⭐

**Patrón dominante en `python_adapter.run_l1`–`l4`, `tool_versions`.**

```diff
-    bandit_findings = self._run_bandit(repo, env)
+    bandit_findings = self._run_bandit(None, env)
```

**Receta — wiring test con call_args_list**:

```python
def test_run_l4_wiring_exacto(adapter, monkeypatch):
    repo, env = Path("/repo/único"), {"MARCADOR": "xyz"}
    spies = {}
    for name in ("_run_bandit", "_run_deptry"):
        spies[name] = MagicMock(return_value=[])
        monkeypatch.setattr(adapter, name, spies[name])

    adapter.run_l4(repo, env)

    for name, spy in spies.items():
        assert spy.call_args_list == [call(repo, env)], name
        assert spy.call_args.args[0] is repo                   # identidad
        assert spy.call_args.args[1] is env
```

### H2. Redondeos y tiempo

```diff
-        duration_sec=round(duration, 3),
+        duration_sec=round(duration, None),
```

**Receta — congelar el reloj**:

```python
def test_duration_redondeo_exacto(adapter, monkeypatch):
    ticks = iter([100.0, 101.23456])
    monkeypatch.setattr(time, "monotonic", lambda: next(ticks))
    result = adapter.run_l1(repo, env)
    assert result.duration_sec == 1.235
    assert isinstance(result.duration_sec, float)
```

### H3. Logging con placeholders

```diff
-    logger.info("ruff: %d findings", len(ruff_findings))
+    logger.info("XXruff: %d findingsXX", len(ruff_findings))
```

**Receta**:

```python
def test_run_l3a_logs(adapter, caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger="harness_quality_gate")
    result = adapter.run_l3a(repo, env)
    assert "ruff: 2 findings" in [r.getMessage() for r in caplog.records]
```

### H4. Tablas de verdad incompletas

Para `passed = mutation_stats.survived == 0 and mutation_stats.timed_out == 0`:

```python
@pytest.mark.parametrize("survived,timed_out,expected", [
    (0, 0, True),
    (1, 0, False),   # mata and→or
    (0, 1, False),   # mata and→or y ==→!=
])
```

### H5. El orquestador sobre-mockeado

No puedes matar mutantes DENTRO de lo mockeado desde tests del orquestador.
Testea cada capa por separado: orquestador = cableado + agregación + logs;
método hoja = subprocess.run + parseo.

### H6. Manejo de errores y fallbacks

```python
def test_tool_versions_herramienta_rota(adapter):
    adapter.ruff.version = MagicMock(side_effect=OSError("no existe"))
    versions = adapter.tool_versions()
    assert versions["ruff"] == "MISSING"   # exacto, no `in`
```

### H7. Listas argv y orden

Igualdad COMPLETA en la asersión: `assert_called_once_with([...exacta...], ...)`.

### H8. Iteradores espías para loops puros

Ya cubierto en H4 arriba.

### H9. Mutantes ⏰ (timeout) y 🤔 (suspicious)

- **⏰**: test unitario rápido y específico de la condición (frontera exacta).
- **🤔**: caché sin limpiar, estado global. Fixture que resetea `cache_clear()`.

### H10. Estado global y caches

Fixture de aislamiento que resetea entre tests.

### H11. Inputs "imposibles" en ramas defensivas

1. Construir por la puerta de atrás (`object.__new__`).
2. Testear el método privado directamente.
3. Si es inalcanzable → código muerto → pragma con invariante citado.

### H12. Debugging: el test "correcto" que no mata

1. **Caché sucia** → `make clean-mutmut`
2. **Test fuera de scope** → debe estar en `tests/unit/`
3. **Coverage viejo** → regenerar `.coverage`
4. **Assert no toca la rama** → `mutmut apply`, pytest, `git checkout --`
5. **Mock neutraliza la mutación** → testas la capa equivocada (H5)

---

## Checklist por mutante

```
[ ] mutmut show <id> — leer el diff completo
[ ] ¿Test débil? → endurecer asersión (§4.1–4.3)
[ ] ¿Observable? → asersión densa o frontera (§4)
[ ] ¿Sigue vivo? → mutmut apply + pytest -x (debugging)
[ ] ¿Equivalente? → clasificar en §5 y aplicar REFACTOR
[ ] ¿Refactor imposible? → pragma con reason+audited (§7 de la guía)
[ ] Verificar: suite verde, coverage 100%
```

---

## Para integrar en subagentes

Cuando el coordinador lance a un subagente a matar supervivientes:

1. **Lee esta guía Parte II** (casos H1–H12, arriba).
2. Cada `mutmut show` entra en el triage (§3).
3. Sigue la receta exacta del tipo que identifiques (§4, §5, o §6).
4. Verifica siempre: `mutmut apply`, test solo, revertir, suite completa.
5. Si creas un nuevo test, documenta CUÁL es el mutante que mata.

**Referencia complementaria**: MUTATION_TESTING.md (workflow de comandos, caché, coverage, lectura de resultados).
