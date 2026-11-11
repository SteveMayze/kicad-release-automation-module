#!/usr/bin/env python3
"""Generate KiCad release deliverables from a single entrypoint.

Current deliverables:
- Gerber plot files
- Drill files

Future-ready flags are included for schematic and board PDFs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

TAG_PATTERN = re.compile(r"^r(?P<version>\d+\.\d+\.\d+)$")
PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
WINDOWS_DRIVE_PATH_PATTERN = re.compile(r"^[A-Za-z]:[\\/]")
UNC_PATH_PATTERN = re.compile(r"^[\\/]{2}[^\\/]+[\\/][^\\/]+")
WSL_MOUNT_DRIVE_PATTERN = re.compile(r"^/mnt/([a-zA-Z])(?:/(.*))?$")
DEFAULT_CONFIG_FILE = "release-artifacts.json"
DEFAULT_MANIFEST_NAME = "release-manifest.json"
MANIFEST_SCHEMA_VERSION = 1
PCB_GENERATOR_VERSION_PATTERN = re.compile(r'\(generator_version\s+"([^"]+)"\)')
VERSION_NUMBER_PATTERN = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")
KICAD_CLI_VERSION_TIMEOUT_SECONDS = 300


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate KiCad release artifacts (Gerbers first)."
    )
    parser.add_argument(
        "--project",
        type=Path,
        help=(
            "Path to .kicad_pro file. If omitted, this script auto-discovers a single "
            ".kicad_pro under the repository root."
        ),
    )
    parser.add_argument(
        "--project-id",
        action="append",
        default=[],
        help=(
            "Project ID(s) to build from config projects[]. Repeat for multiple IDs. "
            "Only valid when config uses projects[]."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(DEFAULT_CONFIG_FILE),
        help=(
            "Path to release automation config JSON file "
            f"(default: {DEFAULT_CONFIG_FILE})."
        ),
    )
    parser.add_argument(
        "--tag",
        type=str,
        help="Release tag in r#.#.# format. If set, RELEASE is derived from this.",
    )
    parser.add_argument(
        "--release",
        type=str,
        help="Explicit release value (e.g. 1.2.3). Used if --tag is not set.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("gerber"),
        help="Output directory for Gerber and drill files (default: gerber).",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help=(
            "Path of the manifest JSON written after a successful run "
            f"(default: <output-dir>/{DEFAULT_MANIFEST_NAME})."
        ),
    )
    parser.add_argument(
        "--no-update-release-variable",
        action="store_true",
        help="Do not write text_variables.RELEASE in the .kicad_pro file.",
    )
    parser.add_argument(
        "--schematic-pdf",
        action="store_true",
        help="Also export schematic PDF (future requirement; optional now).",
    )
    parser.add_argument(
        "--board-pdf",
        action="store_true",
        help="Also export board PDF (future requirement; optional now).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print actions without running kicad-cli export commands, modifying "
            "project files or creating directories."
        ),
    )
    return parser.parse_args()


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def find_repo_root(script_file: Path) -> Path:
    return script_file.resolve().parent.parent


def validate_runtime_cwd(repo_root: Path) -> None:
    runtime_cwd = Path.cwd().resolve()
    if runtime_cwd == repo_root:
        return

    fail(
        "Current working directory does not match repository root derived from "
        f"script location. cwd={runtime_cwd}, repo_root={repo_root}. "
        "Run this script from the repository root so relative paths in "
        "release-artifacts.json resolve predictably."
    )


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


def wsl_to_windows_path(path_value: Path) -> str:
    posix = path_value.as_posix()
    match = WSL_MOUNT_DRIVE_PATTERN.match(posix)
    if not match:
        fail(
            "Cannot pass non-/mnt/<drive> paths to Windows kicad-cli.exe from WSL: "
            f"{path_value}"
        )

    drive = match.group(1).upper()
    remainder = match.group(2) or ""
    if not remainder:
        return f"{drive}:\\"

    normalized_remainder = remainder.replace("/", "\\")
    return f"{drive}:\\{normalized_remainder}"


def wsl_mount_text_to_windows_path(path_value: str) -> Optional[str]:
    normalized = path_value.replace("\\", "/")
    match = WSL_MOUNT_DRIVE_PATTERN.match(normalized)
    if not match:
        return None

    drive = match.group(1).upper()
    remainder = match.group(2) or ""
    if not remainder:
        return f"{drive}:\\"

    normalized_remainder = remainder.replace("/", "\\")
    return f"{drive}:\\{normalized_remainder}"


def wsl_to_windows_cli_path(path_value: Path) -> str:
    path_text = str(path_value)
    wslpath_cmd = shutil.which("wslpath")
    if wslpath_cmd:
        result = subprocess.run(
            [wslpath_cmd, "-w", path_text],
            check=False,
            capture_output=True,
            text=True,
        )
        converted = result.stdout.strip()
        if result.returncode == 0 and converted:
            return converted

    return wsl_to_windows_path(path_value)


def cli_uses_windows_paths(kicad_cli: str) -> bool:
    if not is_wsl_environment():
        return False

    cli_text = kicad_cli.strip()
    if not cli_text:
        return False

    lower = cli_text.lower()
    return lower.endswith(".exe") or bool(WINDOWS_DRIVE_PATH_PATTERN.match(cli_text))


def format_path_for_cli(path_value: Path, use_windows_paths: bool) -> str:
    if use_windows_paths:
        if is_wsl_environment():
            return wsl_to_windows_cli_path(path_value)
        return str(path_value)
    return str(path_value)


def format_cli_executable_for_windows_shell(kicad_cli: str) -> str:
    cli_text = kicad_cli.strip()
    if WINDOWS_DRIVE_PATH_PATTERN.match(cli_text):
        return cli_text

    if is_wsl_environment() and cli_text.lower().endswith(".exe") and cli_text.startswith("/"):
        return wsl_to_windows_cli_path(Path(cli_text))

    return cli_text


def build_cmd_exe_wrapper(command: list[str], windows_cwd: Optional[str] = None) -> list[str]:
    if not command:
        fail("Internal error: empty command cannot be wrapped for cmd.exe")

    windows_command = list(command)
    windows_command[0] = format_cli_executable_for_windows_shell(windows_command[0])
    cmdline = subprocess.list2cmdline(windows_command)

    if windows_cwd:
        windows_cwd_quoted = subprocess.list2cmdline([windows_cwd])
        cmdline = f"cd /d {windows_cwd_quoted} && {cmdline}"

    # Wrap once more so cmd.exe /c receives one command string in canonical form.
    return ["cmd.exe", "/d", "/c", f'"{cmdline}"']


def normalize_user_path(raw_path: str, repo_root: Path, context: str) -> Path:
    path_text = os.path.expandvars(os.path.expanduser(raw_path.strip()))
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
        if os.name == "nt":
            converted_wsl_mount = wsl_mount_text_to_windows_path(path_text)
            candidate = Path(converted_wsl_mount or path_text)
        else:
            candidate = Path(path_text.replace("\\", "/"))

    if not candidate.is_absolute():
        candidate = repo_root / candidate

    return candidate.resolve()


def resolve_configured_project_path(repo_root: Path, config: dict) -> Optional[Path]:
    project_config = config.get("project")
    if project_config is None:
        return None
    if not isinstance(project_config, dict):
        fail("Config field 'project' must be a JSON object.")

    configured_path = project_config.get("path")
    if configured_path is None:
        return None
    if not isinstance(configured_path, str) or not configured_path.strip():
        fail("Config field project.path must be a non-empty string.")

    candidate = normalize_user_path(
        configured_path,
        repo_root,
        context="config field project.path",
    )
    if not candidate.exists():
        fail(
            "Configured project.path does not exist: "
            f"{configured_path} -> {candidate}"
        )
    if candidate.suffix != ".kicad_pro":
        fail(f"Configured project.path must point to a .kicad_pro file: {candidate}")

    return candidate


def find_project_file(
    repo_root: Path,
    explicit_project: Optional[Path],
    configured_project: Optional[Path],
) -> Path:
    if explicit_project:
        project_path = normalize_user_path(
            str(explicit_project),
            repo_root,
            context="--project",
        )
        if not project_path.exists():
            fail(f"Project file not found: {project_path}")
        if project_path.suffix != ".kicad_pro":
            fail(f"Project file must be a .kicad_pro file: {project_path}")
        return project_path

    if configured_project:
        return configured_project

    project_files = sorted(repo_root.rglob("*.kicad_pro"))
    if not project_files:
        fail(f"No .kicad_pro file found under {repo_root}")
    if len(project_files) > 1:
        names = ", ".join(str(path.relative_to(repo_root)) for path in project_files)
        fail(
            "Multiple .kicad_pro files found under repository root. "
            "Use --project to choose one: "
            f"{names}"
        )
    return project_files[0]


def parse_project_id(raw_project_id: str, context: str) -> str:
    project_id = raw_project_id.strip()
    if not project_id:
        fail(f"{context} must be a non-empty string.")
    if not PROJECT_ID_PATTERN.match(project_id):
        fail(
            f"{context} must match {PROJECT_ID_PATTERN.pattern}: {raw_project_id!r}"
        )
    return project_id


def resolve_projects_from_config(
    repo_root: Path,
    config: dict[str, Any],
    selected_project_ids: list[str],
) -> Optional[list[dict[str, Any]]]:
    projects_raw = config.get("projects")
    if projects_raw is None:
        return None
    if not isinstance(projects_raw, list) or not projects_raw:
        fail("Config field 'projects' must be a non-empty list when present.")

    defaults_raw = config.get("defaults")
    if defaults_raw is None:
        defaults_raw = {}
    if not isinstance(defaults_raw, dict):
        fail("Config field 'defaults' must be a JSON object when present.")
    defaults_gerber_raw = defaults_raw.get("gerber")
    if defaults_gerber_raw is None:
        defaults_gerber_raw = {}
    if not isinstance(defaults_gerber_raw, dict):
        fail("Config field defaults.gerber must be a JSON object when present.")

    selected_normalized = [
        parse_project_id(project_id, "--project-id value")
        for project_id in selected_project_ids
    ]
    selected_lookup = set(selected_normalized)

    projects: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, project_raw in enumerate(projects_raw):
        context = f"config field projects[{index}]"
        if not isinstance(project_raw, dict):
            fail(f"{context} must be a JSON object.")

        configured_path = project_raw.get("path")
        if not isinstance(configured_path, str) or not configured_path.strip():
            fail(f"{context}.path must be a non-empty string.")
        project_file = normalize_user_path(
            configured_path,
            repo_root,
            context=f"{context}.path",
        )
        if not project_file.exists():
            fail(
                f"Configured {context}.path does not exist: "
                f"{configured_path} -> {project_file}"
            )
        if project_file.suffix != ".kicad_pro":
            fail(f"Configured {context}.path must point to a .kicad_pro file: {project_file}")

        configured_project_id = project_raw.get("id")
        if configured_project_id is None:
            project_id = parse_project_id(project_file.stem, f"{context} derived ID")
        elif isinstance(configured_project_id, str):
            project_id = parse_project_id(configured_project_id, f"{context}.id")
        else:
            fail(f"{context}.id must be a string when present.")

        if project_id in seen_ids:
            fail(f"Duplicate project ID in config projects[]: {project_id}")
        seen_ids.add(project_id)

        project_gerber_raw = project_raw.get("gerber")
        if project_gerber_raw is None:
            project_gerber_raw = {}
        if not isinstance(project_gerber_raw, dict):
            fail(f"{context}.gerber must be a JSON object when present.")

        merged_gerber = dict(defaults_gerber_raw)
        merged_gerber.update(project_gerber_raw)
        normalized = {
            "id": project_id,
            "project_file": project_file,
            "gerber": merged_gerber,
        }
        projects.append(normalized)

    if selected_lookup:
        unknown = sorted(selected_lookup - seen_ids)
        if unknown:
            fail(
                "Unknown project ID(s) passed via --project-id: "
                + ", ".join(unknown)
            )
        projects = [project for project in projects if project["id"] in selected_lookup]

    return sorted(projects, key=lambda item: item["id"])


def resolve_kicad_cli(dry_run: bool = False) -> str:
    env_cli = os.environ.get("KICAD_CLI")
    if env_cli:
        if Path(env_cli).exists() or shutil.which(env_cli):
            return env_cli

    from_path = shutil.which("kicad-cli")
    if from_path:
        return from_path

    if dry_run:
        print("kicad-cli not found; continuing because --dry-run was set.")
        return "kicad-cli"

    fail(
        "kicad-cli not found. Install KiCad or set KICAD_CLI to the executable path. "
        "Use scripts/find_kicad_cli.py to locate it."
    )
    raise RuntimeError("unreachable")


def parse_release_target(value: str, context: str) -> tuple[Optional[str], str]:
    if not value:
        fail(f"{context} must not be empty.")

    candidate = value.strip()
    if candidate.startswith("r/"):
        candidate = candidate[2:]
    elif candidate.startswith("r") and len(candidate) > 1 and (
        candidate[1] == "/" or candidate[1].isdigit()
    ):
        candidate = candidate[1:]

    if "/" in candidate:
        project_id, version = candidate.split("/", 1)
        project_id = project_id.strip()
        version = version.strip()
        if not project_id or not re.fullmatch(PROJECT_ID_PATTERN.pattern, project_id):
            fail(f"{context} project ID must match {PROJECT_ID_PATTERN.pattern}: {value!r}")
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            fail(
                f"{context} project-scoped release must match <project-id>/#.#.#: {value!r}"
            )
        return project_id, version

    if re.fullmatch(r"\d+\.\d+\.\d+", candidate):
        return None, candidate

    fail(f"{context} must match #.#.# or <project-id>/#.#.# (example: 1.2.3 or board-a/1.2.3)")


def extract_release(tag: Optional[str], release: Optional[str]) -> Optional[str]:
    if tag:
        try:
            _, version = parse_release_target(tag, "--tag")
            return version
        except SystemExit:
            match = TAG_PATTERN.match(tag)
            if not match:
                raise
            return match.group("version")

    if release:
        _, version = parse_release_target(release, "--release")
        return version

    env_tag = os.environ.get("GITHUB_REF_NAME")
    if env_tag:
        try:
            _, version = parse_release_target(env_tag, "GITHUB_REF_NAME")
            return version
        except SystemExit:
            pass

    return None


def set_project_release(project_file: Path, release_value: str) -> None:
    with project_file.open("r", encoding="utf-8-sig") as handle:
        project_data = json.load(handle)

    text_variables = project_data.get("text_variables")
    if not isinstance(text_variables, dict):
        text_variables = {}
        project_data["text_variables"] = text_variables

    previous = text_variables.get("RELEASE")
    text_variables["RELEASE"] = release_value

    with project_file.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(project_data, handle, indent=2)
        handle.write("\n")

    if previous != release_value:
        print(f"Updated RELEASE text variable: {previous!r} -> {release_value!r}")
    else:
        print(f"RELEASE text variable already set to {release_value!r}")


def read_board_generator_version(pcb_file: Path) -> Optional[str]:
    """Return the generator_version recorded in a .kicad_pcb header, if any."""
    try:
        with pcb_file.open("r", encoding="utf-8-sig", errors="ignore") as handle:
            header = handle.read(4096)
    except OSError:
        return None

    match = PCB_GENERATOR_VERSION_PATTERN.search(header)
    if not match:
        return None
    return match.group(1).strip() or None


def parse_major_version(version_text: str) -> Optional[int]:
    match = VERSION_NUMBER_PATTERN.search(version_text)
    if not match:
        return None
    return int(match.group(1))


def kicad_cli_is_available(kicad_cli: str) -> bool:
    return Path(kicad_cli).exists() or shutil.which(kicad_cli) is not None


def query_kicad_cli_version(kicad_cli: str, cwd: Path) -> Optional[str]:
    """Return the version line printed by kicad-cli --version, or None."""
    try:
        result = subprocess.run(
            [kicad_cli, "--version"],
            cwd=str(cwd),
            check=False,
            capture_output=True,
            text=True,
            timeout=KICAD_CLI_VERSION_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None

    for line in result.stdout.splitlines():
        if VERSION_NUMBER_PATTERN.search(line):
            return line.strip()
    return None


def preflight_board_versions(
    kicad_cli: str,
    projects: list[dict[str, Any]],
    repo_root: Path,
    dry_run: bool,
) -> None:
    """Fail early when kicad-cli is older than a selected board's file format."""
    boards: list[tuple[str, Path, str, int]] = []
    for project in projects:
        pcb_file = project["project_file"].with_suffix(".kicad_pcb")
        if not pcb_file.exists():
            continue
        board_version = read_board_generator_version(pcb_file)
        if board_version is None:
            continue
        board_major = parse_major_version(board_version)
        if board_major is None:
            continue
        boards.append((project["id"], pcb_file, board_version, board_major))

    if not boards:
        return

    if dry_run and not kicad_cli_is_available(kicad_cli):
        print("Skipping board/kicad-cli version check (--dry-run without kicad-cli).")
        return

    cli_version = query_kicad_cli_version(kicad_cli, repo_root)
    cli_major = parse_major_version(cli_version) if cli_version else None
    if cli_version is None or cli_major is None:
        print(
            "WARNING: could not determine the kicad-cli version; "
            "skipping board/kicad-cli version check.",
            file=sys.stderr,
        )
        return

    print(f"kicad-cli version: {cli_version}")
    for project_id, pcb_file, board_version, board_major in boards:
        if cli_major < board_major:
            image = os.environ.get("KICAD_IMAGE") or "not set"
            fail(
                f"Board {pcb_file} (project '{project_id}') was saved by KiCad "
                f"{board_version}, but kicad-cli is version {cli_version}. "
                f"A kicad-cli of version {board_major} or newer is required. "
                f"In CI, set KICAD_IMAGE (currently: {image}) or kicad.image in "
                "release-artifacts.json to a matching KiCad image."
            )


