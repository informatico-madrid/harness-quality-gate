# Análisis de Agentes Nativos OpenCode con Problema de Modelo `inherit`

## Fecha de Investigación
2026-06-16

## Fuentes Analizadas

1. [`/home/malka/.config/opencode/opencode.json`](https://github.com/opencode-ai/opencode) - Configuración actual
2. [`/home/malka/.config/opencode/node_modules/@opencode-ai/sdk/dist/v2/gen/types.gen.d.ts`](https://github.com/opencode-ai/opencode) - Esquema de tipos SDK v2
3. [`/home/malka/.config/opencode/agents/`](https://github.com/opencode-ai/opencode) - Directorio de agentes personalizados (196 archivos)

---

## 1. Esquema de Tipos de `AgentConfig`

Según [`types.gen.d.ts`](/home/malka/.config/opencode/node_modules/@opencode-ai/sdk/dist/v2/gen/types.gen.d.ts:1385), el tipo `AgentConfig` es:

```typescript
export type AgentConfig = {
    model?: string;
    variant?: string;
    temperature?: number;
    top_p?: number;
    prompt?: string;
    tools?: { [key: string]: boolean };
    disable?: boolean;
    description?: string;
    mode?: "subagent" | "primary" | "all";
    hidden?: boolean;
    options?: { [key: string]: unknown };
    color?: string | "primary" | "secondary" | "accent" | "success" | "warning" | "error" | "info";
    steps?: number;
    maxSteps?: number;
    permission?: PermissionConfig;
    [key: string]: unknown;
};
```

## 2. Esquema de Configuración de Agentes Nativos

Según [`types.gen.d.ts`](/home/malka/.config/opencode/node_modules/@opencode-ai/sdk/dist/v2/gen/types.gen.d.ts:1597-1605), la configuración de agentes nativos se define en:

```typescript
agent?: {
    plan?: AgentConfig;
    build?: AgentConfig;
    general?: AgentConfig;
    explore?: AgentConfig;
    title?: AgentConfig;
    summary?: AgentConfig;
    compaction?: AgentConfig;
    [key: string]: AgentConfig | undefined;
};
```

**Los 7 agentes nativos de OpenCode son:**

| # | Agente Nativo | Descripción |
|---|---------------|-------------|
| 1 | `plan` | Plan agent |
| 2 | `build` | Build agent |
| 3 | `general` | General agent |
| 4 | `explore` | Explore agent |
| 5 | `title` | Title agent |
| 6 | `summary` | Summary agent |
| 7 | `compaction` | Compaction agent |

## 3. Configuración Actual en `opencode.json`

Según [`opencode.json`](/home/malka/.config/opencode/opencode.json), la configuración actual de agentes es:

```json
{
  "agent": {
    "explore": {
      "model": "cefprovider/Qwen3.6-35B-A3B-FP8"
    }
  }
}
```

**Solo 1 de 7 agentes nativos tiene modelo configurado explícitamente.**

## 4. Tabla de Análisis Completo

| Agente Nativo | ¿En opencode.json? | ¿Modelo explícito? | ¿Archivo en agents/? | Estado |
|---------------|---------------------|---------------------|----------------------|--------|
| `plan` | ❌ No | ❌ No (hereda) | ❌ No | **PROBLEMA: inherit** |
| `build` | ❌ No | ❌ No (hereda) | ❌ No | **PROBLEMA: inherit** |
| `general` | ❌ No | ❌ No (hereda) | ❌ No | **PROBLEMA: inherit** |
| `explore` | ✅ Sí | ✅ `cefprovider/Qwen3.6-35B-A3B-FP8` | ❌ No | OK - configurado |
| `title` | ❌ No | ❌ No (hereda) | ❌ No | **PROBLEMA: inherit** |
| `summary` | ❌ No | ❌ No (hereda) | ❌ No | **PROBLEMA: inherit** |
| `compaction` | ❌ No | ❌ No (hereda) | ❌ No | **PROBLEMA: inherit** |

## 5. Resumen de Agentes con Problema de `inherit`

**5 de 7 agentes nativos NO tienen modelo configurado** y por tanto heredarán el modelo global (`model` o `small_model`) de forma implícita:

| Agente | Riesgo |
|--------|--------|
| `plan` | Alto - El agent de planificación usa modelo no especificado |
| `build` | Alto - El agent de build usa modelo no especificado |
| `general` | Alto - El agent general usa modelo no especificado |
| `title` | Medio - El agent de títulos usa modelo no especificado |
| `summary` | Medio - El agent de resúmenes usa modelo no especificado |

**Solo `explore` está explícitamente configurado** con `"model": "cefprovider/Qwen3.6-35B-A3B-FP8"`.

## 6. Verificación de Agentes Personalizados

Se verificó el directorio `/home/malka/.config/opencode/agents/` que contiene **196 archivos de agentes personalizados**.

**Búsqueda específica:** No se encontraron archivos personalizados para ninguno de los agentes nativos:
- No existe `*__plan.md`
- No existe `*__build.md`
- No existe `*__general.md`
- No existe `*__title.md`
- No existe `*__summary.md`
- No existe `*__compaction.md`

Los resultados de búsqueda `documentation-generation__reference-builder.md`, `general-mutation-testing.md`, `seo-analysis-monitoring__seo-authority-builder.md`, y `seo-content-creation__seo-content-planner.md` son archivos de agentes personalizados con nombres diferentes (no agentes nativos).

## 7. Recomendaciones

### Críticos (configurar inmediatamente)

1. **`plan`** - El agent de planificación es fundamental para el flujo de trabajo. Debería tener su modelo explícito configurado.

2. **`build`** - El agent de build ejecuta operaciones de construcción. Necesita modelo explícito para consistencia.

3. **`general`** - El agent general es el fallback por defecto. Si no tiene modelo explícito, el comportamiento de herencia puede ser impredecible.

### Importantes (configurar próximamente)

4. **`title`** - El agent de generación de títulos. Aunque es menos crítico, debería tener modelo explícito.

5. **`summary`** - El agent de resúmenes. Similar al anterior.

### Configuración Recomendada

```json
{
  "agent": {
    "explore": {
      "model": "cefprovider/Qwen3.6-35B-A3B-FP8"
    },
    "plan": {
      "model": "cefprovider/Qwen3.6-35B-A3B-FP8"
    },
    "build": {
      "model": "cefprovider/Qwen3.6-35B-A3B-FP8"
    },
    "general": {
      "model": "cefprovider/Qwen3.6-35B-A3B-FP8"
    },
    "title": {
      "model": "cefprovider/Qwen3.6-35B-A3B-FP8"
    },
    "summary": {
      "model": "cefprovider/Qwen3.6-35B-A3B-FP8"
    },
    "compaction": {
      "model": "cefprovider/Qwen3.6-35B-A3B-FP8"
    }
  }
}
```

## 8. Notas Técnicas

- El campo `model` en `AgentConfig` es de tipo `string | undefined`. Cuando es `undefined`, OpenCode debe determinar el modelo por otro medio (herencia del global, fallback, etc.).
- El mecanismo exacto de herencia (`inherit`) no está documentado en el esquema de tipos. Se necesita investigar el código fuente de OpenCode para entender qué ocurre cuando `model` es `undefined`.
- No se encontró ninguna referencia a `inherit` en el código fuente de OpenCode (solo `stdio: "inherit"` en procesos child).
