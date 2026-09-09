#!/usr/bin/env python3
"""Install, upgrade, and inspect the portable Harness Kit v1."""

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
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any


KIT_VERSION = "1.7.0"
TRUSTED_PRIOR_RELEASES = frozenset(
    {"1.0.0", "1.1.0", "1.2.0", "1.3.0", "1.4.0", "1.4.1", "1.5.0", "1.6.0"}
)
MANIFEST_PATH = Path(".agents/harness/kit-manifest.json")
PROJECT_RE = re.compile(r"^project:[a-z0-9]+(?:-[a-z0-9]+)*$")
USER_OWNED = {
    "AGENTS.md",
    "FAILURE_LOG.md",
    ".agents/context.json",
    ".agents/routing.md",
    ".agents/eidos/direction.md",
    ".agents/eidos/identity.json",
}
MIGRATION_EXTENSION_ROOTS = (
    ".agents/eidos/archive",
    ".agents/eidos/work",
    ".agents/failures",
    ".agents/routes",
)
MAX_MIGRATION_EXTENSION_FILES = 2048
MAX_MIGRATION_EXTENSION_BYTES = 32 * 1024 * 1024
MISPLACED_ROOT_CACHES = {
    ".mypy_cache": ".cache/mypy",
    ".pytest_cache": ".cache/pytest",
    ".ruff_cache": ".cache/ruff",
}
REQUIREMENTS_RELEASE_PATHS = frozenset(
    {
        ".agents/harness/requirements.md",
        ".agents/harness/requirements.example.json",
        ".agents/tools/requirements.py",
    }
)
HARNESS_RELEASE_PATHS = REQUIREMENTS_RELEASE_PATHS | frozenset(
    {
        "CLAUDE.md",
        ".agents/harness/contract.md",
        ".agents/harness/repository-layout.md",
        ".agents/failures/_template.md",
        ".agents/routes/_template.md",
        ".agents/rubrics/common-change.md",
        ".agents/rubrics/public-contract.md",
        ".agents/rubrics/artifact-or-model.md",
        ".agents/rubrics/release-or-external.md",
        ".agents/skills/project-harness/SKILL.md",
        ".agents/tools/harness.py",
        ".agents/workflows/change.md",
        ".agents/workflows/verification.md",
        ".claude/skills/project-harness/SKILL.md",
    }
)


class HarnessKitError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class FileSnapshot:
    existed: bool
    data: bytes | None
    mode: int | None


def _root() -> Path:
    return Path(__file__).resolve().parent


def _template_root() -> Path:
    return _root() / "template"


def _release_descriptor(version: str) -> dict[str, Any]:
    path = _root() / "release-manifests" / f"{version}.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HarnessKitError(
            "upgrade_path", f"Trusted release descriptor is unavailable: {version}"
        ) from exc
    if (
        not isinstance(value, dict)
        or value.get("kit_version") != version
        or value.get("schema_version") != 1
        or not isinstance(value.get("files"), dict)
        or set(value["files"])
        != (
            HARNESS_RELEASE_PATHS
            - REQUIREMENTS_RELEASE_PATHS
            - (
                {".agents/harness/repository-layout.md"}
                if version != "1.6.0"
                else set()
            )
            if version in TRUSTED_PRIOR_RELEASES
            else HARNESS_RELEASE_PATHS
        )
        or any(
            not isinstance(digest, str) or re.fullmatch(r"[a-f0-9]{64}", digest) is None
            for digest in value["files"].values()
        )
        or not isinstance(value.get("eidos"), dict)
        or not isinstance(value["eidos"].get("kit_version"), str)
        or not isinstance(value["eidos"].get("files"), dict)
        or any(
            not isinstance(relative, str)
            or not isinstance(digest, str)
            or re.fullmatch(r"[a-f0-9]{64}", digest) is None
            for relative, digest in value["eidos"].get("files", {}).items()
        )
    ):
        raise HarnessKitError("upgrade_path", f"Invalid release descriptor: {version}")
    return value


def _release_hashes(version: str) -> dict[str, str]:
    descriptor = _release_descriptor(version)
    return descriptor["files"]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: Any) -> bytes:
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


def _safe_target(root: Path, relative: str, label: str) -> Path:
    raw = relative.replace("\\", "/")
    candidate = Path(raw)
    if (
        not raw.strip()
        or candidate.is_absolute()
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise HarnessKitError("path_invalid", f"Unsafe {label}: {relative}")
    current = root
    for part in candidate.parts:
        current /= part
        if (current.exists() or current.is_symlink()) and _is_reparse(current):
            raise HarnessKitError(
                "path_reparse", f"{label} traverses a reparse point: {current}"
            )
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise HarnessKitError(
            "path_escape", f"{label} escapes the repository."
        ) from exc
    return root / candidate


def _git(root: Path, *arguments: str) -> str:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        check=False,
    )
    if result.returncode != 0:
        raise HarnessKitError(
            "not_git_repository",
            result.stderr.strip() or "Target is not a Git repository.",
        )
    return result.stdout.strip()


def _check_root(raw: Path) -> Path:
    absolute = Path(os.path.abspath(raw))
    for component in (absolute, *absolute.parents):
        if (component.exists() or component.is_symlink()) and _is_reparse(component):
            raise HarnessKitError(
                "root_reparse", f"--root traverses a reparse point: {component}"
            )
    root = absolute.resolve()
    if not root.is_dir():
        raise HarnessKitError("root_missing", f"Target root does not exist: {root}")
    top = Path(_git(root, "rev-parse", "--show-toplevel")).resolve()
    if top != root:
        raise HarnessKitError("root_not_toplevel", "--root must be the Git top level.")
    _safe_target(root, ".agents", ".agents")
    _safe_target(root, ".claude", ".claude")
    return root


def _template_files() -> list[Path]:
    return sorted(
        (
            path
            for path in _template_root().rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix not in {".pyc", ".pyo"}
        ),
        key=lambda item: item.relative_to(_template_root()).as_posix(),
    )


