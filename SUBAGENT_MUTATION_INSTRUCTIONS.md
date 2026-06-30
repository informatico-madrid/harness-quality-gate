# Instrucciones para subagentes: Matar mutantes

> **¿Repo PHP?** Este protocolo es para Python/mutmut. Si el gate que falló es
> **L1 Infection (PHP)** — escaped > 0, MSI < 100, covered MSI < 100 o
> timeouts — sigue **[MUTANT_KILLING_GUIDE_PHP.md](MUTANT_KILLING_GUIDE_PHP.md)**:
> bucle con `vendor/bin/infection --filter=<file> --show-mutations`, trampas
> T1 (`assertSame`, nunca `assertEquals`/`toEqual`), T2 (mocks con
> `expects()->with($this->identicalTo(...))`) y T3 (covered MSI = cobertura
> primero). Supresión solo con `@infection-ignore-all` + `reason:` + `audited:`.

Cuando el coordinador te envíe a cerrar supervivientes de mutmut, sigue este protocolo:

## 0. Preparación (2 min)

1. Lee **[MUTANT_KILLING_GUIDE.md](MUTANT_KILLING_GUIDE.md)** — especialmente Parte II (casos H1–H12).
2. Verifica que estés en `tests/unit/` scope y que `.coverage` esté fresco:
   ```bash
   .venv/bin/python -m pytest tests/unit/ -q --cov=harness_quality_gate --cov-report= -p no:randomly
   ```
3. Limpia caché: `make clean-mutmut`

## 1. Por cada superviviente

```bash
# Ver el diff exacto
mutmut show harness_quality_gate.adapters.python.python_adapter.xǁPythonAdapterǁrun_l4__mutmut_4

# Clasificar por tipo (§3 de la guía)
# ¿Observable desde fuera? → §4 (test débil)
# ¿Solo rendimiento? → §5.A (refactor)
# ¿Frontera imposible? → §5.B (invariante)
# ¿Default muerto? → §5.C (test con ausencia)

# Seguir la receta exacta del tipo (§4 o §5 o §6.H1–H12)
```

## 2. Protocolo de verificación

**Antes de escribir el test**: si el mutante te parece extraño, verifica que te
afecta:

```bash
mutmut apply harness_quality_gate.adapters.python.python_adapter.xǁPythonAdapterǁrun_l4__mutmut_4
.venv/bin/python -m pytest tests/unit/test_python_adapter.py::test_your_new_test -x
# ¿FALLA? → tu test toca la rama → escribe el test
# ¿PASA? → el mutante NO afecta esa rama → es otro archivo o función
git checkout -- harness_quality_gate/
```

## 3. Después de escribir el test

```bash
# 1. Verifica que el test pase en código ORIGINAL
.venv/bin/python -m pytest tests/unit/ -q -p no:randomly

# 2. Re-ejecuta SOLO esos mutantes específicos (filtra por nombre, no por path)
uv run mutmut run

# 3. Si el superviviente sigue vivo:
#    - Aplicalo, corre tu test solo, revertir (protocolo de §1)
#    - Si el test pasa CON el mutante → no estás tocando esa rama
#    - Si falla → falta caché, coverage viejo o scope (tests/unit vs integration)
```

## 4. Si un mutante sigue invencible (3+ intentos)

1. **No es equivalente hasta probarlo**: lee §5 y §6 de la guía y encuentra tu
   caso. Casi siempre hay una receta.
2. Si de verdad no hay test posible (tipo B, C, D):
   - Refactor que elimina el mutante (preferido), o
   - Pragma con `# reason:` + `# audited: 2026-06-09` (último recurso)
   - Verifica: `python -m harness_quality_gate audit-ignores harness_quality_gate`
     → exit 0

## 4b. Formato OBLIGATORIO para pragmas (evita fallo de audit-ignores)

**CRÍTICO**: Un pragma sin `# reason:` + `# audited:` causa que CI falle en el paso
"Audit suppressions" (`.github/workflows/ci.yml` línea 70-71).

### Requisitos:

