# Plan: Desacoplamiento de bmad-harness como módulo BMad genérico

## Objetivo

Convertir `bmad-harness` de un conjunto de archivos acoplados a `harness-quality-gate` en un **módulo BMad instalable standalone** que funcione con **cualquier lenguaje y cualquier nombre de paquete de producción**.

## Arquitectura del módulo tras desacoplamiento

```
bmad-harness/                       # Módulo BMad standalone
├── config.yaml                     # NUEVO: configuración del módulo
│   ├── prod_package: "harness_quality_gate"  # configurable por usuario
│   └── test_package: "tests"
├── hooks/
│   └── tdd_cycle_gate.py           # DESACOPLADO: lee prod_package desde config
├── plugins/
│   └── tdd-gate/
│       └── plugin.js               # DESACOPLADO: lee prod_package desde config
├── skills/
│   └── gherkin-author/
│       └── SKILL.md                # DESACOPLADO: sin referencias al proyecto
├── overrides/
│   ├── bmad-agent-dev.toml         # DESACOPLADO: referencias genéricas
│   ├── bmad-dev-story.toml         # DESACOPLADO: <prod-package> placeholder
│   └── bmad-code-review.toml       # DESACOPLADO: <prod-package> placeholder
├── docs/
│   ├── README.md                   # DESACOPLADO: instalación genérica
│   ├── standards.md                # DESACOPLADO: <prod-package> placeholder
│   └── learnings.md                # PLANTILLA: sin contenido específico
├── bootstrap.sh                    # ACTUALIZADO: lee config, genera hooks
└── OPTIONAL/                       # SUB-MÓDULO OPCIONAL (Python)
    ├── mutation-killing/
    │   └── SUBAGENT_MUTATION_INSTRUCTIONS.md
    └── README.md                   # "Instalar solo si usas Python/mutmut"
```

---

## Paso 1: Crear `config.yaml` del módulo

**Archivo nuevo:** `tools/bmad-harness/config.yaml`

```yaml
# bmad-harness configuration
# Este archivo es leído por tdd_cycle_gate.py y plugin.js
# El usuario lo edita tras instalar el módulo BMad

# Paquete de producción (ej: "harness_quality_gate", "src/myapp", "lib")
prod_package: "harness_quality_gate"

# Paquete de tests (generalmente "tests")
test_package: "tests"

# Habilitar gate TDD (true) o solo documentación (false)
enable_gate: true

# Habilitar Puerta Gherkin (true) o solo TDD gate (false)
enable_gherkin: true
```

**Razón:** Centraliza la configuración. El bootstrap lee este archivo y lo usa para generar los hooks con los valores correctos.

---

## Paso 2: Desacoplar `tdd_cycle_gate.py`

**Cambios:**

1. **Eliminar** hardcoded `_PROD_PREFIX = "harness_quality_gate/"`
2. **Agregar** función `_load_config()` que lee `tools/bmad-harness/config.yaml`
3. **Fallback:** si config no existe, usar `prod_package` del primer director encontrado bajo `harness_quality_gate/` o `src/`
4. **Actualizar** `_classify()` para usar `_config["prod_package"]`

**Código nuevo (reemplaza líneas 58-60):**

```python
# ── Configuration ──────────────────────────────────────────────────────────────
_CONFIG_FILE = Path("tools/bmad-harness/config.yaml")

def _load_config() -> dict:
    """Load module configuration (best-effort; never raises)."""
    try:
        import yaml  # pyyaml may not be installed; fall back to regex
        data = yaml.safe_load(_CONFIG_FILE.read_text(encoding="utf-8"))
        return {
            "prod_package": data.get("prod_package", "src/"),
            "test_package": data.get("test_package", "tests/"),
        }
    except ImportError:
        # Fallback: simple regex parse (no dependency on pyyaml)
        text = _CONFIG_FILE.read_text(encoding="utf-8")
        prod = re.search(r'prod_package:\s*"([^"]+)"', text)
        test = re.search(r'test_package:\s*"([^"]+)"', text)
        return {
            "prod_package": prod.group(1) if prod else "src/",
            "test_package": test.group(1) if test else "tests/",
        }
    except OSError:
        return {"prod_package": "src/", "test_package": "tests/"}

_config = _load_config()
_PROD_PREFIX = _config["prod_package"]
_TEST_PREFIX = _config["test_package"]
```

