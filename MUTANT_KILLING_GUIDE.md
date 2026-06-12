# Guía para matar mutantes al 100% (mutmut)

Manual operativo para los subagentes que cierran supervivientes de mutmut.
El flujo de ejecución (comandos, caché, coverage, lectura de resultados) está
en [MUTATION_TESTING.md](MUTATION_TESTING.md) y en la cabecera del `Makefile`.
Este documento cubre lo otro: **cómo matar cada mutante y qué hacer cuando
parece equivalente**.

---

## TL;DR — Árbol de decisión (si solo lees una cosa, lee esto)

Para CADA superviviente, en este orden y sin saltarte pasos:

1. `mutmut show <id>` — lee el diff. Sin diff no hay diagnóstico.
2. ¿El cambio es observable (retorno, excepción, string, llamada a una
   dependencia)? → **escribe/endurece un test** que lo fije (§4): asersión
   densa, frontera exacta, string exacto o `assert_called_once_with` completo.
3. ¿No es observable porque es un default muerto, rama inalcanzable o código
   redundante? → **refactoriza para que el mutante no pueda existir** (§5:
   p. ej. `d.get(k, X)` → `d.get(k)` cuando `X` es inobservable). El código
   queda más limpio y el mutante desaparece.
4. ¿Ni test ni refactor posibles (caso raro y PROBADO)? → **pragma** con
   `# reason:` + `# audited:` (§7). Último recurso, no el primero.
5. **Nunca** termines en "es equivalente" escrito solo en un informe: si el
   código no cambió (test, refactor o pragma), el mutante NO está resuelto.

Verificación obligatoria en todos los caminos: el test pasa con el código
original y falla con `mutmut apply <id>` aplicado (revertir después).

---

## 0. Reglas de oro (no negociables)

1. **Prioridad estricta**: test que mata > refactor que elimina el mutante > pragma.
   El pragma es el ÚLTIMO recurso y exige `# reason:` + `# audited:` (ver §7).
2. **"Equivalente" es una afirmación que hay que PROBAR, no una excusa.**
   Antes de declarar un mutante equivalente, debes haber intentado las
   estrategias de §4 y §5 para su tipo. La mayoría de "equivalentes" son
   tests débiles.
3. **Declarar "equivalente" exige actuar en el CÓDIGO, no en el informe.**
   Toda equivalencia termina en uno de dos sitios: un REFACTOR que elimina el
   mutante (§5) o un pragma auditado (§7). Un informe que lista "equivalentes"
   sin tocar el código deja los supervivientes restando MSI y obliga al
   siguiente agente a repetir el triage desde cero. Caso real (2026-06-10):
   6 supervivientes de `psalm_taint_adapter.py` declarados equivalentes solo en
   el informe — con razonamiento falso en 2 de ellos (`isinstance([], list)` ES
   `True`) — cuando el Tipo C los eliminaba quitando el default muerto.
4. **Nunca modificar el código fuente de mutmut** (`.venv/lib/python*/site-packages/mutmut/`).
   Si mutmut se comporta raro (menos mutantes de los esperados, 0 mutantes,
   resultados extraños): desinstalar y reinstalar mutmut ANTES de investigar.
5. **Nunca debilitar el código de producción para matar un mutante.** Un
   refactor que elimina un mutante equivalente debe preservar el comportamiento
   (los 1139 tests deben seguir en verde y coverage en 100%).
6. **Regenerar `.coverage` antes de cada run** (con `mutate_only_covered_lines = true`,
   un coverage viejo manda mutantes a `no_tests`). El `make mutation` ya lo gestiona.
7. Paralelismo: `--max-children 20` (≈ la mitad de los cores). Saturar todos los
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

Catálogo completo: `node_mutation.py` en el repo de mutmut (no tocarlo, solo leerlo).

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

Anti-patrones de test que generan supervivientes (búscalos primero en el test
existente antes de escribir uno nuevo):

