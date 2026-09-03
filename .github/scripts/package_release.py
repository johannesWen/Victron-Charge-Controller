"""Build and validate the HACS release archive."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

INTEGRATION_RELATIVE_PATH = Path("custom_components/victron_charge_control")
MANIFEST_FILENAME = "manifest.json"
CARD_RELATIVE_PATH = PurePosixPath("static/victron-charge-controller-card.js")
DEFAULT_ARCHIVE_FILENAME = "victron_charge_control.zip"
RC_SUFFIX_PATTERN = re.compile(r"-rc\.\d+$")


class ReleasePackageError(RuntimeError):
    """Raised when a release archive fails validation."""


def release_version_from_tag(tag: str) -> str:
    """Return the manifest version expected for a release tag.

    A leading ``v`` is optional. Release-candidate suffixes are removed because
    this repository intentionally uses the base integration version for all
    candidates of a release.

    Args:
        tag: Git tag or release name, such as ``v2.0.2`` or ``v2.0.2-rc.0``.

    Returns:
        The base version that must be present in ``manifest.json``.

    Raises:
        ReleasePackageError: If the tag is empty or only contains ``v``.
    """
    normalized_tag = tag.strip().removeprefix("v")

    version = RC_SUFFIX_PATTERN.sub("", normalized_tag)
    if not version:
        raise ReleasePackageError("Release tag must contain a version")
    return version


def load_manifest_version(manifest_path: Path) -> str:
    """Load and validate the integration version from a manifest.

    Args:
        manifest_path: Path to the Home Assistant integration manifest.

    Returns:
        The non-empty manifest version.

    Raises:
        ReleasePackageError: If the manifest is missing, invalid, or has no
            usable version.
    """
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ReleasePackageError(f"Manifest not found: {manifest_path}") from error
    except json.JSONDecodeError as error:
        raise ReleasePackageError(
            f"Manifest is not valid JSON: {manifest_path}"
        ) from error

    if not isinstance(manifest, dict):
        raise ReleasePackageError(
            f"Manifest must contain a JSON object: {manifest_path}"
        )

    version = manifest.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ReleasePackageError("Manifest version must be a non-empty string")
    return version.strip()


def validate_release_version(tag: str, manifest_version: str) -> None:
    """Require a release tag to match the integration manifest version.

    Args:
        tag: Git tag or release name.
        manifest_version: Version read from the integration manifest.

    Raises:
        ReleasePackageError: If the versions differ.
    """
    expected_version = release_version_from_tag(tag)
    if expected_version != manifest_version:
        raise ReleasePackageError(
            "Release tag and manifest version differ: "
            f"tag {tag!r} expects {expected_version!r}, "
            f"manifest contains {manifest_version!r}"
        )


def require_non_empty_file(path: Path, description: str) -> None:
    """Require a regular file with at least one byte.

    Args:
        path: File to validate.
        description: Human-readable name included in error messages.

    Raises:
        ReleasePackageError: If the file is missing or empty.
    """
    if not path.is_file():
        raise ReleasePackageError(f"{description} not found: {path}")
    if path.stat().st_size == 0:
        raise ReleasePackageError(f"{description} is empty: {path}")


def create_release_archive(integration_dir: Path, archive_path: Path) -> None:
    """Create a ZIP whose root contains the integration files.

    Args:
        integration_dir: Directory containing the integration manifest.
        archive_path: ZIP file to create or replace.

    Raises:
        ReleasePackageError: If the integration directory is missing or has no
            files to package.
    """
    if not integration_dir.is_dir():
        raise ReleasePackageError(f"Integration directory not found: {integration_dir}")

    files = sorted(path for path in integration_dir.rglob("*") if path.is_file())
    if not files:
        raise ReleasePackageError(f"Integration directory is empty: {integration_dir}")

    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.unlink(missing_ok=True)
    with ZipFile(archive_path, mode="w", compression=ZIP_DEFLATED) as archive:
        for source_path in files:
            archive.write(
                source_path, source_path.relative_to(integration_dir).as_posix()
            )


def validate_release_archive(
    archive_path: Path,
    integration_dir: Path,
    manifest_version: str,
) -> None:
    """Validate the contents and embedded version of a release ZIP.

    Args:
        archive_path: Archive to inspect.
        integration_dir: Source integration directory used for comparison.
        manifest_version: Expected integration and frontend version.

    Raises:
        ReleasePackageError: If required files, paths, contents, or versions
            are invalid.
    """
    source_manifest_path = integration_dir / MANIFEST_FILENAME
    source_card_path = integration_dir / Path(CARD_RELATIVE_PATH.as_posix())
    source_manifest = source_manifest_path.read_bytes()
    source_card = source_card_path.read_bytes()

    try:
        with ZipFile(archive_path, mode="r") as archive:
            names = archive.namelist()
            for name in names:
                member_path = PurePosixPath(name)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise ReleasePackageError(f"Unsafe archive path: {name}")

            required_names = (MANIFEST_FILENAME, CARD_RELATIVE_PATH.as_posix())
            for required_name in required_names:
                if names.count(required_name) != 1:
                    raise ReleasePackageError(
                        f"Archive must contain {required_name!r} exactly once at its root"
                    )

            manifest_info = archive.getinfo(MANIFEST_FILENAME)
            card_info = archive.getinfo(CARD_RELATIVE_PATH.as_posix())
            if manifest_info.file_size == 0:
                raise ReleasePackageError("Archived manifest is empty")
            if card_info.file_size == 0:
                raise ReleasePackageError("Archived Lovelace card is empty")

            archived_manifest = archive.read(MANIFEST_FILENAME)
            archived_card = archive.read(CARD_RELATIVE_PATH.as_posix())
    except FileNotFoundError as error:
        raise ReleasePackageError(
            f"Release archive not found: {archive_path}"
        ) from error
    except BadZipFile as error:
        raise ReleasePackageError(
            f"Release archive is not a valid ZIP: {archive_path}"
        ) from error

    if archived_manifest != source_manifest:
        raise ReleasePackageError(
            "Archived manifest does not match the source manifest"
        )
    if archived_card != source_card:
        raise ReleasePackageError(
            "Archived Lovelace card does not match the built card"
        )

    archived_version = load_manifest_version_from_bytes(archived_manifest)
    if archived_version != manifest_version:
        raise ReleasePackageError(
            "Archived manifest version differs from the source manifest: "
            f"{archived_version!r} != {manifest_version!r}"
        )
    if manifest_version.encode("utf-8") not in archived_card:
        raise ReleasePackageError(
            f"Bundled Lovelace card does not contain version {manifest_version!r}"
        )


def load_manifest_version_from_bytes(manifest_data: bytes) -> str:
    """Return a validated version from archived manifest bytes.

    Args:
        manifest_data: UTF-8 encoded manifest JSON.

    Returns:
        The non-empty manifest version.

    Raises:
        ReleasePackageError: If the archived manifest is invalid.
    """
    try:
        manifest = json.loads(manifest_data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReleasePackageError(
            "Archived manifest is not valid UTF-8 JSON"
        ) from error

    if not isinstance(manifest, dict):
        raise ReleasePackageError("Archived manifest must contain a JSON object")
    version = manifest.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ReleasePackageError(
            "Archived manifest version must be a non-empty string"
        )
    return version.strip()


def package_release(repository_root: Path, archive_path: Path, tag: str) -> None:
    """Build and validate a release archive from a repository checkout.

    Args:
        repository_root: Root of the checked-out repository.
        archive_path: ZIP file to create.
        tag: Release tag whose version must match the manifest.
    """
    integration_dir = repository_root / INTEGRATION_RELATIVE_PATH
    manifest_path = integration_dir / MANIFEST_FILENAME
    card_path = integration_dir / Path(CARD_RELATIVE_PATH.as_posix())

    manifest_version = load_manifest_version(manifest_path)
    validate_release_version(tag, manifest_version)
    require_non_empty_file(card_path, "Built Lovelace card")
    create_release_archive(integration_dir, archive_path)
    validate_release_archive(archive_path, integration_dir, manifest_version)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    repository_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Create and validate the Victron Charge Control release ZIP."
    )
    parser.add_argument(
        "--tag", required=True, help="Release tag, for example v2.0.2-rc.0"
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=repository_root,
        help="Repository root; defaults to the checkout containing this script",
    )
    parser.add_argument(
        "--archive",
        type=Path,
        default=repository_root / DEFAULT_ARCHIVE_FILENAME,
        help="Output ZIP path",
    )
    return parser.parse_args()


def main() -> int:
    """Run release packaging and report validation failures to GitHub Actions."""
    args = parse_args()
    try:
        package_release(
            repository_root=args.repository_root.resolve(),
            archive_path=args.archive.resolve(),
            tag=args.tag,
        )
    except (OSError, ReleasePackageError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1

    print(f"Release archive validated: {args.archive.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