def _render_harness(
    project_id: str,
    project_name: str,
    eidos: bool,
    eidos_tool_sha256: str | None = None,
) -> dict[str, bytes]:
    if eidos:
        if (
            not isinstance(eidos_tool_sha256, str)
            or re.fullmatch(r"[a-f0-9]{64}", eidos_tool_sha256) is None
        ):
            raise HarnessKitError(
                "eidos_render", "The trusted Eidos tool digest is invalid."
            )
    else:
        eidos_tool_sha256 = "0" * 64
    rendered: dict[str, bytes] = {}
    for source in _template_files():
        relative = source.relative_to(_template_root()).as_posix()
        text = source.read_text(encoding="utf-8")
        if relative == ".agents/context.json":
            context = json.loads(text)
            context["project"] = {"id": project_id, "name": project_name}
            rendered[relative] = _json_bytes(context)
            continue
        text = text.replace("project:example", project_id).replace(
            "Example Project", project_name
        )
        text = text.replace("{{EIDOS_ENABLED}}", "true" if eidos else "false")
        text = text.replace("{{EIDOS_TOOL_SHA256}}", eidos_tool_sha256)
        rendered[relative] = text.encode("utf-8")
    return rendered


def _load_eidos_module():
    source = _root().parents[1] / "eidos" / "v3" / "eidos_kit.py"
    if not source.is_file() or _is_reparse(source):
        raise HarnessKitError(
            "eidos_source", "Trusted Eidos v3 manager is unavailable."
        )
    name = f"_harness_eidos_{os.getpid()}_{id(source)}"
    module = types.ModuleType(name)
    module.__file__ = str(source)
    sys.modules[name] = module
    try:
        code = compile(source.read_bytes(), str(source), "exec")
        exec(code, module.__dict__)
    except Exception as exc:
        raise HarnessKitError(
            "eidos_source", "Cannot load trusted Eidos v3 manager."
        ) from exc
    return module


def _combined_render(
    project_id: str, project_name: str, eidos: bool
) -> dict[str, bytes]:
    eidos_files: dict[str, bytes] = {}
    eidos_version: str | None = None
    eidos_digest: str | None = None
    eidos_tool_sha256: str | None = None
    if eidos:
        module = _load_eidos_module()
        try:
            eidos_files = module.render_installation(project_id, project_name)
        except Exception as exc:
            raise HarnessKitError("eidos_render", str(exc)) from exc
        eidos_manifest_path = ".agents/eidos/kit-manifest.json"
        eidos_manifest = json.loads(eidos_files[eidos_manifest_path].decode("utf-8"))
        eidos_tool_path = ".agents/tools/eidos.py"
        eidos_tool_record = eidos_manifest.get("files", {}).get(eidos_tool_path)
        if (
            not isinstance(eidos_tool_record, dict)
            or eidos_tool_record.get("ownership") != "kit"
            or eidos_tool_record.get("sha256")
            != _sha(eidos_files.get(eidos_tool_path, b""))
        ):
            raise HarnessKitError(
                "eidos_render", "Rendered Eidos tool trust binding is invalid."
            )
        eidos_tool_sha256 = eidos_tool_record["sha256"]
    rendered = _render_harness(project_id, project_name, eidos, eidos_tool_sha256)
    if eidos:
        overlap = set(rendered) & set(eidos_files)
        allowed = {".agents/context.json"}
        if overlap - allowed:
            raise HarnessKitError(
                "composition_collision",
                f"Harness and Eidos templates overlap: {sorted(overlap - allowed)[0]}",
            )
        eidos_context = json.loads(eidos_files[".agents/context.json"].decode("utf-8"))
        eidos_context["harness"] = {
            "version": 1,
            "eidos_enabled": True,
            "routing_path": ".agents/routing.md",
            "failure_root": ".agents/failures",
        }
        eidos_files[".agents/context.json"] = _json_bytes(eidos_context)
        eidos_manifest["files"][".agents/context.json"]["sha256"] = _sha(
            eidos_files[".agents/context.json"]
        )
        eidos_files[eidos_manifest_path] = _json_bytes(eidos_manifest)
        eidos_version = str(eidos_manifest["kit_version"])
        eidos_digest = _sha(eidos_files[eidos_manifest_path])
        rendered.update(eidos_files)
    else:
        context = json.loads(rendered[".agents/context.json"].decode("utf-8"))
        context["harness"] = {
            "version": 1,
            "eidos_enabled": False,
            "routing_path": ".agents/routing.md",
            "failure_root": ".agents/failures",
        }
        rendered[".agents/context.json"] = _json_bytes(context)
    manifest = {
        "schema_version": 1,
        "kit_version": KIT_VERSION,
        "project_id": project_id,
        "project_name": project_name,
        "eidos": {
            "enabled": eidos,
            "kit_version": eidos_version,
            "manifest_sha256": eidos_digest,
        },
        "files": {
            relative: {
                "sha256": _sha(data),
                "mode": "100644",
                "ownership": "project" if relative in USER_OWNED else "kit",
            }
            for relative, data in sorted(rendered.items())
        },
    }
    rendered[MANIFEST_PATH.as_posix()] = _json_bytes(manifest)
    return rendered


