# H21. Parsers de índice manual: el clúster de timeouts+supervivientes es un olor arquitectónico, no una lista de mutantes

**Caso real** (rompehielos, `characterisation.extract_scenario_names`, 2026-07-04):
un parser Gherkin con `while i < len(lines): ... i += 1` (avance manual del
índice, sentinelas `header_idx = None`, `last_example_row = header_idx`) tenía
**20 de 26 mutantes problemáticos** (11 supervivientes + 9 timeouts reales —
bucles infinitos de verdad, no espurios) concentrados en un único bloque.

**Por qué el enfoque "uno a uno" falla aquí:** aplicar H9 (test rápido para
CADA condición de salida) mutante a mutante funciona pero es la señal, no la
cura — cuando >50% de los mutantes de una función caen en aritmética de
índices (`i += 1 → i += 2`, `k = x + 1 → x - 1`, sentinela `None → True`), la
función misma es el problema: **cualquier** desplazamiento de un token en el
avance manual puede colgar el parser o saltarse una entrada.

**La receta de un solo paso NO basta — hay una trampa de segundo orden.**
Reescribir el `while` a una máquina de estados con flags booleanos (`in_examples
= False`, `header_seen = False`, …) SÍ mata los timeouts (ya no hay índices que
desbordar), pero crea una **nueva** oleada de supervivientes: los mutantes
`False → None` / `False → True` sobre esos flags son gemelos falsy en
inicializadores (ver [H15](h15-gemelos-falsy-en-inicializadores-none-falsenone-none.md))
que se resetean antes de leerse — equivalentes reales, ~20 nuevos en este caso.

**Fix correcto: eliminar el estado mutable por completo, no solo los índices.**
Partir el input en bloques inmutables por adelantado (`starts = [i for i, ln in
enumerate(lines) if ln.strip().lower().startswith(("scenario:", "scenario
outline:"))]`) y procesar cada bloque `lines[start:end]` con funciones puras
sobre slices (`pipe_rows[1:]` en vez de un contador que salta la cabecera). Sin
variables de estado de larga vida, casi no queda superficie de equivalentes: en
este caso, de 20 supervivientes en la versión stateful se pasó a 2 (ambos en el
cálculo del límite del bloque, `end = starts[k+1] if k+1<len(starts) else
len(lines)`), matados con UN test (outline sin `Examples:` seguido de outline
CON `Examples:` no debe robar la tabla del siguiente).

**Diagnóstico rápido:** si el clúster de supervivientes/timeouts de una función
es grande Y las mutaciones son todas variaciones de `i±1`, `None` de sentinela,
o de un flag booleano — no sigas escribiendo tests de frontera uno a uno.
Reescribe el algoritmo a slicing/comprehensions sin contador; si la primera
reescritura todavía usa flags de larga vida, esa es la señal de que hace falta
una segunda pasada hacia stateless puro, no más tests.
