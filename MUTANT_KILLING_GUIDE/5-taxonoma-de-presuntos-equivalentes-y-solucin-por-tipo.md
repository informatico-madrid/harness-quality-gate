# 5. Taxonomía de (presuntos) equivalentes y solución por tipo

> Detectar equivalentes es indecidible en general (Wikipedia / literatura
> académica), pero en la práctica caen en pocos tipos, y casi todos tienen
> solución sin pragma. La estrategia maestra: **si no puedes matarlo,
> refactoriza para que el mutante no pueda existir.**

## Tipo A — Equivalente "solo rendimiento" (`break`→`continue`, orden de comprobaciones)

El programa produce lo mismo pero hace trabajo de más.
- **Primero**: intenta §4.7 (contar iteraciones/llamadas). Si hay CUALQUIER
  efecto en el cuerpo del loop, NO es equivalente.
- **Si es puro de verdad**: refactor que elimina la sentencia mutable:
  `for`+`break` → `next((x for x in xs if p(x)), default)` o `any()`/`all()`.
  El `break` ya no existe → no hay mutante.

## Tipo B — Frontera inalcanzable (`x > 0` → `x >= 0` con invariante `x != 0`)

El valor límite no puede ocurrir por un invariante (tipos, validación previa).
- ¿La función es pública/llamable con el límite aunque "no deba pasar"?
  → llámala con el límite en el test y fija el comportamiento. Ya no es equivalente.
- ¿El invariante es estructural (p. ej. `len(x) >= 0`)? → refactor que disuelve
  la comparación: `if len(x) > 0:` → `if x:`; `if n >= 0` sobre un `len()` →
  eliminar la rama muerta.
- ¿Invariante de dominio garantizado aguas arriba? → mueve la validación
  (raise) a esta función y testea el raise; o pragma con el invariante citado
  en `# reason:`.

## Tipo C — Default muerto (`d.get(k, X)` cuando `k` siempre existe; kwarg default nunca usado)

La mutación de `X` no es observable porque el camino del default nunca se ejecuta.
- ¿Puede faltar la clave en algún input legal (JSON externo, config de usuario)?
  → test con la clave AUSENTE que observe `X`. Muerto.
- ¿La clave está garantizada por contrato? → refactor: `d[k]` (sin default).
  El mutante desaparece y además un KeyError temprano es mejor diagnóstico.
- Patrón ya usado en este repo (commit `e49e6d9`): `d.get(k, X)` → `d.get(k) or X`
  cuando el default debe aplicar también a valores falsy (`""`, `None` del JSON).
  OJO: solo es válido si `0`/`""`/`False` no son valores legítimos de la clave.
- Kwarg default que ninguna ruta usa → elimina el default y hazlo obligatorio.
- **El equivalente se crea AGUAS ABAJO.** Un `dict.get(k) or X` / `... or []`
  en una función *downstream* normaliza `None`/falsy → valor por defecto, lo que
  vuelve equivalente un mutante *upstream* que produce ese vacío. Caso real:
  `build_checkpoint` hacía `lr.get("findings") or []`, así que el mutante
  upstream `findings=[]→None` era inobservable (ambos → `[]`). El kill limpio
  está en la función downstream, no en el sitio del mutante: índice directo
  `lr["findings"]` si la clave es obligatoria por contrato, **o** `lr.get(k, X)`
  + un test de **clave ausente** que ejerza `X`. OJO al trade-off: `or X` hace
  matable el upstream pero deja el default-twin; `.get(k, X)` mata el upstream
  pero su default solo se prueba con la clave ausente. Elige según qué claves
  pueden faltar de verdad.
- **Filtro/guarda redundante con uno upstream.** `[p for p in package_dirs(repo)
  if "test" not in p.lower()]` es equivalente si `package_dirs` ya excluye los
  nombres `test`/`tests` exactos: el filtro local no quita nada → sus mutantes
  de string/case son inobservables. Para hacerlo observable, da un input que
  *pase* el filtro upstream pero *dispare* el local (ej. un paquete `mytests`:
  contiene "test" pero no es exactamente `tests`). Si de verdad es 100%
  redundante → elimínalo (código muerto).

## Tipo D — Código defensivo inalcanzable (ramas `else` imposibles, re-raise genéricos)

- Si la rama es inalcanzable de verdad → es código muerto: elimínala (coverage
  100% lo confirmará) o conviértela en `raise AssertionError(...)` y testea
  el raise inyectando el estado "imposible" con mocks.
- Si solo es "difícil de alcanzar" → mock de la dependencia que lo provoca
  (`side_effect=OSError(...)`) y assert del manejo exacto.

## Tipo E — Constantes de tuning (timeouts, tamaños de buffer, sleeps)

`timeout=600` → `601` no cambia ningún resultado de test... salvo que el test
observe el VALOR, no el efecto:
- Si la constante se pasa a una dependencia → §4.4 la mata siempre
  (`assert_called_once_with(..., timeout=600, ...)`). **Este tipo casi nunca
  es equivalente en este repo** — los adapters pasan todo a `subprocess`.
- Si la constante es consumida internamente sin salir (p. ej. tamaño de chunk
  con resultado idéntico para cualquier valor) → extraerla a constante de
  módulo y testear la constante (`assert DEFAULT_TIMEOUT == 600.0`), o
  pragma con reason (es de los pocos casos legítimos; ver `models.py`).

## Tipo F — String interno consistente (clave usada solo dentro del módulo)

Si la misma clave literal se escribe Y se lee dentro del código mutado en un
solo punto de mutación... en realidad mutmut muta cada literal por separado,
así que casi siempre ES matable: el lado mutado deja de encajar con el otro.
- Si sobrevive: el test no recorre el camino lectura+escritura juntos →
  test de ida y vuelta (escribir y leer por la API pública).
- Si la clave es contrato externo (JSON de verdict, argv) → assert sobre la
  salida serializada exacta.
- Refactor preventivo: literales repetidos → constante de módulo única +
  test del valor de la constante.

## Tipo G — `is` ↔ `==` con singletons (`None`, sentinels)

Para `None` y sentinels propios (`x is SENTINEL`), ambos operadores son
equivalentes de verdad si la clase no define `__eq__` raro.
- Refactor preferido: usa el patrón que haga la mutación letal — para
  sentinels, define el sentinel como `object()` y testea con un objeto que
  implemente `__eq__` devolviendo `True` para todo (`is` y `==` divergen → muere).
- Si no compensa: pragma con reason (equivalencia semántica probada).

## Tipo H — Mensajes/representaciones "que no importan"

Mensajes de log de debug, `__repr__`, textos de excepciones internas.
**No son equivalentes**: son matables con `caplog`/`capsys`/`str(exc)` (§4.3).
La pereza de assertar strings no convierte al mutante en equivalente. En este
repo los mensajes de `messages_es.py` son contrato de usuario — igualdad exacta.

## Tipo I — Mutación con efecto solo en el rendimiento de la suite (timeouts ⏰)

Un mutante `timeout` (⏰) suele ser un loop infinito creado por la mutación —
cuenta como muerto para el MSI de mutmut pero el gate de CI lo rechaza.
Investiga: casi siempre indica que falta un test rápido y específico que
mate ese mutante ANTES de colgar la suite (test unitario de la condición del
loop con frontera exacta).

---