def path_for_manifest(path_value: Path, repo_root: Path) -> str:
    """Repo-relative POSIX path when inside the repository, else absolute."""
    try:
        return path_value.relative_to(repo_root).as_posix()
    except ValueError:
        return str(path_value)


def write_manifest(
    manifest_path: Path,
    repo_root: Path,
    release_value: Optional[str],
    entries: list[dict[str, Any]],
) -> None:
    payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "release": release_value,
        "projects": [
            {
                "id": entry["id"],
                "project_file": path_for_manifest(entry["project_file"], repo_root),
                "output_dir": path_for_manifest(entry["output_dir"], repo_root),
                "release": release_value,
            }
            for entry in entries
        ],
    }

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    print(f"Wrote manifest: {manifest_path}")


def load_config(repo_root: Path, config_path: Path) -> dict:
    resolved_path = normalize_user_path(
        str(config_path),
        repo_root,
        context="--config",
    )

    if not resolved_path.exists():
        print(
            f"Config file not found at {resolved_path}. "
            "Continuing with default export behavior."
        )
        return {}

    with resolved_path.open("r", encoding="utf-8-sig") as handle:
        config_data = json.load(handle)

    if not isinstance(config_data, dict):
        fail(f"Config root must be a JSON object: {resolved_path}")

    print(f"Loaded config: {resolved_path}")
    return config_data


