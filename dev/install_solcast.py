#!/usr/bin/env python3
"""Install pinned Solcast code into the dev HA volume before Home Assistant starts."""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import sys
import tempfile
from pathlib import Path, PurePosixPath
from urllib.request import urlopen
from zipfile import BadZipFile, ZipFile

VERSION = "v4.6.1"
URL = f"https://github.com/BJReplay/ha-solcast-solar/releases/download/{VERSION}/solcast_solar.zip"
SHA256 = "b46de7500775e7d159f10dd744d399e956e0cedcf481e7a320bed69f0cf67e03"
MAX_DOWNLOAD = 4 * 1024 * 1024
MAX_EXPANDED = 8 * 1024 * 1024


def install(config: Path = Path("/config")) -> None:
    """Install once atomically; preserve any existing integration directory or link."""
    components = config / "custom_components"
    destination = components / "solcast_solar"
    if os.path.lexists(destination):
        print("Solcast code already exists; preserving the installed integration.")
        return
    with urlopen(URL, timeout=30) as response:
        payload = response.read(MAX_DOWNLOAD + 1)
    if len(payload) > MAX_DOWNLOAD:
        raise ValueError("Solcast release exceeds the download size limit")
    if hashlib.sha256(payload).hexdigest() != SHA256:
        raise ValueError("Solcast release checksum does not match the pinned version")
    with ZipFile(io.BytesIO(payload)) as archive:
        members = archive.infolist()
        if len(members) > 256 or sum(item.file_size for item in members) > MAX_EXPANDED:
            raise ValueError("Solcast release exceeds the extracted size limit")
        paths = set()
        for item in members:
            filename = item.orig_filename
            path = PurePosixPath(filename)
            mode = stat.S_IFMT(item.external_attr >> 16)
            if (
                path.is_absolute() or not path.parts
                or any(part in ("", ".", "..") for part in filename.rstrip("/").split("/"))
                or "\\" in filename or ":" in filename
                or mode not in (0, stat.S_IFREG, stat.S_IFDIR)
                or path in paths
            ):
                raise ValueError("Solcast release contains an unsafe archive path or file")
            paths.add(path)
        if not {PurePosixPath(name) for name in ("manifest.json", "__init__.py", "config_flow.py")} <= paths:
            raise ValueError("Solcast release is missing required integration files")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("domain") != "solcast_solar" or manifest.get("version") != VERSION:
            raise ValueError("Solcast release manifest does not match the pinned integration")
        components.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".solcast-install-", dir=components) as temporary:
            staged = Path(temporary) / "solcast_solar"
            archive.extractall(staged)
            if os.path.lexists(destination):
                print("Solcast code appeared during installation; preserving it.")
                return
            staged.rename(destination)
    print(f"Solcast {VERSION} installed in the Home Assistant config volume.")


if __name__ == "__main__":
    try:
        install()
    except (OSError, ValueError, RuntimeError, BadZipFile):
        print(
            "Solcast installation failed: could not download, validate, or install the pinned release. "
            "Check network access, the release checksum, and config volume permissions.",
            file=sys.stderr,
        )
        sys.exit(1)