1. **Metadatos en las 5 líneas PREVIAS al pragma**:
   ```python
   # reason: el mutante timeout=600→601 es equivalente porque...
   # audited: 2026-06-30
   # pragma: no mutate
   timeout: float = 600.0
   ```
   Ambas líneas (`# reason:` y `# audited:`) deben estar presentes en las 5 líneas anteriores.
   El auditor las busca con regex (ver `allow_list_auditor.py:_METADATA_WINDOW=5`).

2. **Pragma en línea ÚNICA (mismo token físico)**:
   ```python
   # ✓ CORRECTO: pragma en la misma línea del token mutado
   timeout: float = 600.0  # pragma: no mutate
   
   # ✗ INCORRECTO: pragma en línea separada (NO detectado por mutmut)
   timeout: float = 600.0
   # pragma: no mutate
   
   # ✗ INCORRECTO: pragma en llamada multi-línea (NO funciona)
   result = subprocess.run(
       cmd,
       timeout=600.0,  # pragma: no mutate — ← FALLA aquí
   )
   ```
   Si el pragma está en una línea separada o dentro de una llamada multi-línea, mutmut
   no lo reconoce y el mutante sigue vivo. Probado 2026-06-24 (3 mutantes escaparon así).

3. **Verificación ANTES de hacer push**:
   ```bash
   python -m harness_quality_gate audit-ignores harness_quality_gate
   # Exit 0 = todos los pragmas tienen # reason: + # audited:
   # Exit 1 = pragmas unjustified → CI fallará en GitHub
   ```

### Patrón correcto (cópiate si es necesario):

```python
# reason: <tipo de equivalencia A/B/C/D/E> + <por qué §4/§5 no aplica>
# audited: <YYYY-MM-DD>
DEFAULT_TIMEOUT = 600.0  # pragma: no mutate
```

**Nota**: si el mutante es en realidad matrable, refactor es mejor (código más limpio,
cero pragmas). Solo usa pragma si exhaustiste §4 (test denso, spies, boundaries, etc.)
y §5 (refactor para eliminar el mutante).

## 5. Al terminar la tandada (final)

```bash
# Suite completa en verde
.venv/bin/python -m pytest tests/unit/ -q --cov=harness_quality_gate --cov-fail-under=100 -p no:randomly

# Mutation testing final (toda la suite, ~20 min)
make mutation

# Verificar que mutmut pase
python -c "
import json
s = json.load(open('mutants/mutmut-cicd-stats.json'))
print(f'MSI: {s[\"killed\"]}/{s[\"killed\"]+s[\"survived\"]} = {s[\"killed\"]/(s[\"killed\"]+s[\"survived\"])*100:.1f}%')
print(f'GATE PASSES: {not (s[\"survived\"] or s[\"no_tests\"] or s[\"suspicious\"] or s[\"timeout\"])}')
"
```

## Referencias rápidas

- **Técnicas generales** (§4): asersiones densas, fronteras exactas, spies con
  `assert_called_once_with(...)`, caplog/capsys exacto, valores no simétricos,
  `break/continue` con iteradores espías, tablas de verdad mínimas.
- **Tipos de equivalentes** (§5): A = rendimiento (refactor a `next()`), B =
  frontera inalcanzable (test o refactor), C = default muerto (test sin clave),
  D = código defensivo (eliminar o raise), E = constants (spy mata siempre).
- **Casos duros reales** (§6): H1 = passthrough a deps mockeadas (wiring test),
  H2 = reloj congelado, H3 = caplog exacto, H4 = tabla de verdad, H5 = no
  testear orquestador, H6 = side_effect OSError, H7 = argv completo, H12 =
  debug (apply, pytest, revertir).

**NUNCA**:
- Modificar código fuente de mutmut (reinstalar si se comporta raro).
- Debilitar el código de producción para matar un mutante.
- Correr fuera de `tests/unit/`.
- Usar `coverage` viejo con `mutate_only_covered_lines=true`.

**SIEMPRE**:
- Regenerar `.coverage` antes de mutmut.
- Limpiar caché: `make clean-mutmut`.
- Verificar que el test falla CON el mutante aplicado.
- Asersiones DENSAS (objeto/dict completo, no fragmentos).
- `assert_called_once_with(...)` COMPLETO, no `assert_called()`.
