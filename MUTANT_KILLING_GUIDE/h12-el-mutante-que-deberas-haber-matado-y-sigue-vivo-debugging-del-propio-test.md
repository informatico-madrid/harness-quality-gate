# H12. El mutante que "deberías haber matado" y sigue vivo (debugging del propio test)

Cuando escribes el test correcto y el mutante sobrevive igualmente, en este
repo las causas reales han sido, por frecuencia:
1. **Caché sucia de mutmut** → `make clean-mutmut` y relanzar. (Si los
   números son absurdos: reinstalar mutmut — regla del proyecto.)
2. **El test no corre bajo mutmut**: el runner es `pytest tests/unit/ -q` —
   un test en `tests/integration/` NO mata nada. Verifica la ruta.
3. **Coverage desactualizado** con `mutate_only_covered_lines = true`: la
   línea aparece como no cubierta y el mutante ni se evalúa contra tu test.
   Regenerar `.coverage` con el MISMO scope (`tests/unit/`).
4. **El assert no ejecuta la rama mutada** → protocolo de verificación:
   `mutmut apply <id>`, correr SOLO tu test, debe FALLAR; `git checkout --` para
   revertir. Si pasa con el mutante aplicado, tu test no toca esa rama: usa
   `pytest --pdb` o un print temporal para ver qué camino recorre de verdad.
5. **Mock que neutraliza la mutación**: mockeaste la función mutada o una
   que la envuelve (H5).

---