def get_configured_gerber_layers_list(config: dict) -> Optional[list[str]]:
    gerber_config = config.get("gerber")
    if gerber_config is None:
        return None
    if not isinstance(gerber_config, dict):
        fail("Config field 'gerber' must be a JSON object.")

    include_layers = gerber_config.get("include_layers")
    if include_layers is None:
        return None
    if not isinstance(include_layers, list) or not include_layers:
        fail("Config field gerber.include_layers must be a non-empty list.")

    normalized_layers: list[str] = []
    for layer in include_layers:
        if not isinstance(layer, str) or not layer.strip():
            fail("Each item in gerber.include_layers must be a non-empty string.")
        normalized_layers.append(layer.strip())

    return normalized_layers


def parse_board_layers(pcb_file: Path) -> set[str]:
    """Parse layer names from the (layers ...) section in a KiCad PCB file."""
    with pcb_file.open("r", encoding="utf-8-sig") as handle:
        content = handle.read()

    start = content.find("(layers")
    if start == -1:
        fail(f"Could not find '(layers' section in PCB file: {pcb_file}")

    depth = 0
    end = None
    for index, char in enumerate(content[start:], start=start):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                end = index
                break

    if end is None:
        fail(f"Could not parse '(layers' section in PCB file: {pcb_file}")

    layers_section = content[start : end + 1]
    # Matches lines like: (0 "F.Cu" signal)
    layer_names = set(re.findall(r'\(\s*\d+\s+"([^"]+)"\s+[^\)]+\)', layers_section))
    if not layer_names:
        fail(f"No board layers parsed from PCB file: {pcb_file}")

    return layer_names


