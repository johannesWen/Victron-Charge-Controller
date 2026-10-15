"""Exercise the dev-only Solcast installer without downloading releases."""

import hashlib
import io
import json
from pathlib import Path
import stat
from unittest.mock import Mock
from zipfile import ZipFile, ZipInfo

import pytest

from dev import install_solcast as installer


def release(monkeypatch, extra_files=(), *, version=installer.VERSION):
    """Provide a small archive with the verified upstream root layout."""
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"domain": "solcast_solar", "version": version}))
        archive.writestr("__init__.py", "# test integration\n")
        archive.writestr("config_flow.py", "# test flow\n")
        for name, content in extra_files:
            if isinstance(name, str):
                member = ZipInfo()
                member.filename = name  # Preserve unsafe separators verbatim on Windows too.
                name = member
            archive.writestr(name, content)
    payload = buffer.getvalue()
    monkeypatch.setattr(installer, "SHA256", hashlib.sha256(payload).hexdigest())
    download = Mock(return_value=io.BytesIO(payload))
    monkeypatch.setattr(installer, "urlopen", download)
    return download


def test_installs_into_existing_config_volume_and_preserves_other_data(monkeypatch, tmp_path):
    other = tmp_path / "custom_components" / "victron_charge_control"
    other.mkdir(parents=True)
    (other / "__init__.py").write_text("user code")
    storage = tmp_path / ".storage"
    storage.mkdir()
    (storage / "config_entries").write_text("user settings")
    download = release(monkeypatch)

    installer.install(tmp_path)

    manifest = tmp_path / "custom_components" / "solcast_solar" / "manifest.json"
    assert json.loads(manifest.read_text())["version"] == installer.VERSION
    assert (other / "__init__.py").read_text() == "user code"
    assert (storage / "config_entries").read_text() == "user settings"
    download.assert_called_once_with(installer.URL, timeout=30)
    assert not list(manifest.parent.parent.glob(".solcast-install-*"))

    (manifest.parent / "__init__.py").write_text("edited code")
    installer.install(tmp_path)

    assert download.call_count == 1
    assert (manifest.parent / "__init__.py").read_text() == "edited code"


def test_existing_incomplete_install_is_preserved_without_network(monkeypatch, tmp_path):
    destination = tmp_path / "custom_components" / "solcast_solar"
    destination.mkdir(parents=True)
    (destination / "notes.txt").write_text("preserve")
    download = Mock(side_effect=AssertionError("must not download"))
    monkeypatch.setattr(installer, "urlopen", download)

    installer.install(tmp_path)

    assert (destination / "notes.txt").read_text() == "preserve"
    download.assert_not_called()


@pytest.mark.parametrize("invalid_path", ["../outside.py", "/outside.py", "a/../../outside.py", "a\\outside.py", "C:/outside.py", "a//b.py"])
def test_rejects_unsafe_archive_paths(monkeypatch, tmp_path, invalid_path):
    release(monkeypatch, [(invalid_path, "bad")])

    with pytest.raises(ValueError, match="unsafe archive"):
        installer.install(tmp_path)

    assert not (tmp_path / "custom_components").exists()


def test_rejects_archive_symlinks(monkeypatch, tmp_path):
    link = ZipInfo("link.py")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    release(monkeypatch, [(link, "../outside.py")])

    with pytest.raises(ValueError, match="unsafe archive"):
        installer.install(tmp_path)


def test_rejects_wrong_checksum_before_installing(monkeypatch, tmp_path):
    release(monkeypatch)
    monkeypatch.setattr(installer, "SHA256", "wrong")

    with pytest.raises(ValueError, match="checksum"):
        installer.install(tmp_path)

    assert not (tmp_path / "custom_components").exists()


def test_rejects_wrong_release_manifest(monkeypatch, tmp_path):
    release(monkeypatch, version="v0.0.0")

    with pytest.raises(ValueError, match="manifest"):
        installer.install(tmp_path)


@pytest.mark.parametrize("limit", ["MAX_DOWNLOAD", "MAX_EXPANDED"])
def test_rejects_oversized_release(monkeypatch, tmp_path, limit):
    release(monkeypatch)
    monkeypatch.setattr(installer, limit, 1)

    with pytest.raises(ValueError, match="size limit"):
        installer.install(tmp_path)


def test_failed_extraction_never_leaves_partial_integration(monkeypatch, tmp_path):
    release(monkeypatch)

    def failed_extract(archive, destination):
        Path(destination).mkdir()
        (Path(destination) / "__init__.py").write_text("partial")
        raise OSError("disk full")

    monkeypatch.setattr(ZipFile, "extractall", failed_extract)
    with pytest.raises(OSError, match="disk full"):
        installer.install(tmp_path)

    assert not (tmp_path / "custom_components" / "solcast_solar").exists()
    assert not list((tmp_path / "custom_components").iterdir())
