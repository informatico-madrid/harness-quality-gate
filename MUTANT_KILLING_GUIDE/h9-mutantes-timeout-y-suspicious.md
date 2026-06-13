# H9. Mutantes ⏰ (timeout) y 🤔 (suspicious)

- **⏰**: la mutación creó un loop infinito (p. ej. `continue` que ya no
  avanza, condición de salida invertida). El gate los rechaza. Receta: test
  unitario rápido y específico de la condición de salida (frontera exacta,
  §4.2) para que un test BARATO falle antes de que la suite cuelgue.
- **🤔**: el test falla de forma no determinista con el mutante (flaky).
  Busca dependencia de orden (`-p no:randomly` ya está en el runner), estado
  global, `lru_cache` sin limpiar entre tests, o archivos compartidos.
  Fixture que limpie caches (`func.cache_clear()`) y `tmp_path` por test.
