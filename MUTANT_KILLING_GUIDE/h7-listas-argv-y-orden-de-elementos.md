# H7. Listas argv y orden de elementos

`["phpmd", str(path), "json", ruleset]` — mutaciones de cada string y del
orden. Sobreviven si el test hace `assert "phpmd" in cmd`.

**Receta**: igualdad de la lista COMPLETA en la asersión de la llamada
(`assert_called_once_with([...exacta...], ...)`). Si el comando se construye
condicionalmente (flags opcionales), un test por rama con la lista completa
de esa rama.