- `assert result` / `assert result is not None` → cambiar por igualdad exacta.
- `assert "fragmento" in mensaje` → cambiar por `==` del mensaje completo.
- `mock.assert_called()` sin args → cambiar por `assert_called_once_with(args exactos)`.
- Solo happy path → añadir el camino del guard/early-return.
- Comparar solo 1-2 campos de un objeto → comparar el objeto/dict completo.
- Un solo elemento en listas de entrada → usar ≥2 elementos asimétricos.

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
# y no:  assert finding.line == 42
```

Para dicts/JSON: `assert parsed == {dict literal completo}`.

### 4.2 Fronteras exactas (mata `<` ↔ `<=`, `>` ↔ `>=`)

Tres inputs por cada comparación: **debajo, EXACTAMENTE en el límite, encima**.
El caso del límite exacto es el único que distingue `<` de `<=`.

```python
assert gate(msi=99.99) is False   # debajo
assert gate(msi=100.0) is True    # EN el límite — este mata el mutante
assert gate(msi=100.01) is True   # encima
```

Si no puedes construir el input límite porque un invariante lo impide → es el
equivalente tipo B (§5.2).

### 4.3 Strings exactos: mensajes, logs, claves

- Mensajes de error: `pytest.raises(ValueError, match=re.escape("mensaje exacto"))`
  o `assert str(exc.value) == "..."`.
- Logging: `caplog` con igualdad exacta:
  `assert caplog.records[0].message == "Capa L1 completada: OK"`.
- stdout/stderr: `capsys` y comparar la línea completa.
- Claves de dicts que cruzan una frontera (JSON, argv, env): assert sobre la
  serialización externa, donde `"XXkeyXX"` rompe el contrato.

### 4.4 Spies sobre dependencias (mata kwargs, flags, timeouts, rutas)

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

### 4.5 Defaults de parámetros

Para `def f(x, timeout=600.0)`: ten al menos un test que llame a `f` **sin**
`timeout` y observe el 600.0 (normalmente vía el spy de §4.4 aguas abajo).
Si el default jamás llega a ninguna parte observable → tipo C (§5.3).

### 4.6 Acumuladores y aritmética (`+=` ↔ `=`, `+` ↔ `-`)

- Usa **≥2 iteraciones / ≥2 elementos**: con un solo elemento, `+=` y `=`
  son indistinguibles partiendo de 0.
- Usa **valores asimétricos**: `2 + 2 == 2 * 2`; con `3` y `5` no hay empate.
- Evita `0` y `1` como datos de test en rutas aritméticas (son identidades
  de `+`/`*` y enmascaran mutaciones).

### 4.7 `break` ↔ `continue` y early-returns

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

### 4.8 Ramas booleanas (`and` ↔ `or`)

Tabla de verdad mínima: un caso donde **solo el primer operando** decide y
otro donde **solo el segundo** decide. Con `(True, True)` y `(False, False)`
ambos operadores dan lo mismo y el mutante sobrevive.

### 4.9 Property-based testing (cuando los ejemplos no llegan)

Para parsers y funciones con muchos inputs, una propiedad con `hypothesis`
mata familias enteras de mutantes aritméticos y de comparación que los
ejemplos puntuales no alcanzan (p. ej. `parse(render(x)) == x`,
monotonicidad, idempotencia). Úsalo con moderación: los tests deben seguir
siendo rápidos, mutmut ejecuta la suite miles de veces.

---

## 5. Taxonomía de (presuntos) equivalentes y solución por tipo

> Detectar equivalentes es indecidible en general (Wikipedia / literatura
> académica), pero en la práctica caen en pocos tipos, y casi todos tienen
> solución sin pragma. La estrategia maestra: **si no puedes matarlo,
> refactoriza para que el mutante no pueda existir.**

### Tipo A — Equivalente "solo rendimiento" (`break`→`continue`, orden de comprobaciones)

El programa produce lo mismo pero hace trabajo de más.
- **Primero**: intenta §4.7 (contar iteraciones/llamadas). Si hay CUALQUIER
  efecto en el cuerpo del loop, NO es equivalente.
- **Si es puro de verdad**: refactor que elimina la sentencia mutable:
  `for`+`break` → `next((x for x in xs if p(x)), default)` o `any()`/`all()`.
  El `break` ya no existe → no hay mutante.

### Tipo B — Frontera inalcanzable (`x > 0` → `x >= 0` con invariante `x != 0`)

El valor límite no puede ocurrir por un invariante (tipos, validación previa).
- ¿La función es pública/llamable con el límite aunque "no deba pasar"?
  → llámala con el límite en el test y fija el comportamiento. Ya no es equivalente.
- ¿El invariante es estructural (p. ej. `len(x) >= 0`)? → refactor que disuelve
  la comparación: `if len(x) > 0:` → `if x:`; `if n >= 0` sobre un `len()` →
  eliminar la rama muerta.
- ¿Invariante de dominio garantizado aguas arriba? → mueve la validación
  (raise) a esta función y testea el raise; o pragma con el invariante citado
  en `# reason:`.

