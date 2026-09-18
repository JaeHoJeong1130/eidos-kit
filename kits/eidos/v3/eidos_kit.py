#!/usr/bin/env python3
"""Install and inspect the portable Eidos v3 kit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


KIT_VERSION = "3.4.0"
TRUSTED_PRIOR_RELEASES = frozenset({"3.0.0", "3.1.0", "3.2.0", "3.2.1", "3.3.0"})
PROJECT_RE = re.compile(r"^project:[a-z0-9]+(?:-[a-z0-9]+)*$")
REVISION_RE = re.compile(r"^D(?P<number>\d{4})$")
WORK_RE = re.compile(
    r"^W-\d{8}-(?:\d{2}|m-[a-z0-9][a-z0-9-]*-[a-f0-9]{12})-"
    r"[a-z0-9]+(?:-[a-z0-9]+)*$"
)
MANIFEST_PATH = Path(".agents/eidos/kit-manifest.json")
USER_OWNED = {
    ".agents/context.json",
    ".agents/eidos/direction.md",
    ".agents/eidos/identity.json",
}


class KitError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ScalarMarkdown:
    metadata: dict[str, str]
    body: str
    text: str


def _kit_root() -> Path:
    return Path(__file__).resolve().parent


def _template_root() -> Path:
    return _kit_root() / "template"


def _release_descriptor(version: str) -> dict[str, Any]:
    path = _kit_root() / "release-manifests" / f"{version}.json"
    value = _load_json(path, "upgrade_path")
    if (
        value.get("schema_version") != 1
        or value.get("kit_version") != version
        or not isinstance(value.get("files"), dict)
        or any(
            not isinstance(relative, str)
            or not isinstance(digest_value, str)
            or re.fullmatch(r"[a-f0-9]{64}", digest_value) is None
            for relative, digest_value in value.get("files", {}).items()
        )
    ):
        raise KitError("upgrade_path", f"Invalid release descriptor: {version}")
    return value


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _template_files() -> list[Path]:
    return sorted(
        (
            path
            for path in _template_root().rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix not in {".pyc", ".pyo"}
        ),
        key=lambda path: path.relative_to(_template_root()).as_posix(),
    )


def _render(path: Path, project_id: str, project_name: str) -> bytes:
    data = path.read_bytes()
    relative = path.relative_to(_template_root()).as_posix()
    if relative == ".agents/context.json":
        try:
            context = json.loads(data.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise KitError("template_invalid", "Invalid context template.") from exc
        context["project"] = {"id": project_id, "name": project_name}
        return (json.dumps(context, ensure_ascii=False, indent=2) + "\n").encode(
            "utf-8"
        )
    if relative in {
        ".agents/eidos/direction.md",
        ".agents/eidos/work/_template.md",
    }:
        try:
            text = data.decode("utf-8")
        except UnicodeError as exc:
            raise KitError(
                "template_invalid", f"Expected UTF-8 template: {relative}"
            ) from exc
        text = text.replace("project:example", project_id).replace(
            "Example Project", project_name
        )
        if relative == ".agents/eidos/direction.md":
            text = re.sub(
                r"(?m)^updated_at:\s*\d{4}-\d{2}-\d{2}$",
                f"updated_at: {date.today().isoformat()}",
                text,
            )
        data = text.encode("utf-8")
    return data


def _manifest(
    project_id: str, project_name: str, rendered: dict[str, bytes]
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kit_version": KIT_VERSION,
        "project_id": project_id,
        "project_name": project_name,
        "files": {
            path: {
                "sha256": _sha(data),
                "ownership": "project" if path in USER_OWNED else "kit",
            }
            for path, data in sorted(rendered.items())
        },
    }


def _rendered_files(project_id: str, project_name: str) -> dict[str, bytes]:
    return {
        path.relative_to(_template_root()).as_posix(): _render(
            path, project_id, project_name
        )
        for path in _template_files()
    }


def render_installation(project_id: str, project_name: str) -> dict[str, bytes]:
    """Return the complete fresh-install write set without touching a repository.

    Composite installers use this API so the Eidos files and their own files can be
    committed as one atomic filesystem transaction.  The returned mapping includes
    the Eidos manifest and does not execute any target-repository code.
    """

    if not PROJECT_RE.fullmatch(project_id):
        raise KitError("project_id", "project_id must use project:<kebab-id>.")
    project_name = project_name.strip()
    if not project_name:
        raise KitError("project_name", "project_name is required.")
    rendered = _rendered_files(project_id, project_name)
    manifest = _manifest(project_id, project_name, rendered)
    return {**rendered, MANIFEST_PATH.as_posix(): _manifest_bytes(manifest)}


def _write_exclusive(path: Path, data: bytes, on_created=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise KitError("target_exists", f"Refusing to overwrite: {path}") from exc
    try:
        if on_created is not None:
            created_stat = os.fstat(descriptor)
            on_created((created_stat.st_dev, created_stat.st_ino))
    except Exception:
        os.close(descriptor)
        raise
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)


def _replace(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(raw)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _replace_guarded(path: Path, data: bytes, expected: _FileSnapshot) -> None:
    """Replace one existing file without losing a concurrent edit."""

    if not expected.existed:
        raise KitError("replace_contract", "Guarded replacement requires a file.")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(raw)
    backup_descriptor, backup_raw = tempfile.mkstemp(
        prefix=f".{path.name}.previous.", dir=path.parent
    )
    os.close(backup_descriptor)
    backup = Path(backup_raw)
    backup.unlink()
    displaced = False
    published = False
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        temporary.chmod(expected.mode if expected.mode is not None else 0o644)
        os.rename(path, backup)
        displaced = True
        if (
            backup.read_bytes() != expected.data
            or stat.S_IMODE(backup.stat().st_mode) != expected.mode
        ):
            raise KitError(
                "concurrent_modification",
                f"Target changed during migration: {path}",
            )
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise KitError(
                "concurrent_modification",
                f"Target changed during migration: {path}",
            ) from exc
        published = True
        temporary.unlink()
        backup.unlink()
        displaced = False
    finally:
        if displaced and backup.exists():
            if published and path.is_file() and path.read_bytes() == data:
                path.unlink()
            if not path.exists():
                os.rename(backup, path)
        if temporary.exists():
            temporary.unlink()
        if backup.exists() and not path.exists():
            os.rename(backup, path)


def _write_manifest(root: Path, value: dict[str, Any]) -> None:
    _replace(
        root / MANIFEST_PATH,
        (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )


def _manifest_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _is_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None:
        try:
            if is_junction():
                return True
        except OSError:
            return True
    try:
        attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & 0x400)


def _safe_repository_target(root: Path, relative: str | Path, label: str) -> Path:
    raw = str(relative).replace("\\", "/")
    candidate = Path(raw)
    if (
        not raw.strip()
        or candidate.is_absolute()
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise KitError(
            "context_path", f"{label} must be a safe repository-relative path."
        )
    current = root
    for part in candidate.parts:
        current = current / part
        if current.exists() or current.is_symlink():
            if _is_reparse(current):
                raise KitError(
                    "path_reparse",
                    f"{label} traverses a symlink, junction, or reparse point: {current}",
                )
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise KitError(
            "context_path", f"{label} points outside the repository."
        ) from exc
    return root / candidate


@dataclass(frozen=True)
class _FileSnapshot:
    existed: bool
    data: bytes | None
    mode: int | None


def _atomic_write_set(
    root: Path,
    writes: dict[str, bytes],
    *,
    require_absent: set[str] | None = None,
) -> None:
    """Apply a bounded file set and restore every target after any write failure."""

    absent = require_absent or set()
    targets = {
        relative: _safe_repository_target(root, relative, relative)
        for relative in writes
    }
    snapshots: dict[str, _FileSnapshot] = {}
    existing_directories: set[Path] = set()
    for relative, target in targets.items():
        if target.exists() and not target.is_file():
            raise KitError("target_type", f"Target is not a regular file: {relative}")
        if relative in absent and target.exists():
            raise KitError("target_exists", f"Refusing to overwrite: {relative}")
        snapshots[relative] = _FileSnapshot(
            target.is_file(),
            target.read_bytes() if target.is_file() else None,
            stat.S_IMODE(target.stat().st_mode) if target.is_file() else None,
        )
        parent = target.parent
        while parent != root:
            if parent.is_dir():
                existing_directories.add(parent)
            parent = parent.parent
    try:
        for relative, data in writes.items():
            target = targets[relative]
            if relative in absent:
                _write_exclusive(target, data)
            else:
                _replace(target, data)
    except Exception:
        for relative in reversed(list(writes)):
            target = targets[relative]
            snapshot = snapshots[relative]
            if snapshot.existed:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("wb") as handle:
                    handle.write(snapshot.data or b"")
                if snapshot.mode is not None:
                    target.chmod(snapshot.mode)
            elif target.is_file() or target.is_symlink():
                target.unlink()
        candidate_directories = {
            parent
            for target in targets.values()
            for parent in target.parents
            if parent != root and root in parent.parents
        }
        for directory in sorted(
            candidate_directories - existing_directories,
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise


def _atomic_context_migration(
    root: Path,
    writes: dict[str, bytes],
    context_snapshot: _FileSnapshot,
) -> None:
    """Create Eidos files, then publish the guarded context as the final write."""

    context_relative = ".agents/context.json"
    if list(writes)[-1] != context_relative:
        raise KitError(
            "migration_contract", "Context must be the final migration write."
        )
    targets = {
        relative: _safe_repository_target(root, relative, relative)
        for relative in writes
    }
    existing_directories: set[Path] = set()
    created_identities: dict[str, tuple[int, int]] = {}
    for relative, target in targets.items():
        if target.exists() and not target.is_file():
            raise KitError("target_type", f"Target is not a regular file: {relative}")
        if relative != context_relative and target.exists():
            raise KitError("target_exists", f"Refusing to overwrite: {relative}")
        parent = target.parent
        while parent != root:
            if parent.is_dir():
                existing_directories.add(parent)
            parent = parent.parent
    try:
        for relative, data in writes.items():
            target = targets[relative]
            if relative == context_relative:
                _replace_guarded(target, data, context_snapshot)
            else:
                _write_exclusive(
                    target,
                    data,
                    lambda identity, relative=relative: created_identities.__setitem__(
                        relative, identity
                    ),
                )
    except Exception:
        context_target = targets[context_relative]
        if (
            context_target.is_file()
            and context_target.read_bytes() == writes[context_relative]
        ):
            context_target.write_bytes(context_snapshot.data or b"")
            if context_snapshot.mode is not None:
                context_target.chmod(context_snapshot.mode)
        for relative in reversed([item for item in writes if item != context_relative]):
            target = targets[relative]
            identity = created_identities.get(relative)
            if identity is None or not target.is_file():
                continue
            target_stat = target.stat(follow_symlinks=False)
            current = target.read_bytes()
            if (target_stat.st_dev, target_stat.st_ino) == identity and writes[
                relative
            ].startswith(current):
                target.unlink()
        candidate_directories = {
            parent
            for target in targets.values()
            for parent in target.parents
            if parent != root and root in parent.parents
        }
        for directory in sorted(
            candidate_directories - existing_directories,
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise


def _load_json(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise KitError(code, f"Invalid JSON file: {path}") from exc
    if not isinstance(value, dict):
        raise KitError(code, f"Expected a JSON object: {path}")
    return value


def _load_manifest(root: Path) -> dict[str, Any]:
    path = root / MANIFEST_PATH
    if not path.is_file():
        raise KitError("manifest_missing", "Eidos v3 kit manifest is missing.")
    value = _load_json(path, "manifest_invalid")
    if value.get("schema_version") != 1 or not isinstance(value.get("files"), dict):
        raise KitError("manifest_invalid", "Unsupported kit manifest schema.")
    return value


def _parse_markdown(path: Path) -> ScalarMarkdown:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise KitError("read_failed", f"Cannot read UTF-8 file: {path}") from exc
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise KitError("frontmatter_missing", f"Missing scalar frontmatter: {path}")
    try:
        closing = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        )
    except StopIteration as exc:
        raise KitError("frontmatter_unclosed", f"Unclosed frontmatter: {path}") from exc
    metadata: dict[str, str] = {}
    for line in lines[1:closing]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[:1].isspace() or ":" not in line:
            raise KitError(
                "frontmatter_not_scalar",
                f"Only scalar frontmatter is supported: {path}",
            )
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()
    return ScalarMarkdown(
        metadata, "\n".join(lines[closing + 1 :]).strip() + "\n", text
    )


def _sections(body: str) -> dict[str, str]:
    values: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            current = match.group(1)
            if current in values:
                raise KitError(
                    "direction_section_duplicate",
                    f"Direction contains a duplicate section: {current}",
                )
            values[current] = []
        elif current is not None:
            values[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in values.items()}


def _run_git(root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise KitError("git_unavailable", "Git is unavailable.") from exc
    if result.returncode != 0:
        raise KitError(
            "not_git_repository",
            result.stderr.strip() or "Target is not a Git repository.",
        )
    return result.stdout.strip()


def _check_root(root: Path) -> Path:
    root = root.resolve()
    if not root.is_dir():
        raise KitError("root_missing", f"Target root does not exist: {root}")
    top = Path(_run_git(root, "rev-parse", "--show-toplevel")).resolve()
    if top != root:
        raise KitError("root_not_toplevel", f"--root must be the Git top level: {top}")
    return root


def _project_path(root: Path, raw: Any, label: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise KitError("context_path", f"{label} must be a repository-relative path.")
    return _safe_repository_target(root, raw, label)


def _command_install(args: argparse.Namespace) -> int:
    root = _check_root(args.root)
    _safe_repository_target(root, ".agents", ".agents")
    if not PROJECT_RE.fullmatch(args.project_id):
        raise KitError("project_id", "--project-id must use project:<kebab-id>.")
    if not args.project_name.strip():
        raise KitError("project_name", "--project-name is required.")
    rendered = _rendered_files(args.project_id, args.project_name.strip())
    for relative in (*rendered, MANIFEST_PATH.as_posix()):
        _safe_repository_target(root, relative, relative)
    collisions = [path for path in rendered if (root / path).exists()]
    if (root / MANIFEST_PATH).exists():
        collisions.append(MANIFEST_PATH.as_posix())
    if collisions:
        raise KitError(
            "target_exists",
            f"Install would overwrite existing path: {sorted(set(collisions))[0]}",
        )
    value = _manifest(args.project_id, args.project_name.strip(), rendered)
    writes = {**rendered, MANIFEST_PATH.as_posix(): _manifest_bytes(value)}
    _atomic_write_set(root, writes, require_absent=set(writes))
    print(
        f"Installed Eidos v{VERSION_TEXT} for {args.project_id} ({len(rendered)} files)."
    )
    return 0


def _validate_migration_candidate(writes: dict[str, bytes]) -> None:
    """Validate only trusted rendered Eidos files in an isolated repository."""

    with tempfile.TemporaryDirectory() as raw:
        candidate = Path(raw) / "candidate"
        candidate.mkdir()
        subprocess.run(
            ["git", "init", "--quiet", str(candidate)],
            capture_output=True,
            check=True,
        )
        for relative, data in writes.items():
            target = candidate / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        tool = candidate / ".agents/tools/eidos.py"
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(tool),
                "validate",
                "--root",
                str(candidate),
                "--json",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=environment,
        )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise KitError(
                "migration_invalid",
                result.stderr.strip() or "Migration candidate returned invalid JSON.",
            ) from exc
        if (
            result.returncode != 0
            or not isinstance(payload, dict)
            or not payload.get("ok")
        ):
            raise KitError(
                "migration_invalid",
                result.stdout.strip()
                or result.stderr.strip()
                or "Invalid migration candidate.",
            )


def _command_migrate(args: argparse.Namespace) -> int:
    root = _check_root(args.root)
    _safe_repository_target(root, ".agents", ".agents")
    if not PROJECT_RE.fullmatch(args.project_id):
        raise KitError("project_id", "--project-id must use project:<kebab-id>.")
    project_name = args.project_name.strip()
    if not project_name or any(ord(character) < 32 for character in project_name):
        raise KitError("project_name", "--project-name is required.")
    context_path = _safe_repository_target(
        root, ".agents/context.json", ".agents/context.json"
    )
    if not context_path.is_file():
        raise KitError(
            "context_missing", "Migration requires an existing context file."
        )
    context_snapshot = _FileSnapshot(
        True,
        context_path.read_bytes(),
        stat.S_IMODE(context_path.stat().st_mode),
    )
    context = _load_json(context_path, "context_invalid")
    if type(context.get("schema_version")) is not int or context["schema_version"] != 2:
        raise KitError(
            "context_invalid", "Migration requires context schema_version 2."
        )
    if "eidos" in context:
        raise KitError("already_managed", "Context already contains an eidos contract.")
    project = context.get("project")
    if not isinstance(project, dict):
        raise KitError("context_invalid", "Context project must be a JSON object.")
    rendered = _rendered_files(args.project_id, project_name)
    template_context = json.loads(rendered[".agents/context.json"].decode("utf-8"))
    merged_context = dict(context)
    merged_project = dict(project)
    merged_project.update({"id": args.project_id, "name": project_name})
    merged_context["project"] = merged_project
    merged_context["eidos"] = template_context["eidos"]
    rendered[".agents/context.json"] = (
        json.dumps(merged_context, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    for relative in (*rendered, MANIFEST_PATH.as_posix()):
        _safe_repository_target(root, relative, relative)
    collisions = [
        relative
        for relative in rendered
        if relative != ".agents/context.json" and (root / relative).exists()
    ]
    if (root / MANIFEST_PATH).exists():
        collisions.append(MANIFEST_PATH.as_posix())
    if collisions:
        raise KitError(
            "target_exists",
            f"Migration would overwrite existing path: {sorted(set(collisions))[0]}",
        )
    manifest = _manifest(args.project_id, project_name, rendered)
    candidate_writes = {
        **rendered,
        MANIFEST_PATH.as_posix(): _manifest_bytes(manifest),
    }
    _validate_migration_candidate(candidate_writes)
    writes = {
        **{
            relative: data
            for relative, data in rendered.items()
            if relative != ".agents/context.json"
        },
        MANIFEST_PATH.as_posix(): _manifest_bytes(manifest),
        ".agents/context.json": rendered[".agents/context.json"],
    }
    _atomic_context_migration(root, writes, context_snapshot)
    print(
        f"Migrated existing context to Eidos v{VERSION_TEXT} for {args.project_id} "
        f"({len(rendered) - 1} new files)."
    )
    return 0


VERSION_TEXT = "3"


def _migration_direction(
    old: ScalarMarkdown, next_revision: str, project_id: str
) -> bytes:
    sections = _sections(old.body)
    title = next(
        (line[2:].strip() for line in old.body.splitlines() if line.startswith("# ")),
        "Project Direction",
    )
    raw_stages = sections.get("Stages", "")
    stage_blocks: list[tuple[str, str, list[str], str]] = []
    current_id: str | None = None
    current_title = ""
    current_lines: list[str] = []
    for line in raw_stages.splitlines():
        heading = re.match(r"^###\s+(S\d{2,})\s+[—-]\s+(.+?)\s*$", line)
        if heading:
            if current_id is not None:
                gate = next(
                    (
                        item.split(":", 1)[1].strip()
                        for item in current_lines
                        if item.startswith("- Gate:")
                    ),
                    "Confirm the Stage outcome.",
                )
                stage_blocks.append(
                    (
                        current_id,
                        current_title,
                        [
                            item
                            for item in current_lines
                            if not item.startswith("- Gate:")
                        ],
                        gate,
                    )
                )
            current_id, current_title, current_lines = (
                heading.group(1),
                heading.group(2).strip(),
                [],
            )
        elif current_id is not None:
            current_lines.append(line)
    if current_id is not None:
        gate = next(
            (
                item.split(":", 1)[1].strip()
                for item in current_lines
                if item.startswith("- Gate:")
            ),
            "Confirm the Stage outcome.",
        )
        stage_blocks.append(
            (
                current_id,
                current_title,
                [item for item in current_lines if not item.startswith("- Gate:")],
                gate,
            )
        )
    if not stage_blocks:
        raise KitError(
            "migration_direction", "Cannot migrate a Direction without parsed Stages."
        )
    stages_text = "\n\n".join(
        f"### {stage_id} — {stage_title}\n" + "\n".join(lines).strip()
        for stage_id, stage_title, lines, _gate in stage_blocks
    )
    gates_text = "\n\n".join(
        f"### G{index:02d} — {stage_title}\n\n- Stage: {stage_id}\n- Criteria: {gate}\n- Evidence: pending"
        for index, (stage_id, stage_title, _lines, gate) in enumerate(
            stage_blocks, start=1
        )
    )
    result = f"""---
