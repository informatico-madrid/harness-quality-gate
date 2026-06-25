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
   aplica el mutante en disco, corre SOLO tu test, debe FALLAR; revierte. Si
   pasa con el mutante aplicado, tu test no toca esa rama: usa `pytest --pdb` o
   un print temporal para ver qué camino recorre de verdad.
5. **Mock que neutraliza la mutación**: mockeaste la función mutada o una
   que la envuelve (H5).

## Verificación manual a mano (sed/apply + revert): dos trampas de tooling

Si verificas mutantes editando el fuente a mano (en vez de `mutmut apply`), dos
cosas dan falsos positivos:

- **`.pyc` rancio.** Tras mutar + correr el test + revertir, el bytecode
  cacheado puede no invalidarse a tiempo (sobre todo si reviertes con `cp`, que
  reescribe el mtime de forma confusa). Un test que **PASA** (mutante no matado)
  puede ser falso-negativo del `.pyc` viejo. Regla: **un FAILED es fiable** (el
  mutante murió de verdad); **un PASSED hay que re-verificarlo** limpiando pyc
  antes de creértelo → `find . -path ./.venv -prune -o -name '*.pyc' -delete`
  ENTRE cada iteración.
- **No reviertas con `git checkout -- <fichero>` si el working tree difiere de
  HEAD.** Te devuelve la versión de HEAD, no la que tenías antes de mutar — y si
  el working tree tenía cambios sin commitear (p. ej. pragmas ya quitados),
  `git checkout` los reintroduce silenciosamente y corrompes tu estado. Usa un
  backup con `cp` tomado ANTES de mutar (y verifica que el backup no sea ya una
  versión mutada de una iteración previa: confirma el fuente con `grep` tras
  restaurar).

---