### Tipo C — Default muerto (`d.get(k, X)` cuando `k` siempre existe; kwarg default nunca usado)

La mutación de `X` no es observable porque el camino del default nunca se ejecuta.
- ¿Puede faltar la clave en algún input legal (JSON externo, config de usuario)?
  → test con la clave AUSENTE que observe `X`. Muerto.
- ¿La clave está garantizada por contrato? → refactor: `d[k]` (sin default).
  El mutante desaparece y además un KeyError temprano es mejor diagnóstico.
- Patrón ya usado en este repo (commit `e49e6d9`): `d.get(k, X)` → `d.get(k) or X`
  cuando el default debe aplicar también a valores falsy (`""`, `None` del JSON).
  OJO: solo es válido si `0`/`""`/`False` no son valores legítimos de la clave.
- Kwarg default que ninguna ruta usa → elimina el default y hazlo obligatorio.

### Tipo D — Código defensivo inalcanzable (ramas `else` imposibles, re-raise genéricos)

- Si la rama es inalcanzable de verdad → es código muerto: elimínala (coverage
  100% lo confirmará) o conviértela en `raise AssertionError(...)` y testea
  el raise inyectando el estado "imposible" con mocks.
- Si solo es "difícil de alcanzar" → mock de la dependencia que lo provoca
  (`side_effect=OSError(...)`) y assert del manejo exacto.

### Tipo E — Constantes de tuning (timeouts, tamaños de buffer, sleeps)

`timeout=600` → `601` no cambia ningún resultado de test... salvo que el test
observe el VALOR, no el efecto:
- Si la constante se pasa a una dependencia → §4.4 la mata siempre
  (`assert_called_once_with(..., timeout=600, ...)`). **Este tipo casi nunca
  es equivalente en este repo** — los adapters pasan todo a `subprocess`.
- Si la constante es consumida internamente sin salir (p. ej. tamaño de chunk
  con resultado idéntico para cualquier valor) → extraerla a constante de
  módulo y testear la constante (`assert DEFAULT_TIMEOUT == 600.0`), o
  pragma con reason (es de los pocos casos legítimos; ver `models.py`).

### Tipo F — String interno consistente (clave usada solo dentro del módulo)

Si la misma clave literal se escribe Y se lee dentro del código mutado en un
solo punto de mutación... en realidad mutmut muta cada literal por separado,
así que casi siempre ES matable: el lado mutado deja de encajar con el otro.
- Si sobrevive: el test no recorre el camino lectura+escritura juntos →
  test de ida y vuelta (escribir y leer por la API pública).
- Si la clave es contrato externo (JSON de verdict, argv) → assert sobre la
  salida serializada exacta.
- Refactor preventivo: literales repetidos → constante de módulo única +
  test del valor de la constante.

### Tipo G — `is` ↔ `==` con singletons (`None`, sentinels)

