# Plan: Restaurar la idea original de spec/php-support (revisado y alineado con decisiones deliberadas)

> **NO EJECUTAR TODAVÍA** — esperar confirmación del usuario.

## Contexto

La spec `php-support` se dio por implementada. Las sesiones de caza de mutantes (MSI 47%→100%)
incluyeron refactors agresivos. El commit `69b05df` (2026-06-04) **eliminó deliberadamente**
~2.3k LOC de fontanería standalone: `detector.py`, `dispatcher.py`, `doctor.py`, `installer.py`,
`configurator.py`, `framework_sniffer.py`, `concurrency.py`, `state.py`, `messages_fr.py`,
`checkpoint_v2.py`.

**Decisión deliberada ratificada**: el skill es invocado por un LLM, no como CLI standalone.
Solo `all` y `audit-ignores` son subcomandos necesarios. La detección es simple
(composer.json → PHP, si no → Python). No híbridos.

Este plan `plan-restaurar-php-support.md` fue creado el 2026-06-09, 5 días DESPUÉS de la
eliminación deliberada. Decía aceptar la decisión pero luego la contradecía proponiendo
re-crear `doctor.py` como módulo/subcomando. Este documento **reemplaza** esa versión con
los análisis corregidos.

**Problemas confirmados que SÍ necesitan arreglarse:**

1. **Capas L2/L3B intercambiadas** en PhpAdapter Y PythonAdapter.
   - Espec: L2 = test quality (weak-tests, diversity, mutation kill-map);
     L3B = deep quality (SOLID Tier B BMAD, antipatterns deep, Deptrac).
   - PhpAdapter: `run_l2` = antipatterns Tier A (duplicado de L3A), `run_l3b` = weak-tests.
   - PythonAdapter: `run_l2` = ruff+vulture+deptry (linting), `run_l3b` = mutmut (mutation).
   - Ambos tienen las capas intercambiadas respecto a la idea original.

2. **Config v1 rejection no cableado**: `config.py:ConfigInvalid` existe pero `_cmd_all()` nunca
   carga config. El e2e `test_config_v1_hard_error.py` falla con exit 5 (INTERNAL_ERROR)
   en vez de 4 (CONFIG_INVALID).

3. **Infra-check no emitida**: cuando herramientas PHP faltan, los adaptadores loguean warnings
   pero `_cmd_all()` sale con exit 0 (PASS) en vez de exit 3 (INFRA_INCOMPLETE). La FEATURE
   de diagnosticar infra falta (FR-26/27) es necesaria, pero la FORMA de subcomando `doctor`
   fue eliminada deliberadamente. Se cableará dentro de `_cmd_all()`.

4. **Tests e2e de doctor prueban feature eliminada**: `test_doctor_missing_php.py` asume
   subcomando `doctor` que no existe.

5. **php-tool-taxonomy.json tiene 4 capas incorrectas**.

6. **Steps con errores**: `--repo` posicional en step-03-layer2-php, invocación con puntos
   en step-03-layer2.md, step-04-layer3b-php sin nota BMAD, step-06 sin PHP.

7. **E2e tests nunca se ejecutan en CI**: Makefile solo corre `tests/unit/`.

8. **Spec docs desactualizadas**: requirements.md, design.md, tasks.md describen 12 subcomandos
   y módulos que ya no existen por decisión deliberada.

## Decisiones deliberadas (NO se revierten)

- **No crear `doctor.py`** como módulo ni subcomando. La diagnosis de infra se cablea dentro
  de `_cmd_all()`.
- **No crear `detector.py`**, `dispatcher.py`, `concurrency.py`, `state.py`, `installer.py`,
  `configurator.py`**. Eliminados deliberadamente. Funcionalidad inlineada.
- **No crear 10 subcomandos CLI**. Solo `all` y `audit-ignores`.
- **No implementar detección 3-tier/hybrid**. Detección simple de 5 líneas.
- **No crear `legacy_shims/`**. Sin backward compat.
- **No usar commit huérfano 74c4eb5 como referencia**. Es código standalone eliminado.

## Cambios

### Fase 1 — SWAP L2/L3B en ambos adaptadores

Espec (glosario requirements.md:686):
- **L2** = test quality: weak-test detection + diversity + mutation kill-map
- **L3B** = deep quality: SOLID + antipattern Tier B BMAD + Deptrac architecture

