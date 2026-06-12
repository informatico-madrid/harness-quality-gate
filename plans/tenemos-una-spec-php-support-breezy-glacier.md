# Plan unificado y final — php-support: cableado funcional + e2e reales

## Contexto

La spec `specs/php-support` se implementó y luego se refactorizó agresivamente (campaña MSI 47%→100%, eliminación deliberada de ~2.3k LOC de fontanería: detector/dispatcher/doctor/installer/configurator/concurrency/state/framework_sniffer/messages_fr/checkpoint_v2). El refactor rompió cableados de features y dejó los e2e obsoletos. Este plan **reemplaza** a `plans/plan-restaurar-php-support.md` y `plans/plan-restaurar-php-support-revisado.md`, integrando sus análisis con la **realidad verificada del código a 2026-06-11**.

**Objetivo**: la skill funciona perfectamente en repos Python (como funcionaba originalmente) y en repos PHP (el soporte añadido), con el mínimo código modificado, manteniendo 100% coverage y 100% MSI, y con e2e que verifican exactamente esa realidad funcional.

### Estado verificado del código (auditoría 2026-06-11)

| Sospecha del plan revisado | Estado real verificado |
|---|---|
| PyrightAdapter.parse() crash | **CONFIRMADO** — [pyright_adapter.py:75](harness_quality_gate/adapters/python/pyright_adapter.py#L75) acepta 1 arg; [python_adapter.py:245](harness_quality_gate/adapters/python/python_adapter.py#L245) le pasa 3 → TypeError → exit 5 |
| P7 tool_specific no serializable | **CONFIRMADO** — [cli.py:131-132](harness_quality_gate/cli.py#L131-L132) pasa `lr.tool_specific` sin `_asdict()`; `checkpoint.build()` tampoco lo procesa ([checkpoint.py:63-64](harness_quality_gate/checkpoint.py#L63-L64)). MutationStats dataclass → `validate()`/`json.dumps` crash → checkpoint timestamped se pierde silenciosamente |
| P8 rule_id null → ValidationError | **CONFIRMADO** — cli.py:128 convierte findings a dicts CON Nones; `checkpoint.build._to_dict` ([checkpoint.py:42-48](harness_quality_gate/checkpoint.py#L42-L48)) solo strippea Nones de dataclasses, no de dicts |
| P9 write sin try/except | **YA HECHO** — cli.py:158-172 ya envuelve ambos writes. No tocar |
| P10 OSError no capturado | **CONFIRMADO** — `BaseAdapter._run` ([base.py:187](harness_quality_gate/adapters/base.py#L187)) deja propagar FileNotFoundError; php_adapter.py tiene ~17 `except RuntimeError` (líneas 370-930) que no lo capturan. phpunit_adapter.invoke no comprueba binario → `vendor/bin/phpunit` ausente = crash exit 5 |
| Config v1 rejection no cableado | **CONFIRMADO** — `_cmd_all()` nunca llama `config.load()`; `CONFIG_INVALID=4` e `INFRA_INCOMPLETE=3` definidos en exit_codes.py pero jamás emitidos |
| Capas L2/L3B desalineadas | **CONFIRMADO** — glosario spec (requirements.md ~línea 686): L1=ejecución tests+coverage+mutación, L2=test quality (weak-tests+diversity+kill-map), L3B=deep (SOLID+Tier B BMAD+arquitectura/Deptrac). Python: L2=ruff+vulture+deptry, L3B=mutmut. PHP: L2=antipatterns TierA, L3B=weak-tests. Ambos desalineados |
| Steps con invocaciones rotas | **CONFIRMADO** — 7+ errores (detalle en Fase 4) |
| Taxonomy con capas mal | **CONFIRMADO** — infection=L3B (debe ser L1), etc. Solo lo consumen docs, ningún .py |
| e2e obsoletos | **CONFIRMADO** — `test_doctor_missing_php.py` prueba subcomando eliminado; `test_config_v1_hard_error.py` acepta exit codes laxos; no existen smoke tests |

### Decisiones fijadas (ratificadas por Joao 2026-06-11)

1. **mutmut → L1 Python** (paridad con Infection en L1 PHP, según glosario spec).
2. **vulture+deptry → L4 Python** (equivalentes de dead-code-detector/composer-dependency-analyser que PHP corre en L4).
3. **deptrac → L3B PHP** (mover bloque de run_l4 a run_l3b; coherente con spec y taxonomía).
4. **parse(): solo arreglar PyrightAdapter** (los ~10 `*_compat` funcionan; no normalizar).

### Decisiones deliberadas que NO se revierten (commit 69b05df)

- No recrear doctor/detector/dispatcher/installer/configurator/concurrency/state/framework_sniffer/messages_fr/checkpoint_v2.
- CLI solo con `all` y `audit-ignores`. Infra-check y config-rejection se cablean **dentro** de `_cmd_all()`.
- Detección simple: composer.json → PHP, si no → Python. Sin híbridos, sin 3-tier, sin cache.
- No usar commit huérfano 74c4eb5 como referencia.

## Modelo de capas objetivo

| Capa | Python (`PythonAdapter`) | PHP (`PhpAdapter`) |
|---|---|---|
| L3A smoke | ruff + pyright *(sin cambio)* | phpstan + phpmd + php-cs-fixer + visitors Tier A *(sin cambio)* |
| L1 ejecución | pytest + **mutmut** *(movido desde L3B, conserva MutationStats + remediation)* | phpunit/pest + pcov + infection *(sin cambio)* |
| L2 test quality | **weak_test A1-A8 + diversity** *(nuevo cableado)* | **weak-tests A1-A8** *(cuerpo actual de run_l3b, layer="L2")* |
| L3B deep | **solid_metrics + antipattern Tier A** *(nuevo cableado; Tier B BMAD lo orquesta el LLM vía steps)* | **antipatterns Tier A** *(cuerpo actual de run_l2, layer="L3B")* + **deptrac** *(movido desde L4)* |
| L4 seguridad | bandit + **vulture + deptry** *(movidos desde L2)* | psalm-taint + composer-audit + security-checker + dead-code + dep-analyser *(deptrac sale)* |

Reutilizar funciones existentes — **no escribir analizadores nuevos**:
- `harness_quality_gate/adapters/python/weak_test.py:268` → `run_weak_test_analysis(tests_dir, src_dir) -> dict`
- `harness_quality_gate/bmad/diversity_metric.py:185` → `diversity(repo, language) -> dict`
- `harness_quality_gate/adapters/python/solid_metrics.py:210` → `analyze_solid(src_dir) -> dict`
- `harness_quality_gate/adapters/python/antipattern_tier_a.py` → función de análisis existente (verificar entrypoint, tiene detect_ap01..ap17)

---

## Fase 0 — Bugs de crash y serialización (hace `all` ejecutable de punta a punta)

1. **PyrightAdapter.parse** ([pyright_adapter.py:75](harness_quality_gate/adapters/python/pyright_adapter.py#L75)): firma → `parse(self, stdout: str, *_compat: object)` con `# type: ignore[override]`, igual que RuffAdapter.
2. **P7** ([cli.py:132](harness_quality_gate/cli.py#L132)): `ld["tool_specific"] = _asdict(lr.tool_specific)`.
3. **P8** ([checkpoint.py:42-48](harness_quality_gate/checkpoint.py#L42-L48)): extender `_to_dict` para strippear Nones también de dicts planos: `if isinstance(obj, dict): return {k: v for k, v in obj.items() if v is not None}`.
4. **P10** (php_adapter.py): ampliar los ~17 `except RuntimeError` a `except (OSError, RuntimeError)` (líneas 370, 378, 398, 406, 447, 478, 557, 645, 674, 745, 773, 841, 859, 876, 894, 912, 930 — verificar tras Fase 1 porque las líneas se mueven), patrón idéntico a PythonAdapter.

Tests unitarios para cada fix (incluye test de regresión: tool_specific con MutationStats serializa; finding-dict con rule_id None valida; invoke que lanza FileNotFoundError se degrada a warning).

## Fase 1 — Re-mapeo de capas (mínimo movimiento, máxima reutilización)

**PhpAdapter** ([php_adapter.py](harness_quality_gate/adapters/php/php_adapter.py)):
- `run_l2` (línea ~751) ⇄ `run_l3b` (línea ~789): intercambiar cuerpos; ajustar `layer="L2"`/`"L3B"` en LayerResults (el weak-test delegado `PhpWeakTestLayerAdapter.run_l3b` debe emitir layer="L2" — renombrar/parametrizar ese método en weak_test_php.py).
- Mover el bloque deptrac de `run_l4` (~línea 930) al nuevo `run_l3b`.
- Docstrings de capas actualizados.

**PythonAdapter** ([python_adapter.py](harness_quality_gate/adapters/python/python_adapter.py)):
- `run_l1` (línea 105): añadir mutmut tras pytest (mover `_run_mutmut` + `_mutation_remediation` + tool_specific desde run_l3b). `passed` = pytest sin findings AND survived==0 AND timed_out==0. Si mutmut no está en PATH se mantiene el skip-con-warning actual (comportamiento original Python: degradación elegante).
- `run_l2` (línea 127): sustituir ruff/vulture/deptry por `run_weak_test_analysis()` (convertir su dict a Findings) + `diversity()` en `tool_specific["diversity"]`. Manejar repos sin `tests/`/`src/` (0 findings, passed=True).
- `run_l3b` (línea 157): sustituir mutmut por `analyze_solid()` + antipattern Tier A (convertir violaciones a Findings; métricas en tool_specific). Tier B BMAD queda en steps (LLM).
- `run_l4` (línea 204): añadir `_run_vulture` y `_run_deptry` junto a bandit.

Actualizar tests unitarios afectados (`tests/unit/adapters/python/`, `tests/unit/adapters/php/test_php_adapter_full.py`, `tests/unit/test_python_adapters.py`...). Todo valor que entre a `tool_specific` debe ser JSON-serializable o pasar por `_asdict` (Fase 0.2 ya lo garantiza).

## Fase 2 — Exit codes 3 y 4 dentro de `_cmd_all()` ([cli.py](harness_quality_gate/cli.py))

**2a. Config v1 rejection (exit 4)** — tras `_detect_language`:
```python
from .config import ConfigInvalid, load as config_load
from .exit_codes import CONFIG_INVALID
try:
    config_load(repo)
except ConfigInvalid as exc:
    return _exit_with(CONFIG_INVALID, {"error": str(exc), "exit_code": CONFIG_INVALID}, quiet=args.quiet)
except FileNotFoundError:
    pass  # sin config → defaults
```
`config.load`/`ConfigInvalid` ya existen ([config.py:59,172](harness_quality_gate/config.py#L59)); busca `.quality-gate.yaml`, `config/quality-gate.yaml`, `quality-gate.yaml`. El mensaje ya existe: `messages_es.py` key `err.config.v1`.

**2b. Infra-check PHP (exit 3)** — solo si `language == "php"`, antes de ejecutar capas: comprobar herramientas críticas (binario `php`, phpunit, phpstan, infection — vía `shutil.which` o `vendor/bin/<tool>` del repo objetivo). Si falta alguna → `_exit_with(INFRA_INCOMPLETE, {"error": <msg con lista>, "missing_tools": [...], "exit_code": 3})`. Añadir key `err.infra.missing` a `messages_es.py`. Implementación inline o como método pequeño `PhpAdapter.missing_critical_tools(repo) -> list[str]` (nota: el `check_tools()` existente usa `Path.cwd()`, no sirve para el repo objetivo sin ajuste). **Python NO lleva infra-check**: su comportamiento original es degradación elegante con warnings.

## Fase 3 — Suite e2e alineada a la realidad funcional deseada

- **Eliminar** `tests/e2e/test_doctor_missing_php.py` (prueba subcomando eliminado).
- **Reescribir** `tests/e2e/test_config_v1_hard_error.py`: con Fase 2a, `all` sobre `tests/fixtures/legacy-config-v1` → **exit 4 exacto** + JSON `{"error", "exit_code": 4}`.
- **Crear** `tests/e2e/test_smoke_python.py`: `python3 -m harness_quality_gate all tests/fixtures/python-pure-pass --json` → no crash, JSON válido, `language=="python"`, 5 capas L3A/L1/L2/L3B/L4, L1 con mutation_stats serializado en tool_specific, checkpoint escrito en disco y válido contra `references/verdict-schema.json`. Variante con PATH restringido → completa sin crash (skips con warning).
- **Crear** `tests/e2e/test_smoke_php.py` (markers `e2e` + `needs-php`/`needs-composer`, ya configurados en pyproject.toml): fixture session-scoped que hace `composer install` en `tests/fixtures/php-pure-pass` si falta vendor/ (skip si composer/red no disponibles; en esta máquina hay PHP 8.3 + composer). Asserts: `language=="php"`, 5 capas, L1 con Infection stats, L2 = weak-tests, L3B = antipatterns+deptrac, exit ∈ {0,1}.
- **Crear** `tests/e2e/test_infra_incomplete.py`: tmp repo con composer.json + `PATH=/usr/bin` recortado sin herramientas PHP → **exit 3** con `missing_tools` en JSON.
- **Makefile**: target `test-e2e: $(VENV)/bin/python -m pytest tests/e2e/ -q -m e2e --tb=short` + mención en help. (CI ya corre todo pytest; los e2e con needs-php hacen skip limpio donde falte toolchain.)

## Fase 4 — Steps de la skill y taxonomy

Correcciones de invocación (el CLI real es `python3 -m harness_quality_gate all <repo> [--json] [--quiet]`; los módulos sueltos se invocan con `-m`):
- `steps/step-03-layer2-php.md:17` — quitar `--repo` (el repo es posicional).
- Sintaxis con puntos → `-m`: `steps/step-02-layer1.md:109`, `steps/step-03-layer2.md:23,79`, `steps/step-03a-layer3a.md:110,145,180` (`python3 ${CLAUDE_SKILL_DIR}/harness_quality_gate.x.y` → `python3 -m harness_quality_gate.x.y`).
- Placeholders literales no ejecutables: `steps/step-04-layer3b.md:37,182` (`BMAD Tier B (deferred)`) y `steps/step-03-layer2.md:110` (`Deferred`) → invocación real de los módulos bmad existentes (`harness_quality_gate.bmad.llm_solid_judge` / `antipattern_judge` / `diversity_metric` — verificar entrypoints `main()` de cada uno) o procedimiento BMAD documentado si el módulo solo genera contexto.
- `steps/step-06-layer4.md:113` — invocación malformada con espacios → módulo correcto; añadir subsección PHP (psalm-taint, composer-audit, security-checker, dead-code, dep-analyser; nota: deptrac ahora en L3B).
- `steps/step-04-layer3b-php.md` — nota: `run_l3b` cubre la parte determinista (Tier A + deptrac); el juicio Tier B BMAD es del LLM.

`config/php-tool-taxonomy.json` (solo lo consumen docs): infection → **L1**; deptrac → **L3B**; shipmonk/dead-code-detector → **L4**; shipmonk/composer-dependency-analyser → **L4**.

## Fase 5 — Documentación, spec y limpieza

- `specs/php-support/`: añadir sección "Decisiones deliberadas post-refactor" (en requirements.md o `decisions.md` nuevo): solo `all`+`audit-ignores`, detección simple, módulos eliminados no se restauran, infra-check/config-rejection inline en `_cmd_all()`, mapa de capas final (tabla de arriba). Purgar de design.md/tasks.md las referencias a los 12 subcomandos y módulos eliminados (cli.py es el entry point, no dispatcher.py).
- `SKILL.md`: política de detección explícita (composer.json ⇒ PHP-only; híbridos no soportados); completar lista de herramientas PHP (deptrac, psalm --taint-analysis, composer audit).
- `README.md`: sección soporte PHP (adaptadores, capas, gate Infection 100/100, detección). **No documentar `HARNESS_INFECTION_REQUIRED`** — verificado: no existe en el código (el plan revisado lo arrastraba por error).
- `references/security-tools-guide-php.md`: añadir psalm --taint-analysis y shipmonk tools.
- Limpieza de fixtures sin uso (verificado por grep: ningún test las referencia): `tests/fixtures/hybrid-py-php/`, `tests/fixtures/php-no-runtime/`, `tests/fixtures/installer-config/` (re-grep antes de borrar; `test_checkpoint_contract.py` menciona "hybrid" a nivel de schema, no de fixture).

## Verificación (cada fase + final)

1. `make check-tests` — suite unit verde (2615+ tests).
2. `make coverage` — **100%** se mantiene.
3. `make mutation` (o `make mutation-path FILE_PATH=<archivo>` por cada archivo tocado durante el desarrollo; mutmut con `--max-children 40`; si mutmut se comporta raro: reinstalar antes de investigar) — **MSI 100%** se mantiene; mutantes nuevos muertos con tests reales, pragmas solo con justificación reason/audited.
4. `make test-e2e` — verde (skips limpios solo donde falte toolchain).
5. Dogfooding manual:
   - `python3 -m harness_quality_gate all tests/fixtures/python-pure-pass --json` → exit {0,1}, JSON válido, 5 capas correctas, sin TypeError.
   - `python3 -m harness_quality_gate all tests/fixtures/php-pure-pass --json` (con vendor instalado) → exit {0,1}, L1 con Infection, L2 weak-tests, L3B antipatterns+deptrac.
   - `PATH=/usr/bin python3 -m harness_quality_gate all <repo-php>` → exit 3 con mensaje claro.
   - `all` sobre `tests/fixtures/legacy-config-v1` → exit 4.
6. `python3 -m harness_quality_gate audit-ignores .` → exit 0.

## Restricciones operativas

- **Git intocable**: no commits/push salvo petición explícita de Joao; cambios quirúrgicos, alcance estricto.
- No restaurar módulos eliminados; no crear subcomandos; no detección híbrida.
- Subagentes nunca tocan código fuente de mutmut (solo tests).
- Orden de ejecución de fases: 0 → 1 → 2 → 3 → 4 → 5 (la 0 desbloquea el dogfooding que valida las demás). Las fases 4 y 5 son paralelizables entre sí.
