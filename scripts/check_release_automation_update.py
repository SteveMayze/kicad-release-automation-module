#!/usr/bin/env python3
"""Check whether a newer module release is available for a target repository."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_METADATA_FILE = ".kicad-release-automation-version.json"
DEFAULT_API_BASE = "https://api.github.com"


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
    return parser.parse_args()


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def load_metadata(metadata_path: Path) -> dict[str, Any]:
    resolved_path = metadata_path.resolve()
    if not resolved_path.exists():
        fail(
            f"Installed module metadata file not found: {resolved_path}. "
            "Re-run install.sh from the module repository first."
        )

    with resolved_path.open("r", encoding="utf-8") as handle:
        metadata = json.load(handle)

    if not isinstance(metadata, dict):
        fail(f"Metadata root must be a JSON object: {resolved_path}")

    metadata["_path"] = str(resolved_path)
    return metadata


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


def main() -> None:
    args = parse_args()
    metadata = load_metadata(args.metadata)
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
