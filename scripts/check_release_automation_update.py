#!/usr/bin/env python3
"""Check whether a newer module release is available for a target repository."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_METADATA_FILE = ".kicad-release-automation-version.json"
DEFAULT_API_BASE = "https://api.github.com"
WINDOWS_DRIVE_PATH_PATTERN = re.compile(r"^[A-Za-z]:[\\/]")
UNC_PATH_PATTERN = re.compile(r"^[\\/]{2}[^\\/]+[\\/][^\\/]+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check whether a newer KiCad release automation module version is available."
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=Path(DEFAULT_METADATA_FILE),
        help=(
            "Path to the installed module metadata JSON file "
            f"(default: {DEFAULT_METADATA_FILE})."
        ),
    )
    parser.add_argument(
        "--repo",
        type=str,
        help="Override the GitHub repository slug to query (owner/repo).",
    )
    parser.add_argument(
        "--api-base-url",
        type=str,
        default=DEFAULT_API_BASE,
        help="GitHub API base URL (default: https://api.github.com).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify managed file versions and SHA256 checksums from metadata.",
    )
    return parser.parse_args()


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


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


def windows_to_wsl_path(path_value: str) -> str:
    drive = path_value[0].lower()
    remainder = path_value[2:].replace("\\", "/")
    if not remainder.startswith("/"):
        remainder = f"/{remainder}"
    return f"/mnt/{drive}{remainder}"


def normalize_user_path(raw_path: str, context: str) -> Path:
    path_text = raw_path.strip()
    if not path_text:
        fail(f"Path for {context} must be a non-empty string.")

    if UNC_PATH_PATTERN.match(path_text):
        fail(
            f"UNC paths are not supported for {context}: {path_text}. "
            "Mount the network share and use the mounted path instead."
        )

    if WINDOWS_DRIVE_PATH_PATTERN.match(path_text):
        if os.name == "nt":
            candidate = Path(path_text)
        elif is_wsl_environment():
            candidate = Path(windows_to_wsl_path(path_text))
        else:
            fail(
                f"Windows-style path is not supported on this platform for {context}: "
                f"{path_text}"
            )
    else:
        candidate = Path(path_text.replace("\\", "/"))

    return candidate.resolve()


def load_metadata(metadata_path: Path) -> dict[str, Any]:
    resolved_path = normalize_user_path(str(metadata_path), context="--metadata")
    if not resolved_path.exists():
        fail(
            f"Installed module metadata file not found: {resolved_path}. "
            "Re-run install.sh from the module repository first."
        )

    with resolved_path.open("r", encoding="utf-8") as handle:
        metadata = json.load(handle)

    if not isinstance(metadata, dict):
        fail(f"Metadata root must be a JSON object: {resolved_path}")

    schema_version = metadata.get("schema_version", 1)
    if isinstance(schema_version, int):
        metadata["schema_version"] = schema_version
    else:
        metadata["schema_version"] = 1

    installed_version = metadata.get("installed_version")
    if not isinstance(installed_version, str) or not installed_version.strip():
        module_version = metadata.get("module_version")
        if isinstance(module_version, str) and module_version.strip():
            metadata["installed_version"] = module_version.strip()
        else:
            metadata["installed_version"] = "unknown"

    managed_files = metadata.get("managed_files")
    if managed_files is None:
        metadata["managed_files"] = {}
    elif not isinstance(managed_files, dict):
        fail("Metadata field 'managed_files' must be a JSON object when present.")

    metadata["_path"] = str(resolved_path)
    return metadata


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_managed_files(metadata: dict[str, Any]) -> dict[str, Any]:
    metadata_path = Path(metadata["_path"])
    base_dir = metadata_path.parent
    managed_files = metadata.get("managed_files", {})

    result: dict[str, Any] = {
        "metadata_path": str(metadata_path),
        "schema_version": metadata.get("schema_version", 1),
        "module_version": metadata.get("installed_version", "unknown"),
        "verified": False,
        "valid": False,
        "files": [],
        "errors": [],
    }

    if not managed_files:
        result["errors"].append(
            "Metadata does not include managed_files. Re-run install.sh to upgrade metadata."
        )
        return result

    result["verified"] = True
    valid = True
    for relative_path, details in managed_files.items():
        if not isinstance(details, dict):
            valid = False
            result["errors"].append(
                f"Metadata entry for '{relative_path}' must be a JSON object."
            )
            continue

        file_path = (base_dir / relative_path).resolve()
        expected_hash = details.get("sha256")
        expected_version = details.get("version")

        file_result: dict[str, Any] = {
            "path": relative_path,
            "resolved_path": str(file_path),
            "expected_version": expected_version,
            "expected_sha256": expected_hash,
            "exists": file_path.exists(),
            "version_match": None,
            "sha256_match": None,
            "actual_sha256": None,
            "valid": False,
        }

        if not file_path.exists():
            valid = False
            result["errors"].append(f"Managed file missing: {relative_path}")
            result["files"].append(file_result)
            continue

        if file_path.is_dir():
            valid = False
            result["errors"].append(f"Managed path is not a file: {relative_path}")
            result["files"].append(file_result)
            continue

        actual_hash = hash_file(file_path)
        file_result["actual_sha256"] = actual_hash

        if isinstance(expected_hash, str) and expected_hash.strip():
            hash_match = actual_hash == expected_hash.strip()
            file_result["sha256_match"] = hash_match
            if not hash_match:
                valid = False
                result["errors"].append(f"SHA256 mismatch: {relative_path}")
        else:
            valid = False
            result["errors"].append(f"Missing expected SHA256 in metadata: {relative_path}")

        if isinstance(expected_version, str) and expected_version.strip():
            version_match = expected_version.strip() == metadata.get("installed_version")
            file_result["version_match"] = version_match
            if not version_match:
                valid = False
                result["errors"].append(
                    f"Version mismatch in metadata: {relative_path}"
                )
        else:
            valid = False
            result["errors"].append(f"Missing expected version in metadata: {relative_path}")

        file_result["valid"] = bool(file_result["sha256_match"]) and bool(
            file_result["version_match"]
        )
        result["files"].append(file_result)

    result["valid"] = valid
    return result


def get_repo_slug(metadata: dict[str, Any], explicit_repo: str | None) -> str:
    if explicit_repo:
        return explicit_repo

    repo_slug = metadata.get("module_repo")
    if not isinstance(repo_slug, str) or not repo_slug.strip():
        fail(
            "Module repository slug is missing from metadata. "
            "Re-run install.sh from a git checkout or pass --repo owner/repo."
        )

    return repo_slug.strip()


def fetch_latest_release(repo_slug: str, api_base_url: str) -> dict[str, Any]:
    url = f"{api_base_url.rstrip('/')}/repos/{repo_slug}/releases/latest"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "kicad-release-automation-update-check",
        },
    )

    try:
        with urllib.request.urlopen(request) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        fail(f"GitHub API request failed ({error.code}) for {url}")
    except urllib.error.URLError as error:
        fail(f"Could not reach GitHub API at {url}: {error.reason}")

    if not isinstance(payload, dict):
        fail(f"Unexpected GitHub API response from {url}")

    return payload


def parse_version(tag: str) -> tuple[int, int, int] | None:
    if not tag.startswith("module-v"):
        return None

    raw_version = tag.removeprefix("module-v")
    parts = raw_version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None

    return tuple(int(part) for part in parts)


def determine_update_status(installed_version: str, latest_version: str) -> bool | None:
    installed_tuple = parse_version(installed_version)
    latest_tuple = parse_version(latest_version)
    if installed_tuple is None or latest_tuple is None:
        return None
    return latest_tuple > installed_tuple


def emit_text_result(result: dict[str, Any]) -> None:
    print(f"Metadata file: {result['metadata_path']}")
    print(f"Module repository: {result['module_repo']}")
    print(f"Installed version: {result['installed_version']}")
    print(f"Latest release: {result['latest_release']}")

    update_available = result["update_available"]
    if update_available is True:
        print("Update available: yes")
    elif update_available is False:
        print("Update available: no")
    else:
        print("Update available: unknown (version format is not comparable)")


def emit_verify_text_result(result: dict[str, Any]) -> None:
    print(f"Metadata file: {result['metadata_path']}")
    print(f"Schema version: {result['schema_version']}")
    print(f"Installed version: {result['module_version']}")

    if not result["verified"]:
        print("Managed file verification: unavailable")
        for error in result["errors"]:
            print(f"- {error}")
        return

    print("Managed file verification: passed" if result["valid"] else "Managed file verification: failed")
    for file_result in result["files"]:
        status = "ok" if file_result["valid"] else "failed"
        print(f"- {file_result['path']}: {status}")
    if result["errors"]:
        print("Issues:")
        for error in result["errors"]:
            print(f"- {error}")


def main() -> None:
    args = parse_args()
    metadata = load_metadata(args.metadata)

    if args.verify:
        verify_result = verify_managed_files(metadata)
        if args.json:
            print(json.dumps(verify_result, indent=2))
        else:
            emit_verify_text_result(verify_result)
        if not verify_result["valid"]:
            sys.exit(1)
        return

    repo_slug = get_repo_slug(metadata, args.repo)
    latest_release = fetch_latest_release(repo_slug, args.api_base_url)

    latest_tag = latest_release.get("tag_name")
    if not isinstance(latest_tag, str) or not latest_tag.strip():
        fail("Latest GitHub release response did not include a tag_name.")

    installed_version = metadata.get("installed_version", "unknown")
    if not isinstance(installed_version, str) or not installed_version.strip():
        installed_version = "unknown"

    result = {
        "metadata_path": metadata["_path"],
        "module_repo": repo_slug,
        "installed_version": installed_version,
        "latest_release": latest_tag.strip(),
        "update_available": determine_update_status(installed_version, latest_tag),
    }

    if args.json:
        print(json.dumps(result, indent=2))
        return

    emit_text_result(result)


if __name__ == "__main__":
    main()
