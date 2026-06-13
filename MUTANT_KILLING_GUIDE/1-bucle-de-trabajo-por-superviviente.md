# 1. Bucle de trabajo por superviviente

```bash
# 1. Lista de supervivientes (señal accionable, sin ruido)
mutmut results 2>&1 | grep survived

# 2. Ver el diff exacto de UN mutante
mutmut show harness_quality_gate.config.x_validate__mutmut_5

# 3. Clasificarlo (ver §3 y §5) y escribir/reforzar el test

# 4. Verificar que el test pasa con el código ORIGINAL
.venv/bin/python -m pytest tests/unit/test_config.py -q -x

# 5. Re-ejecutar SOLO ese mutante (o el módulo)
mutmut run harness_quality_gate.config.x_validate__mutmut_5
mutmut run 'harness_quality_gate.config.*'
```

Truco de depuración cuando no entiendes por qué sobrevive: aplica el mutante
en disco, ejecuta el test que debería matarlo y mira qué pasa de verdad:

```bash
mutmut apply <mutant-id>
.venv/bin/python -m pytest tests/unit/test_config.py -q -x   # ¿pasa? → tu assert no toca esa rama
git diff && git checkout -- harness_quality_gate/             # SIEMPRE revertir
```

Si tras matar un mutante el conteo del módulo no baja: caché sucia →
`make clean-mutmut` y relanzar el módulo.

**Regla del test nuevo**: cada test que escribas debe (a) pasar con el código
original y (b) fallar con el mutante aplicado. Si no cumple (b), no has matado
nada — solo has añadido coverage.

---
