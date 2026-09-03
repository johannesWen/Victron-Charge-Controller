"""Tests for the GitHub release packaging safeguard."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

SCRIPT_PATH = Path(__file__).parents[1] / ".github" / "scripts" / "package_release.py"


def _load_package_module() -> ModuleType:
    """Load the release helper from its non-package ``.github`` directory."""
    spec = importlib.util.spec_from_file_location("package_release", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load release helper from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


package_module = _load_package_module()
ReleasePackageError = package_module.ReleasePackageError


def _create_integration(
    tmp_path: Path,
    *,
    version: str = "2.0.2",
    card_content: str | None = None,
) -> Path:
    """Create a minimal integration directory for packaging tests."""
    integration_dir = tmp_path / "custom_components" / "victron_charge_control"
    card_path = integration_dir / "static" / "victron-charge-controller-card.js"
    card_path.parent.mkdir(parents=True)
    manifest = {"domain": "victron_charge_control", "version": version}
    (integration_dir / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    card_path.write_text(
        card_content if card_content is not None else f"console.info('{version}');",
        encoding="utf-8",
    )
    (integration_dir / "__init__.py").write_text("", encoding="utf-8")
    return integration_dir


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("v2.0.2", "2.0.2"),
        ("2.0.2", "2.0.2"),
        ("v2.0.2-rc.0", "2.0.2"),
        ("v2.0.2-rc.12", "2.0.2"),
    ],
)
def test_release_version_from_tag(tag: str, expected: str) -> None:
    """Stable and RC tags resolve to the intended manifest version."""
    assert package_module.release_version_from_tag(tag) == expected


def test_release_version_from_tag_rejects_empty_version() -> None:
    """An empty tag cannot produce a release version."""
    with pytest.raises(ReleasePackageError, match="must contain a version"):
        package_module.release_version_from_tag("v")


def test_validate_release_version_rejects_mismatch() -> None:
    """A tag cannot publish an archive containing another version."""
    with pytest.raises(ReleasePackageError, match="tag and manifest version differ"):
        package_module.validate_release_version("v2.0.2", "2.0.1")


@pytest.mark.parametrize("card_content", [None, ""])
def test_package_release_rejects_missing_or_empty_card(
    tmp_path: Path, card_content: str | None
) -> None:
    """Packaging fails when the frontend build is absent or empty."""
    integration_dir = _create_integration(
        tmp_path, card_content=card_content or "placeholder"
    )
    card_path = integration_dir / "static" / "victron-charge-controller-card.js"
    if card_content is None:
        card_path.unlink()
    else:
        card_path.write_text("", encoding="utf-8")

    with pytest.raises(ReleasePackageError, match="Built Lovelace card"):
        package_module.package_release(
            repository_root=tmp_path,
            archive_path=tmp_path / "release.zip",
            tag="v2.0.2",
        )


def test_package_release_creates_rooted_valid_archive(tmp_path: Path) -> None:
    """The complete safeguard creates the layout expected by HACS."""
    _create_integration(tmp_path)
    archive_path = tmp_path / "victron_charge_control.zip"

    package_module.package_release(tmp_path, archive_path, "v2.0.2-rc.0")

    with ZipFile(archive_path) as archive:
        assert "manifest.json" in archive.namelist()
        assert "static/victron-charge-controller-card.js" in archive.namelist()
        assert not any(
            name.startswith("victron_charge_control/") for name in archive.namelist()
        )


def test_validate_release_archive_rejects_nested_required_paths(tmp_path: Path) -> None:
    """A ZIP wrapping the integration directory is rejected."""
    integration_dir = _create_integration(tmp_path)
    archive_path = tmp_path / "nested.zip"
    with ZipFile(archive_path, mode="w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("victron_charge_control/manifest.json", '{"version":"2.0.2"}')
        archive.writestr(
            "victron_charge_control/static/victron-charge-controller-card.js",
            "2.0.2",
        )

    with pytest.raises(ReleasePackageError, match="manifest.json.*exactly once"):
        package_module.validate_release_archive(archive_path, integration_dir, "2.0.2")


def test_validate_release_archive_rejects_embedded_manifest_mismatch(
    tmp_path: Path,
) -> None:
    """The archived manifest must be byte-for-byte identical to the source."""
    integration_dir = _create_integration(tmp_path)
    archive_path = tmp_path / "mismatch.zip"
    card_data = (
        integration_dir / "static/victron-charge-controller-card.js"
    ).read_bytes()
    with ZipFile(archive_path, mode="w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", '{"version":"2.0.1"}')
        archive.writestr("static/victron-charge-controller-card.js", card_data)

    with pytest.raises(ReleasePackageError, match="does not match the source manifest"):
        package_module.validate_release_archive(archive_path, integration_dir, "2.0.2")


def test_validate_release_archive_rejects_card_without_version(tmp_path: Path) -> None:
    """The built frontend must expose the integration version for diagnostics."""
    integration_dir = _create_integration(
        tmp_path, card_content="console.info('card');"
    )
    archive_path = tmp_path / "missing-version.zip"
    package_module.create_release_archive(integration_dir, archive_path)

    with pytest.raises(ReleasePackageError, match="does not contain version"):
        package_module.validate_release_archive(archive_path, integration_dir, "2.0.2")
