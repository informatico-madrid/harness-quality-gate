# 7. Política de pragmas (último recurso)

Regla del proyecto: **"Cero pragmas sobre lógica."** Solo para equivalentes
PROBADOS tras agotar §4 y §5, y siempre con metadatos auditables:

```python
# reason: timeout=600.0 es default de API pública; la mutación (601.0) es equivalente — ningún consumidor observable. # audited: 2026-06-09
timeout: float = 600.0,  # pragma: no mutate
```

- `# reason:` y `# audited: YYYY-MM-DD` deben estar en las 5 líneas anteriores
  y empezar por `#` (regex del `allow_list_auditor`).
- El reason debe nombrar el TIPO de equivalencia (§5) y por qué las técnicas
  de §4 no aplican. "es equivalente" a secas no pasa revisión.
- Verificar SIEMPRE tras añadir uno:
  `python -m harness_quality_gate audit-ignores harness_quality_gate` → exit 0.
- Variantes (`# pragma: no mutate block`, `start`/`end`, `do_not_mutate_patterns`)
  existen en mutmut pero están desaconsejadas aquí: ocultan demasiado.
- **El pragma solo surte efecto en líneas de _statement completo_.** mutmut
  atribuye la mutación a la línea donde *empieza* la sentencia, no a las de
  continuación. Un `# pragma: no mutate` sobre un kwarg dentro de una llamada
  multi-línea NO silencia nada:
  ```python
  json.dumps(
      data,
      ensure_ascii=False,   # pragma: no mutate   ← INÚTIL: el mutante sobrevive
  )
  ```
  Ponlo en la sentencia de una línea, o extrae el valor a su propia línea:
  ```python
  json.dumps(data, ensure_ascii=False)   # pragma: no mutate   ← funciona
  ```
  (Verificado 2026-06-24: la forma multi-línea dejó vivos 3 mutantes
  `ensure_ascii=False`; la single-line los silenció. OJO: el single-line
  silencia TODA la línea — si conviven mutantes matables, extrae primero a su
  propia línea solo el valor equivalente.)

---
