"""Unit tests for the Spanish diagnostic messages registry.

Covers MSG dict completeness (E1–E19), t() formatting with kwargs,
fallback for unknown keys, and legacy key resolution.
"""

from __future__ import annotations

from harness_quality_gate.messages_es import MSG, t


# ---------------------------------------------------------------------------
# MSG dict completeness
# ---------------------------------------------------------------------------


def test_all_e1_e19_keys_present() -> None:
    """All 19 failure-mode keys E1…E19 exist in MSG."""
    for i in range(1, 20):
        assert f"E{i}" in MSG, f"Missing MSG key E{i}"


def test_legacy_keys_present() -> None:
    """Known legacy keys exist for backward compatibility."""
    legacy = [
        "err.lang.unsupported",
        "err.tool.missing",
        "err.tool.timeout",
        "err.tool.exit_nonzero",
        "err.parser.bad_json",
        "err.parser.missing_file",
        "err.schema.invalid",
        "err.schema.missing",
        "err.config.v1",
        "err.config.ramp",
        "err.mutation.timeout",
        "err.mutation.msi",
        "err.mutation.covered",
        "err.checkpoint.write",
        "err.checkpoint.schema",
        "err.discovery.tool",
        "err.cache.corrupt",
        "err.concurrent.pool",
        "err.framework.unknown",
    ]
    for key in legacy:
        assert key in MSG, f"Missing legacy key: {key}"


def test_e15_e16_are_empty() -> None:
    """E15 and E16 are intentionally empty (silent messages)."""
    assert MSG["E15"] == ""
    assert MSG["E16"] == ""


def test_msg_key_count() -> None:
    """MSG has at least 20 keys (E1-E19 + TOOL_MISSING + INFRA_OK + DETECT_* + E17-E19 + legacy)."""
    assert len(MSG) >= 35


# ---------------------------------------------------------------------------
# t() — formatting
# ---------------------------------------------------------------------------


def test_t_basic_lookup() -> None:
    """Known key → template string without formatting."""
    result = t("TOOL_MISSING")
    assert result == "Herramienta requerida no encontrada: {tool}"


def test_t_with_kwargs() -> None:
    """Known key + kwargs → formatted string."""
    result = t("TOOL_MISSING", tool="ruff")
    assert result == "Herramienta requerida no encontrada: ruff"


def test_t_e6_mutation_message() -> None:
    """E6 MSI message with multiple kwargs."""
    result = t("E6", msi="45.2%", escaped="3")
    assert result == "MSI = 45.2% (< 100) — 3 mutantes escapados"


def test_t_detect_success() -> None:
    """DETECT_SUCCESS with language and confidence."""
    result = t("DETECT_SUCCESS", language="python", confidence=0.95)
    assert result == "Lenguaje detectado: python (confianza: 95.0%)"


def test_t_unknown_key_fallback() -> None:
    """Unknown key → key itself returned unchanged."""
    assert t("NONEXISTENT_KEY") == "NONEXISTENT_KEY"


def test_t_empty_template_with_no_kwargs() -> None:
    """Empty template (E15/E16) returns empty string."""
    assert t("E15") == ""
    assert t("E16") == ""


def test_t_err_config_v1() -> None:
    """err.config.v1 key with path kwarg."""
    result = t("err.config.v1", path="/tmp/.quality-gate.yaml")
    assert "tmp" in result
    assert "v2" in result


def test_t_err_config_ramp() -> None:
    """err.config.ramp with min_msi value."""
    result = t("err.config.ramp", val=90.0)
    assert "90" in result


# ---------------------------------------------------------------------------
# Catalog snapshot — the messages are USER CONTRACT (guide §5 Tipo H):
# any wording change must be deliberate and updated here in the same commit.
# Kills every key/value string mutation in the catalog.
# ---------------------------------------------------------------------------

EXPECTED_MSG = {
    'TOOL_MISSING': 'Herramienta requerida no encontrada: {tool}',
    'INFRA_OK': 'Todas las herramientas están instaladas',
    'DETECT_SUCCESS': 'Lenguaje detectado: {language} (confianza: {confidence:.1%})',
    'DETECT_HYBRID': 'Repositorio híbrido detectado: {languages}',
    'LAYER_COMPLETE': 'Capa {layer} completada: {result}',
    'LAYER_FAILED': 'La capa {layer} no pasó: {count} hallazgos',
    'DOCTOR_WARN_XDEBUG_PCOV': '¡ADVERTENCIA! PCOV y Xdebug están ambos habilitados. Solo uno debe estar activo.',
    'E1': 'No se detectó Python ni PHP — añada `.quality-gate-lang`',
    'E2': 'PHP 8.2+ requerido — instale via gestor de paquetes',
    'E3': 'Composer no encontrado y descarga de PHAR falló: {tool}',
    'E4': 'Herramienta crítica faltante: {tool} — ejecute `install-tools`',
    'E5': 'Paquete opcional ausente: {tool} (continuando)',
    'E6': 'MSI = {msi} (< 100) — {escaped} mutantes escapados',
    'E7': 'Covered MSI = {covered_msi} (< 100)',
    'E8': 'Ignore sin justificación añadida en {file}:{line}',
    'E9': 'Esquema v1 ya no soportado. v2.0.0 es la primera versión pública',
    'E10': 'Umbral de MSI no puede bajar de 100 — revise política',
    'E11': 'PCOV ausente — usando Xdebug (2.8× más lento)',
    'E12': 'PCOV y Xdebug ambos activos — desactive Xdebug para Infection',
    'E13': 'Pest sin plugin de mutación — saltando Infection',
    'E14': 'PHAR corrupto: {tool} — checksum no coincide',
    'E15': '',
    'E16': '',
    'E17': 'Herramienta {tool} excedió timeout {seconds}s',
    'E18': 'Checkpoint v2 no valida — error interno',
    'E19': 'Error interno: {exc}',
    'err.lang.unsupported': 'No se detectó un lenguaje soportado en {repo}',
    'err.tool.missing': 'Herramienta requerida no encontrada: {tool}',
    'err.tool.timeout': 'Tiempo de espera agotado para {tool} (>{timeout}s)',
    'err.tool.exit_nonzero': '{tool} exitó con código {code}: {stderr}',
    'err.parser.bad_json': 'JSON inválido de {tool}: {error}',
    'err.parser.missing_file': 'Archivo inexistente en output de {tool}: {path}',
    'err.schema.invalid': 'Schemas inválido: {error}',
    'err.schema.missing': 'Campo obligatorio faltante en schema: {field}',
    'err.config.v1': 'Configuración v1 obsoleta: {path}. Actualice a v2.',
    'err.config.ramp': 'min_msi={val} < 100 — permitido solo con --allow-ramp y override',
    'err.mutation.timeout': 'Mutation timeout: {killed}/{total} en {sec}s',
    'err.mutation.msi': 'MSI={msi:.1%} < mínimo={min:.1%}',
    'err.mutation.covered': 'Covered MSI={msi:.1%} < mínimo={min:.1%}',
    'err.checkpoint.write': 'Error escribiendo checkpoint: {path}',
    'err.checkpoint.schema': 'Validación schema fallida: {error}',
    'err.discovery.tool': 'No se encontró herramienta {tool} en {paths}',
    'err.cache.corrupt': 'Cache corrupto: {path}',
    'err.concurrent.pool': 'Error creando ThreadPoolExecutor: {error}',
    'err.framework.unknown': 'Framework desconocido: {framework}',
}

def test_msg_catalog_snapshot_exact() -> None:
    assert MSG == EXPECTED_MSG
