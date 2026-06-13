# H8. break/continue y early-return en loops puros (el equivalente clásico que no lo es)

Ya cubierto en §4.7/§5.A; el caso DIFÍCIL es cuando el cuerpo del loop no
llama a nada tuyo (puro de verdad). Receta avanzada — **iterador espía**:

```python
class IterEspia:
    def __init__(self, items): self.items, self.consumidos = iter(items), 0
    def __iter__(self): return self
    def __next__(self): self.consumidos += 1; return next(self.items)

espia = IterEspia([obj_que_matchea, obj_extra])
buscar_primero(espia)
assert espia.consumidos == 1     # continue habría consumido 2 → muere
```

Si ni siquiera puedes pasar un iterable (el loop itera algo interno):
refactor a `next()`/`any()` (§5.A) — es el único caso donde tocar el código
es la respuesta correcta.
