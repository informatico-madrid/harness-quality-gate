"""Spanish diagnostic messages for the quality gate system.

Provides ``MSG`` dict and ``t(key, **kwargs) -> str`` formatter.
"""

from __future__ import annotations

MSG: dict[str, str] = {
    "TOOL_MISSING": "Herramienta requerida no encontrada: {tool}",
    "INFRA_OK": "Todas las herramientas están instaladas",
    "DETECT_SUCCESS": "Lenguaje detectado: {language} (confianza: {confidence:.1%})",
    "DETECT_HYBRID": "Repositorio híbrido detectado: {languages}",
    "LAYER_COMPLETE": "Capa {layer} completada: {result}",
    "LAYER_FAILED": "La capa {layer} no pasó: {count} hallazgos",
    "DOCTOR_WARN_XDEBUG_PCOV": "¡ADVERTENCIA! PCOV y Xdebug están ambos habilitados. Solo uno debe estar activo.",
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
    return template.format(**kwargs)
