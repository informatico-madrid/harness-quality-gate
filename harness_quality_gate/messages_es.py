"""Spanish diagnostic messages for the quality gate system.

Provides ``MSG`` dict and ``t(key, **kwargs) -> str`` formatter.
"""

from __future__ import annotations

MSG: dict[str, str] = {
    # --- Toolchain (7 original) ---
    "TOOL_MISSING": "Herramienta requerida no encontrada: {tool}",
    "INFRA_OK": "Todas las herramientas están instaladas",
    "DETECT_SUCCESS": "Lenguaje detectado: {language} (confianza: {confidence:.1%})",
    "DETECT_HYBRID": "Repositorio híbrido detectado: {languages}",
    "LAYER_COMPLETE": "Capa {layer} completada: {result}",
    "LAYER_FAILED": "La capa {layer} no pasó: {count} hallazgos",
    "DOCTOR_WARN_XDEBUG_PCOV": "¡ADVERTENCIA! PCOV y Xdebug están ambos habilitados. Solo uno debe estar activo.",
    # --- Failure modes E1–E19 (design.md §Error Handling) ---
    # E1: No language detected (exit 2 UNSUPPORTED)
    "E1": "No se detectó Python ni PHP — añada `.quality-gate-lang`",
    # E2: PHP runtime missing (exit 3 INFRA_INCOMPLETE)
    "E2": "PHP 8.2+ requerido — instale via gestor de paquetes",
    # E3: Composer missing AND PHAR download fails (exit 5 INTERNAL_ERROR)
    "E3": "Composer no encontrado y descarga de PHAR falló: {tool}",
    # E4: Critical tool missing (exit 3 INFRA_INCOMPLETE)
    "E4": "Herramienta crítica faltante: {tool} — ejecute `install-tools`",
    # E5: Optional tool missing (continue + WARNING)
    "E5": "Paquete opcional ausente: {tool} (continuando)",
    # E6: Infection MSI < 100 (exit 1 FAIL)
    "E6": "MSI = {msi} (< 100) — {escaped} mutantes escapados",
    # E7: Infection covered MSI < 100 (exit 1 FAIL)
    "E7": "Covered MSI = {covered_msi} (< 100)",
    # E8: Allow-list violation (exit 1 FAIL)
    "E8": "Ignore sin justificación añadida en {file}:{line}",
    # E9: Config v1 schema (exit 4 CONFIG_INVALID)
    "E9": "Esquema v1 ya no soportado. v2.0.0 es la primera versión pública",
    # E10: Threshold lowered without --allow-ramp (exit 4 CONFIG_INVALID)
    "E10": "Umbral de MSI no puede bajar de 100 — revise política",
    # E11: PCOV unavailable, Xdebug present (continue + WARNING)
    "E11": "PCOV ausente — usando Xdebug (2.8× más lento)",
    # E12: PCOV + Xdebug both enabled (continue + WARNING)
    "E12": "PCOV y Xdebug ambos activos — desactive Xdebug para Infection",
    # E13: Pest without pest-plugin-mutate (continue + mutation_skipped)
    "E13": "Pest sin plugin de mutación — saltando Infection",
    # E14: PHAR SHA-256 mismatch (exit 5 INTERNAL_ERROR)
    "E14": "PHAR corrupto: {tool} — checksum no coincide",
    # E15: Detection cache stale — silent re-compute, no message emitted
    "E15": "",
    # E16: Hybrid run with --only — normal flow, no message emitted
    "E16": "",
    # E17: Subprocess timeout (exit 1 FAIL)
    "E17": "Herramienta {tool} excedió timeout {seconds}s",
    # E18: Schema validation fails on checkpoint write (exit 5 INTERNAL_ERROR)
    "E18": "Checkpoint v2 no valida — error interno",
    # E19: Internal exception / uncaught (exit 5 INTERNAL_ERROR)
    "E19": "Error interno: {exc}",
    # --- Legacy keys (used by existing code, preserved for backward compat) ---
    "err.lang.unsupported": "No se detectó un lenguaje soportado en {repo}",
    "err.tool.missing": "Herramienta requerida no encontrada: {tool}",
    "err.tool.timeout": "Tiempo de espera agotado para {tool} (>{timeout}s)",
    "err.tool.exit_nonzero": "{tool} exitó con código {code}: {stderr}",
    "err.parser.bad_json": "JSON inválido de {tool}: {error}",
    "err.parser.missing_file": "Archivo inexistente en output de {tool}: {path}",
    "err.schema.invalid": "Schemas inválido: {error}",
    "err.schema.missing": "Campo obligatorio faltante en schema: {field}",
    "err.config.v1": "Configuración v1 obsoleta: {path}. Actualice a v2.",
    "err.config.ramp": "min_msi={val} < 100 — permitido solo con --allow-ramp y override",
    "err.mutation.timeout": "Mutation timeout: {killed}/{total} en {sec}s",
    "err.mutation.msi": "MSI={msi:.1%} < mínimo={min:.1%}",
    "err.mutation.covered": "Covered MSI={msi:.1%} < mínimo={min:.1%}",
    "err.checkpoint.write": "Error escribiendo checkpoint: {path}",
    "err.checkpoint.schema": "Validación schema fallida: {error}",
    "err.discovery.tool": "No se encontró herramienta {tool} en {paths}",
    "err.cache.corrupt": "Cache corrupto: {path}",
    "err.concurrent.pool": "Error creando ThreadPoolExecutor: {error}",
    "err.framework.unknown": "Framework desconocido: {framework}",
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
