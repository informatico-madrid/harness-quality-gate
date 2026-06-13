# H15. Gemelos falsy en inicializadores (`None`→`""`, `False`→`None`, `[]`→`None`)

mutmut muta el valor inicial de una variable a otro valor FALSY
(`x = None` → `x = ""`). Si todos los consumidores usan truthiness
(`if x:`), el gemelo es estructuralmente equivalente y NINGÚN test lo mata.
- **Solución**: cambia los consumidores a identidad: `if x is not None:`.
  Con eso el gemelo `""` entra en la rama y se vuelve observable (una clave
  extra en el dict de salida, un crash de atributo…) → test lo mata.
- **Flags booleanos** (`ok = False` → `None`): no hay check que distinga
  `False` de `None` por truthiness. Elimina el flag: deriva la condición del
  dato real (p. ej. guarda el resultado en `remediation: dict | None = None`
  y comprueba `is not None`), como se hizo en `php_adapter.run_l1`.
- Caso real: `php_adapter.run_l1` tenía 3 gemelos supervivientes
  (`mutation_stats`, `mutation_skipped`, `mutation_gate_failed`); los tres
  cayeron con este patrón sin cambiar el comportamiento.
