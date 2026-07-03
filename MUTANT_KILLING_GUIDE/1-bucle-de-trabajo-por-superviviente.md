# 1. Bucle de trabajo por superviviente

```bash
# 1. Lista de supervivientes (señal accionable, sin ruido)
mutmut results 2>&1 | grep survived

# 2. Ver el diff exacto de UN mutante
mutmut show harness_quality_gate.config.x_validate__mutmut_5

# 3. LOCALIZAR la línea mutada en el fuente y hacer la tripartición (§3):
#    ¿es código VIVO? (¿tiene caller/edge, o es un nodo/rama huérfano?)
#    ¿qué test del TIER DEL GATE la recorre? (no vale uno @integration excluido)
#    Solo si es vivo + cubrible + diseño correcto → escribir/reforzar el test (§4/§5)

# 4. Verificar que el test pasa con el código ORIGINAL
.venv/bin/python -m pytest tests/unit/test_config.py -q -x

# 5. PRUEBA DE MUERTE OBLIGATORIA — aplica el mutante y confirma que el test FALLA
mutmut apply harness_quality_gate.config.x_validate__mutmut_5
.venv/bin/python -m pytest tests/unit/test_config.py -q -x   # DEBE fallar (rojo)
git checkout -- harness_quality_gate/                        # SIEMPRE revertir

# 6. Re-ejecutar SOLO ese mutante (mutmut cachea por HASH DEL FUENTE, no del test:
#    un test nuevo NO invalida un superviviente cacheado → re-run explícito)
mutmut run harness_quality_gate.config.x_validate__mutmut_5
mutmut run 'harness_quality_gate.config.*'
```

**Regla del test nuevo (paso 5, NO opcional)**: cada test debe (a) pasar con el
código original y (b) **fallar con el mutante aplicado**. La comprobación (b) con
`mutmut apply` es el paso que caza los tres fallos silenciosos más comunes:
- **Firma-ciega ([H18](h18-inspect-signature-no-mata-defaults-el-trampoln-conserva-la-firma.md))**:
  un test de `inspect.signature` sobre un default mutado PASA con el mutante
  aplicado → no mata nada. Solo `mutmut apply` lo revela.
- **Caché rancia**: crees que lo mataste, pero `mutmut results` muestra el
  superviviente cacheado hasta el re-run del paso 6.
- **Rama equivocada**: tu test cubre la rama gemela, no la que muta ([H19](h19-coverage-gap-por-tier-el-mutante-vivo-que-solo-cubre-integration-excluido.md)).

Si tras el paso 6 el conteo no baja y no es ninguno de los anteriores: caché
sucia → `make clean-mutmut` y relanza el módulo.

---