eidos_version: 3
document_type: direction
project_id: {project_id}
revision: {next_revision}
updated_at: {date.today().isoformat()}
---

# {title}

## Purpose

{sections.get("Purpose", "State the stable purpose.")}

## Boundaries

{sections.get("Boundaries", "State the project boundaries.")}

## Baseline

{sections.get("Baseline", "State the verified baseline.")}

## Stages

{stages_text}

## Gates

{gates_text}

## Dependencies

{sections.get("Dependencies", "none")}
"""
    return result.encode("utf-8")


def _legacy_open_work(root: Path, context: dict[str, Any]) -> list[str]:
    eidos = context.get("eidos")
    if not isinstance(eidos, dict):
        raise KitError("context_invalid", "Legacy context eidos object is missing.")
    raw = eidos.get("work_root", ".agents/eidos/work")
    work_root = _project_path(root, raw, "eidos.work_root")
    open_work: list[str] = []
    if not work_root.is_dir():
        return open_work
    for path in sorted(work_root.glob("W-*.md")):
        document = _parse_markdown(path)
        if document.metadata.get("eidos_version") in {
            "1",
            "2",
        } and document.metadata.get("status") not in {"done", "failed", "cancelled"}:
            open_work.append(path.name)
    return open_work


def _upgrade_v2(root: Path, context: dict[str, Any]) -> tuple[str, str]:
    project = context.get("project")
    if not isinstance(project, dict) or not PROJECT_RE.fullmatch(
        str(project.get("id", ""))
    ):
        raise KitError("project_id", "Legacy context project.id is invalid.")
    project_id = str(project["id"])
    project_name = str(project.get("name", project_id)).strip() or project_id
    open_work = _legacy_open_work(root, context)
    if open_work:
        raise KitError(
            "legacy_open_work",
            f"Close or explicitly migrate legacy open Work first: {open_work[0]}",
        )
    eidos = context.get("eidos")
    if not isinstance(eidos, dict):
        raise KitError("context_invalid", "Legacy context eidos object is missing.")
    direction_path = _project_path(
        root,
        eidos.get("direction_path", ".agents/eidos/direction.md"),
        "eidos.direction_path",
    )
    archive_root = _project_path(
        root,
        eidos.get("archive_root", ".agents/eidos/archive"),
        "eidos.archive_root",
    )
    old_bytes = direction_path.read_bytes()
    old = _parse_markdown(direction_path)
    if old.metadata.get("eidos_version") not in {"1", "2"}:
        raise KitError("migration_version", "Legacy Direction must use Eidos v1 or v2.")
    revision = old.metadata.get("revision", "")
    match = REVISION_RE.fullmatch(revision)
    if match is None or int(match.group("number")) >= 9999:
        raise KitError(
            "direction_revision", "Legacy Direction revision is invalid or exhausted."
        )
    archive = archive_root / f"{revision}.md"
    if archive.exists():
        raise KitError(
            "archive_collision", f"Direction archive already exists: {archive}"
        )
    if (root / MANIFEST_PATH).exists():
        raise KitError(
            "manifest_collision",
            "A kit manifest already exists in the legacy installation.",
        )
    next_revision = f"D{int(match.group('number')) + 1:04d}"
    new_direction = _migration_direction(old, next_revision, project_id)
    rendered = _rendered_files(project_id, project_name)
    rendered[".agents/eidos/direction.md"] = new_direction
    updated_context = dict(context)
    updated_context["schema_version"] = 2
    updated_eidos = dict(eidos)
    updated_eidos["version"] = 3
    updated_context["eidos"] = updated_eidos
    rendered[".agents/context.json"] = (
        json.dumps(updated_context, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    archive_relative = archive.relative_to(root).as_posix()
    manifest_value = _manifest(project_id, project_name, rendered)
    writes = {
        **rendered,
        archive_relative: old_bytes,
        MANIFEST_PATH.as_posix(): _manifest_bytes(manifest_value),
    }
    _atomic_write_set(
        root,
        writes,
        require_absent={archive_relative, MANIFEST_PATH.as_posix()},
    )
    return revision, next_revision


def _validate_installed_context_paths(root: Path, context: dict[str, Any]) -> None:
    eidos = context.get("eidos")
    if not isinstance(eidos, dict):
        raise KitError("context_invalid", "Context eidos object is missing.")
    for key, fallback in (
        ("direction_path", ".agents/eidos/direction.md"),
        ("archive_root", ".agents/eidos/archive"),
        ("work_root", ".agents/eidos/work"),
        ("identity_path", ".agents/eidos/identity.json"),
    ):
        _project_path(root, eidos.get(key, fallback), f"eidos.{key}")


def _validate_upgrade_trust(
    root: Path,
    manifest: dict[str, Any],
    project_id: str,
    project_name: str,
    rendered: dict[str, bytes],
) -> None:
    installed_version = manifest.get("kit_version")
    if installed_version not in {KIT_VERSION, *TRUSTED_PRIOR_RELEASES}:
        raise KitError(
            "upgrade_path", f"Unsupported Eidos Kit version: {installed_version}"
        )
    if any(
        manifest.get(field) != expected
        for field, expected in (
            ("schema_version", 1),
            ("project_id", project_id),
            ("project_name", project_name),
        )
    ):
        raise KitError("manifest_untrusted", "Installed manifest identity changed.")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise KitError("manifest_untrusted", "Installed manifest files are invalid.")
    current_manifest = _manifest(project_id, project_name, rendered)
    release_hashes = _release_descriptor(str(installed_version))["files"]
    expected_paths = set(release_hashes) | {
        ".agents/context.json",
        ".agents/eidos/direction.md",
    }
    if installed_version != "3.0.0":
        expected_paths.add(".agents/eidos/identity.json")
    if set(files) != expected_paths:
        raise KitError("manifest_untrusted", "Installed manifest file set changed.")
    for relative, record in files.items():
        expected = current_manifest["files"].get(relative)
        if (
            not isinstance(record, dict)
            or set(record) != {"ownership", "sha256"}
            or not isinstance(expected, dict)
            or record.get("ownership") != expected.get("ownership")
            or re.fullmatch(r"[a-f0-9]{64}", str(record.get("sha256", ""))) is None
        ):
            raise KitError(
                "manifest_untrusted", f"Untrusted manifest record: {relative}"
            )
        if record["ownership"] != "kit":
            continue
        target = _safe_repository_target(
            root, relative, f"installed kit file {relative}"
        )
        if not target.is_file() or _sha(target.read_bytes()) != record["sha256"]:
            raise KitError(
                "local_modification", f"Installed kit file changed: {relative}"
            )
        trusted_hash = release_hashes.get(relative)
        canonical = target.read_bytes().replace(
            project_id.encode("utf-8"), b"project:example"
        )
        if trusted_hash is None or _sha(canonical) != trusted_hash:
            raise KitError(
                "manifest_untrusted", f"Release trust hash changed: {relative}"
            )


def _command_upgrade(args: argparse.Namespace) -> int:
    root = _check_root(args.root)
    _safe_repository_target(root, ".agents", ".agents")
    context_path = _safe_repository_target(
        root, ".agents/context.json", ".agents/context.json"
    )
    if not context_path.is_file():
        raise KitError(
            "context_missing",
            "Eidos context is missing; use install for a new project.",
        )
    context = _load_json(context_path, "context_invalid")
    _validate_installed_context_paths(root, context)
    version = (
        str(context.get("eidos", {}).get("version", ""))
        if isinstance(context.get("eidos"), dict)
        else ""
    )
    if version in {"1", "2"}:
        previous, current = _upgrade_v2(root, context)
        print(
            f"Migrated Eidos {version} Direction {previous} to v3 {current}; legacy bytes archived unchanged."
        )
        return 0
    if version != "3":
        raise KitError(
            "eidos_version",
            f"Unsupported installed Eidos version: {version or 'missing'}",
        )
    _safe_repository_target(root, MANIFEST_PATH, MANIFEST_PATH.as_posix())
    manifest = _load_manifest(root)
    project_id = str(
        context.get("project", {}).get("id", manifest.get("project_id", ""))
    )
    project_name = str(
        context.get("project", {}).get("name", manifest.get("project_name", ""))
    )
    if not PROJECT_RE.fullmatch(project_id):
        raise KitError("project_id", "Installed context project.id is invalid.")
    if not project_name.strip():
        raise KitError("project_name", "Installed context project.name is required.")
    rendered = _rendered_files(project_id, project_name)
    _validate_upgrade_trust(root, manifest, project_id, project_name, rendered)
    for relative in (*rendered, MANIFEST_PATH.as_posix()):
        _safe_repository_target(root, relative, relative)
    old_files = manifest.get("files", {})
    conflicts: list[str] = []
    for relative, data in rendered.items():
        if relative in USER_OWNED:
            continue
        target = root / relative
        old = old_files.get(relative) if isinstance(old_files, dict) else None
        if (
            target.exists()
            and isinstance(old, dict)
            and _sha(target.read_bytes()) != old.get("sha256")
        ):
            conflicts.append(relative)
        elif target.exists() and old is None and target.read_bytes() != data:
            conflicts.append(relative)
    if conflicts:
        raise KitError(
            "local_modification",
            f"Refusing to overwrite locally modified kit path: {conflicts[0]}",
        )
    # Preserve current hashes for project-owned records while refreshing kit-owned entries.
    manifest_data = _manifest(project_id, project_name, rendered)
    for relative in USER_OWNED:
        target = root / relative
        if target.is_file():
            manifest_data["files"][relative]["sha256"] = _sha(target.read_bytes())
    # A newly introduced project-owned template is created once, then preserved.
    # Existing project-owned files are never rewritten by upgrade.
    writes = {
        relative: data
        for relative, data in rendered.items()
        if relative not in USER_OWNED or not (root / relative).exists()
    }
    writes[MANIFEST_PATH.as_posix()] = _manifest_bytes(manifest_data)
    _atomic_write_set(root, writes)
    print(f"Eidos kit is at {KIT_VERSION}.")
    return 0


def _diff_data(root: Path) -> dict[str, Any]:
    manifest = _load_manifest(root)
    files = manifest.get("files", {})
    rows: list[dict[str, Any]] = []
    for relative, record in sorted(files.items()):
        target = _safe_repository_target(root, relative, f"manifest file {relative}")
        expected = record.get("sha256") if isinstance(record, dict) else None
        actual = _sha(target.read_bytes()) if target.is_file() else None
        rows.append(
            {
                "path": relative,
                "ownership": record.get("ownership")
                if isinstance(record, dict)
                else None,
                "status": "missing"
                if actual is None
                else "unchanged"
                if actual == expected
                else "modified",
                "expected_sha256": expected,
                "actual_sha256": actual,
            }
        )
    return {"kit_version": manifest.get("kit_version"), "files": rows}


def _doctor_trust_data(root: Path) -> dict[str, Any]:
    """Verify kit bytes against this manager's source, not the target manifest."""

    context_path = _safe_repository_target(
        root, ".agents/context.json", ".agents/context.json"
    )
    context = _load_json(context_path, "context_invalid")
    _validate_installed_context_paths(root, context)
    project = context.get("project")
    if not isinstance(project, dict):
        raise KitError("context_invalid", "Context project object is missing.")
    project_id = str(project.get("id", ""))
    project_name = str(project.get("name", ""))
    if not PROJECT_RE.fullmatch(project_id):
        raise KitError("project_id", "Installed context project.id is invalid.")
    if not project_name.strip():
        raise KitError("project_name", "Installed context project.name is required.")
    eidos = context.get("eidos")
    if not isinstance(eidos, dict) or eidos.get("version") != 3:
        raise KitError("eidos_version", "Doctor requires an installed Eidos v3 kit.")

    rendered = _rendered_files(project_id, project_name)
    trusted = _manifest(project_id, project_name, rendered)
    target = _load_manifest(root)
    if set(target) != set(trusted) or any(
        target.get(field) != trusted.get(field)
        for field in ("schema_version", "kit_version", "project_id", "project_name")
    ):
        raise KitError(
            "manifest_untrusted",
            "The target manifest header does not match this kit manager and context.",
        )
    target_files = target.get("files")
    trusted_files = trusted["files"]
    if not isinstance(target_files, dict) or set(target_files) != set(trusted_files):
        raise KitError(
            "manifest_untrusted",
            "The target manifest file set does not match this kit manager.",
        )

    rows: list[dict[str, Any]] = []
    for relative, expected_record in sorted(trusted_files.items()):
        record = target_files.get(relative)
        if (
            not isinstance(record, dict)
            or set(record) != {"ownership", "sha256"}
            or record.get("ownership") != expected_record["ownership"]
            or not isinstance(record.get("sha256"), str)
            or re.fullmatch(r"[a-f0-9]{64}", record["sha256"]) is None
        ):
            raise KitError(
                "manifest_untrusted",
                f"The target manifest record is invalid: {relative}",
            )
        if (
            expected_record["ownership"] == "kit"
            and record["sha256"] != expected_record["sha256"]
        ):
            raise KitError(
                "manifest_untrusted",
                f"The target manifest changed a manager-owned trust hash: {relative}",
            )
        target_path = _safe_repository_target(
            root, relative, f"trusted kit file {relative}"
        )
        actual = _sha(target_path.read_bytes()) if target_path.is_file() else None
        expected = expected_record["sha256"]
        rows.append(
            {
                "path": relative,
                "ownership": expected_record["ownership"],
                "status": "missing"
                if actual is None
                else "unchanged"
                if expected_record["ownership"] == "project" or actual == expected
                else "modified",
                "expected_sha256": expected,
                "actual_sha256": actual,
            }
        )
    return {"kit_version": KIT_VERSION, "files": rows}


