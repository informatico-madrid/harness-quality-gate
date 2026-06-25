# H16. Exit -24 (SIGXCPU) en runs paralelos: casi siempre es flake, no timeout

Con `--max-children` alto, algunos mutantes terminan con exit `-24` (límite
de CPU del worker) aunque sus tests los matan en <2s. Antes de tratarlos como
⏰ reales:
```bash
cd mutants && MUTANT_UNDER_TEST=<id-completo> python -m pytest tests/unit/<archivo> -x -q
```
Si falla rápido → flake del paralelismo; se resolverá en el run final (o
re-ejecutando el módulo). Si de verdad cuelga → Tipo I (§5).

**PERO: un `-24` _persistente_ NO es contención, es un blowup de recursos.** Si
los MISMOS mutantes dan `-24` a paralelismo alto Y bajo (probé 18, 12 y 8), no
es flake: algún test que los cubre consume CPU/RAM sin límite. Síntoma gemelo:
bajo `ulimit -v` el `-24` se convierte en `exit=3` (pytest INTERNAL ERROR por
`MemoryError`). Casi siempre es el caso de **H17** (un `MagicMock` de input que
un mutante arrastra a un bucle/stream infinito). No lo descartes como flake:
aíslalo single-child bajo `ulimit` y arregla el test que lo cubre.
