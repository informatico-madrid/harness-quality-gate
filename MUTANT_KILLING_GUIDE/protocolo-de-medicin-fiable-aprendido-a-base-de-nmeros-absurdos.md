# Protocolo de medición fiable (aprendido a base de números absurdos)

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
   (`exit_code_by_key`: 0=survived, 1=killed, -24=ver H16/H17, exit=3=
   `MemoryError`/pytest INTERNAL ERROR — ver H17);
   `scripts/extract_survivors.py` la resume por método.
6. **Captura los diffs ANTES de `clean-mutmut`**: la limpieza destruye TODOS
   los metas (también los de archivos que no ibas a re-medir). Vuelca primero
   los supervivientes a un archivo de trabajo:
   `mutmut show <id>` en bucle → `/tmp/survivors.txt` — y luego limpia.
   Corolario: un `mutation-path` tras un clean repuebla SOLO el filtro pedido;
   el resto del board queda vacío hasta el siguiente run amplio.
7. **Un `.coverage` parcial INFRA-cuenta el board dramáticamente.** Con
   `mutate_only_covered_lines = true`, si el `.coverage` se generó desde un
   SUBCONJUNTO de tests (lo dejó un `mutation-path`, un run de un solo archivo,
   o una sesión interrumpida), mutmut solo muta esas líneas: el board muestra
   muchísimos menos mutantes y supervivientes de los reales. Caso real
   (2026-06-24): el board visible decía **60 supervivientes**; tras regenerar
   `.coverage` desde la suite COMPLETA, eran **111** (de 8786 mutantes). Un
   board "limpio" tras un run parcial es una **mentira**. → Antes de fiarte de
   cualquier conteo: `pytest tests/unit/ --cov=harness_quality_gate
   --cov-report=` con el scope COMPLETO, luego `make clean-mutmut` y run amplio.
8. **Un `mutmut run` largo (>10 min) necesita backgrounding REAL, no un
   `nohup ... & echo PID; disown` metido dentro de una llamada de shell normal.**
   Ese patrón hace que el harness marque la tarea "completed" en cuanto el
   WRAPPER (el `echo`) termina — no cuando `mutmut` de verdad acaba — porque
   `disown` desliga el proceso de la sesión pero no cambia qué comando está
   siendo trackeado. Leer `export-cicd-stats` en ese punto captura el sqlite de
   mutmut A MITAD DE ESCRITURA: produce basura tipo `killed=0, survived=0,
   total=N` que parece "mutmut roto" (dispara la regla del punto 4) pero es
   solo una condición de carrera del propio operador, no un fallo de mutmut.
   Caso real (2026-07-02): confirmado con `ps aux` que el proceso seguía vivo
   (`grep mutmut`) mientras el export ya mostraba 0/0. → Usa el parámetro nativo
   de backgrounding de tu herramienta (el que el harness trackea de verdad y te
   notifica al terminar), NO un truco manual de shell. Si ya lanzaste mal:
   verifica con `ps aux | grep mutmut` antes de leer ningún número — si hay
   proceso vivo, espera a que `ps` no muestre nada (ni siquiera `<defunct>`)
   antes de exportar.
