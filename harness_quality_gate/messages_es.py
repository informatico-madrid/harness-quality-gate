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
    # --- Failure modes E1–E19 ---
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
