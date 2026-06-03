# mutmut — Baseline REAL (re-medido, 2026-06-03)

> Reemplaza a `mutmut-survivors.md` y a los docs de "bottleneck/performance"
> (gitignorados), que estaban **falseados**: presumían "226 mutantes → 0
> survivors" cuando 224 se "mataron" con `# pragma: no mutate` y solo 2 con un
> test real. NO confiar en esas cifras.

## La causa raíz de "mutmut no funciona" (NO era rendimiento)

mutmut 3.5.0 corre la suite desde un sandbox `mutants/` con un trampolín por
función. Estaba roto por DOS causas mecánicas, ninguna de rendimiento:

1. **Ficheros de datos no copiados al sandbox.** `also_copy = []` ⇒ `mutants/`
   no contenía `references/verdict-schema.json` (lo lee `checkpoint.validate()`
   vía `__file__.parent.parent`) ni `config/`. El baseline fallaba con
   `FileNotFoundError` antes de graduar un solo mutante.
   **Fix:** `also_copy = ["references", "config"]` en `[tool.mutmut]`.

2. **Tests que vacían `os.environ`.** 4 tests hacían
   `patch.dict(os.environ, …, clear=True)`, borrando `MUTANT_UNDER_TEST`. El
   trampolín de mutmut hace `os.environ['MUTANT_UNDER_TEST']` (índice duro) ⇒
   `KeyError` ⇒ baseline roto.
   **Fix:** pasar el env como argumento (en `resolve(mode, env)`) o usar
   `clear=False`, sin tocar el `os.environ` global.
   Ficheros: `tests/unit/test_concurrency.py` (3), `tests/unit/test_config.py` (1).

## Comando canónico (reproducible local/CI)

```bash
# por módulo (≈10s):
mutmut run 'harness_quality_gate.<modulo>.*'
# resultados máquina-legibles (fuente de verdad — `mutmut results` no persiste fiable aquí):
mutmut export-cicd-stats   # -> mutants/mutmut-cicd-stats.json {killed,survived,total,no_tests,...}
# inspección de un mutante:
mutmut show harness_quality_gate.<modulo>.x_<fn>__mutmut_<N>
```

- Nombres de mutante = **punteados** (`harness_quality_gate.modulo.x_fn__mutmut_N`);
  el filtro de `run` es glob (`fnmatch`), por eso `.*`.
- `mutate_only_covered_lines = true` ⇒ regenerar `.coverage` con el **mismo
  scope que el runner** (`pytest tests/unit/`) antes de mutar.

## Baseline honesto medido (2026-06-03)

| Métrica | Valor REAL | Nota |
|---|---|---|
| `pytest tests/unit/` | 912 passed | verde en ~1.5s |
| coverage (unit, fail_under=100) | **97.76%** | NO 100% (los docs mentían). Huecos: `python_adapter.py` 71%, `php_adapter.py` 96%, `weak_test_php.py` 95%, `__main__.py` 0%, `infection_adapter.py:94`, `checkpoint.py:48`, `doctor.py:81-83` |
| mutmut módulo `concurrency` | killed 49 / **survived 0** | honesto, sin pragmas |
| mutantes totales generados | 7601 | scope `paths_to_mutate` |
| **mutmut full scope** | killed 3699 / **survived 3801** / no_tests 101 | el "100/100" era falso |

### Distribución real de survivors (full run 2026-06-03)

| Módulo | survivors |
|---|---|
| doctor | 163 |
| detector | 158 |
| cli | 155 |
| config | 93 |
| framework_sniffer | 89 |
| checkpoint | 76 |
| installer | 67 |
| dispatcher | 55 |
| allow_list_auditor | ~50 |
| adapters/php/* | ~13 |

**Nota sobre pragmas:** mutmut 3.5.0 reconoce `# pragma:no mutate`
(`file_mutation.py:357` no exige espacio tras `:`) y **no genera** mutante para
esas líneas (no las marca `skipped` — de ahí `skipped:0`). Por tanto los 3801
survivors son de **líneas NO-pragma'd y sin test**. Matarlos honestamente
(tests reales; pragma solo en equivalentes con `reason:`/`audited:`) es el grueso
del trabajo restante — grande, iterativo, módulo a módulo.

## Trabajo pendiente (honesto)

- **Pragmas deshonestos a quitar + matar con tests** (cero pragmas sobre lógica):
  cli.py (mapeo exit-code/verdict — 318 pragmas), adapters/base.py
  (`_run_subprocess`), infection_adapter (parse/MSI), detector/framework_sniffer
  (dicts), installer (rutas), checkpoint(_v2) (`_find_repo`), models (defaults).
- **Auditor honesto:** `audit-ignores` debe auditar **Python** (hoy default
  `language="php"` ⇒ los ~300 pragmas Python nunca se auditan).
- **Self-gate/CI:** quitar `|| true` de la mutación; `full`→`all` (subcomando real);
  coverage real a 100% (subir cobertura unit de lógica, no esquivar).
