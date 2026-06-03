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
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

TAG_PATTERN = re.compile(r"^r(?P<version>\d+\.\d+\.\d+)$")
DEFAULT_CONFIG_FILE = "release-artifacts.json"


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
        help="Print actions without running kicad-cli commands.",
    )
    return parser.parse_args()


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def find_repo_root(script_file: Path) -> Path:
    return script_file.resolve().parent.parent


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

    candidate = Path(configured_path)
    if not candidate.is_absolute():
        candidate = repo_root / candidate

    candidate = candidate.resolve()
    if not candidate.exists():
        fail(f"Configured project.path does not exist: {candidate}")
    if candidate.suffix != ".kicad_pro":
        fail(f"Configured project.path must point to a .kicad_pro file: {candidate}")

    return candidate


def find_project_file(
    repo_root: Path,
    explicit_project: Optional[Path],
    configured_project: Optional[Path],
) -> Path:
    if explicit_project:
        project_path = explicit_project.resolve()
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


def resolve_kicad_cli(dry_run: bool = False) -> str:
    env_cli = os.environ.get("KICAD_CLI")
    if env_cli:
        if Path(env_cli).exists() or shutil.which(env_cli):
            return env_cli

    from_path = shutil.which("kicad-cli")
    if from_path:
        return from_path

    candidates: list[Path] = []
    if sys.platform == "darwin":
        candidates.extend(
            [
                Path("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"),
                Path("/Applications/KiCad/KiCad Nightly.app/Contents/MacOS/kicad-cli"),
            ]
        )
    elif os.name == "nt":
        program_files = [
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramFiles(x86)"),
        ]
        for base in filter(None, program_files):
            candidates.extend(Path(base).glob("KiCad/*/bin/kicad-cli.exe"))
            candidates.extend(Path(base).glob("KiCad/bin/kicad-cli.exe"))
    else:
        candidates.extend([Path("/usr/bin/kicad-cli"), Path("/usr/local/bin/kicad-cli")])

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    if dry_run:
        print("kicad-cli not found; continuing because --dry-run was set.")
        return "kicad-cli"

    fail(
        "kicad-cli not found. Install KiCad or set KICAD_CLI to the executable path."
    )
    raise RuntimeError("unreachable")


def extract_release(tag: Optional[str], release: Optional[str]) -> Optional[str]:
    if tag:
        match = TAG_PATTERN.match(tag)
        if not match:
            fail(f"Tag '{tag}' does not match required pattern r#.#.#")
        return match.group("version")

    if release:
        if not re.match(r"^\d+\.\d+\.\d+$", release):
            fail("--release must match #.#.# (example: 1.2.3)")
        return release

    env_tag = os.environ.get("GITHUB_REF_NAME")
    if env_tag and TAG_PATTERN.match(env_tag):
        return TAG_PATTERN.match(env_tag).group("version")

    return None


def set_project_release(project_file: Path, release_value: str) -> None:
    with project_file.open("r", encoding="utf-8") as handle:
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


def load_config(repo_root: Path, config_path: Path) -> dict:
    resolved_path = config_path
    if not resolved_path.is_absolute():
        resolved_path = repo_root / resolved_path

    if not resolved_path.exists():
        print(
            f"Config file not found at {resolved_path}. "
            "Continuing with default export behavior."
        )
        return {}

    with resolved_path.open("r", encoding="utf-8") as handle:
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
    with pcb_file.open("r", encoding="utf-8") as handle:
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


def run_cmd(command: list[str], cwd: Path, dry_run: bool = False) -> None:
    print(f"+ {' '.join(command)}")
    if dry_run:
        return

    result = subprocess.run(command, cwd=str(cwd), check=False)
    if result.returncode != 0:
        fail(f"Command failed with exit code {result.returncode}: {' '.join(command)}")


def main() -> None:
    args = parse_args()
    script_file = Path(__file__)
    repo_root = find_repo_root(script_file)

    config = load_config(repo_root, args.config)
    configured_project = resolve_configured_project_path(repo_root, config)

    project_file = find_project_file(repo_root, args.project, configured_project)
    project_stem = project_file.stem
    pcb_file = project_file.with_suffix(".kicad_pcb")
    sch_file = project_file.with_suffix(".kicad_sch")

    if not pcb_file.exists():
        fail(f"PCB file not found: {pcb_file}")

    release_value = extract_release(args.tag, args.release)
    if release_value and not args.no_update_release_variable:
        set_project_release(project_file, release_value)
    elif release_value:
        print("Skipping RELEASE text variable update (--no-update-release-variable).")
    else:
        print("No release value provided. Existing RELEASE text variable is unchanged.")

    configured_layer_list = get_configured_gerber_layers_list(config)
    if configured_layer_list:
        available_layers = parse_board_layers(pcb_file)
        validate_configured_layers(configured_layer_list, available_layers)
    configured_layers = ",".join(configured_layer_list) if configured_layer_list else None

    kicad_cli = resolve_kicad_cli(dry_run=args.dry_run)
    output_dir = (repo_root / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Using kicad-cli: {kicad_cli}")
    print(f"Project file: {project_file}")
    print(f"PCB file: {pcb_file}")
    print(f"Output directory: {output_dir}")

    gerber_command = [
        kicad_cli,
        "pcb",
        "export",
        "gerbers",
        "--output",
        str(output_dir),
    ]
    if configured_layers:
        print(f"Using configured Gerber layers: {configured_layers}")
        gerber_command.extend(["--layers", configured_layers])
    else:
        print("No explicit Gerber layers configured. Exporting CLI defaults.")
    gerber_command.append(str(pcb_file))

    run_cmd(
        gerber_command,
        cwd=repo_root,
        dry_run=args.dry_run,
    )

    run_cmd(
        [
            kicad_cli,
            "pcb",
            "export",
            "drill",
            "--output",
            str(output_dir),
            str(pcb_file),
        ],
        cwd=repo_root,
        dry_run=args.dry_run,
    )

    if args.schematic_pdf:
        if not sch_file.exists():
            fail(f"Schematic file not found: {sch_file}")
        run_cmd(
            [
                kicad_cli,
                "sch",
                "export",
                "pdf",
                "--output",
                str(output_dir / f"{project_stem}_schematic.pdf"),
                str(sch_file),
            ],
            cwd=repo_root,
            dry_run=args.dry_run,
        )

    if args.board_pdf:
        run_cmd(
            [
                kicad_cli,
                "pcb",
                "export",
                "pdf",
                "--output",
                str(output_dir / f"{project_stem}_board.pdf"),
                str(pcb_file),
            ],
            cwd=repo_root,
            dry_run=args.dry_run,
        )

    print("Artifact generation complete.")


if __name__ == "__main__":
    main()