**PhpAdapter** (`harness_quality_gate/adapters/php/php_adapter.py`):
- `run_l2` (línea ~751): actualmente ejecuta antipatterns Tier A → cambiar a weak-tests A1-A8
  vía `PhpWeakTestLayerAdapter` (el cuerpo actual de `run_l3b`), con `layer="L2"`.
- `run_l3b` (línea ~789): actualmente ejecuta weak-tests → cambiar a antipatterns Tier A merge
  (cuerpo actual de `run_l2`), con `layer="L3B"`. Nota: Tier B (BMAD) lo orquesta el LLM
  a través de steps, no el adaptador.

**PythonAdapter** (`harness_quality_gate/adapters/python/python_adapter.py`):
- `run_l2` (línea ~127): actualmente ejecuta ruff+vulture+deptry (linting) → cambiar a
  weak-test detection + diversity.
- `run_l3b` (línea ~157): actualmente ejecuta mutmut (mutation) → cambiar a SOLID metrics
  + antipatterns Tier B (BMAD).

Actualizar tests unitarios afectados en `tests/unit/adapters/php/test_php_adapter_full.py`
y `tests/unit/adapters/python/`. Preservar 100% coverage y 100% MSI.

### Fase 2 — Cablear config v1 rejection e infra-check en `_cmd_all()`

**Archivo**: `harness_quality_gate/cli.py`

2a. **Config v1 rejection**: Anadir despues de la detección de lenguaje:
```python
from .config import ConfigInvalid, load as config_load
from .exit_codes import CONFIG_INVALID

try:
    config_load(repo)
except ConfigInvalid as exc:
    return _exit_with(
        CONFIG_INVALID,
        {"error": str(exc), "exit_code": CONFIG_INVALID},
        quiet=args.quiet,
    )
except FileNotFoundError:
    pass  # No config file, use defaults
```

2b. **Infra-check (FR-26/27)**: Antes de ejecutar las capas, si `language == "php"`,
verificar que herramientas críticas estén disponibles. Si faltan herramientas críticas
(phpstan, phpunit, infection), emitir exit 3 (INFRA_INCOMPLETE) con mensaje clear,
no exit 5 (INTERNAL_ERROR) con traceback.

Implementación inline en `_cmd_all()` (no módulo doctor separado):
- Iterar sobre herramientas críticas del PhpAdapter
- Si alguna falta → `_exit_with(INFRA_INCOMPLETE, {...})`
- Usar `messages_es.py` para mensajes en español

Actualizar tests e2e:
- `test_config_v1_hard_error.py`: esperar exit 4 con config v1
- `test_doctor_missing_php.py`: **re-escribir** para testear que `_cmd_all()` emite
  exit 3 cuando herramientas PHP no están, o **eliminar** si se prefiere dejarlo como
  futuro trabajo.

### Fase 3 — Corregir steps de la skill

- `steps/step-03-layer2-php.md`:
  - Línea 17: `--repo` → posicional. Cambiar
    `python3 -m harness_quality_gate all --repo {project-root}` a
    `python3 -m harness_quality_gate all {project-root}`
  - Tras Fase 1, la llamada a `run_l2` para weak-tests queda correcta.
- `steps/step-03-layer2.md` (Python, línea ~23):
  - Corregir `python3 ${CLAUDE_SKILL_DIR}/harness_quality_gate.adapters.python.weak_test`
    a `python3 -m harness_quality_gate.adapters.python.weak_test`
- `steps/step-04-layer3b-php.md`:
  - Añadir nota: `run_l3b` cubre la parte determinista (Tier A antipatterns + Deptrac
    architecture). El juicio BMAD Tier B es del LLM (no deterministico).
- `steps/step-06-layer4.md`:
  - Añadir subsección PHP documentando que `PhpAdapter.run_l4` ejecuta psalm-taint,
    composer audit, local-php-security-checker, dead-code-detector,
    composer-dependency-analyser y deptrac.

### Fase 4 — Corregir php-tool-taxonomy.json

Archivo: `config/php-tool-taxonomy.json`

| Herramienta | Capa actual | Capa correcta | Justificación |
|-------------|-------------|---------------|---------------|
| infection | L3B | **L1** | Mutation testing → test execution |
| deptrac | L3A | **L3B** | Architecture validation → deep quality |
| shipmonk/dead-code-detector | L3A | **L4** | Dead code → security/L4 |
| shipmonk/composer-dependency-analyser | L3A | **L4** | Dependency analysis → security/L4 |

### Fase 5 — Sincronizar documentación y spec

5a. **Actualizar spec para reflejar decisiones deliberadas**:

Añadir sección "Decisiones deliberadas post-refactor" a `specs/php-support/requirements.md`
(o crear `specs/php-support/decisions.md`) documentando:

- CLI tiene solo `all` y `audit-ignores`. Los 10 subcomandos eliminados
  (detect, doctor, install-tools, configure, layer3a, layer1, layer2, layer3b, layer4, checkpoint)
  no se restauran. El LLM invoca `all` y los steps guían la ejecución capa por capa.
- Detección simple: `composer.json` → PHP, si no → Python. No 3-tier, no hybrid, no cache.
- Los módulos eliminados (detector, dispatcher, doctor, installer, configurator, concurrency,
  state, framework_sniffer, messages_fr, checkpoint_v2) no se restauran.
- Infra-check se hace dentro de `_cmd_all()`, no como subcomando separado.
- Config v1 rejection se hace dentro de `_cmd_all()`, no como subcomando separado.

5b. **Actualizar design.md y tasks.md** para reflejar:
- Eliminar referencias a módulos eliminados
- Eliminar referencias a 12 subcomandos
- Actualizar diagramas de arquitectura (cli.py es el punto de entrada, no dispatcher.py)

5c. **Otros docs**:
- `README.md`: sección de soporte PHP (adaptadores, capas, gate Infection 100/100,
  detección composer.json) y documentar `HARNESS_INFECTION_REQUIRED`.
- `references/security-tools-guide-php.md`: añadir psalm --taint-analysis,
  shipmonk/dead-code-detector, shipmonk/composer-dependency-analyser.
- `SKILL.md`: nota explícita de la política de detección — repo con composer.json
  se trata como PHP-only; híbridos no soportados (decisión 69b05df ratificada).
- `step-06-layer4.md`: ya mencionado en Fase 3.

5d. **Limpiar**:
- `tests/fixtures/hybrid-py-php/`: confirmar con grep que ningún test lo usa y eliminarlo
  (decisión: híbridos no soportados).
- `harness_quality_gate/adapters/php/weak_test_php.py.bak`: ya no existe, verificar.

### Fase 6 — Hacer visibles los tests e2e/integración

Añadir target al Makefile:
```makefile
test-e2e:
	$(VENV)/bin/python -m pytest tests/e2e/ -q -m "e2e" --tb=short
```

Mencionar en `check-tests` que los e2e existen y deben correrse manualmente
(requieren PHP/composer).

## Fase 7 — Bug signature mismatch en parse() de ToolAdapters

### 7.1 — Audit completo

**SOLO 1 CRASH EN PYTHON (PyrightAdapter)**: El resto usa `*_compat: object` para aceptar extra args.

| Adapter | Firma | ¿Crash? | Patrón |
|---------|-------|---------|--------|
| `PyrightAdapter` | `(self, stdout)` | **SÍ** — TypeError | Sin `*_compat` |
| RuffAdapter | `(self, stdout, *_compat)` | NO | Tiene `*_compat` |
| VultureAdapter | `(self, stdout, *_compat)` | NO | Tiene `*_compat` |
| DeptryAdapter | `(self, stdout, *_compat)` | NO | Tiene `*_compat` |
| MutmutAdapter | `(self, stdout, *_compat)` | NO | Tiene `*_compat` |
| BanditAdapter | `(self, stdout, *_compat)` | NO | Tiene `*_compat` |
| PhpUnitAdapter | `(self, stdout, *_compat)` | NO | Tiene `*_compat` |
| InfectionAdapter | `(self, stdout, *_compat)` | NO | Tiene `*_compat` |
| SecurityCheckerAdapter | `(self, stdout, *_compat)` | NO | Tiene `*_compat` |
| DeadCodeAdapter | `(self, stdout, *_compat)` | NO | Tiene `*_compat` |

**Solución Fase 7.1**: Corregir SOLO PyrightAdapter.parse() para usar
`(self, stdout, *_compat: object)` igual que los demás. Quitar `# type: ignore`.

**Solución Fase 7.2**: Todos los demás adapters tienen `# type: ignore[override]` innecesario.
Quitarlo y cambiar a firma explícita `(self, stdout: str, stderr: str, exitcode: int)`.

### 7.2 — Dogfooding: bugs descubiertos ejecutando la skill contra sí misma

Estos bugs fueron descubiertos ejecutando `python3 -m harness_quality_gate all <fixture>` (Fase 8 del plan).

