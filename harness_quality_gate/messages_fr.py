"""French diagnostic messages for the quality gate system."""


MESSAGES = {
    "TOOL_MISSING": "Outil requis introuvable : {tool}",  # pragma: no mutate
    "INFRA_OK": "Tous les outils sont installes",  # pragma: no mutate
    "DETECT_SUCCESS": "Langage detecte : {language} (confiance : {confidence:.1%})",  # pragma: no mutate
    "DETECT_HYBRID": "Depot hybride detecte : {languages}",  # pragma: no mutate
    "LAYER_COMPLETE": "Couche {layer} terminee : {result}",  # pragma: no mutate
    "LAYER_FAILED": "La couche {layer} a echoue : {count} resultats",  # pragma: no mutate
    "DOCTOR_WARN_XDEBUG_PCOV": "ATTENTION ! PCOV et Xdebug sont tous les deux actives.",  # pragma: no mutate
}


def msg(key: str, **kwargs) -> str:
    """Format a French message string by key.

    Args:
        key: Message key from MESSAGES dict.
        **kwargs: Values for string interpolation.

    Returns:
        The formatted message string.
    """
    template = MESSAGES.get(key, key)
    return template.format(**kwargs)
