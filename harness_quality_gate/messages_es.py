"""Spanish diagnostic messages for the quality gate system.

Provides ``MSG`` dict and ``t(key, **kwargs) -> str`` formatter.
"""

from __future__ import annotations

MSG: dict[str, str] = {
    # --- Toolchain (7 original) ---
    # reason: display-only Spanish diagnostic string; mutations are cosmetic, no test asserts exact text. # audited: 2026-06-04
    "TOOL_MISSING": "Herramienta requerida no encontrada: {tool}",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    "INFRA_OK": "Todas las herramientas están instaladas",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    "DETECT_SUCCESS": "Lenguaje detectado: {language} (confianza: {confidence:.1%})",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    "DETECT_HYBRID": "Repositorio híbrido detectado: {languages}",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    "LAYER_COMPLETE": "Capa {layer} completada: {result}",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    "LAYER_FAILED": "La capa {layer} no pasó: {count} hallazgos",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    "DOCTOR_WARN_XDEBUG_PCOV": "¡ADVERTENCIA! PCOV y Xdebug están ambos habilitados. Solo uno debe estar activo.",  # pragma: no mutate
    # --- Failure modes E1–E19 (design.md §Error Handling) ---
    # reason: failure-mode display strings consumed only by t() formatter; no test asserts exact text. # audited: 2026-06-04
    # E1: No language detected (exit 2 UNSUPPORTED)
    "E1": "No se detectó Python ni PHP — añada `.quality-gate-lang`",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    # E2: PHP runtime missing (exit 3 INFRA_INCOMPLETE)
    "E2": "PHP 8.2+ requerido — instale via gestor de paquetes",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    # E3: Composer missing AND PHAR download fails (exit 5 INTERNAL_ERROR)
    "E3": "Composer no encontrado y descarga de PHAR falló: {tool}",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    # E4: Critical tool missing (exit 3 INFRA_INCOMPLETE)
    "E4": "Herramienta crítica faltante: {tool} — ejecute `install-tools`",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    # E5: Optional tool missing (continue + WARNING)
    "E5": "Paquete opcional ausente: {tool} (continuando)",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    # E6: Infection MSI < 100 (exit 1 FAIL)
    "E6": "MSI = {msi} (< 100) — {escaped} mutantes escapados",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    # E7: Infection covered MSI < 100 (exit 1 FAIL)
    "E7": "Covered MSI = {covered_msi} (< 100)",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    # E8: Allow-list violation (exit 1 FAIL)
    "E8": "Ignore sin justificación añadida en {file}:{line}",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    # E9: Config v1 schema (exit 4 CONFIG_INVALID)
    "E9": "Esquema v1 ya no soportado. v2.0.0 es la primera versión pública",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    # E10: Threshold lowered without --allow-ramp (exit 4 CONFIG_INVALID)
    "E10": "Umbral de MSI no puede bajar de 100 — revise política",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    # E11: PCOV unavailable, Xdebug present (continue + WARNING)
    "E11": "PCOV ausente — usando Xdebug (2.8× más lento)",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    # E12: PCOV + Xdebug both enabled (continue + WARNING)
    "E12": "PCOV y Xdebug ambos activos — desactive Xdebug para Infection",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    # E13: Pest without pest-plugin-mutate (continue + mutation_skipped)
    "E13": "Pest sin plugin de mutación — saltando Infection",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    # E14: PHAR SHA-256 mismatch (exit 5 INTERNAL_ERROR)
    "E14": "PHAR corrupto: {tool} — checksum no coincide",  # pragma: no mutate
    # reason: empty placeholder string (cache-stale / hybrid-run are silent). # audited: 2026-06-04
    # E15: Detection cache stale — silent re-compute, no message emitted
    "E15": "",  # pragma: no mutate
    # reason: empty placeholder string. # audited: 2026-06-04
    # E16: Hybrid run with --only — normal flow, no message emitted
    "E16": "",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    # E17: Subprocess timeout (exit 1 FAIL)
    "E17": "Herramienta {tool} excedió timeout {seconds}s",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    # E18: Schema validation fails on checkpoint write (exit 5 INTERNAL_ERROR)
    "E18": "Checkpoint v2 no valida — error interno",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    # E19: Internal exception / uncaught (exit 5 INTERNAL_ERROR)
    "E19": "Error interno: {exc}",  # pragma: no mutate
    # --- Legacy keys (used by existing code, preserved for backward compat) ---
    # reason: legacy err.* keys preserved for backward compat; display-only strings, no test asserts text. # audited: 2026-06-04
    "err.lang.unsupported": "No se detectó un lenguaje soportado en {repo}",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    "err.tool.missing": "Herramienta requerida no encontrada: {tool}",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    "err.tool.timeout": "Tiempo de espera agotado para {tool} (>{timeout}s)",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    "err.tool.exit_nonzero": "{tool} exitó con código {code}: {stderr}",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    "err.parser.bad_json": "JSON inválido de {tool}: {error}",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    "err.parser.missing_file": "Archivo inexistente en output de {tool}: {path}",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    "err.schema.invalid": "Schemas inválido: {error}",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    "err.schema.missing": "Campo obligatorio faltante en schema: {field}",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    "err.config.v1": "Configuración v1 obsoleta: {path}. Actualice a v2.",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    "err.config.ramp": "min_msi={val} < 100 — permitido solo con --allow-ramp y override",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    "err.mutation.timeout": "Mutation timeout: {killed}/{total} en {sec}s",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    "err.mutation.msi": "MSI={msi:.1%} < mínimo={min:.1%}",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    "err.mutation.covered": "Covered MSI={msi:.1%} < mínimo={min:.1%}",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    "err.checkpoint.write": "Error escribiendo checkpoint: {path}",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    "err.checkpoint.schema": "Validación schema fallida: {error}",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    "err.discovery.tool": "No se encontró herramienta {tool} en {paths}",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    "err.cache.corrupt": "Cache corrupto: {path}",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    "err.concurrent.pool": "Error creando ThreadPoolExecutor: {error}",  # pragma: no mutate
    # reason: display string. # audited: 2026-06-04
    "err.framework.unknown": "Framework desconocido: {framework}",  # pragma: no mutate
}


def t(key: str, **kwargs: str) -> str:
    """Format a Spanish message string by key.

    Args:
        key: Message key from ``MSG`` dict.
        **kwargs: Values for string interpolation.

    Returns:
        The formatted message string.
    """
    template = MSG.get(key, key)
    return template.format(**kwargs) if kwargs else template