**Línea 128:** `_classify()` usa `_PROD_PREFIX` que ahora viene de config.

---

## Paso 3: Desacoplar `plugin.js`

**Cambios:**

1. **Eliminar** hardcoded `const PROD_PREFIX = 'harness_quality_gate/';`
2. **Agregar** función `loadConfig()` que lee `tools/bmad-harness/config.yaml`
3. **Fallback:** si config no existe, usar `'src/'`

**Código nuevo (reemplaza líneas 31-33):**

```javascript
// ── Configuration ────────────────────────────────────────────────────────────

function loadConfig() {
  try {
    const fs = require('fs');
    const configPath = path.join(PROJECT_ROOT, 'tools', 'bmad-harness', 'config.yaml');
    const text = fs.readFileSync(configPath, 'utf-8');
    const prodMatch = text.match(/prod_package:\s*"([^"]+)"/);
    const testMatch = text.match(/test_package:\s*"([^"]+)"/);
    return {
      prod_package: prodMatch ? prodMatch[1] : 'src/',
      test_package: testMatch ? testMatch[1] : 'tests/',
    };
  } catch {
    return { prod_package: 'src/', test_package: 'tests/' };
  }
}

const CONFIG = loadConfig();
const PROD_PREFIX = CONFIG.prod_package;
const TEST_PREFIX = CONFIG.test_package;
```

---

## Paso 4: Desacoplar `bmad-dev-story.toml`

**Cambios:**

1. **Reemplazar** `harness_quality_gate/**` con `<prod-package>/**`
2. **Eliminar** referencia a `SUBAGENT_MUTATION_INSTRUCTIONS.md` de `persistent_facts`
3. **Mover** instrucción de mutantes a nota condicional

**Contenido nuevo:**

```toml
# Team override for bmad-dev-story workflow — bmad-harness extension.
# SPARSE: only the fields we add. Arrays append onto the base customize.toml.
# Source of truth: docs/bmad-harness/standards.md · See docs/bmad-harness/README.md

[workflow]

persistent_facts = [
  "file:{project-root}/docs/bmad-harness/standards.md",
  "file:{project-root}/docs/bmad-harness/learnings.md",
]

activation_steps_prepend = [
  "Puerta Gherkin (gate duro): localiza `tests/contracts/<story-key>.feature` y verifica la firma en cabecera: `# Status: APPROVED` + `# Approved-by:`. Si el archivo no existe o `# Status:` no es APPROVED, HALT: pide generarlo/firmarlo con `/gherkin-author` ANTES de implementar. Sin excepciones (tampoco stories antiguas). No escribas produccion sin contrato firmado.",
]

