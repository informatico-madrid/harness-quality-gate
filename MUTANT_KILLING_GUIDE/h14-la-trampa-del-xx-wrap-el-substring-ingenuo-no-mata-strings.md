# H14. La trampa del XX-wrap: el substring ingenuo NO mata strings

mutmut envuelve strings como `XXfooXX` — y `"foo" in out` SIGUE PASANDO
porque el original está contenido en el mutante. Tres niveles de solución:
1. **Igualdad exacta** del valor (`==`) — siempre que el valor completo sea
   estable (p. ej. snapshot del catálogo `MSG` en messages_es).
2. **Literal anclado con delimitadores** que el wrap rompe:
   `"Run all quality-gate layers\n" in out` falla con `"XX...XX\n"` (el XX se
   interpone ante el `\n`). Mata wrap + case sin acoplarse a mutmut.
3. `assert "XX" not in out` — red de seguridad acoplada al esquema de mutmut;
   solo como complemento, nunca como assert principal (preferencia del
   proyecto: literales anclados).
