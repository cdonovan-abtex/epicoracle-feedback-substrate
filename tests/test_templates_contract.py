from __future__ import annotations

from pathlib import Path


def test_agent_dispatch_template_disables_ghcr_by_default() -> None:
    text = Path("templates/agent-dispatch.yml").read_text()
    assert "GHCR_SANDBOX_ENABLED" in text
    assert "GHCR_PACKAGE_NAME" in text
    assert "SATELLITE_SLUG" not in text
    assert "repository: abtex/epicoracle-feedback-substrate" in text


def test_build_template_is_disabled_artifact_and_uses_current_owner() -> None:
    text = Path("templates/build-ghcr-image.yml").read_text()
    assert "workflow_dispatch" in text
    assert "GHCR_PUBLISHING_ENABLED" in text
    assert "ghcr.io/abtex/" in text
    assert "ghcr.io/cdonovan-abtex" not in text
    assert "disabled artifact" in text