def _replace(path: Path, data: bytes, expected: FileSnapshot | None = None) -> None:
    if expected is None or not expected.existed:
        raise HarnessKitError(
            "replace_contract", "Replacement requires an existing snapshot."
        )
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
        temporary.chmod(0o644)
        # Rename first, then compare the exact displaced inode. This closes the
        # check/replace race: a concurrent pre-rename edit is inspected in backup,
        # while a concurrent recreation makes the exclusive hard-link fail.
        os.rename(path, backup)
        displaced = True
        if (
            backup.read_bytes() != expected.data
            or stat.S_IMODE(backup.stat().st_mode) != expected.mode
        ):
            raise HarnessKitError(
                "concurrent_modification", f"Target changed during upgrade: {path}"
            )
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise HarnessKitError(
                "concurrent_modification", f"Target changed during upgrade: {path}"
            ) from exc
        published = True
        temporary.unlink()
        backup.unlink()
        displaced = False
    finally:
        if displaced and backup.exists():
            if published and path.is_file() and path.read_bytes() == data:
                path.unlink()
                published = False
            if not path.exists():
                os.rename(backup, path)
        if temporary.exists():
            temporary.unlink()
        if backup.exists() and not path.exists():
            os.rename(backup, path)


def _write_exclusive(path: Path, data: bytes, on_created=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise HarnessKitError(
            "target_exists", f"Refusing to overwrite: {path}"
        ) from exc
    if on_created is not None:
        on_created()
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)


def _atomic_write_set(
    root: Path,
    writes: dict[str, bytes],
    *,
    require_absent: bool = False,
    require_absent_paths: frozenset[str] = frozenset(),
    migration_guards: dict[str, FileSnapshot] | None = None,
    stable_guards: dict[str, FileSnapshot] | None = None,
) -> None:
    targets = {
        relative: _safe_target(root, relative, f"target {relative}")
        for relative in writes
    }
    snapshots: dict[str, FileSnapshot] = {}
    created_by_this_transaction: set[str] = set()
    written_by_this_transaction: set[str] = set()
    existing_directories: set[Path] = set()
    for relative, target in targets.items():
        if target.exists() and not target.is_file():
            raise HarnessKitError("target_type", f"Target is not a file: {relative}")
        if (require_absent or relative in require_absent_paths) and target.exists():
            raise HarnessKitError("target_exists", f"Refusing to overwrite: {relative}")
        snapshots[relative] = FileSnapshot(
            target.is_file(),
            target.read_bytes() if target.is_file() else None,
            stat.S_IMODE(target.stat().st_mode) if target.is_file() else None,
        )
        parent = target.parent
        while parent != root:
            if parent.is_dir():
                existing_directories.add(parent)
            parent = parent.parent

    def assert_migration_guards() -> None:
        if migration_guards is None:
            return
        current = _migration_validation_files(root, writes)
        if current != migration_guards:
            raise HarnessKitError(
                "concurrent_modification",
                "Migration control extensions changed during installation.",
            )

    def assert_stable_guards() -> None:
        if stable_guards is None:
            return
        for relative, expected in stable_guards.items():
            target = _safe_target(root, relative, f"stable managed file {relative}")
            if target.exists() and not target.is_file():
                raise HarnessKitError(
                    "concurrent_modification",
                    f"Managed file changed during upgrade: {relative}",
                )
            actual = FileSnapshot(
                target.is_file(),
                target.read_bytes() if target.is_file() else None,
                stat.S_IMODE(target.stat().st_mode) if target.is_file() else None,
            )
            if actual != expected:
                raise HarnessKitError(
                    "concurrent_modification",
                    f"Managed file changed during upgrade: {relative}",
                )

    try:
        assert_migration_guards()
        assert_stable_guards()
        for relative, data in writes.items():
            target = targets[relative]
            if require_absent or relative in require_absent_paths:
                _write_exclusive(
                    target,
                    data,
                    lambda relative=relative: created_by_this_transaction.add(relative),
                )
            elif not snapshots[relative].existed:
                _write_exclusive(
                    target,
                    data,
                    lambda relative=relative: created_by_this_transaction.add(relative),
                )
                written_by_this_transaction.add(relative)
            else:
                written_by_this_transaction.add(relative)
                _replace(target, data, snapshots[relative])
            if not require_absent and not snapshots[relative].existed:
                created_by_this_transaction.add(relative)
            assert_migration_guards()
            assert_stable_guards()
        assert_migration_guards()
        assert_stable_guards()
    except Exception:
        for relative in reversed(list(writes)):
            target = targets[relative]
            snapshot = snapshots[relative]
            if snapshot.existed and relative in written_by_this_transaction:
                if target.is_file() and target.read_bytes() != writes[relative]:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(snapshot.data or b"")
                if snapshot.mode is not None:
                    target.chmod(snapshot.mode)
            elif relative in created_by_this_transaction and (
                target.is_file() or target.is_symlink()
            ):
                target.unlink()
        directories = {
            parent
            for target in targets.values()
            for parent in target.parents
            if parent != root and root in parent.parents
        }
        for directory in sorted(
            directories - existing_directories,
            key=lambda value: len(value.parts),
            reverse=True,
        ):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise


def _load_manifest(root: Path) -> dict[str, Any]:
    path = _safe_target(root, MANIFEST_PATH.as_posix(), "Harness manifest")
    if not path.is_file():
        raise HarnessKitError("manifest_missing", "Harness Kit manifest is missing.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HarnessKitError(
            "manifest_invalid", "Harness manifest is invalid."
        ) from exc
    if (
        not isinstance(value, dict)
        or type(value.get("schema_version")) is not int
        or value.get("schema_version") != 1
        or not isinstance(value.get("files"), dict)
    ):
        raise HarnessKitError("manifest_invalid", "Harness manifest schema is invalid.")
    return value


def _validate_identity(project_id: str, project_name: str) -> tuple[str, str]:
    if not PROJECT_RE.fullmatch(project_id):
        raise HarnessKitError("project_id", "--project-id must use project:<kebab-id>.")
    project_name = project_name.strip()
    if not project_name or any(ord(character) < 32 for character in project_name):
        raise HarnessKitError("project_name", "--project-name is required.")
    return project_id, project_name


