# H13. `monkeypatch.chdir` rompe la recolección de stats de mutmut

Síntoma real (2026-06-11): `failed to collect stats. runner returned 1` con
`FileNotFoundError: .../tmp_path/harness_quality_gate` — mutmut resuelve las
rutas de los módulos mutados RELATIVAS al cwd, y un test que hace
`monkeypatch.chdir(tmp_path)` se lo cambia a mitad de recolección.
- **Prohibido `chdir` en tests unitarios** de este repo. Para matar un
  `default="."` de argparse: spy sobre el comando despachado y assert
  `args.repo == "."` (sin tocar el cwd).