**BUG P7 — MutationStats no serializable a JSON**:
- **Archivo**: `cli.py:_cmd_all()` línea 131
- **Código**: `ld["tool_specific"] = lr.tool_specific` — NO pasa por `_asdict()`
- **Síntoma**: `json.dumps(data)` crash en `cli.py:169` con
  `TypeError: Object of type MutationStats is not JSON serializable`
- **Causa**: `lr.tool_specific` contiene `MutationStats` dataclass directo.
  `_asdict()` se llama sobre `lr.findings` pero NO sobre `lr.tool_specific`.
- **Excepción**: No afecta cuando `tool_specific` solo tiene valores primitivos
  (dict con str/int/float ya serializable).
- **Reproductible**: `python3 -m harness_quality_gate all tests/fixtures/python-pure-pass --json`
  (después de corregir PyrightAdapter.parse(), ya no crash pero write() sí crash ea).

**BUG P8 — rule_id:null produce jsonschema.ValidationError en write()**:
- **Archivos**: `cli.py:_asdict()` + `checkpoint.py:build()` + `checkpoint.py:validate()`
- **Código**: `_asdict(Finding)` → `dataclasses.asdict()` → conserva `rule_id: None`
  → `build()` solo strippea Nones de dataclass objects, no de dicts
  → `validate()` → ValidationError: "None is not of type 'string'"
- **Síntoma**: Python fixture produce JSON inválido en `write()` con
  `jsonschema.exceptions.ValidationError: None is not of type 'string'
   on rule_id: None`
- **Código corregible**: `cli.py:_asdict()` debería strippear Nones OR
  `checkpoint.py:build()` debería strippear Nones de dict-based findings

**BUG P9 — write_checkpoint() crashea silenciosamente**:
- **Archivo**: `checkpoint.py:write()`
- **Problema**: `validate()` y `json.dumps()` pueden crashear
  (BUG P7/P8) pero no hay try/except. El crash se captura en `cli.py:_cmd_all()`
  line 160 con `logger.warning(...)` pero el checkpoint NO se escribe en disco.
- **Impacto**: Se pierde el checkpoint por completo si tiene cualquier dato invalido.
  El usuario ve JSON inválido en stdout pero no hay checkpoint en disco.
- **Fix**: envolver `validate()` y `write_text()` en try/except en `cli.py:_cmd_all()`.

**BUG P10 — `_run_phpunit_tests` no captura OSError**:
- **Archivo**: `php_adapter.py:645`
- **Código**: `except RuntimeError:` — captura solo RuntimeError
- **Problema**: `subprocess.run()` raises `FileNotFoundError` (OSError, no RuntimeError)
  cuando el binario no existe
- **Síntoma**: `INTERNAL_ERROR: [Errno 2] No such file or directory: 'vendor/bin/phpunit'`
- **Solución**: `except (OSError, RuntimeError):` igual que PythonAdapter

## Fase 8 — E2E smoke tests para detección de bugs en runtime

Objetivo: crear tests e2e que ejerzan el pipeline completo (`python3 -m harness_quality_gate all <fixture>`)
contra fixtures Python y PHP reales. Estos tests detectan bugs de integración como el
PyrightAdapter.parse() mismatch, herramientas faltantes, y errores de contrato entre
adapters y el CLI.

### 8a — E2E smoke test Python

Crear `tests/e2e/test_smoke_python.py`:

```python
@pytest.mark.e2e
def test_all_python_pure_pass():
    """Ejecutar 'all' contra fixture python-pure-pass → checkpoint con estructura correcta."""
    result = subprocess.run(
        [sys.executable, "-m", "harness_quality_gate", "all", str(fixture), "--json"],
        capture_output=True, text=True,
        env={**os.environ, "PATH": os.environ.get("PATH", "")},
    )
    # El gate corre (puede fallar por herramientas faltantes, pero no debe crashear)
    assert result.returncode in (0, 1, 2, 3, 5), f"Unexpected exit code: {result.returncode}"
    if result.returncode not in (2,):  # UNSUPPORTED = fixture no encontrado
        data = json.loads(result.stdout)
        assert data["language"] == "python"
        assert len(data["layers"]) == 5  # L3A, L1, L2, L3B, L4
        # Verificar que NO hay TypeError por parse() signature mismatch
        for layer in data["layers"]:
            assert isinstance(layer["passed"], bool)
            assert isinstance(layer["duration_sec"], (int, float))
```

### 8b — E2E smoke test PHP

Crear `tests/e2e/test_smoke_php.py`:

```python
@pytest.mark.e2e
def test_all_php_pure_pass():
    """Ejecutar 'all' contra fixture php-pure-pass → checkpoint con estructura correcta."""
    result = subprocess.run(
        [sys.executable, "-m", "harness_quality_gate", "all", str(fixture), "--json"],
        capture_output=True, text=True,
        env={**os.environ, "PATH": os.environ.get("PATH", "")},
    )
    assert result.returncode in (0, 1, 2, 3, 5), f"Unexpected exit code: {result.returncode}"
    if result.returncode not in (2,):
        data = json.loads(result.stdout)
        assert data["language"] == "php"
        assert len(data["layers"]) == 5  # L3A, L1, L2, L3B, L4
```

### 8c — E2E infra-check (Fase 2)

Crear `tests/e2e/test_infra_incomplete.py` (reemplaza `test_doctor_missing_php.py`):

```python
@pytest.mark.e2e
def test_all_exits_3_when_php_missing(tmp_path):
    """'all' sobre repo con composer.json pero sin PHP en PATH → exit 3 (INFRA_INCOMPLETE)."""
    # Crear composer.json para detectar como PHP
    (tmp_path / "composer.json").write_text('{"name": "test/infra-check"}')
    # Restringir PATH para que no encuentre phpstan/phpunit/infection
    env = {**os.environ, "PATH": "/usr/bin"}
    result = subprocess.run(
        [sys.executable, "-m", "harness_quality_gate", "all", str(tmp_path)],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 3, f"Expected exit 3 (INFRA_INCOMPLETE), got {result.returncode}"
```

### 8d — Procedimiento manual de replicación

Para detectar bugs como PyrightAdapter.parse() que solo aparecen en runtime real:

**Python** (requiere ruff, pyright, pytest, mutmut, bandit, vulture, deptry en PATH):

```bash
# 1. Run contra fixture Python
python3 -m harness_quality_gate all tests/fixtures/python-pure-pass --json

# 2. Verificar:
#    - Exit code en {0, 1} (no crashee)
#    - JSON tiene "language": "python"
#    - 5 capas presentes (L3A, L1, L2, L3B, L4)
#    - L3A contiene pyright findings (o vacío si no hay errores)
#    - Ningún TypeError en stderr (hubiera indicado signature mismatch)

# 3. Run con PATH restringido (solo herramientas Python básicas):
PATH=/usr/bin python3 -m harness_quality_gate all tests/fixtures/python-pure-pass --json
#    - Debe completarse sin crashear (herramientas opcionales se skip con warning)
```

**PHP** (requiere php, composer, phpstan, phpunit, infection en PATH):

```bash
# 1. Run contra fixture PHP
python3 -m harness_quality_gate all tests/fixtures/php-pure-pass --json

# 2. Verificar:
#    - Exit code en {0, 1, 3} (0=PASS, 1=FAIL, 3=INFRA_INCOMPLETE)
#    - JSON tiene "language": "php"
#    - 5 capas presentes (L3A, L1, L2, L3B, L4)
#    - L2 = weak-tests (antipatterns DESPUÉS del SWAP de Fase 1)
#    - L3B = antipatterns Tier A (DESPUÉS del SWAP de Fase 1)
#    - L1 contiene Infection stats

# 3. Run con PATH sin PHP (verificar INFRA_INCOMPLETE):
PATH=/usr/bin python3 -m harness_quality_gate all tests/fixtures/php-pure-pass --json
#    - Exit code = 3
#    - Mensaje claro sobre herramientas faltantes
```

**Para detectar bugs de contrato (signature mismatches, import errors, etc.)**:

```bash
# Run con import verification (sin ejecutar herramientas reales):
python3 -c "
from harness_quality_gate.cli import main
import sys
sys.exit(main(['all', 'tests/fixtures/python-pure-pass', '--quiet']))
"
# Esto detecta TypeError, ImportError, y otros errores de contrato
# que los unit tests con mocks no capturan.
```

**Para detectar bugs de parse() signature mismatches específicamente**:

```bash
# Grep rápido: buscar firmas parse() que no cumplan ToolAdapter.parse(self, stdout, stderr, exitcode)
rg "def parse\(self" harness_quality_gate/adapters/ --include='*.py'
# Cada adapter debe tener parse(self, stdout: str, stderr: str, exitcode: int)
# Cualquier firma con menos args es un bug.
```

### 8e — Eliminar test_doctor_missing_php.py