Para `None` y sentinels propios (`x is SENTINEL`), ambos operadores son
equivalentes de verdad si la clase no define `__eq__` raro.
- Refactor preferido: usa el patrón que haga la mutación letal — para
  sentinels, define el sentinel como `object()` y testea con un objeto que
  implemente `__eq__` devolviendo `True` para todo (`is` y `==` divergen → muere).
- Si no compensa: pragma con reason (equivalencia semántica probada).

### Tipo H — Mensajes/representaciones "que no importan"

Mensajes de log de debug, `__repr__`, textos de excepciones internas.
**No son equivalentes**: son matables con `caplog`/`capsys`/`str(exc)` (§4.3).
La pereza de assertar strings no convierte al mutante en equivalente. En este
repo los mensajes de `messages_es.py` son contrato de usuario — igualdad exacta.

### Tipo I — Mutación con efecto solo en el rendimiento de la suite (timeouts ⏰)

Un mutante `timeout` (⏰) suele ser un loop infinito creado por la mutación —
cuenta como muerto para el MSI de mutmut pero el gate de CI lo rechaza.
Investiga: casi siempre indica que falta un test rápido y específico que
mate ese mutante ANTES de colgar la suite (test unitario de la condición del
loop con frontera exacta).

---

## 6. Estrategia de campaña (para el coordinador)

1. **Agrupa supervivientes por archivo y por tipo de mutación**, no uno a uno:
   un solo test denso (§4.1) o un spy completo (§4.4) suele matar 5-20
   mutantes del mismo bloque. Mira primero los clusters grandes.
2. Orden de ataque por rentabilidad:
   1º llamadas a subprocess/deps sin `assert_called_once_with` completo,
   2º resultados comparados parcialmente → igualdad de objeto completo,
   3º strings/mensajes sin asserts exactos,
   4º fronteras de comparación,
   5º casos raros uno a uno.
3. Cada subagente trabaja con `make mutation-path FILE_PATH=...` (directorios
   aislados, paralelizable sin conflictos). Máximo 2 subagentes en paralelo
   (límites de tokens).
4. Al final de cada tanda: suite completa + coverage 100% + `make clean-mutmut`
   + run completo. La verdad está en `mutants/mutmut-cicd-stats.json`, NO en
   `mutmut results` (que arrastra `not checked` de runs interrumpidos).
5. Si un subagente lleva 3+ intentos con el mismo mutante sin matarlo: STOP,
   aplicar el mutante en disco (§1) y entender el porqué antes de escribir
   más tests a ciegas.
6. **Informe de subagente: evidencia por mutante, no veredictos.** Cada mutante
   reportado debe citar su evidencia verificable: qué test lo mata (y que ese
   test FALLA con `mutmut apply <id>` aplicado), o qué refactor/pragma lo
   eliminó (diff concreto). Una columna "Reason" redactada sin haber aplicado
   el mutante no es evidencia — así se cuelan razonamientos falsos. El
   coordinador rechaza tablas de "equivalentes declarados" sin diff asociado.

---

## 7. Política de pragmas (último recurso)

Regla del proyecto: **"Cero pragmas sobre lógica."** Solo para equivalentes
PROBADOS tras agotar §4 y §5, y siempre con metadatos auditables:

```python
# reason: timeout=600.0 es default de API pública; la mutación (601.0) es equivalente — ningún consumidor observable. # audited: 2026-06-09
timeout: float = 600.0,  # pragma: no mutate
```

- `# reason:` y `# audited: YYYY-MM-DD` deben estar en las 5 líneas anteriores
  y empezar por `#` (regex del `allow_list_auditor`).
- El reason debe nombrar el TIPO de equivalencia (§5) y por qué las técnicas
  de §4 no aplican. "es equivalente" a secas no pasa revisión.
- Verificar SIEMPRE tras añadir uno:
  `python -m harness_quality_gate audit-ignores harness_quality_gate` → exit 0.
- Variantes (`# pragma: no mutate block`, `start`/`end`, `do_not_mutate_patterns`)
  existen en mutmut pero están desaconsejadas aquí: ocultan demasiado.

---

