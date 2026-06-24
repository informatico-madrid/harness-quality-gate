

def test_parse_junit_assert_message_when_getroot_returns_none(tmp_path):
    """A parsed tree whose getroot() is None trips the exact assert message.

    Kills the XX-wrap / case mutations of the assertion text.
    """
    import pytest
    from unittest.mock import MagicMock, patch
    from pathlib import Path
    from harness_quality_gate.adapters.php.phpunit_adapter import PhpUnitAdapter

    fake_tree = MagicMock()
    fake_tree.getroot.return_value = None
    with patch(
        "harness_quality_gate.adapters.php.phpunit_adapter.DET.parse",
        return_value=fake_tree,
    ):
        with pytest.raises(AssertionError) as exc:
            PhpUnitAdapter._parse_junit_xml(Path("/whatever.xml"))
    assert str(exc.value) == "DET.parse succeeded but getroot returned None"