def validate_configured_layers(config_layers: list[str], available_layers: set[str]) -> None:
    invalid_layers = [layer for layer in config_layers if layer not in available_layers]
    if not invalid_layers:
        return

    available = ", ".join(sorted(available_layers))
    invalid = ", ".join(invalid_layers)
    fail(
        "Invalid Gerber layer(s) in config: "
        f"{invalid}. Available layers in PCB: {available}"
    )


def get_configured_additional_files(repo_root: Path, config: dict) -> list[Path]:
    gerber_config = config.get("gerber")
    if gerber_config is None:
        return []
    if not isinstance(gerber_config, dict):
        fail("Config field 'gerber' must be a JSON object.")

    additional_files = gerber_config.get("additional_files")
    if additional_files is None:
        return []
    if not isinstance(additional_files, list):
        fail("Config field gerber.additional_files must be a list.")

    resolved_files: list[Path] = []
    source_by_name: dict[str, Path] = {}
    for additional_file in additional_files:
        if not isinstance(additional_file, str) or not additional_file.strip():
            fail("Each item in gerber.additional_files must be a non-empty string.")

        candidate = normalize_user_path(
            additional_file,
            repo_root,
            context="config field gerber.additional_files",
        )
        if not candidate.exists():
            fail(
                "Configured gerber.additional_files entry does not exist: "
                f"{additional_file} -> {candidate}"
            )
        if not candidate.is_file():
            fail(
                "Configured gerber.additional_files entry must be a file: "
                f"{additional_file} -> {candidate}"
            )

        file_name = candidate.name
        previous_source = source_by_name.get(file_name)
        if previous_source is not None:
            fail(
                "Configured gerber.additional_files entries must have unique file "
                f"names for ZIP packaging: {previous_source} and {candidate}"
            )

        source_by_name[file_name] = candidate
        resolved_files.append(candidate)

    return resolved_files