## 8. Checklist por mutante (resumen ejecutable)

```text
[ ] mutmut show <id> — leer el diff completo
[ ] ¿Test existente débil? (assert truthy / in / called sin args) → endurecer
[ ] ¿Observable por retorno/excepción? → asersión densa (§4.1) o frontera (§4.2)
[ ] ¿Observable por string? → igualdad exacta + caplog/capsys (§4.3)
[ ] ¿Observable por dependencia? → assert_called_once_with completo (§4.4)
[ ] ¿Default / acumulador / break? → §4.5–§4.7
[ ] ¿Sigue vivo? → mutmut apply + pytest -x para entender (y revertir)
[ ] ¿Equivalente? → clasificar en §5 y aplicar el REFACTOR del tipo
[ ] ¿Refactor imposible sin romper API? → pragma con reason+audited (§7)
[ ] Verificar: test pasa en original, mutante muere, suite verde, coverage 100%
[ ] Informe: evidencia por mutante (test que falla con apply / diff de refactor
    o pragma). PROHIBIDO "equivalente" sin acción en el código (§0 regla 3)

```

---

# PARTE II — Casos difíciles (con supervivientes reales de este repo)

Los mutantes "fáciles" mueren con §4. Los que quedan vivos al final de una
campaña casi siempre son de los tipos de esta parte. Cada caso incluye: cómo
se ve el diff, POR QUÉ sobrevive aunque haya tests, y la receta exacta.

## H1. Passthrough de argumentos a colaboradores mockeados ⭐ (el nº 1 de este repo)

**Diff real** (`python_adapter.run_l4__mutmut_4`, superviviente hoy):

```diff
-    bandit_findings = self._run_bandit(repo, env)
+    bandit_findings = self._run_bandit(None, env)
```

Variantes reales: `_run_vulture(repo, None)`, `_run_mutmut(repo, None)`,
`adapter.version(None, {})`. Hay decenas en `run_l1`–`run_l4` y `tool_versions`.

**Por qué sobrevive**: el test del orquestador mockea `_run_bandit` con un
`MagicMock`, que acepta CUALQUIER argumento (incluido `None`) y devuelve lo
configurado. El resultado final del orquestador es idéntico → el test pasa.
Esto es la trampa estructural de los orquestadores: cuanto más mockeas, más
mutantes de cableado sobreviven.

**Receta — el "test de cableado" (wiring test)**: un único test por
orquestador que verifica TODAS las llamadas con argumentos exactos. Mata
todos los passthrough del método de golpe:

```python
def test_run_l4_wiring_exacto(adapter, monkeypatch):
    repo, env = Path("/repo/único"), {"MARCADOR": "xyz"}   # valores únicos, no triviales
    spies = {}
    for name in ("_run_bandit", "_run_deptry"):
        spies[name] = MagicMock(return_value=[])
        monkeypatch.setattr(adapter, name, spies[name])

    adapter.run_l4(repo, env)

    for name, spy in spies.items():
        assert spy.call_args_list == [call(repo, env)], name   # posición Y valor
        assert spy.call_args.args[0] is repo                   # identidad: mata repo→None
        assert spy.call_args.args[1] is env                    # identidad: mata env→None
```

Claves de la receta:
- **`call_args_list == [call(...)]`** completo, nunca `assert_called()`.
- **Asersión de identidad (`is`)** además de igualdad: inmune a mutaciones
  que produzcan un valor "igual pero distinto" (p. ej. `Path(".")` recreado).
- **Valores centinela únicos** (`{"MARCADOR": "xyz"}`, rutas raras): si usas
  `{}` o `Path(".")`, una mutación a otro valor vacío/default puede empatar.
- **`autospec=True`** en los patches (`patch.object(adapter, "_run_bandit", autospec=True)`):
  un mock con spec rechaza llamadas con aridad/kwargs inválidos, matando
  mutaciones de firma gratis.

