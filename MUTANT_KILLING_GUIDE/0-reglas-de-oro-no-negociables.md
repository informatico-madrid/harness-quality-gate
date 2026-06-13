# 0. Reglas de oro (no negociables)

1. **Prioridad estricta**: test que mata > refactor que elimina el mutante > pragma.
   El pragma es el ÚLTIMO recurso y exige `# reason:` + `# audited:` (ver §7).
2. **"Equivalente" es una afirmación que hay que PROBAR, no una excusa.**
   Antes de declarar un mutante equivalente, debes haber intentado las
   estrategias de §4 y §5 para su tipo. La mayoría de "equivalentes" son
   tests débiles.
3. **Declarar "equivalente" exige actuar en el CÓDIGO, no en el informe.**
   Toda equivalencia termina en uno de dos sitios: un REFACTOR que elimina el
   mutante (§5) o un pragma auditado (§7). Un informe que lista "equivalentes"
   sin tocar el código deja los supervivientes restando MSI y obliga al
   siguiente agente a repetir el triage desde cero. Caso real (2026-06-10):
   6 supervivientes de `psalm_taint_adapter.py` declarados equivalentes solo en
   el informe — con razonamiento falso en 2 de ellos (`isinstance([], list)` ES
   `True`) — cuando el Tipo C los eliminaba quitando el default muerto.
4. **Nunca modificar el código fuente de mutmut** (`.venv/lib/python*/site-packages/mutmut/`).
   Si mutmut se comporta raro (menos mutantes de los esperados, 0 mutantes,
   resultados extraños): desinstalar y reinstalar mutmut ANTES de investigar.
5. **Nunca debilitar el código de producción para matar un mutante.** Un
   refactor que elimina un mutante equivalente debe preservar el comportamiento
   (los 1139 tests deben seguir en verde y coverage en 100%).
6. **Regenerar `.coverage` antes de cada run** (con `mutate_only_covered_lines = true`,
   un coverage viejo manda mutantes a `no_tests`). El `make mutation` ya lo gestiona.
7. Paralelismo: `--max-children 20` (≈ la mitad de los cores). Saturar todos los
   cores deja sin CPU a los hijos y produce timeouts espurios (verificado
   2026-06-12); el Makefile ya usa 20 por defecto.

---
