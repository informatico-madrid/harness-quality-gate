# H20. `path_map` de LangGraph: identidad→`None` es equivalente; clave/valor mangleado NO

En `builder.add_conditional_edges(src, router, path_map)`, mutmut ataca el
`path_map` de tres formas. NO todas son iguales:

**Equivalente genuino — mapa IDENTIDAD → `None` o eliminado.**
`{"model_call": "model_call", "staging": "staging"}` → `None`. Cuando el mapa es
la **identidad** (cada clave apunta a un nodo de su mismo nombre), pasar `None`
hace que LangGraph use el valor de retorno del router **directamente** como destino
→ ruteo **idéntico en runtime**. Estos mutantes (`→ None`, borrar el arg) son
equivalentes reales → pragma honesto, o elimina el `path_map` redundante. (Ojo: si
el mapa NO es identidad, `→ None` SÍ cambia comportamiento y es matable.)

**Matable — clave o valor mangleado.**
`{"XXmodel_callXX": "model_call", ...}` (clave) o `{"model_call": "STAGE"}` (valor).
Rompe el ruteo **solo en runtime**, cuando el router devuelve esa clave. Compila
igual → un `assert graph is not None` NO lo mata. Hay que **recorrer la ruta**:
`invoke()` el grafo por el camino que devuelve esa clave (retry, loop-back,
escalación) y afirmar el resultado observable. Ver [H19](h19-coverage-gap-por-tier-el-mutante-vivo-que-solo-cubre-integration-excluido.md)
(los tests de recorrido suelen estar mal-marcados como `@integration`).

**Diagnóstico rápido del diff:** ¿el `+` cambió el lado izquierdo (clave) o derecho
(valor) del dict, o lo sustituyó por `None`/lo borró? Los dos primeros = matable por
recorrido; el tercero = equivalente **solo si el mapa era identidad**.
