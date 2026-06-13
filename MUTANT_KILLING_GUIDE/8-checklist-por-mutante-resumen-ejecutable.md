# 8. Checklist por mutante (resumen ejecutable)

```text
[ ] mutmut show <id> — leer el diff completo
[ ] ¿Test existente débil? (assert truthy / in / called sin args) → endurecer
[ ] ¿Observable por retorno/excepción? → asersión densa (§4.1) o frontera (§4.2)
[ ] ¿Observable por string? → igualdad exacta + caplog/capsys (§4.3)
[ ] ¿Observable por dependencia? → assert_called_once_with completo (§4.4)
[ ] ¿Default / acumulador / break? → §4.5–§4.7
[ ] ¿Sigue vivo? → mutmut apply + pytest -x para entender (y revertir)
[ ] ¿Equivalente? → clasificar en §5 y aplicar el REFACTOR del tipo
[ ] ¿Refactor imposible sin romper API? → pragma con reason+audited (§7)
[ ] Verificar: test pasa en original, mutante muere, suite verde, coverage 100%
[ ] Informe: evidencia por mutante (test que falla con apply / diff de refactor
    o pragma). PROHIBIDO "equivalente" sin acción en el código (§0 regla 3)

```

---
