# Decisiones deliberadas post-refactor (estado vigente)

> **Este documento es la fuente de verdad del estado post-refactor.**
> `requirements.md`, `design.md` y `tasks.md` describen el diseño original
> (12 subcomandos, módulos detector/dispatcher/doctor/installer/configurator,
> detección 3-tier con híbridos). Donde contradigan este documento, **manda
> este documento**. Las decisiones se tomaron durante la campaña de mutación
> MSI 47%→100% (commits 69b05df y posteriores, ratificadas 2026-06-11).

## 1. CLI mínima: solo `all` y `audit-ignores`

Los 10 subcomandos restantes del diseño original (detect, doctor,
install-tools, configure, layer3a, layer1, layer2, layer3b, layer4,
checkpoint) **no se restauran**. El skill lo invoca un LLM, no un humano
desde una terminal: el LLM ejecuta `all` (motor determinista que emite el
checkpoint v2) y los `steps/*.md` orquestan capa a capa lo no determinista.

## 2. Módulos de fontanería eliminados (no se restauran)

`detector.py`, `dispatcher.py`, `doctor.py`, `installer.py`,
`configurator.py`, `framework_sniffer.py`, `concurrency.py`, `state.py`,
`messages_fr.py`, `checkpoint_v2.py` (~2.3k LOC). Su funcionalidad esencial
quedó inlineada:

- **Detección** (`detector.py` → `cli._detect_language`, 5 líneas):
  `composer.json` ⇒ PHP-only; si no ⇒ Python. Sin 3-tier, sin cache, sin
  híbridos. `tests/fixtures/hybrid-py-php/` fue eliminada.
- **Doctor / infra-check** (FR-26/27 → `cli._missing_php_tools` dentro de
  `_cmd_all()`): si a un repo PHP le faltan herramientas críticas (php,
  phpunit, phpstan, infection — resueltas en PATH, `vendor/bin/` o `bin/`)
  el gate sale con **exit 3 (INFRA_INCOMPLETE)** y la lista en
  `missing_tools`. Python conserva su comportamiento original: degradación
  elegante (skip + warning), nunca exit 3.
- **Config v1 rejection** (FR-34 → `config.load()` dentro de `_cmd_all()`):
  un archivo de config con esquema v1 es error duro **exit 4
  (CONFIG_INVALID)**; la ausencia de config significa defaults.
- **Dispatcher** → bucle secuencial de 5 capas en `_cmd_all()`.

## 3. Mapa de capas final (glosario de requirements.md, ahora cableado)

| Capa | Python (`PythonAdapter`) | PHP (`PhpAdapter`) |
|------|--------------------------|--------------------|
| L3A smoke | ruff + pyright | phpstan + phpmd + php-cs-fixer + visitors Tier A |
| L1 ejecución | pytest + **mutmut** (gate 100/100) | phpunit/pest + pcov + **infection** (gate MSI 100/100) |
| L2 test quality | weak-tests A1-A9 + diversity (gate: solo ERROR) | weak-tests A1-A8 |
| L3B deep | solid_metrics + antipattern Tier A | antipattern Tier A + **deptrac** |
| L4 seguridad | bandit + vulture + deptry | psalm-taint + composer-audit + security-checker + dead-code-detector + dep-analyser |

El juicio Tier B (BMAD Party Mode) sigue siendo del LLM vía
`steps/step-04-layer3b*.md`; el adaptador solo cubre la parte determinista.

## 4. Códigos de salida (NFR-15) — todos cableados

0 PASS · 1 FAIL · 2 UNSUPPORTED · 3 INFRA_INCOMPLETE · 4 CONFIG_INVALID ·
5 INTERNAL_ERROR. Verificados por `tests/e2e/`.

## 5. Política de mutación

Gate duro 100/100 en ambos lenguajes (Infection `--min-msi=100
--min-covered-msi=100`; mutmut sin supervivientes ni timeouts). Los ramps de
umbral por módulo del diseño original (`[tool.quality-gate.mutation]`) no se
soportan. `harness_quality_gate.bmad.mutation_analyzer` expone el kill-map
(`-m ... <repo>`) y el gate (`--gate`).

## 6. No usar el commit huérfano 74c4eb5

Contiene el código standalone eliminado; no es referencia para nada.

## 7. Variables fantasma

`HARNESS_INFECTION_REQUIRED` no existe en el código — cualquier doc que la
mencione está desactualizado.
