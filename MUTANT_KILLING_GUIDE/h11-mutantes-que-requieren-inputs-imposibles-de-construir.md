# H11. Mutantes que requieren inputs "imposibles de construir"

La rama necesita un objeto que el constructor público no permite crear
(validación previa). Opciones en orden:
1. Construir el objeto inválido por la puerta de atrás del test:
   `object.__new__(Cls)` + setattr, o `dataclasses.replace`, o un stub con
   la misma interfaz. El test documenta "si esto ocurriera, haríamos X".
2. Testear el método privado que contiene la rama directamente
   (`adapter._parse_línea(línea_corrupta)`) — un test de método privado es
   mejor que un pragma.
3. Si de verdad es inalcanzable desde cualquier interfaz → es código muerto
   o invariante: §5.B / §5.D (refactor o pragma con el invariante citado).