Eliminar `tests/e2e/test_doctor_missing_php.py` (prueba un subcomando que no existe).
Su funcionalidad se reemplaza con `test_infra_incomplete.py` (Fase 8c).

## Verificación

1. `make check-tests` (unit completo) — verde.
2. `python3 -m pytest tests/e2e/test_config_v1_hard_error.py -q` — verde
   (exit 4 con config v1).
3. `make coverage` — se mantiene 100%.
4. `make mutation` — MSI se mantiene en 100%.
5. `python3 -m harness_quality_gate all tests/fixtures/php-pure-pass --json`:
   checkpoint con L2=weak-tests y L3B=antipatterns; gate Infection intacto.
6. `python3 -m harness_quality_gate all tests/fixtures/php-pure-pass --json`
   con PATH restringido (sin phpstan/phpunit): exit 3 (INFRA_INCOMPLETE) con mensaje claro.
7. Repetir con fixture Python para confirmar que Python sigue intacto.
8. `rg "def parse\(self" harness_quality_gate/adapters/` → todos los adapters cumplen
   la firma `(self, stdout, stderr, exitcode)`.
9. `python3 -m pytest tests/e2e/test_smoke_python.py tests/e2e/test_smoke_php.py -q` — verde
   (o skip si las herramientas no están instaladas, pero no fail por TypeError).
10. `python3 -m pytest tests/e2e/test_infra_incomplete.py -q` — verde (exit 3 cuando falta PHP).
11. **P7**: `python3 -m harness_quality_gate all tests/fixtures/python-pure-pass --json` →
    JSON válido con MutationStats serializado (no crash en write_checkpoint).
12. **P8**: Checkpoint generado no contiene `rule_id: null` — todos los campos opcionales
    son strings vacíos o están ausentes.
13. **P9**: `json.dumps()` nunca se ejecuta dentro de `write()` sin manejo de errores.
14. **P10**: `php_adapter.py:645/674/745` → `except (OSError, RuntimeError):` para herramientas PHP faltantes.

## Restricciones operativas

1. **Preservar 100% MSI** — cada cambio requiere kill de mutantes nuevos.
2. **Preservar 100% coverage** — cada nuevo módulo requiere tests completos.
3. **No restaurar módulos eliminados** — detector, dispatcher, doctor, installer,
   configurator, concurrency, state, framework_sniffer, messages_fr, checkpoint_v2.
4. **No crear subcomandos** — solo `all` y `audit-ignores`.
5. **No implementar detección 3-tier/hybrid** — detección simple de 5 líneas.
6. Commits: pequeños e incrementales siguiendo el estilo del repo, solo cuando el
   usuario lo pida.

## Diferencias vs plan anterior (plan-restaurar-php-support.md original)

| Item del plan original | Decisión deliberada | Plan revisado |
|------------------------|---------------------|---------------|
| Fase 1: Re-crear `doctor.py` como módulo + subcomando | **CONTRADICE** 69b05df | **NO crear doctor.py**. Cablear infra-check dentro de `_cmd_all()`. |
| Fase 1: Usar commit huérfano 74c4eb5 como referencia | Código standalone eliminado | **NO usar commit huérfano**. Implementar inline. |
| Fase 1: Crear subcomando `doctor` | **CONTRADICE** decisión de solo `all` + `audit-ignores` | **NO crear subcomando**. |
| Fase 1: Cablear `config.load()` en `_cmd_all()` | **ALINEADO** | **SI** — igual, cablear inline. |
| Fase 2: SWAP L2/L3B solo en PhpAdapter | Incompleto — PythonAdapter también swapeado | **Extender a PythonAdapter** también |
| Tests e2e de doctor: "arreglar" | Prueban feature eliminada | **Re-escribir** para testear infra-check dentro de `all`, o eliminar |
| Crear detector.py/dispatcher.py/etc. | **CONTRADICE** decisión deliberada | **NO crear** |
| Crear 10 subcomandos CLI | **CONTRADICE** decisión deliberada | **NO crear** |
| Fase 3: Corregir steps | **ALINEADO** | Igual |
| Fase 4: Corregir taxonomy | **ALINEADO** | Igual |
| Fase 4: Documentar decisiones en spec | No mencionado en plan original | **NUEVO** — actualizar spec con decisiones deliberadas |
| Eliminar `weak_test_php.py.bak` | Ya no existe | **YA HECHO** |
| Fase 5: Hacer visibles e2e tests | **ALINEADO** | Igual |