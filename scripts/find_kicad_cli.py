#!/usr/bin/env python3
"""Locate a KiCad CLI executable on the current system or the Windows side of WSL."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def is_wsl_environment() -> bool:
    if os.name == "nt":
        return False
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    proc_version = Path("/proc/version")
    if not proc_version.exists():
        return False
    try:
        content = proc_version.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    lowered = content.lower()
    return "microsoft" in lowered or "wsl" in lowered


def find_windows_kicad_cli_candidates() -> list[Path]:
    candidates: list[Path] = []
    root_candidates: list[Path] = []

    for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
        value = os.environ.get(env_name)
        if value:
            root_candidates.append(Path(value) / "KiCad")

    if is_wsl_environment():
        for prefix in (Path("/mnt/c"), Path("/mnt/d")):
            root_candidates.extend([
                prefix / "Program Files" / "KiCad",
                prefix / "Program Files (x86)" / "KiCad",
            ])

    for root in root_candidates:
        if not root.exists() or not root.is_dir():
            continue

        direct_bin_dir = root / "bin"
        for executable_name in ("kicad-cli.exe", "kicad-cli-nightly.exe"):
            candidate = direct_bin_dir / executable_name
            if candidate.exists():
                candidates.append(candidate)

        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            bin_dir = child / "bin"
            for executable_name in ("kicad-cli.exe", "kicad-cli-nightly.exe"):
                candidate = bin_dir / executable_name
                if candidate.exists():
                    candidates.append(candidate)

    return sorted({candidate.resolve() for candidate in candidates})


def find_kicad_cli() -> str | None:
    env_cli = os.environ.get("KICAD_CLI")
    if env_cli:
        path = Path(env_cli)
        if path.exists() or shutil.which(env_cli):
            return str(path if path.exists() else shutil.which(env_cli))

    path_from_env = shutil.which("kicad-cli")
    if path_from_env:
        return path_from_env

    nightly = shutil.which("kicad-cli-nightly")
    if nightly:
        return nightly

    for candidate in find_windows_kicad_cli_candidates():
        return str(candidate)

    return None


def main() -> int:
    cli_path = find_kicad_cli()
    if cli_path is None:
        print("kicad-cli not found", file=sys.stderr)
        return 1
    print(cli_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
