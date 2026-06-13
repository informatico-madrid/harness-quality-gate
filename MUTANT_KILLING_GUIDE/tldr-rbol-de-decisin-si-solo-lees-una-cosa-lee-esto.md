# TL;DR — Árbol de decisión (si solo lees una cosa, lee esto)

Para CADA superviviente, en este orden y sin saltarte pasos:

1. `mutmut show <id>` — lee el diff. Sin diff no hay diagnóstico.
2. ¿El cambio es observable (retorno, excepción, string, llamada a una
   dependencia)? → **escribe/endurece un test** que lo fije (§4): asersión
   densa, frontera exacta, string exacto o `assert_called_once_with` completo.
3. ¿No es observable porque es un default muerto, rama inalcanzable o código
   redundante? → **refactoriza para que el mutante no pueda existir** (§5:
   p. ej. `d.get(k, X)` → `d.get(k)` cuando `X` es inobservable). El código
   queda más limpio y el mutante desaparece.
4. ¿Ni test ni refactor posibles (caso raro y PROBADO)? → **pragma** con
   `# reason:` + `# audited:` (§7). Último recurso, no el primero.
5. **Nunca** termines en "es equivalente" escrito solo en un informe: si el
   código no cambió (test, refactor o pragma), el mutante NO está resuelto.

Verificación obligatoria en todos los caminos: el test pasa con el código
original y falla con `mutmut apply <id>` aplicado (revertir después).

---
