# 6. Estrategia de campaña (para el coordinador)

1. **Agrupa supervivientes por archivo y por tipo de mutación**, no uno a uno:
   un solo test denso (§4.1) o un spy completo (§4.4) suele matar 5-20
   mutantes del mismo bloque. Mira primero los clusters grandes.
2. Orden de ataque por rentabilidad:
   1º llamadas a subprocess/deps sin `assert_called_once_with` completo,
   2º resultados comparados parcialmente → igualdad de objeto completo,
   3º strings/mensajes sin asserts exactos,
   4º fronteras de comparación,
   5º casos raros uno a uno.
3. Cada subagente trabaja con `make mutation-path FILE_PATH=...` (directorios
   aislados, paralelizable sin conflictos). Máximo 2 subagentes en paralelo
   (límites de tokens).
4. Al final de cada tanda: suite completa + coverage 100% + `make clean-mutmut`
   + run completo. La verdad está en `mutants/mutmut-cicd-stats.json`, NO en
   `mutmut results` (que arrastra `not checked` de runs interrumpidos).
5. Si un subagente lleva 3+ intentos con el mismo mutante sin matarlo: STOP,
   aplicar el mutante en disco (§1) y entender el porqué antes de escribir
   más tests a ciegas.
6. **Informe de subagente: evidencia por mutante, no veredictos.** Cada mutante
   reportado debe citar su evidencia verificable: qué test lo mata (y que ese
   test FALLA con `mutmut apply <id>` aplicado), o qué refactor/pragma lo
   eliminó (diff concreto). Una columna "Reason" redactada sin haber aplicado
   el mutante no es evidencia — así se cuelan razonamientos falsos. El
   coordinador rechaza tablas de "equivalentes declarados" sin diff asociado.

---
