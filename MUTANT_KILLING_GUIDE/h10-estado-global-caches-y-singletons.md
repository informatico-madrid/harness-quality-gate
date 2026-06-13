# H10. Estado global, caches y singletons

Mutante en código que solo se ejecuta UNA vez por proceso (init de módulo,
`lru_cache`, registro de adapters): el primer test lo ejecuta, los demás ven
la cache → la mutación "no afecta" al test que debía matarla.

**Receta**: fixture de aislamiento que resetea el estado entre tests
(`cache_clear()`, `importlib.reload` como último recurso, monkeypatch del
registro). Si el módulo tiene side-effects de import → refactor a init
explícito (los side-effects de import son inmatables Y mal diseño).
