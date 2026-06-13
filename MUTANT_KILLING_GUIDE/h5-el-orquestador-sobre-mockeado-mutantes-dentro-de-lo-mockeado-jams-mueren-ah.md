# H5. El orquestador sobre-mockeado (mutantes DENTRO de lo mockeado jamás mueren ahí)

Si el test de `run_l3a` mockea `_run_ruff`, ningún test de `run_l3a` puede
matar mutantes DE `_run_ruff`. Parece obvio, pero es la causa nº 1 de "he
añadido 5 tests y el conteo no baja": el test ataca la capa equivocada.

**Receta — dos niveles, responsabilidades separadas**:
1. Tests del orquestador: SOLO cableado (H1) + agregación (orden de findings,
   `extend` exacto) + logs (H3) + duración (H2).
2. Tests del método hoja (`_run_ruff`): mock de `subprocess.run` con stdout
   realista, asersiones densas del parseo (§4.1) y de la llamada (§4.4).

Antes de escribir un test, localiza en qué función vive el mutante
(el nombre lo dice: `xǁPythonAdapterǁrun_l2__mutmut_18` → `run_l2`) y testea
ESA función directamente.
