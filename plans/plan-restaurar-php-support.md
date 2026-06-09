# Plan: Restaurar la idea original de spec/php-support tras el refactor + caza de mutantes

> ⚠️ **NO EJECUTAR TODAVÍA**: hay trabajo activo de subagentes en el repo. Este plan se ejecuta solo cuando el usuario confirme que el repo está libre.

## Contexto

La spec `php-support` se dio por implementada, pero las sesiones de caza de mutantes (MSI 47%→82%) incluyeron refactors agresivos y el usuario teme que la idea original se haya perdido. Diagnóstico realizado (solo lectura):

**La idea central SIGUE VIVA**: detección automática de lenguaje, pipeline 5 capas (L3A→L1→L2→L3B→L4) con adaptadores PHP completos, gate duro Infection MSI 100/100 + coveredMSI 100, allow-list de ignores justificados, checkpoint JSON unificado. El refactor `69b05df` (06-04) eliminó deliberadamente la "visión standalone" (~2.3k LOC: detector/dispatcher/doctor/installer/configurator/híbridos) — decisión aceptada por el usuario, EXCEPTO:

**Problemas confirmados:**

1. **Trabajo perdido por accidente**: el 06-07 a las 09:50 cinco `git reset HEAD~1` dejaron huérfanos 7 commits. El crítico es `74c4eb5` (doctor CLI re-implementado + rechazo de config v1 con exit 4 / FR-34). Hoy: los E2E `tests/e2e/test_doctor_missing_php.py` **fallan** (exit 2, verificado) y `config.load()` existe pero nada lo invoca desde el CLI. Hay un `stash@{0}` encima de 74c4eb5 con ajustes menores (pyproject + 2 tests).
2. **Capas L2/L3B intercambiadas en PhpAdapter** vs. la idea original (L2 = calidad de tests/weak-tests; L3B = deep quality): `run_l2` repite antipatrones Tier A (duplicado de L3A) y `run_l3b` ejecuta los weak-tests A1–A8. El step `steps/step-03-layer2-php.md` llama a `run_l2` esperando weak-tests → obtiene lo equivocado.
3. **Comandos documentados rotos**: `step-03-layer2-php.md:17` usa `--repo` (no existe; repo es posicional); `step-03-layer2.md:23` (python) invoca `python3 ${CLAUDE_SKILL_DIR}/harness_quality_gate.adapters.python.weak_test` (ruta con puntos, inválida; el módulo sí tiene `__main__` en weak_test.py:316).
4. **Docs desfasadas**: `config/php-tool-taxonomy.json` (infection=L3B debería ser L1; deptrac=L3A debería ser L4); README con framing solo-Python; `HARNESS_INFECTION_REQUIRED` (php_adapter.py:534) sin documentar; `references/security-tools-guide-php.md` sin 3 herramientas que L4 sí ejecuta (psalm-taint, dead-code-detector, composer-dependency-analyser); `steps/step-06-layer4.md` sin mención PHP pese a que step-04-php enlaza a él; `weak_test_php.py.bak` huérfano dentro del paquete.
5. **Los E2E nunca se ejecutan**: todos los targets de make corren solo `tests/unit/` — por eso nadie vio los fallos.

**Decisiones del usuario:**
- Intercambiar L2/L3B en código (alinear con la idea original).
- Re-implementar doctor + config v1 a mano (consultar commit huérfano `74c4eb5` como referencia de solo lectura).
- Aceptar la detección simple (composer.json → PHP, si no → Python); híbridos descartados.

## Cambios

### Fase 1 — Re-implementar doctor + config v1 (commit huérfano solo como referencia de LECTURA)

> **Regla de oro: NO tocar el estado de git.** Nada de `cherry-pick`, `stash apply/pop`, `reset` ni reescritura de historia. El commit huérfano `74c4eb5` y `stash@{0}` se consultan solo con comandos de lectura (`git show 74c4eb5 -- harness_quality_gate/cli.py`, `git stash show -p stash@{0}`) y el código se escribe a mano, quirúrgicamente, sobre el working tree actual.

1. Leer `git show 74c4eb5` como referencia y re-implementar manualmente en `harness_quality_gate/cli.py`:
   - Subcomando `doctor` (`_cmd_doctor` + `_check_tool`): chequea python/php/composer, construye `DoctorReport`, exit 3 (INFRA_INCOMPLETE) si falta runtime, `--json`.
   - Cableado de `config.load(repo)` en `_cmd_all`: `ConfigInvalid` → exit 4 (CONFIG_INVALID); `FileNotFoundError` → continuar sin config.
2. Mejoras sobre la versión huérfana (que quedó a medias):
   - Poblar `php_version`/`composer_version` desde `ToolCheckReport.output` cuando la herramienta exista (la versión huérfana dejaba "not found" siempre).
   - Actualizar el docstring de cli.py con los exit codes 3 y 4.
   - Verificar que `models.DoctorReport`/`ToolCheckReport` actuales casan con lo que se implementa.
