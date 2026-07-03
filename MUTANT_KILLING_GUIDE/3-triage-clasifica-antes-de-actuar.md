# 3. Triage: clasifica antes de actuar

Por cada `mutmut show`, responde en orden:

1. **¿El cambio es observable desde fuera de la función?**
   (retorno, excepción, efecto sobre un mock, log, archivo, exit code)
   → SÍ en ~90% de los casos: es un **test débil**, ve a §4.
2. **¿El cambio es observable solo "desde dentro"?**
   (nº de iteraciones, valor intermedio, kwarg pasado a una dependencia)
   → Sigue siendo matable con spies/mocks: §4.4 y §4.7.
3. **¿El cambio es genuinamente inobservable bajo CUALQUIER input y CUALQUIER
   doble de test?** → Candidato a equivalente: ve a §5 y busca su tipo.
   Casi siempre hay un refactor que lo elimina.

**Antes de escribir "equivalente", descarta las OTRAS dos causas (tripartición).**
Un mutante que "no se deja matar" casi nunca es un equivalente inocente: es una
**señal**. El fin del mutation testing no es matar por deporte, es encontrar
deficiencias. Un superviviente difícil suele ser una de tres cosas — y cada una
tiene una acción distinta:

| Causa | Señal | Acción correcta |
|---|---|---|
| **Código muerto** | el mutante está sobre un nodo/rama/símbolo sin usar (sin edge, sin caller) | **BORRAR** el código muerto → el mutante desaparece. NO pragma |
| **Coverage gap** | el comportamiento es real pero ningún test del *tier del gate* lo recorre (está en `@integration`, o en una rama gemela sin cubrir) | Escribir el test **offline en el tier del gate** ([H19](h19-coverage-gap-por-tier-el-mutante-vivo-que-solo-cubre-integration-excluido.md)). NO pragma |
| **Señal de diseño** | inmatable porque el valor está saturado / es una fuente de verdad duplicada / desconectada | **Rediseñar** (el mutante muere al arreglar el diseño) — ver [H18](h18-inspect-signature-no-mata-defaults-el-trampoln-conserva-la-firma.md) |

Solo lo que sobrevive a las TRES (no es muerto, sí está cubierto en el tier del
gate, el diseño es correcto) es candidato legítimo a equivalente/pragma (§5, §7).

Anti-patrones de test que generan supervivientes (búscalos primero en el test
existente antes de escribir uno nuevo):

- `assert result` / `assert result is not None` → cambiar por igualdad exacta.
- `assert "fragmento" in mensaje` → cambiar por `==` del mensaje completo.
- `mock.assert_called()` sin args → cambiar por `assert_called_once_with(args exactos)`.
- Solo happy path → añadir el camino del guard/early-return.
- Comparar solo 1-2 campos de un objeto → comparar el objeto/dict completo.
- Un solo elemento en listas de entrada → usar ≥2 elementos asimétricos.

---