Para `tool_versions` (muta `adapter.version(self.repo_placeholder(Path(".")), {})`
→ `version(None, {})`): mismo patrón, asserta sobre el mock de cada
sub-adapter: `sub.version.assert_called_once_with(expected_path, {})` y
comprueba `call_args.args[0] == adapter.repo_placeholder(Path("."))`.

## H2. Valores no deterministas: tiempo, duraciones, redondeos

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

## H3. Logging con placeholders `%`

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

## H4. Tablas de verdad incompletas en condiciones compuestas

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

## H5. El orquestador sobre-mockeado (mutantes DENTRO de lo mockeado jamás mueren ahí)

Si el test de `run_l3a` mockea `_run_ruff`, ningún test de `run_l3a` puede
matar mutantes DE `_run_ruff`. Parece obvio, pero es la causa nº 1 de "he
añadido 5 tests y el conteo no baja": el test ataca la capa equivocada.

**Receta — dos niveles, responsabilidades separadas**:
1. Tests del orquestador: SOLO cableado (H1) + agregación (orden de findings,
   `extend` exacto) + logs (H3) + duración (H2).
2. Tests del método hoja (`_run_ruff`): mock de `subprocess.run` con stdout
   realista, asersiones densas del parseo (§4.1) y de la llamada (§4.4).

Antes de escribir un test, localiza en qué función vive el mutante
(el nombre lo dice: `xǁPythonAdapterǁrun_l2__mutmut_18` → `run_l2`) y testea
ESA función directamente.

## H6. Manejo de errores: `except` que tragan y fallbacks

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

## H7. Listas argv y orden de elementos

`["phpmd", str(path), "json", ruleset]` — mutaciones de cada string y del
orden. Sobreviven si el test hace `assert "phpmd" in cmd`.

**Receta**: igualdad de la lista COMPLETA en la asersión de la llamada
(`assert_called_once_with([...exacta...], ...)`). Si el comando se construye
condicionalmente (flags opcionales), un test por rama con la lista completa
de esa rama.

## H8. break/continue y early-return en loops puros (el equivalente clásico que no lo es)

Ya cubierto en §4.7/§5.A; el caso DIFÍCIL es cuando el cuerpo del loop no
llama a nada tuyo (puro de verdad). Receta avanzada — **iterador espía**:

```python
class IterEspia:
    def __init__(self, items): self.items, self.consumidos = iter(items), 0
    def __iter__(self): return self
    def __next__(self): self.consumidos += 1; return next(self.items)

espia = IterEspia([obj_que_matchea, obj_extra])
buscar_primero(espia)
assert espia.consumidos == 1     # continue habría consumido 2 → muere
```

Si ni siquiera puedes pasar un iterable (el loop itera algo interno):
refactor a `next()`/`any()` (§5.A) — es el único caso donde tocar el código
es la respuesta correcta.

## H9. Mutantes ⏰ (timeout) y 🤔 (suspicious)

- **⏰**: la mutación creó un loop infinito (p. ej. `continue` que ya no
  avanza, condición de salida invertida). El gate los rechaza. Receta: test
  unitario rápido y específico de la condición de salida (frontera exacta,
  §4.2) para que un test BARATO falle antes de que la suite cuelgue.
- **🤔**: el test falla de forma no determinista con el mutante (flaky).
  Busca dependencia de orden (`-p no:randomly` ya está en el runner), estado
  global, `lru_cache` sin limpiar entre tests, o archivos compartidos.
  Fixture que limpie caches (`func.cache_clear()`) y `tmp_path` por test.

## H10. Estado global, caches y singletons

Mutante en código que solo se ejecuta UNA vez por proceso (init de módulo,
`lru_cache`, registro de adapters): el primer test lo ejecuta, los demás ven
la cache → la mutación "no afecta" al test que debía matarla.

**Receta**: fixture de aislamiento que resetea el estado entre tests
(`cache_clear()`, `importlib.reload` como último recurso, monkeypatch del
registro). Si el módulo tiene side-effects de import → refactor a init
explícito (los side-effects de import son inmatables Y mal diseño).

