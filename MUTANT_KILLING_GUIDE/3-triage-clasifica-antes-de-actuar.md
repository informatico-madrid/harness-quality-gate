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

Anti-patrones de test que generan supervivientes (búscalos primero en el test
existente antes de escribir uno nuevo):

- `assert result` / `assert result is not None` → cambiar por igualdad exacta.
- `assert "fragmento" in mensaje` → cambiar por `==` del mensaje completo.
- `mock.assert_called()` sin args → cambiar por `assert_called_once_with(args exactos)`.
- Solo happy path → añadir el camino del guard/early-return.
- Comparar solo 1-2 campos de un objeto → comparar el objeto/dict completo.
- Un solo elemento en listas de entrada → usar ≥2 elementos asimétricos.

---