activation_steps_append = [
  # ── Bitacora TDD — GATE MECANICO POR ESCENARIO ──────────────────────────────
  "Bitacora TDD durable — GATE MECANICO POR ESCENARIO (regla de secuencia de tool calls, no consejo): por CADA @s del contrato, el ciclo obligatorio de herramientas es: (1) Escribe el test minimo → ejecuta pytest → confirma FAILED en pantalla. (2) PAUSA COMPLETA. Llama a Edit/Write sobre el archivo de story AHORA para escribir en '### TDD Bitacora': '@sN — <comportamiento>\\n  ROJO: <comando exacto> → <primeras 3-5 lineas del error REAL>'. Este Edit es una tool call confirmada por el sistema, no texto en contexto — sin ese Edit el ciclo ROJO no ha ocurrido y NO debes avanzar. (3) Solo despues de que el Edit esté confirmado: escribe el codigo de produccion minimo para pasar el test. (4) Despues de VERDE: llama a Edit para anadir '  VERDE: <cambio de produccion minimo>'. (5) Despues de REFACTOR: llama a Edit para anadir '  REFACTOR: <que / o nada>'. NO abras el siguiente @s hasta que el Edit de ROJO del @s actual esté confirmado — la compactacion destruye lo que esta en contexto, solo el archivo persiste. Al cerrar el ultimo @s, escribe el mapa de trazabilidad @s→test. Respeta las Tres Leyes del TDD (standards.md Atomo 2a). GATE Paso 9: NO marques la story ni el sprint-status como 'review' si algun @s tiene ROJO vacio o 'PENDIENTE' sin explicacion. Si el ROJO se perdió, documenta la desviacion honesta (causa + medida correctiva) — PROHIBIDO inventar a posteriori.",
  # ── Mutant killing (opcional: solo para proyectos Python con mutmut) ─────────
  # Si este proyecto usa Python + mutmut: sigue el protocolo en OPTIONAL/mutation-killing/SUBAGENT_MUTATION_INSTRUCTIONS.md
  # Cargar con: /subagent-mutation-instructions
  # Si NO es Python: omitir esta sección.
]
```

---

## Paso 5: Desacoplar `bmad-code-review.toml`

**Cambios:**

1. **Reemplazar** `harness_quality_gate/**` con `<prod-package>/**`

**Contenido nuevo:**

```toml
# Team override for bmad-code-review workflow — bmad-harness extension.
# SPARSE: only the fields we add. Arrays append onto the base customize.toml.
# Source of truth: docs/bmad-harness/standards.md · See docs/bmad-harness/README.md

[workflow]

persistent_facts = [
  "file:{project-root}/docs/bmad-harness/standards.md",
  "file:{project-root}/docs/bmad-harness/learnings.md",
]

activation_steps_append = [
  # ── Auditoria de Proceso (Atomo 3) ─────────────────────────────────────────
  "Auditoria de Proceso (4º pase): cruza la 'TDD Bitacora' del Dev Agent Record + el `.feature` firmado + el diff final. Caza: (a) produccion-sin-ROJO-previo — diff edita `<prod-package>/**` sin ROJO en bitacora para ese @s; (b) scope creep — diff implementa algo no cubierto por ningun @s del .feature; (c) refactor-en-rojo — diff edita produccion sin VERDE previo en bitacora; (d) green-falso — test pasa pero no es el minimo (asserts extras, mockeo excesivo); (e) @s sin test — escenario @s en .feature sin entrada correspondiente en bitacora. Reporta citando archivo:linea.",
]
```

---

## Paso 6: Desacoplar `standards.md`

**Cambios:**

1. **Reemplazar** `harness_quality_gate/**` con `<prod-package>/**`
2. **Agregar** nota explicando que `<prod-package>` se configura en `config.yaml`

**Contenido nuevo (líneas 37-42 y tabla):**

```markdown
> **🔒 GATE MECANICO (no advisory).** Esta regla la **impone un hook de Claude Code**,
> no tu disciplina: `tools/bmad-harness/hooks/tdd_cycle_gate.py` (cableado en
> `.claude/settings.json` por el bootstrap). Mientras una story está `in-progress`,
> el hook **bloquea** (a) editar `<prod-package>/**` si no hay un ROJO registrado
> (fase ≠ `CODING`/`REFACTOR`), y (b) abrir el siguiente test sin cerrar el `@s` actual
> (VERDE+REFACTOR).
>
> **Configuración:** `<prod-package>` se define en `tools/bmad-harness/config.yaml`
> (por defecto `src/`). Edita este archivo tras instalar el módulo.

## Atomo 3 — Auditoria de Proceso en Code Review

`bmad-code-review` mantiene sus 3 capas (Blind Hunter, Edge Case, Acceptance Auditor)
**intactas** y anade un pase de **Auditoria de Proceso** que **no mira solo el diff**:
cruza la **bitacora TDD** del Dev Agent Record + el `.feature` + el diff y reporta,
citando `archivo:linea`:

| Caza que | Como |
|-----------|------|
| Produccion-sin-ROJO-previo | Diff edita `<prod-package>/**` sin ROJO en bitacora para ese @s |
| Scope creep | Diff implementa algo no cubierto por ningun @s del .feature |
| Refactor-en-rojo | Diff edita produccion sin VERDE previo en bitacora |
| Green-falso | Test pasa pero no es el minimo (asserts extras, mockeo excesivo) |
| @s sin test | Escenario @s en .feature sin entrada correspondiente en bitacora |
```

---

## Paso 7: Desacoplar `gherkin-author/SKILL.md`

**Cambios:**

1. **Reemplazar** referencia a `harness-quality-gate project asset` con `bmad-harness module asset`
2. Las referencias a `{project-root}/_bmad/bmm/config.yaml` y `{project-root}/docs/bmad-harness/standards.md` ya son genéricas

**Línea 3 nueva:**

```markdown
description: 'Distil a story''s Acceptance Criteria into the Gherkin dev-contract tests/contracts/<story-key>.feature (@s1..@sn) and walk it through human signature (Puerta Gherkin, Atomo 1). bmad-harness module asset — not part of BMad. Run before dev-story on every story; supports --retrofit for already-implemented stories.'
```

---

## Paso 8: Crear `learnings.md` plantilla

**Archivo nuevo (reemplaza contenido existente):**

```markdown
# Learnings `bmad-harness`

Lecciones aprendidas iterativamente durante la implementacion de stories.

> Esta es una plantilla. Las lecciones se registran aqui durante el uso del modulo.

## Historial de iteraciones

### <fecha> — <titulo>

- PROBLEMA: ...
- LECCION: ...
```

---

## Paso 9: Separar `SUBAGENT_MUTATION_INSTRUCTIONS.md` como sub-módulo opcional

**Acción:**

1. **Mover** `SUBAGENT_MUTATION_INSTRUCTIONS.md` a `tools/bmad-harness/OPTIONAL/mutation-killing/SUBAGENT_MUTATION_INSTRUCTIONS.md`
2. **Crear** `tools/bmad-harness/OPTIONAL/README.md`:

```markdown
# Sub-módulos opcionales de bmad-harness

Estos sub-módulos solo son relevantes para proyectos con requisitos específicos.

## mutation-killing/

**Relevante para:** Proyectos Python que usan `mutmut` para testing de mutación.

Contiene el protocolo de matanza de mutantes (`SUBAGENT_MUTATION_INSTRUCTIONS.md`)
adaptado para `harness_quality_gate/`.

**Para usar:**
1. Copiar `SUBAGENT_MUTATION_INSTRUCTIONS.md` a la raiz del proyecto
2. Ajustar referencias a tu paquete (`harness_quality_gate` → tu paquete)
3. Cargar con: `/subagent-mutation-instructions`

**No relevante para:** Proyectos PHP, TypeScript, u otros lenguajes.
```

3. **Actualizar** `bmad-dev-story.toml` para que la referencia a mutation instructions sea condicional (paso 4 ya lo hace)

---

## Paso 10: Actualizar `bootstrap.sh`

**Cambios:**

1. **Leer** `tools/bmad-harness/config.yaml` para obtener `prod_package`
2. **Validar** que el paquete existe en el repositorio
3. **Actualizar** `tdd_cycle_gate.py` para que use el valor de config (ya se hace en paso 2)
4. **Agregar** mensaje de instalación: "Edita tools/bmad-harness/config.yaml para configurar tu prod_package"

**Sección nueva (después de línea 111):**

```bash
echo
echo "== bmad-harness configuration =="
CONFIG="tools/bmad-harness/config.yaml"
if [ -f "$CONFIG" ]; then
  PROD_PKG=$(grep 'prod_package:' "$CONFIG" | sed 's/.*:\s*"\([^"]*\)".*/\1/')
  echo "  prod_package: $PROD_PKG (from $CONFIG)"
  echo "  note: Edit $CONFIG to change prod_package"
