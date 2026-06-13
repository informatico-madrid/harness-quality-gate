# H1. Passthrough de argumentos a colaboradores mockeados ⭐ (el nº 1 de este repo)

**Diff real** (`python_adapter.run_l4__mutmut_4`, superviviente hoy):

```diff
-    bandit_findings = self._run_bandit(repo, env)
+    bandit_findings = self._run_bandit(None, env)
```

Variantes reales: `_run_vulture(repo, None)`, `_run_mutmut(repo, None)`,
`adapter.version(None, {})`. Hay decenas en `run_l1`–`run_l4` y `tool_versions`.

**Por qué sobrevive**: el test del orquestador mockea `_run_bandit` con un
`MagicMock`, que acepta CUALQUIER argumento (incluido `None`) y devuelve lo
configurado. El resultado final del orquestador es idéntico → el test pasa.
Esto es la trampa estructural de los orquestadores: cuanto más mockeas, más
mutantes de cableado sobreviven.

**Receta — el "test de cableado" (wiring test)**: un único test por
orquestador que verifica TODAS las llamadas con argumentos exactos. Mata
todos los passthrough del método de golpe:

```python
def test_run_l4_wiring_exacto(adapter, monkeypatch):
    repo, env = Path("/repo/único"), {"MARCADOR": "xyz"}   # valores únicos, no triviales
    spies = {}
    for name in ("_run_bandit", "_run_deptry"):
        spies[name] = MagicMock(return_value=[])
        monkeypatch.setattr(adapter, name, spies[name])

    adapter.run_l4(repo, env)

    for name, spy in spies.items():
        assert spy.call_args_list == [call(repo, env)], name   # posición Y valor
        assert spy.call_args.args[0] is repo                   # identidad: mata repo→None
        assert spy.call_args.args[1] is env                    # identidad: mata env→None
```

Claves de la receta:
- **`call_args_list == [call(...)]`** completo, nunca `assert_called()`.
- **Asersión de identidad (`is`)** además de igualdad: inmune a mutaciones
  que produzcan un valor "igual pero distinto" (p. ej. `Path(".")` recreado).
- **Valores centinela únicos** (`{"MARCADOR": "xyz"}`, rutas raras): si usas
  `{}` o `Path(".")`, una mutación a otro valor vacío/default puede empatar.
- **`autospec=True`** en los patches (`patch.object(adapter, "_run_bandit", autospec=True)`):
  un mock con spec rechaza llamadas con aridad/kwargs inválidos, matando
  mutaciones de firma gratis.

Para `tool_versions` (muta `adapter.version(self.repo_placeholder(Path(".")), {})`
→ `version(None, {})`): mismo patrón, asserta sobre el mock de cada
sub-adapter: `sub.version.assert_called_once_with(expected_path, {})` y
comprueba `call_args.args[0] == adapter.repo_placeholder(Path("."))`.