def _migration_validation_files(
    root: Path, writes: dict[str, bytes]
) -> dict[str, FileSnapshot]:
    """Read unmanaged control extensions needed to validate the final migrated tree."""

    files: dict[str, FileSnapshot] = {}
    total_bytes = 0
    pending = [root / relative for relative in MIGRATION_EXTENSION_ROOTS]
    while pending:
        directory = pending.pop()
        if not os.path.lexists(directory):
            continue
        if _is_reparse(directory) or not directory.is_dir():
            relative = directory.relative_to(root).as_posix()
            raise HarnessKitError(
                "migration_extension", f"Unsafe migration extension: {relative}"
            )
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            raise HarnessKitError(
                "migration_extension",
                f"Cannot inspect migration extension: {directory}",
            ) from exc
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            _safe_target(root, relative, f"migration extension {relative}")
            if entry.is_symlink() or _is_reparse(path):
                raise HarnessKitError(
                    "migration_extension", f"Unsafe migration extension: {relative}"
                )
            if entry.is_dir(follow_symlinks=False):
                pending.append(path)
                continue
            if not entry.is_file(follow_symlinks=False) or relative in writes:
                continue
            if path.suffix.casefold() != ".md":
                continue
            try:
                data = path.read_bytes()
            except OSError as exc:
                raise HarnessKitError(
                    "migration_extension",
                    f"Cannot read migration extension: {relative}",
                ) from exc
            total_bytes += len(data)
            if (
                len(files) >= MAX_MIGRATION_EXTENSION_FILES
                or total_bytes > MAX_MIGRATION_EXTENSION_BYTES
            ):
                raise HarnessKitError(
                    "migration_extension", "Migration control extensions exceed bounds."
                )
            files[relative] = FileSnapshot(
                existed=True,
                data=data,
                mode=stat.S_IMODE(path.stat().st_mode),
            )
    return files