## H11. Mutantes que requieren inputs "imposibles de construir"

La rama necesita un objeto que el constructor público no permite crear
(validación previa). Opciones en orden:
1. Construir el objeto inválido por la puerta de atrás del test:
   `object.__new__(Cls)` + setattr, o `dataclasses.replace`, o un stub con
   la misma interfaz. El test documenta "si esto ocurriera, haríamos X".
2. Testear el método privado que contiene la rama directamente
   (`adapter._parse_línea(línea_corrupta)`) — un test de método privado es
   mejor que un pragma.
3. Si de verdad es inalcanzable desde cualquier interfaz → es código muerto
   o invariante: §5.B / §5.D (refactor o pragma con el invariante citado).

## H12. El mutante que "deberías haber matado" y sigue vivo (debugging del propio test)

Cuando escribes el test correcto y el mutante sobrevive igualmente, en este
repo las causas reales han sido, por frecuencia:
1. **Caché sucia de mutmut** → `make clean-mutmut` y relanzar. (Si los
   números son absurdos: reinstalar mutmut — regla del proyecto.)
2. **El test no corre bajo mutmut**: el runner es `pytest tests/unit/ -q` —
   un test en `tests/integration/` NO mata nada. Verifica la ruta.
3. **Coverage desactualizado** con `mutate_only_covered_lines = true`: la
   línea aparece como no cubierta y el mutante ni se evalúa contra tu test.
   Regenerar `.coverage` con el MISMO scope (`tests/unit/`).
4. **El assert no ejecuta la rama mutada** → protocolo de verificación:
   `mutmut apply <id>`, correr SOLO tu test, debe FALLAR; `git checkout --` para
   revertir. Si pasa con el mutante aplicado, tu test no toca esa rama: usa
   `pytest --pdb` o un print temporal para ver qué camino recorre de verdad.
5. **Mock que neutraliza la mutación**: mockeaste la función mutada o una
   que la envuelve (H5).

---

## H13. `monkeypatch.chdir` rompe la recolección de stats de mutmut

Síntoma real (2026-06-11): `failed to collect stats. runner returned 1` con
`FileNotFoundError: .../tmp_path/harness_quality_gate` — mutmut resuelve las
rutas de los módulos mutados RELATIVAS al cwd, y un test que hace
`monkeypatch.chdir(tmp_path)` se lo cambia a mitad de recolección.
- **Prohibido `chdir` en tests unitarios** de este repo. Para matar un
  `default="."` de argparse: spy sobre el comando despachado y assert
  `args.repo == "."` (sin tocar el cwd).

## H14. La trampa del XX-wrap: el substring ingenuo NO mata strings

mutmut envuelve strings como `XXfooXX` — y `"foo" in out` SIGUE PASANDO
porque el original está contenido en el mutante. Tres niveles de solución:
1. **Igualdad exacta** del valor (`==`) — siempre que el valor completo sea
   estable (p. ej. snapshot del catálogo `MSG` en messages_es).
2. **Literal anclado con delimitadores** que el wrap rompe:
   `"Run all quality-gate layers\n" in out` falla con `"XX...XX\n"` (el XX se
   interpone ante el `\n`). Mata wrap + case sin acoplarse a mutmut.
3. `assert "XX" not in out` — red de seguridad acoplada al esquema de mutmut;
   solo como complemento, nunca como assert principal (preferencia del
   proyecto: literales anclados).

## H15. Gemelos falsy en inicializadores (`None`→`""`, `False`→`None`, `[]`→`None`)

mutmut muta el valor inicial de una variable a otro valor FALSY
(`x = None` → `x = ""`). Si todos los consumidores usan truthiness
(`if x:`), el gemelo es estructuralmente equivalente y NINGÚN test lo mata.
- **Solución**: cambia los consumidores a identidad: `if x is not None:`.
  Con eso el gemelo `""` entra en la rama y se vuelve observable (una clave
  extra en el dict de salida, un crash de atributo…) → test lo mata.
