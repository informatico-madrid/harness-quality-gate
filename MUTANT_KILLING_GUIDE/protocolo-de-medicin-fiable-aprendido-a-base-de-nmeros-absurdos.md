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
   (`exit_code_by_key`: 0=survived, 1=killed, -24=ver H16);
   `scripts/extract_survivors.py` la resume por método.
6. **Captura los diffs ANTES de `clean-mutmut`**: la limpieza destruye TODOS
   los metas (también los de archivos que no ibas a re-medir). Vuelca primero
   los supervivientes a un archivo de trabajo:
   `mutmut show <id>` en bucle → `/tmp/survivors.txt` — y luego limpia.
   Corolario: un `mutation-path` tras un clean repuebla SOLO el filtro pedido;
   el resto del board queda vacío hasta el siguiente run amplio.