else
  echo "  WARNING: $CONFIG not found — using defaults (src/, tests/)"
  echo "  Create $CONFIG with your prod_package setting." >&2
fi
```

---

## Paso 11: Actualizar `README.md` del módulo

**Cambios:**

1. **Reemplazar** todas las referencias a `harness_quality_gate` con `<prod-package>`
2. **Agregar** sección "Instalación" con pasos genéricos
3. **Agregar** sección "Configuración" explicando `config.yaml`
4. **Agregar** tabla de lenguajes soportados

**Nueva sección "Instalación":**

```markdown
## Instalación

1. Instalar el módulo BMad en tu proyecto:
   ```bash
   bmad-module-builder install bmad-harness
   ```

2. Configurar `tools/bmad-harness/config.yaml`:
   ```yaml
   prod_package: "mi_paquete"    # ← cambiar por tu paquete de producción
   test_package: "tests"          # ← generalmente no necesita cambio
   enable_gate: true              # ← activar gate mecanico
   enable_gherkin: true           # ← activar Puerta Gherkin
   ```

3. Ejecutar bootstrap:
   ```bash
   bash scripts/bmad-harness-bootstrap.sh
   ```

4. Verificar:
   ```bash
   python3 tools/bmad-harness/hooks/tdd_cycle_gate.py status
   ```