- **Flags booleanos** (`ok = False` → `None`): no hay check que distinga
  `False` de `None` por truthiness. Elimina el flag: deriva la condición del
  dato real (p. ej. guarda el resultado en `remediation: dict | None = None`
  y comprueba `is not None`), como se hizo en `php_adapter.run_l1`.
- Caso real: `php_adapter.run_l1` tenía 3 gemelos supervivientes
  (`mutation_stats`, `mutation_skipped`, `mutation_gate_failed`); los tres
  cayeron con este patrón sin cambiar el comportamiento.

## H16. Exit -24 (SIGXCPU) en runs paralelos: casi siempre es flake, no timeout

Con `--max-children` alto, algunos mutantes terminan con exit `-24` (límite
de CPU del worker) aunque sus tests los matan en <2s. Antes de tratarlos como
⏰ reales:
```bash
cd mutants && MUTANT_UNDER_TEST=<id-completo> python -m pytest tests/unit/<archivo> -x -q
```
Si falla rápido → flake del paralelismo; se resolverá en el run final (o
re-ejecutando el módulo). Si de verdad cuelga → Tipo I (§5).

## Protocolo de medición fiable (aprendido a base de números absurdos)

1. **Si cambiaste CÓDIGO FUENTE**: `make clean-mutmut` SIEMPRE antes de medir.
   `mutation-path` no borra `mutants/` y la regeneración incremental deja
   metas parciales (31 mutantes donde había 294).
2. **Regenera `.coverage`** tras cambiar fuente
   (`pytest tests/unit/ --cov=harness_quality_gate --cov-report=`): el
   preflight de los targets NO lo hace, y con `mutate_only_covered_lines`
   un coverage rancio descarta mutantes en silencio.
3. **Si solo cambiaste TESTS**: run incremental directo
   (`mutmut run "modulo*"`) — mutmut detecta los tests nuevos y re-evalúa.
4. **Números absurdos pese a todo** (menos mutantes de los esperados, 0
   mutantes, funciones enteras ausentes del meta): reinstala mutmut
   (`pip uninstall -y mutmut && pip install "mutmut>=3.5"`) — regla del
   proyecto, confirmada de nuevo el 2026-06-11.
5. La verdad por archivo está en `mutants/<ruta>.py.meta`
   (`exit_code_by_key`: 0=survived, 1=killed, -24=ver H16);
   `scripts/extract_survivors.py` la resume por método.
6. **Captura los diffs ANTES de `clean-mutmut`**: la limpieza destruye TODOS
   los metas (también los de archivos que no ibas a re-medir). Vuelca primero
   los supervivientes a un archivo de trabajo:
   `mutmut show <id>` en bucle → `/tmp/survivors.txt` — y luego limpia.
   Corolario: un `mutation-path` tras un clean repuebla SOLO el filtro pedido;
   el resto del board queda vacío hasta el siguiente run amplio.

## Fuentes

- [mutmut — documentación oficial](https://mutmut.readthedocs.io/en/latest/index.html) (operadores, pragmas, `browse`/`apply`)
- [Mutation testing — Wikipedia](https://en.wikipedia.org/wiki/Mutation_testing) (problema del mutante equivalente, indecidibilidad)
- [Mitigating the effects of equivalent mutants with mutant classification strategies — Science of Computer Programming](https://www.sciencedirect.com/science/article/pii/S0167642314002603)
- [Using Constraints for Equivalent Mutant Detection — arXiv](https://arxiv.org/pdf/1207.2234)
- [Large Language Models for Equivalent Mutant Detection — arXiv 2024](https://arxiv.org/html/2408.01760v1)
- [An introduction to mutation testing in Python — Opensource.com](https://opensource.com/article/20/7/mutmut-python)
- [Mutation testing in Python using Mutmut — Medium](https://medium.com/@cemeteryblack/mutation-testing-in-python-using-mutmut-a094ad486050)
- [Mutation testing in Python — Deployed.pl](https://deployed.pl/blog/mutation-testing-in-python)