def _semantic_validate(
    writes: dict[str, bytes],
    eidos_enabled: bool,
    *,
    migration_files: dict[str, FileSnapshot] | None = None,
) -> None:
    """Validate the complete candidate tree before touching the target repository."""

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw) / "candidate"
        root.mkdir()
        initialized = subprocess.run(
            ["git", "-C", str(root), "init", "--quiet"],
            capture_output=True,
            check=False,
        )
        if initialized.returncode != 0:
            raise HarnessKitError(
                "candidate_git", "Cannot initialize validation repository."
            )
        candidate_files = {
            relative: snapshot.data or b""
            for relative, snapshot in (migration_files or {}).items()
        }
        candidate_files.update(writes)
        for relative, data in candidate_files.items():
            target = _safe_target(root, relative, f"candidate {relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        tools = [(".agents/tools/harness.py", ["validate", "--json"])]
        if eidos_enabled:
            tools.append((".agents/tools/eidos.py", ["validate", "--json"]))
        for relative, arguments in tools:
            tool = root / relative
            result = subprocess.run(
                [sys.executable, "-B", str(tool), *arguments, "--root", str(root)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError:
                payload = {"ok": False}
            if result.returncode != 0 or payload.get("ok") is not True:
                raise HarnessKitError(
                    "candidate_invalid",
                    f"Candidate validation failed for {relative}: "
                    f"{result.stdout.strip() or result.stderr.strip()}",
                )


def _command_install(args: argparse.Namespace) -> int:
    root = _check_root(args.root)
    project_id, project_name = _validate_identity(args.project_id, args.project_name)
    if (root / MANIFEST_PATH).exists():
        raise HarnessKitError("managed_target", "Harness Kit is already installed.")
    writes = _combined_render(project_id, project_name, not args.without_eidos)
    collisions = [relative for relative in writes if (root / relative).exists()]
    if collisions:
        raise HarnessKitError(
            "target_exists", f"Install would overwrite: {sorted(collisions)[0]}"
        )
    _semantic_validate(writes, not args.without_eidos)
    _atomic_write_set(root, writes, require_absent=True)
    print(f"Installed Harness Kit {KIT_VERSION} ({len(writes) - 1} managed files).")
    return 0


def _adopted_migration_writes(
    root: Path, project_id: str, project_name: str, eidos: bool
) -> dict[str, bytes]:
    """Render a migration while preserving only declared project-owned bytes."""

    writes = _combined_render(project_id, project_name, eidos)
    manifest_path = MANIFEST_PATH.as_posix()
    manifest = json.loads(writes[manifest_path].decode("utf-8"))
    eidos_manifest_path = ".agents/eidos/kit-manifest.json"
    existing_eidos = False
    if eidos and os.path.lexists(root / eidos_manifest_path):
        _validate_adoptable_eidos_installation(
            root,
            json.loads(writes[eidos_manifest_path].decode("utf-8")),
            writes,
        )
        existing_eidos = True
    for relative, record in sorted(manifest["files"].items()):
        target = _safe_target(root, relative, f"migration target {relative}")
        if not os.path.lexists(target):
            continue
        if not target.is_file() or _is_reparse(target):
            raise HarnessKitError(
                "migration_collision", f"Migration target is unsafe: {relative}"
            )
        existing = target.read_bytes()
        if record["ownership"] == "project":
            writes[relative] = existing
        elif existing_eidos and relative == eidos_manifest_path:
            # Project-owned hashes legitimately describe an earlier snapshot. The
            # complete standalone installation was authenticated above; rebuild this
            # manifest after adopting the current project bytes.
            continue
        elif existing != writes[relative] or not _mode_is_regular_writable(target):
            raise HarnessKitError(
                "migration_collision",
                f"Existing kit-owned path is not the exact release byte: {relative}",
            )

    if eidos:
        eidos_manifest = json.loads(writes[eidos_manifest_path].decode("utf-8"))
        for relative, record in eidos_manifest["files"].items():
            if record["ownership"] == "project":
                record["sha256"] = _sha(writes[relative])
        writes[eidos_manifest_path] = _json_bytes(eidos_manifest)
        manifest["eidos"]["manifest_sha256"] = _sha(writes[eidos_manifest_path])

    for relative, record in manifest["files"].items():
        record["sha256"] = _sha(writes[relative])
    writes[manifest_path] = _json_bytes(manifest)
    return writes


def _validate_adoptable_eidos_installation(
    root: Path,
    trusted_manifest: dict[str, Any],
    trusted_writes: dict[str, bytes],
) -> None:
    """Authenticate an existing standalone Eidos v3 installation without executing it."""

    relative = ".agents/eidos/kit-manifest.json"
    target = _safe_target(root, relative, "existing Eidos manifest")
    if (
        not target.is_file()
        or _is_reparse(target)
        or not _mode_is_regular_writable(target)
    ):
        raise HarnessKitError(
            "eidos_migration_manifest", "Existing Eidos manifest is unsafe."
        )
    try:
        existing = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HarnessKitError(
            "eidos_migration_manifest", "Existing Eidos manifest is invalid."
        ) from exc
    if (
        not isinstance(existing, dict)
        or set(existing) != set(trusted_manifest)
        or any(
            existing.get(key) != trusted_manifest.get(key)
            for key in ("schema_version", "kit_version", "project_id", "project_name")
        )
        or not isinstance(existing.get("files"), dict)
        or set(existing["files"]) != set(trusted_manifest["files"])
    ):
        raise HarnessKitError(
            "eidos_migration_manifest",
            "Existing Eidos manifest identity or file set is untrusted.",
        )
    for path, trusted_record in trusted_manifest["files"].items():
        record = existing["files"].get(path)
        if (
            not isinstance(record, dict)
            or set(record) != {"ownership", "sha256"}
            or record.get("ownership") != trusted_record.get("ownership")
            or re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", ""))) is None
        ):
            raise HarnessKitError(
                "eidos_migration_manifest",
                f"Existing Eidos manifest record is untrusted: {path}",
            )
        installed = _safe_target(root, path, f"existing Eidos file {path}")
        if (
            not installed.is_file()
            or _is_reparse(installed)
            or not _mode_is_regular_writable(installed)
        ):
            raise HarnessKitError(
                "eidos_migration_manifest", f"Existing Eidos file is unsafe: {path}"
            )
        if trusted_record["ownership"] == "kit" and (
            record["sha256"] != trusted_record["sha256"]
            or installed.read_bytes() != trusted_writes[path]
        ):
            raise HarnessKitError(
                "eidos_migration_manifest",
                f"Existing Eidos kit file is not trusted: {path}",
            )


def _command_migrate(args: argparse.Namespace) -> int:
    root = _check_root(args.root)
    project_id, project_name = _validate_identity(args.project_id, args.project_name)
    if (root / MANIFEST_PATH).exists():
        raise HarnessKitError("managed_target", "Harness Kit is already installed.")
    writes = _adopted_migration_writes(
        root, project_id, project_name, not args.without_eidos
    )
    migration_files = _migration_validation_files(root, writes)
    _semantic_validate(
        writes,
        not args.without_eidos,
        migration_files=migration_files,
    )
    _atomic_write_set(root, writes, migration_guards=migration_files)
    print(f"Migrated Harness Kit {KIT_VERSION} ({len(writes) - 1} managed files).")
    return 0


def _trusted_expected(root: Path, manifest: dict[str, Any]) -> dict[str, bytes]:
    project_id = manifest.get("project_id")
    project_name = manifest.get("project_name")
    eidos = manifest.get("eidos")
    if (
        not isinstance(project_id, str)
        or not isinstance(project_name, str)
        or not isinstance(eidos, dict)
        or not isinstance(eidos.get("enabled"), bool)
    ):
        raise HarnessKitError("manifest_untrusted", "Manifest identity is invalid.")
    rendered = _combined_render(project_id, project_name, eidos["enabled"])
    installed_version = manifest.get("kit_version")
    prior_release = (
        _release_descriptor(str(installed_version))
        if isinstance(installed_version, str)
        and installed_version in TRUSTED_PRIOR_RELEASES
        and installed_version != KIT_VERSION
        else None
    )
    if eidos["enabled"]:
        relative = ".agents/eidos/kit-manifest.json"
        target_path = _safe_target(root, relative, "Eidos manifest")
        if not target_path.is_file():
            raise HarnessKitError("eidos_manifest", "Eidos manifest is missing.")
        try:
            target = json.loads(target_path.read_text(encoding="utf-8"))
            trusted = json.loads(rendered[relative].decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise HarnessKitError(
                "eidos_manifest", "Eidos manifest is invalid."
            ) from exc
        prior_eidos_version = (
            prior_release["eidos"]["kit_version"] if prior_release is not None else None
        )
        current_eidos_version = trusted.get("kit_version")
        for field in ("schema_version", "project_id", "project_name"):
            if target.get(field) != trusted.get(field):
                raise HarnessKitError(
                    "eidos_manifest", f"Eidos manifest field changed: {field}"
                )
        if target.get("kit_version") not in {
            prior_eidos_version,
            current_eidos_version,
        }:
            raise HarnessKitError(
                "eidos_manifest", "Installed Eidos release is not trusted."
            )
        use_prior_eidos = (
            prior_release is not None
            and target.get("kit_version") == prior_eidos_version
        )
        target_files = target.get("files")
        trusted_files = trusted.get("files")
        if not isinstance(target_files, dict) or (
            prior_release is None and set(target_files) != set(trusted_files)
        ):
            raise HarnessKitError(
                "eidos_manifest", "Eidos manifest file set is invalid."
            )
        current_release = _release_descriptor(KIT_VERSION)
        use_current_release_eidos = (
            prior_release is not None
            and not use_prior_eidos
            and target.get("kit_version") == current_release["eidos"]["kit_version"]
        )
        release_eidos_hashes = (
            prior_release["eidos"]["files"]
            if use_prior_eidos
            else current_release["eidos"]["files"]
            if use_current_release_eidos
            else {}
        )
        for path, record in target_files.items():
            expected = trusted_files.get(path)
            record = target_files.get(path)
            expected_release_hash = release_eidos_hashes.get(path)
            actual_release_hash: str | None = None
            if (
                use_prior_eidos or use_current_release_eidos
            ) and expected_release_hash is not None:
                installed_path = _safe_target(
                    root, path, f"installed Eidos file {path}"
                )
                if not installed_path.is_file():
                    raise HarnessKitError(
                        "eidos_manifest", f"Installed Eidos file is missing: {path}"
                    )
                installed_data = installed_path.read_bytes()
                if _sha(installed_data) != record.get("sha256"):
                    raise HarnessKitError(
                        "eidos_manifest", f"Installed Eidos file changed: {path}"
                    )
                canonical_data = installed_data.replace(
                    project_id.encode("utf-8"), b"project:example"
                )
                actual_release_hash = _sha(canonical_data)
            if (
                not isinstance(expected, dict)
                or not isinstance(record, dict)
                or set(record) != {"ownership", "sha256"}
                or record.get("ownership") != expected["ownership"]
                or not isinstance(record.get("sha256"), str)
                or re.fullmatch(r"[a-f0-9]{64}", record["sha256"]) is None
                or (
                    expected["ownership"] == "kit"
                    and (
                        actual_release_hash != expected_release_hash
                        if use_prior_eidos or use_current_release_eidos
                        else record["sha256"] != expected["sha256"]
                    )
                )
            ):
                raise HarnessKitError(
                    "eidos_manifest", f"Eidos manifest record is invalid: {path}"
                )
        if (use_prior_eidos or use_current_release_eidos) and set(
            release_eidos_hashes
        ) != {
            path
            for path, record in target_files.items()
            if record.get("ownership") == "kit"
        }:
            raise HarnessKitError(
                "eidos_manifest", "Installed Eidos release file set is not trusted."
            )
    return rendered


def _mode_is_regular_writable(path: Path) -> bool:
    permissions = stat.S_IMODE(path.stat().st_mode)
    return bool(permissions & stat.S_IWUSR) and not bool(
        permissions & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    )


def _diff_rows(root: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    files = manifest["files"]
    if not isinstance(files, dict):
        raise HarnessKitError("manifest_invalid", "Manifest files must be an object.")
    rows: list[dict[str, Any]] = []
    for relative, record in sorted(files.items()):
        if not isinstance(relative, str) or not isinstance(record, dict):
            raise HarnessKitError(
                "manifest_invalid", "Manifest file record is invalid."
            )
        target = _safe_target(root, relative, f"manifest file {relative}")
        actual = _sha(target.read_bytes()) if target.is_file() else None
        permissions = stat.S_IMODE(target.stat().st_mode) if target.is_file() else None
        mode_ok = target.is_file() and _mode_is_regular_writable(target)
        expected = record.get("sha256")
        rows.append(
            {
                "path": relative,
                "ownership": record.get("ownership"),
                "status": "missing"
                if actual is None
                else "unchanged"
                if actual == expected and mode_ok and record.get("mode") == "100644"
                else "modified",
                "expected_sha256": expected,
                "actual_sha256": actual,
                "actual_permissions": oct(permissions)
                if permissions is not None
                else None,
            }
        )
    return rows


def _command_upgrade(args: argparse.Namespace) -> int:
    root = _check_root(args.root)
    current = _load_manifest(root)
    _validate_manifest_trust(root, current)
    expected_writes = _trusted_expected(root, current)
    expected_manifest = json.loads(expected_writes[MANIFEST_PATH.as_posix()].decode())
    old_files = current["files"]
    if not set(old_files).issubset(expected_manifest["files"]):
        raise HarnessKitError(
            "upgrade_path", "Upgrade cannot remove prior managed paths implicitly."
        )
    conflicts: list[str] = []
    for relative, record in sorted(old_files.items()):
        if not isinstance(record, dict):
            raise HarnessKitError(
                "manifest_invalid", "Manifest file record is invalid."
            )
        target = _safe_target(root, relative, f"managed file {relative}")
        if not target.is_file():
            conflicts.append(relative)
        elif record.get("ownership") == "kit" and (
            _sha(target.read_bytes()) != record.get("sha256")
            or not _mode_is_regular_writable(target)
        ):
            conflicts.append(relative)
    if conflicts:
        raise HarnessKitError(
            "local_modification",
            f"Refusing to overwrite modified managed path: {conflicts[0]}",
        )
    for relative, record in expected_manifest["files"].items():
        if record["ownership"] == "project":
            target = root / relative
            if not target.is_file():
                if relative in old_files:
                    raise HarnessKitError(
                        "project_file_missing",
                        f"Project-owned path is missing: {relative}",
                    )
                # New project-owned paths are initialized once from the release
                # template and become project-owned immediately after upgrade.
                continue
            expected_writes[relative] = target.read_bytes()
            record["sha256"] = _sha(target.read_bytes())
    eidos_manifest_path = ".agents/eidos/kit-manifest.json"
    if expected_manifest["eidos"]["enabled"]:
        # Keep the project-owned Direction/context hashes consistent in the Eidos manifest.
        eidos_manifest = json.loads(expected_writes[eidos_manifest_path].decode())
        for relative in (
            ".agents/context.json",
            ".agents/eidos/direction.md",
            ".agents/eidos/identity.json",
        ):
            target = root / relative
            if target.is_file():
                eidos_manifest["files"][relative]["sha256"] = _sha(target.read_bytes())
        expected_writes[eidos_manifest_path] = _json_bytes(eidos_manifest)
        expected_manifest["eidos"]["manifest_sha256"] = _sha(
            expected_writes[eidos_manifest_path]
        )
        expected_manifest["files"][eidos_manifest_path]["sha256"] = _sha(
            expected_writes[eidos_manifest_path]
        )
    expected_writes[MANIFEST_PATH.as_posix()] = _json_bytes(expected_manifest)
    _semantic_validate(expected_writes, expected_manifest["eidos"]["enabled"])
    managed_writes = {
        relative: data
        for relative, data in expected_writes.items()
        if relative == MANIFEST_PATH.as_posix()
        or expected_manifest["files"].get(relative, {}).get("ownership") == "kit"
        or relative not in old_files
    }
    writes: dict[str, bytes] = {}
    stable_guards: dict[str, FileSnapshot] = {}
    new_kit_paths = frozenset(
        relative
        for relative, record in expected_manifest["files"].items()
        if relative not in old_files and record["ownership"] == "kit"
    )
    for relative, data in managed_writes.items():
        target = _safe_target(root, relative, f"upgrade target {relative}")
        if relative in new_kit_paths and target.exists():
            raise HarnessKitError(
                "target_exists", f"Refusing to overwrite new managed path: {relative}"
            )
        snapshot = FileSnapshot(
            target.is_file(),
            target.read_bytes() if target.is_file() else None,
            stat.S_IMODE(target.stat().st_mode) if target.is_file() else None,
        )
        if snapshot.existed and snapshot.data == data:
            stable_guards[relative] = snapshot
        else:
            writes[relative] = data
    _atomic_write_set(
        root,
        writes,
        stable_guards=stable_guards,
        require_absent_paths=new_kit_paths,
    )
    print(f"Harness Kit is at {KIT_VERSION}.")
    return 0


def _command_diff(args: argparse.Namespace) -> int:
    root = _check_root(args.root)
    manifest = _load_manifest(root)
    _validate_manifest_trust(root, manifest)
    rows = _diff_rows(root, manifest)
    changed = [
        row
        for row in rows
        if row["ownership"] == "kit" and row["status"] != "unchanged"
    ]
    payload = {
        "ok": not changed,
        "kit_version": manifest.get("kit_version"),
        "files": rows,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for row in rows:
            print(f"{row['status']:9} {row['ownership']:7} {row['path']}")
    return 0 if not changed else 1


def _command_assess(args: argparse.Namespace) -> int:
    root = _check_root(args.root)
    managed = (root / MANIFEST_PATH).is_file()
    candidate = _combined_render("project:example", "Example Project", True)
    collisions = [relative for relative in candidate if (root / relative).exists()]
    payload = {
        "ok": True,
        "managed": managed,
        "installable": not managed and not collisions,
        "collisions": sorted(collisions),
        "provider_activity": "not_observed",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _validate_manifest_trust(root: Path, manifest: dict[str, Any]) -> dict[str, bytes]:
    expected = _trusted_expected(root, manifest)
    expected_manifest = json.loads(expected[MANIFEST_PATH.as_posix()].decode())
    current_files = manifest.get("files")
    installed_version = manifest.get("kit_version")
    version_is_current = installed_version == KIT_VERSION
    version_is_supported_prior = (
        isinstance(installed_version, str)
        and installed_version in TRUSTED_PRIOR_RELEASES
        and installed_version != KIT_VERSION
    )
    if not version_is_current and not version_is_supported_prior:
        raise HarnessKitError(
            "upgrade_path", f"Unsupported Harness Kit version: {installed_version}"
        )
    if set(manifest) != set(expected_manifest) or not isinstance(current_files, dict):
        raise HarnessKitError("manifest_untrusted", "Manifest shape is not trusted.")
    expected_files = expected_manifest["files"]
    if version_is_current and set(current_files) != set(expected_files):
        raise HarnessKitError("manifest_untrusted", "Manifest file set is not trusted.")
    if version_is_supported_prior and not set(current_files).issubset(expected_files):
        raise HarnessKitError(
            "upgrade_path", "This release cannot remove unmanaged prior kit paths."
        )
    prior_hashes = (
        _release_hashes(str(installed_version)) if version_is_supported_prior else {}
    )
    for field in (
        "schema_version",
        "project_id",
        "project_name",
    ):
        if manifest.get(field) != expected_manifest.get(field):
            raise HarnessKitError(
                "manifest_untrusted", f"Manifest field changed: {field}"
            )
    if version_is_current:
        current_eidos = manifest.get("eidos")
        expected_eidos = expected_manifest.get("eidos")
        if (
            not isinstance(current_eidos, dict)
            or not isinstance(expected_eidos, dict)
            or set(current_eidos) != {"enabled", "kit_version", "manifest_sha256"}
            or current_eidos.get("enabled") != expected_eidos.get("enabled")
            or current_eidos.get("kit_version") != expected_eidos.get("kit_version")
            or not isinstance(current_eidos.get("manifest_sha256"), str)
            or re.fullmatch(r"[a-f0-9]{64}", current_eidos["manifest_sha256"]) is None
        ):
            raise HarnessKitError(
                "manifest_untrusted", "Manifest Eidos identity changed."
            )
        if current_eidos["enabled"]:
            installed_eidos_manifest = _safe_target(
                root, ".agents/eidos/kit-manifest.json", "installed Eidos manifest"
            )
            if (
                not installed_eidos_manifest.is_file()
                or _sha(installed_eidos_manifest.read_bytes())
                != current_eidos["manifest_sha256"]
            ):
                raise HarnessKitError(
                    "manifest_untrusted", "Manifest Eidos digest changed."
                )
    if version_is_supported_prior:
        eidos = manifest.get("eidos")
        if (
            not isinstance(eidos, dict)
            or eidos.get("enabled") != expected_manifest["eidos"]["enabled"]
        ):
            raise HarnessKitError(
                "manifest_untrusted", "Manifest Eidos identity changed."
            )
    for relative, current in current_files.items():
        trusted = expected_files.get(relative)
        if not isinstance(trusted, dict):
            raise HarnessKitError("manifest_untrusted", f"Unknown record: {relative}")
        if (
            not isinstance(current, dict)
            or set(current) != {"mode", "ownership", "sha256"}
            or current.get("ownership") != trusted["ownership"]
            or current.get("mode") != "100644"
            or not isinstance(current.get("sha256"), str)
            or re.fullmatch(r"[a-f0-9]{64}", current["sha256"]) is None
        ):
            raise HarnessKitError("manifest_untrusted", f"Invalid record: {relative}")
        if trusted["ownership"] == "kit":
            if relative == ".agents/eidos/kit-manifest.json" and (
                version_is_current or version_is_supported_prior
            ):
                trusted_hash = current["sha256"]
                target = _safe_target(root, relative, "installed Eidos manifest")
                if not target.is_file() or _sha(target.read_bytes()) != trusted_hash:
                    raise HarnessKitError(
                        "manifest_untrusted", "Installed Eidos manifest digest changed."
                    )
            elif (
                version_is_supported_prior
                and relative
                in _release_descriptor(str(installed_version))["eidos"]["files"]
            ):
                target = _safe_target(
                    root, relative, f"installed Eidos file {relative}"
                )
                trusted_hash = _sha(target.read_bytes()) if target.is_file() else None
            else:
                trusted_hash = prior_hashes.get(relative, trusted["sha256"])
            trusted_hashes = {trusted_hash}
            if version_is_supported_prior:
                trusted_hashes.add(trusted["sha256"])
                trusted_hashes.add(_release_hashes(KIT_VERSION).get(relative))
            if current["sha256"] not in trusted_hashes:
                raise HarnessKitError(
                    "manifest_untrusted", f"Kit trust hash changed: {relative}"
                )
    return expected


def _trusted_tool(root: Path, manifest: dict[str, Any]) -> Path:
    expected = _validate_manifest_trust(root, manifest)
    expected_manifest = json.loads(expected[MANIFEST_PATH.as_posix()].decode())
    tool_relative = ".agents/tools/harness.py"
    tool = _safe_target(root, tool_relative, "installed Harness tool")
    if (
        not tool.is_file()
        or _sha(tool.read_bytes())
        != expected_manifest["files"][tool_relative]["sha256"]
    ):
        raise HarnessKitError(
            "tool_untrusted", "Installed Harness tool is not trusted."
        )
    return tool


def _command_doctor(args: argparse.Namespace) -> int:
    findings: list[dict[str, str]] = []
    try:
        root = _check_root(args.root)
        manifest = _load_manifest(root)
        tool = _trusted_tool(root, manifest)
        rows = _diff_rows(root, manifest)
        for row in rows:
            if row["ownership"] == "kit" and row["status"] != "unchanged":
                findings.append(
                    {
                        "severity": "error",
                        "code": f"kit_{row['status']}",
                        "message": row["path"],
                    }
                )
        if not findings:
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(tool),
                    "validate",
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
                payload = json.loads(result.stdout)
            except json.JSONDecodeError:
                payload = {
                    "ok": False,
                    "findings": [{"code": "tool_output", "message": result.stderr}],
                }
            if result.returncode != 0 or payload.get("ok") is not True:
                for item in payload.get("findings", []):
                    if isinstance(item, dict):
                        findings.append(
                            {
                                "severity": str(item.get("severity", "error")),
                                "code": str(item.get("code", "project_invalid")),
                                "message": str(
                                    item.get("message", "Harness validation failed.")
                                ),
                            }
                        )
        if not findings and manifest["eidos"]["enabled"]:
            eidos_tool = _safe_target(
                root, ".agents/tools/eidos.py", "installed Eidos tool"
            )
            expected = _trusted_expected(root, manifest)
            if (
                not eidos_tool.is_file()
                or eidos_tool.read_bytes() != expected[".agents/tools/eidos.py"]
            ):
                raise HarnessKitError(
                    "eidos_tool_untrusted", "Installed Eidos tool is not trusted."
                )
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(eidos_tool),
                    "validate",
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
                payload = json.loads(result.stdout)
            except json.JSONDecodeError:
                payload = {"ok": False}
            if result.returncode != 0 or payload.get("ok") is not True:
                findings.append(
                    {
                        "severity": "error",
                        "code": "eidos_invalid",
                        "message": result.stdout.strip() or result.stderr.strip(),
                    }
                )
        for relative, expected in MISPLACED_ROOT_CACHES.items():
            target = _safe_target(root, relative, "root tool cache")
            if os.path.lexists(target):
                findings.append(
                    {
                        "severity": "warning",
                        "code": "misplaced_root_cache",
                        "message": f"{relative} should be generated under {expected}",
                    }
                )
    except HarnessKitError as exc:
        findings.append({"severity": "error", "code": exc.code, "message": exc.message})
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
        print(
            "Harness Kit doctor: ok" if payload["ok"] else "Harness Kit doctor: failed"
        )
    return 0 if payload["ok"] else 2


def _add_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", type=Path, default=Path.cwd())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Harness Kit v1 manager")
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("install")
    _add_root(install)
    install.add_argument("--project-id", required=True)
    install.add_argument("--project-name", required=True)
    install.add_argument("--without-eidos", action="store_true")
    install.set_defaults(handler=_command_install)
    migrate = commands.add_parser("migrate")
    _add_root(migrate)
    migrate.add_argument("--project-id", required=True)
    migrate.add_argument("--project-name", required=True)
    migrate.add_argument("--without-eidos", action="store_true")
    migrate.set_defaults(handler=_command_migrate)
    upgrade = commands.add_parser("upgrade")
    _add_root(upgrade)
    upgrade.set_defaults(handler=_command_upgrade)
    diff = commands.add_parser("diff")
    _add_root(diff)
    diff.add_argument("--json", action="store_true")
    diff.set_defaults(handler=_command_diff)
    doctor = commands.add_parser("doctor")
    _add_root(doctor)
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(handler=_command_doctor)
    assess = commands.add_parser("assess")
    _add_root(assess)
    assess.set_defaults(handler=_command_assess)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.handler(args))
    except HarnessKitError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