3. Leer `git stash show -p stash@{0}` (pyproject.toml, test_config_v1_hard_error.py, test_coverage_gaps.py): si contiene ajustes aún válidos, re-escribirlos a mano. **No tocar el stash**.
4. Los otros 6 commits huérfanos (refactors de adaptadores + 363 tests) NO se recuperan. Solo lectura si hace falta contexto.

### Fase 2 — Corregir el intercambio L2/L3B en PhpAdapter

Archivo: `harness_quality_gate/adapters/php/php_adapter.py`
- `run_l2` (línea ~760) → pasa a ejecutar weak-tests A1–A8 vía `PhpWeakTestLayerAdapter` (el cuerpo actual de `run_l3b`), con `layer="L2"`.
- `run_l3b` (línea ~798) → pasa a ejecutar el merge de antipatrones Tier A (cuerpo actual de `run_l2`), con `layer="L3B"`. Nota en docstring: el Tier B real (BMAD) lo orquesta el step a nivel LLM.
- Actualizar tests unitarios afectados: `tests/unit/adapters/php/test_php_adapter_full.py` y cualquier test que asuma el mapeo viejo (buscar `run_l2`/`run_l3b` en tests/).
- `checkpoint.py` no mapea nombres semánticos de capas (verificado) — sin cambios allí.

### Fase 3 — Arreglar steps de la skill (la interfaz real del producto)

- `steps/step-03-layer2-php.md`: quitar `--repo` (posicional). Tras la Fase 2, su llamada a `run_l2` para weak-tests queda correcta.
- `steps/step-03-layer2.md` (python, línea 23): corregir invocación a `python3 -m harness_quality_gate.adapters.python.weak_test {project-root}/tests/ {project-root}/src/`.
- `steps/step-04-layer3b-php.md`: añadir nota de que el adaptador `run_l3b` cubre la parte determinista (antipatrones Tier A) y el juicio BMAD Tier B es del LLM.
- `steps/step-06-layer4.md`: añadir subsección PHP documentando que `PhpAdapter.run_l4` ejecuta psalm-taint, composer audit, local-php-security-checker, dead-code-detector, composer-dependency-analyser y deptrac.

### Fase 4 — Sincronizar documentación y limpieza

- `config/php-tool-taxonomy.json`: infection → `"layer": "L1"`; deptrac → `"layer": "L4"`.
- `README.md`: sección de soporte PHP (adaptadores, capas, gate Infection 100/100, detección composer.json) y documentar `HARNESS_INFECTION_REQUIRED`.
- `references/security-tools-guide-php.md`: añadir psalm --taint-analysis, shipmonk/dead-code-detector, shipmonk/composer-dependency-analyser.
- `SKILL.md`: nota explícita de la política de detección — repo con composer.json se trata como PHP-only; híbridos no soportados (decisión 69b05df ratificada).
- Eliminar `harness_quality_gate/adapters/php/weak_test_php.py.bak`.
- `tests/fixtures/hybrid-py-php/`: confirmar con grep que ningún test lo usa y eliminarlo.

### Fase 5 — Hacer visibles los tests E2E/integración

- Añadir target `make test-e2e` (`pytest tests/e2e/ tests/integration/ -q -m "e2e or integration"`, respetando markers needs-php/needs-composer) y encadenarlo o mencionarlo en `check-tests` para que no vuelvan a quedar invisibles.

## Verificación

1. `make check-tests` (unit completo) — verde.
2. `.venv/bin/python -m pytest tests/e2e/test_doctor_missing_php.py tests/e2e/test_config_v1_hard_error.py -q` — verde (hoy doctor falla con exit 2).
3. `make coverage` — se mantiene 100%.
4. `python -m harness_quality_gate all tests/fixtures/php-pure-pass --json`: checkpoint con L2=weak-tests y L3B=antipatrones; gate Infection intacto. Repetir con un fixture Python para confirmar que Python sigue intacto.
5. `python -m harness_quality_gate doctor . --json` → JSON con `verdict`; con PATH restringido → exit 3.
6. Tras estabilizar: `make mutation` para confirmar que el MSI no retrocede con el swap; ajustar tests/pragmas solo si aparecen supervivientes nuevos en el código movido.

## Restricciones operativas

1. **No empezar** hasta que el usuario confirme que los subagentes activos han terminado.
2. **Preservar el flujo de git**: cero operaciones que muevan refs o el stash (cherry-pick, apply, pop, reset, rebase). Commits huérfanos y stash son de solo lectura.
3. Commits: pequeños e incrementales siguiendo el estilo del repo, solo cuando el usuario lo pida.
