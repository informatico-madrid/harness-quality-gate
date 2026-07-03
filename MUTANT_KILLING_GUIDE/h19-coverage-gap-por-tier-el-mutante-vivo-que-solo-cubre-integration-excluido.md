# H19. Coverage gap por tier: el mutante vivo cuyo único test está excluido del gate

**Síntoma:** un mutante de **comportamiento real** (ruteo condicional, valor de
config, una rama) sobrevive aunque "obviamente" hay un test que lo ejerce.

**Causa 1 — el test está en un tier excluido.** El gate de mutación corre con
`pytest_add_cli_args = ["-m", "not (integration or e2e or live_llm)"]`. Si el único
test que recorre esa ruta es `@pytest.mark.integration` (p. ej. porque invoca el
grafo completo y toca red/Docker), mutmut **no lo ejecuta** → el mutante sobrevive.
No es equivalente: es un **hueco de cobertura en el tier del gate**.
  - **Fix correcto:** escribe un test **offline** en el tier unitario que ejerza el
    mismo comportamiento. Para un grafo LangGraph: inyecta `FakeModelRouter()` +
    puertos fake + `calibration_config` de paso, y `invoke()` el grafo real por la
    ruta concreta (loop-back, escalación, retry). Mata el mutante Y cubre el
    comportamiento nuclear que estaba sin test en el gate. NO es un pragma.

**Causa 2 — el test cubre solo UNA de dos ramas gemelas.** mutmut muta *cada*
copia de una línea repetida. Si `compiled.config = {...}` aparece en la rama
`if checkpointer:` (línea A) y en la rama `else` (línea B), un test que solo llama
`build_graph()` (sin checkpointer) mata los mutantes de B pero **no los de A**.
  - **Fix:** un test por rama. `build_graph(checkpointer=build_checkpointer(":memory:"),
    router=FakeModelRouter())` cubre la rama que producción realmente usa.

**Regla:** antes de declarar un mutante de comportamiento "equivalente", comprueba
que el gate **ejecuta** un test que recorre esa ruta **y** esa rama.
