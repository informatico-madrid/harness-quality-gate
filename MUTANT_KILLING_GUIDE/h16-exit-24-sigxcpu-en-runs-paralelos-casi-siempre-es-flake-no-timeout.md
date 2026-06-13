# H16. Exit -24 (SIGXCPU) en runs paralelos: casi siempre es flake, no timeout

Con `--max-children` alto, algunos mutantes terminan con exit `-24` (límite
de CPU del worker) aunque sus tests los matan en <2s. Antes de tratarlos como
⏰ reales:
```bash
cd mutants && MUTANT_UNDER_TEST=<id-completo> python -m pytest tests/unit/<archivo> -x -q
```
Si falla rápido → flake del paralelismo; se resolverá en el run final (o
re-ejecutando el módulo). Si de verdad cuelga → Tipo I (§5).