def _command_diff(args: argparse.Namespace) -> int:
    root = _check_root(args.root)
    data = _diff_data(root)
    changed = [
        row
        for row in data["files"]
        if row["ownership"] == "kit" and row["status"] != "unchanged"
    ]
    if args.json:
        print(
            json.dumps(
                {"ok": not changed, "data": data},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
    else:
        for row in data["files"]:
            print(f"{row['status']:9} {row['ownership']:7} {row['path']}")
    return 1 if changed else 0


def _command_doctor(args: argparse.Namespace) -> int:
    findings: list[dict[str, str]] = []
    execution_allowed = True
    try:
        root = _check_root(args.root)
    except KitError as exc:
        findings.append({"severity": "error", "code": exc.code, "message": exc.message})
        root = args.root.resolve()
        execution_allowed = False
    tool: Path | None = None
    if execution_allowed:
        try:
            _safe_repository_target(root, ".agents", ".agents")
            _safe_repository_target(root, MANIFEST_PATH, "kit manifest")
            tool = _safe_repository_target(
                root, ".agents/tools/eidos.py", "installed Eidos tool"
            )
        except KitError as exc:
            findings.append(
                {"severity": "error", "code": exc.code, "message": exc.message}
            )
            execution_allowed = False
    if execution_allowed:
        try:
            data = _doctor_trust_data(root)
        except KitError as exc:
            findings.append(
                {"severity": "error", "code": exc.code, "message": exc.message}
            )
            execution_allowed = False
        else:
            for row in data["files"]:
                if row["ownership"] == "kit" and row["status"] != "unchanged":
                    findings.append(
                        {
                            "severity": "error",
                            "code": f"kit_{row['status']}",
                            "message": row["path"],
                        }
                    )
                    execution_allowed = False
    if execution_allowed and tool is not None and tool.is_file():
        result = subprocess.run(
            [sys.executable, str(tool), "validate", "--root", str(root), "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode != 0:
            findings.append(
                {
                    "severity": "error",
                    "code": "project_invalid",
                    "message": result.stdout.strip() or result.stderr.strip(),
                }
            )
    elif execution_allowed:
        findings.append(
            {
                "severity": "error",
                "code": "tool_missing",
                "message": ".agents/tools/eidos.py",
            }
        )
    if execution_allowed and tool is not None and tool.is_file():
        claim_result = subprocess.run(
            [
                sys.executable,
                str(tool),
                "claim",
                "list",
                "--root",
                str(root),
                "--json",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        try:
            claim_payload = json.loads(claim_result.stdout)
        except json.JSONDecodeError:
            findings.append(
                {
                    "severity": "error",
                    "code": "claim_list_invalid",
                    "message": claim_result.stderr.strip()
                    or "Claim list did not return valid JSON.",
                }
            )
        else:
            if not isinstance(claim_payload, dict):
                findings.append(
                    {
                        "severity": "error",
                        "code": "claim_list_invalid",
                        "message": "Claim list output must be a JSON object.",
                    }
                )
            else:
                for item in claim_payload.get("findings", []):
                    if isinstance(item, dict):
                        findings.append(
                            {
                                "severity": str(item.get("severity", "error")),
                                "code": str(item.get("code", "claim_invalid")),
                                "message": str(item.get("message", "Invalid claim.")),
                            }
                        )
                for claim in claim_payload.get("claims", []):
                    if isinstance(claim, dict) and claim.get("orphaned_dirty") is True:
                        findings.append(
                            {
                                "severity": "warning",
                                "code": "claim_orphaned_dirty",
                                "message": str(claim.get("claim_id", "unknown")),
                            }
                        )
                for conflict in claim_payload.get("conflicts", []):
                    if isinstance(conflict, dict):
                        findings.append(
                            {
                                "severity": "error",
                                "code": "claim_conflict",
                                "message": f"{conflict.get('left_claim_id')} / {conflict.get('right_claim_id')}",
                            }
                        )
    payload = {
        "ok": not any(item["severity"] == "error" for item in findings),
        "findings": findings,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for finding in findings:
            print(
                f"{finding['severity'].upper()} {finding['code']}: {finding['message']}"
            )
        print("Eidos kit doctor: ok" if payload["ok"] else "Eidos kit doctor: failed")
    return 0 if payload["ok"] else 2


def _add_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", type=Path, default=Path.cwd())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Eidos v3 kit manager")
    sub = parser.add_subparsers(dest="command", required=True)
    install = sub.add_parser("install")
    _add_root(install)
    install.add_argument("--project-id", required=True)
    install.add_argument("--project-name", required=True)
    install.set_defaults(handler=_command_install)
    migrate = sub.add_parser("migrate")
    _add_root(migrate)
    migrate.add_argument("--project-id", required=True)
    migrate.add_argument("--project-name", required=True)
    migrate.set_defaults(handler=_command_migrate)
    upgrade = sub.add_parser("upgrade")
    _add_root(upgrade)
    upgrade.set_defaults(handler=_command_upgrade)
    diff = sub.add_parser("diff")
    _add_root(diff)
    diff.add_argument("--json", action="store_true")
    diff.set_defaults(handler=_command_diff)
    doctor = sub.add_parser("doctor")
    _add_root(doctor)
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(handler=_command_doctor)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.handler(args))
    except KitError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
