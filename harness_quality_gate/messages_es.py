"""Spanish diagnostic messages for the quality gate system."""


MESSAGES = {
    "TOOL_MISSING": "Herramienta requerida no encontrada: {tool}",
    "INFRA_OK": "Todas las herramientas están instaladas",
    "DETECT_SUCCESS": "Lenguaje detectado: {language} (confianza: {confidence:.1%})",
    "DETECT_HYBRID": "Repositorio híbrido detectado: {languages}",
    "LAYER_COMPLETE": "Capa {layer} completada: {result}",
    "LAYER_FAILED": "La capa {layer} no pasó: {count} hallazgos",
    "DOCTOR_WARN_XDEBUG_PCOV": "¡ADVERTENCIA! PCOV y Xdebug están ambos habilitados. Solo uno debe estar activo.",
}


def msg(key: str, **kwargs) -> str:
    """Format a Spanish message string by key.

    Args:
        key: Message key from MESSAGES dict.
        **kwargs: Values for string interpolation.

    Returns:
        The formatted message string.
    """
    template = MESSAGES.get(key, key)
    return template.format(**kwargs)