def copy_additional_files_to_output(
    additional_files: list[Path],
    output_dir: Path,
    dry_run: bool = False,
) -> None:
    for source_file in additional_files:
        destination_file = output_dir / source_file.name
        if destination_file.resolve() == source_file.resolve():
            print(
                f"Skipping additional file already in output directory: {source_file}"
            )
            continue

        print(f"+ copy {source_file} {destination_file}")
        if dry_run:
            continue

        shutil.copy2(source_file, destination_file)


def run_cmd(command: list[str], cwd: Path, dry_run: bool = False) -> None:
    pretty_command = " ".join(shlex.quote(arg) for arg in command)
    print(f"+ {pretty_command}")
    if dry_run:
        return

    result = subprocess.run(
        command,
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(
            result.stderr,
            file=sys.stderr,
            end="" if result.stderr.endswith("\n") else "\n",
        )
    if result.returncode != 0:
        fail(f"Command failed with exit code {result.returncode}: {pretty_command}")


def probe_windows_kicad_cli_under_wsl(kicad_cli: str, cwd: Path, dry_run: bool) -> bool:
    command = [kicad_cli, "--version"]
    pretty_command = " ".join(shlex.quote(arg) for arg in command)
    print("Running kicad-cli probe (--version) in Windows-mode context.")
    print(f"+ {pretty_command}")
    print(f"  cwd={cwd}")
    if dry_run:
        return True

    result = subprocess.run(
        command,
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(
            result.stderr,
            file=sys.stderr,
            end="" if result.stderr.endswith("\n") else "\n",
        )

    if result.returncode == 0:
        print("kicad-cli probe succeeded.")
        return True

    print(
        "kicad-cli probe failed under direct WSL interop; "
        "falling back to cmd.exe invocation mode.",
        file=sys.stderr,
    )
    return False


def run_cmd_with_optional_fallback(
    primary_command: list[str],
    fallback_command: Optional[list[str]],
    cmd_exe_fallback_command: Optional[list[str]],
    primary_cwd: str,
    fallback_cwd: str,
    dry_run: bool = False,
) -> None:
    pretty_primary = " ".join(shlex.quote(arg) for arg in primary_command)
    print(f"+ {pretty_primary}")
    print(f"  cwd={primary_cwd}")
    if dry_run:
        return

    primary_result = subprocess.run(
        primary_command,
        cwd=primary_cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if primary_result.stdout:
        print(
            primary_result.stdout,
            end="" if primary_result.stdout.endswith("\n") else "\n",
        )
    if primary_result.stderr:
        print(
            primary_result.stderr,
            file=sys.stderr,
            end="" if primary_result.stderr.endswith("\n") else "\n",
        )

    if primary_result.returncode == 0:
        return

    if fallback_command is None:
        fail(
            f"Command failed with exit code {primary_result.returncode}: "
            f"{pretty_primary}"
        )

    pretty_fallback = " ".join(shlex.quote(arg) for arg in fallback_command)
    print(
        "Primary command failed under WSL Windows-path mode; "
        "retrying with native POSIX paths."
    )
    print(f"+ {pretty_fallback}")
    print(f"  cwd={fallback_cwd}")

    fallback_result = subprocess.run(
        fallback_command,
        cwd=fallback_cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if fallback_result.stdout:
        print(
            fallback_result.stdout,
            end="" if fallback_result.stdout.endswith("\n") else "\n",
        )
    if fallback_result.stderr:
        print(
            fallback_result.stderr,
            file=sys.stderr,
            end="" if fallback_result.stderr.endswith("\n") else "\n",
        )

    if fallback_result.returncode != 0:
        if cmd_exe_fallback_command is not None:
            pretty_cmd_exe_fallback = " ".join(
                shlex.quote(arg) for arg in cmd_exe_fallback_command
            )
            print(
                "Fallback with native POSIX paths also failed; "
                "retrying through cmd.exe interop."
            )
            print(f"+ {pretty_cmd_exe_fallback}")
            print(f"  cwd={fallback_cwd}")

            cmd_exe_result = subprocess.run(
                cmd_exe_fallback_command,
                cwd=fallback_cwd,
                check=False,
                capture_output=True,
                text=True,
            )
            if cmd_exe_result.stdout:
                print(
                    cmd_exe_result.stdout,
                    end="" if cmd_exe_result.stdout.endswith("\n") else "\n",
                )
            if cmd_exe_result.stderr:
                print(
                    cmd_exe_result.stderr,
                    file=sys.stderr,
                    end="" if cmd_exe_result.stderr.endswith("\n") else "\n",
                )
            if cmd_exe_result.returncode == 0:
                print("Fallback through cmd.exe interop succeeded.")
                return

        if (
            not primary_result.stdout
            and not primary_result.stderr
            and not fallback_result.stdout
            and not fallback_result.stderr
        ):
            print(
                "KiCad CLI produced no stdout/stderr in either mode; "
                "this usually indicates process startup/environment issues "
                "rather than argument content.",
                file=sys.stderr,
            )
        fail(
            "Command failed after both path modes. "
            f"Primary exit={primary_result.returncode}, "
            f"fallback exit={fallback_result.returncode}. "
            f"Primary: {pretty_primary}; fallback: {pretty_fallback}"
        )

    print("Fallback with native POSIX paths succeeded.")


def main() -> None:
    args = parse_args()
    script_file = Path(__file__)
    repo_root = find_repo_root(script_file)
    validate_runtime_cwd(repo_root)

    config = load_config(repo_root, args.config)
    selected_project_ids = list(args.project_id or [])
    release_value = None
    if args.release is not None:
        project_id_from_release, release_value = parse_release_target(
            args.release,
            "--release",
        )
        if project_id_from_release is not None:
            if selected_project_ids and project_id_from_release not in selected_project_ids:
                fail(
                    "--release project-scoped value conflicts with --project-id: "
                    f"{project_id_from_release} vs {selected_project_ids}"
                )
            selected_project_ids = [project_id_from_release]
    elif args.tag is not None:
        project_id_from_tag, release_value = parse_release_target(args.tag, "--tag")
        if project_id_from_tag is not None:
            if selected_project_ids and project_id_from_tag not in selected_project_ids:
                fail(
                    "--tag project-scoped value conflicts with --project-id: "
                    f"{project_id_from_tag} vs {selected_project_ids}"
                )
            selected_project_ids = [project_id_from_tag]
    else:
        release_value = extract_release(args.tag, args.release)

    configured_projects = resolve_projects_from_config(
        repo_root,
        config,
        selected_project_ids=selected_project_ids,
    )

    multi_project_mode = configured_projects is not None
    projects_to_process: list[dict[str, Any]]
    if multi_project_mode:
        if args.project:
            fail("--project cannot be used when config field projects[] is present.")
        projects_to_process = configured_projects
    else:
        if selected_project_ids:
            fail(
                "--project-id is only supported when config field projects[] is present."
            )
        configured_project = resolve_configured_project_path(repo_root, config)
        project_file = find_project_file(repo_root, args.project, configured_project)
        projects_to_process = [
            {
                "id": parse_project_id(project_file.stem, "derived legacy project ID"),
                "project_file": project_file,
                "gerber": config.get("gerber", {}),
            }
        ]

    kicad_cli = resolve_kicad_cli(dry_run=args.dry_run)
    use_windows_paths = cli_uses_windows_paths(kicad_cli)
    output_root_dir = normalize_user_path(
        str(args.output_dir),
        repo_root,
        context="--output-dir",
    )
    if args.manifest is not None:
        manifest_path = normalize_user_path(
            str(args.manifest),
            repo_root,
            context="--manifest",
        )
    else:
        manifest_path = output_root_dir / DEFAULT_MANIFEST_NAME

    preflight_board_versions(
        kicad_cli,
        projects_to_process,
        repo_root,
        dry_run=args.dry_run,
    )

    if not args.dry_run:
        output_root_dir.mkdir(parents=True, exist_ok=True)

    print(f"Using kicad-cli: {kicad_cli}")
    if use_windows_paths:
        print("Detected Windows kicad-cli under WSL; converting file paths to Windows format.")
    print(f"Output root directory: {output_root_dir}")
    print(f"Projects selected: {', '.join(project['id'] for project in projects_to_process)}")

    primary_cwd = str(repo_root)
    fallback_cwd = str(repo_root)
    force_cmd_exe_mode = False
    windows_repo_root: Optional[str] = None
    if use_windows_paths and is_wsl_environment():
        windows_repo_root = wsl_to_windows_cli_path(repo_root)
        force_cmd_exe_mode = not probe_windows_kicad_cli_under_wsl(
            kicad_cli,
            cwd=repo_root,
            dry_run=args.dry_run,
        )
        if force_cmd_exe_mode:
            print("Using cmd.exe interop mode for all KiCad CLI commands.")

    if release_value and args.no_update_release_variable:
        print("Skipping RELEASE text variable update (--no-update-release-variable).")
    elif not release_value:
        print("No release value provided. Existing RELEASE text variable is unchanged.")

    manifest_entries: list[dict[str, Any]] = []
    for project in projects_to_process:
        project_id = project["id"]
        project_file = project["project_file"]
        project_stem = project_file.stem
        pcb_file = project_file.with_suffix(".kicad_pcb")
        sch_file = project_file.with_suffix(".kicad_sch")

        if not pcb_file.exists():
            fail(f"PCB file not found for project '{project_id}': {pcb_file}")

        if release_value and not args.no_update_release_variable:
            if args.dry_run:
                print(
                    "Dry run: RELEASE text variable would be set to "
                    f"{release_value!r} in {project_file}"
                )
            else:
                set_project_release(project_file, release_value)

        project_gerber_config = {"gerber": project.get("gerber", {})}
        configured_layer_list = get_configured_gerber_layers_list(project_gerber_config)
        if configured_layer_list:
            available_layers = parse_board_layers(pcb_file)
            validate_configured_layers(configured_layer_list, available_layers)
        configured_layers = ",".join(configured_layer_list) if configured_layer_list else None
        additional_files = get_configured_additional_files(repo_root, project_gerber_config)

        project_output_dir = output_root_dir if not multi_project_mode else output_root_dir / project_id
        if not args.dry_run:
            project_output_dir.mkdir(parents=True, exist_ok=True)

        print(f"Project: {project_id}")
        print(f"  Project file: {project_file}")
        print(f"  PCB file: {pcb_file}")
        print(f"  Output directory: {project_output_dir}")

        gerber_command = [
            kicad_cli,
            "pcb",
            "export",
            "gerbers",
            "--output",
            format_path_for_cli(project_output_dir, use_windows_paths),
        ]
        if configured_layers:
            print(f"  Using configured Gerber layers: {configured_layers}")
            gerber_command.extend(["--layers", configured_layers])
        else:
            print("  No explicit Gerber layers configured. Exporting CLI defaults.")
        gerber_command.append(format_path_for_cli(pcb_file, use_windows_paths))
        gerber_fallback_command: Optional[list[str]] = None
        gerber_cmd_exe_fallback_command: Optional[list[str]] = None
        drill_command = [
            kicad_cli,
            "pcb",
            "export",
            "drill",
            "--output",
            format_path_for_cli(project_output_dir, use_windows_paths),
            format_path_for_cli(pcb_file, use_windows_paths),
        ]
        drill_fallback_command: Optional[list[str]] = None
        drill_cmd_exe_fallback_command: Optional[list[str]] = None

        if force_cmd_exe_mode:
            gerber_command = build_cmd_exe_wrapper(gerber_command, windows_repo_root)
            drill_command = build_cmd_exe_wrapper(drill_command, windows_repo_root)
        elif use_windows_paths and is_wsl_environment():
            gerber_fallback_command = [
                kicad_cli,
                "pcb",
                "export",
                "gerbers",
                "--output",
                str(project_output_dir),
            ]
            if configured_layers:
                gerber_fallback_command.extend(["--layers", configured_layers])
            gerber_fallback_command.append(str(pcb_file))
            gerber_cmd_exe_fallback_command = build_cmd_exe_wrapper(
                gerber_command,
                windows_repo_root,
            )

            drill_fallback_command = [
                kicad_cli,
                "pcb",
                "export",
                "drill",
                "--output",
                str(project_output_dir),
                str(pcb_file),
            ]
            drill_cmd_exe_fallback_command = build_cmd_exe_wrapper(
                drill_command,
                windows_repo_root,
            )

        run_cmd_with_optional_fallback(
            primary_command=gerber_command,
            fallback_command=gerber_fallback_command,
            cmd_exe_fallback_command=None if force_cmd_exe_mode else gerber_cmd_exe_fallback_command,
            primary_cwd=primary_cwd,
            fallback_cwd=fallback_cwd,
            dry_run=args.dry_run,
        )

        run_cmd_with_optional_fallback(
            primary_command=drill_command,
            fallback_command=drill_fallback_command,
            cmd_exe_fallback_command=None if force_cmd_exe_mode else drill_cmd_exe_fallback_command,
            primary_cwd=primary_cwd,
            fallback_cwd=fallback_cwd,
            dry_run=args.dry_run,
        )

        if additional_files:
            print(
                "  Including additional file(s) in Gerber output: "
                + ", ".join(path.name for path in additional_files)
            )
            copy_additional_files_to_output(
                additional_files,
                project_output_dir,
                dry_run=args.dry_run,
            )

        if args.schematic_pdf:
            if not sch_file.exists():
                fail(f"Schematic file not found for project '{project_id}': {sch_file}")
            schematic_command = [
                kicad_cli,
                "sch",
                "export",
                "pdf",
                "--output",
                format_path_for_cli(
                    project_output_dir / f"{project_stem}_schematic.pdf",
                    use_windows_paths,
                ),
                format_path_for_cli(sch_file, use_windows_paths),
            ]
            schematic_fallback_command: Optional[list[str]] = None
            schematic_cmd_exe_fallback_command: Optional[list[str]] = None
            if force_cmd_exe_mode:
                schematic_command = build_cmd_exe_wrapper(
                    schematic_command,
                    windows_repo_root,
                )
            elif use_windows_paths and is_wsl_environment():
                schematic_fallback_command = [
                    kicad_cli,
                    "sch",
                    "export",
                    "pdf",
                    "--output",
                    str(project_output_dir / f"{project_stem}_schematic.pdf"),
                    str(sch_file),
                ]
                schematic_cmd_exe_fallback_command = build_cmd_exe_wrapper(
                    schematic_command,
                    windows_repo_root,
                )

            run_cmd_with_optional_fallback(
                primary_command=schematic_command,
                fallback_command=schematic_fallback_command,
                cmd_exe_fallback_command=None if force_cmd_exe_mode else schematic_cmd_exe_fallback_command,
                primary_cwd=primary_cwd,
                fallback_cwd=fallback_cwd,
                dry_run=args.dry_run,
            )

        if args.board_pdf:
            board_command = [
                kicad_cli,
                "pcb",
                "export",
                "pdf",
                "--output",
                format_path_for_cli(
                    project_output_dir / f"{project_stem}_board.pdf",
                    use_windows_paths,
                ),
                format_path_for_cli(pcb_file, use_windows_paths),
            ]
            board_fallback_command: Optional[list[str]] = None
            board_cmd_exe_fallback_command: Optional[list[str]] = None
            if force_cmd_exe_mode:
                board_command = build_cmd_exe_wrapper(
                    board_command,
                    windows_repo_root,
                )
            elif use_windows_paths and is_wsl_environment():
                board_fallback_command = [
                    kicad_cli,
                    "pcb",
                    "export",
                    "pdf",
                    "--output",
                    str(project_output_dir / f"{project_stem}_board.pdf"),
                    str(pcb_file),
                ]
                board_cmd_exe_fallback_command = build_cmd_exe_wrapper(
                    board_command,
                    windows_repo_root,
                )

            run_cmd_with_optional_fallback(
                primary_command=board_command,
                fallback_command=board_fallback_command,
                cmd_exe_fallback_command=None if force_cmd_exe_mode else board_cmd_exe_fallback_command,
                primary_cwd=primary_cwd,
                fallback_cwd=fallback_cwd,
                dry_run=args.dry_run,
            )

        manifest_entries.append(
            {
                "id": project_id,
                "project_file": project_file,
                "output_dir": project_output_dir,
            }
        )

    if args.dry_run:
        print(f"Dry run: manifest not written (would be {manifest_path}).")
    else:
        write_manifest(manifest_path, repo_root, release_value, manifest_entries)

    print("Artifact generation complete.")


if __name__ == "__main__":
    main()