## Lenguajes soportados

| Lenguaje | Gate TDD | Puerta Gherkin | Mutation Killing |
|----------|----------|----------------|------------------|
| Python   | ✅       | ✅             | ✅ (opcional)    |
| PHP      | ✅       | ✅             | ❌ (no incluido) |
| TypeScript | ✅     | ✅             | ❌ (no incluido) |
| Cualquier otro | ✅ | ✅           | ❌               |

El gate TDD es **lenguaje-agnóstico**: solo verifica que no edites archivos de
produccion sin pasar por el ciclo ROJO-VERDE-REFACTOR.
```

---

## Paso 12: Preparar para `bmad-module-builder`

**Estructura final esperada:**

```
tools/bmad-harness/                    # Raiz del módulo BMad
├── config.yaml                        # Configuración del módulo
├── hooks/
│   └── tdd_cycle_gate.py              # Hook Python desacoplado
├── plugins/
│   └── tdd-gate/
│       └── plugin.js                  # Plugin OpenCode desacoplado
├── skills/
│   └── gherkin-author/
│       └── SKILL.md                   # Skill desacoplado
├── overrides/
│   ├── bmad-agent-dev.toml            # Override desacoplado
│   ├── bmad-dev-story.toml            # Override desacoplado
│   └── bmad-code-review.toml          # Override desacoplado
├── docs/
│   ├── README.md                      # README genérico
│   ├── standards.md                   # Standards genéricos
│   └── learnings.md                   # Plantilla
├── bootstrap.sh                       # Bootstrap actualizado
└── OPTIONAL/
    ├── README.md                      # README de sub-módulos opcionales
    └── mutation-killing/
        └── SUBAGENT_MUTATION_INSTRUCTIONS.md  # Sub-módulo Python opcional
```

**Pasos para `bmad-module-builder`:**

1. Usar el comando `bmad-module-builder` para crear el módulo
2. El builder debe reconocer la estructura `tools/bmad-harness/` como un módulo
3. Generar un paquete instalable que:
   - Copie todos los archivos al proyecto destino
   - Ejecute `bootstrap.sh` para configurar hooks
   - Pida al usuario que edite `config.yaml`

---

## Diagrama de flujo de configuración

```
Usuario instala módulo
        │
        ▼
config.yaml existe? ──NO──> Usar defaults (src/, tests/)
        │
       SÍ
        │
        ▼
Leer prod_package desde config.yaml
        │
        ▼
tdd_cycle_gate.py usa _PROD_PREFIX = config["prod_package"]
        │
        ▼
plugin.js usa PROD_PREFIX = config.prod_package
        │
        ▼
Overrides usan <prod-package> como placeholder textual
        │
        ▼
Auditoria de Proceso reporta <prod-package>/**
```

---

## Resumen de cambios por archivo

| Archivo | Cambio | Tipo |
|---------|--------|------|
| `config.yaml` | **NUEVO** | Configuración central |
| `tdd_cycle_gate.py` | Leer `_PROD_PREFIX` desde config | Desacoplar |
| `plugin.js` | Leer `PROD_PREFIX` desde config | Desacoplar |
| `bmad-dev-story.toml` | Reemplazar `harness_quality_gate` con `<prod-package>`, mover mutation instructions a OPTIONAL | Desacoplar |
| `bmad-code-review.toml` | Reemplazar `harness_quality_gate` con `<prod-package>` | Desacoplar |
| `bmad-agent-dev.toml` | Sin cambios (ya es genérico) | OK |
| `standards.md` | Reemplazar `harness_quality_gate` con `<prod-package>` | Desacoplar |
| `gherkin-author/SKILL.md` | Limpiar referencia a `harness-quality-gate` | Desacoplar |
| `learnings.md` | Reemplazar con plantilla | Reemplazar |
| `SUBAGENT_MUTATION_INSTRUCTIONS.md` | Mover a OPTIONAL/mutation-killing/ | Separar |
| `bootstrap.sh` | Leer config.yaml, validar prod_package | Actualizar |
| `README.md` | Hacer genérico, agregar sección instalación | Actualizar |
