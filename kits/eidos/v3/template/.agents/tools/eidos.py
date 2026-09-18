#!/usr/bin/env python3
"""Portable, dependency-free Eidos v3 project and local-claim CLI."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Sequence


VERSION = "3"
PROJECT_RE = re.compile(r"^project:[a-z0-9]+(?:-[a-z0-9]+)*$")
REVISION_RE = re.compile(r"^D\d{4}$")
STAGE_RE = re.compile(r"^S\d{2,}$")
LEGACY_WORK_RE = re.compile(r"^W-\d{8}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*$")
WORK_RE = re.compile(
    r"^W-\d{8}-(?:\d{2}|m-[a-z0-9][a-z0-9-]*-[a-f0-9]{12})-"
    r"[a-z0-9]+(?:-[a-z0-9]+)*$"
)
MAX_WORK_FILENAME = 80
MAX_WORK_SLUG = 24
IDENTITY_RE = re.compile(r"^(?:unassigned|[a-z][a-z0-9-]*:[a-z0-9][a-z0-9-]*)$")
WORKSTREAM_RE = re.compile(r"^workstream:[a-z0-9][a-z0-9-]*$")
CLAIM_RE = re.compile(r"^claim-[a-f0-9]{16,64}$")
COMMIT_RE = re.compile(r"^[a-f0-9]{40,64}$")
WORKTREE_ID_RE = re.compile(r"^worktree-[a-f0-9]{32}$")
WORKTREE_INSTANCE_PATH = Path("eidos/worktree-instance")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})$")
STAGE_HEADING_RE = re.compile(r"^###\s+(S\d{2,})\s+[—-]\s+(.+?)\s*$")
STAGE_FIELD_RE = re.compile(r"^-\s+(Status|Outcome|Gate|Depends on):\s*(.*?)\s*$")
GATE_HEADING_RE = re.compile(r"^###\s+(G\d{2,})\s+[—-]\s+(.+?)\s*$")
GATE_FIELD_RE = re.compile(r"^-\s+(Stage|Criteria|Evidence):\s*(.*?)\s*$")
PROGRESS_RE = re.compile(
    r"^-\s+(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2}))\s+—\s+\S.*$"
)

DIRECTION_SECTIONS_V3 = (
    "Purpose",
    "Boundaries",
    "Baseline",
    "Stages",
    "Gates",
    "Dependencies",
)
DIRECTION_SECTIONS_V2 = (
    "Purpose",
    "Boundaries",
    "Baseline",
    "Stages",
    "Current Focus",
    "Dependencies",
    "Decisions Needed",
)
WORK_SECTIONS = (
    "Intent",
    "Plan",
    "Progress",
    "Result",
    "Evidence",
    "Deviation and Next",
)
DIRECTION_FIELDS = (
    "eidos_version",
    "document_type",
    "project_id",
    "revision",
    "updated_at",
)
WORK_FIELDS_V3 = (
    "eidos_version",
    "document_type",
    "project_id",
    "work_id",
    "direction_revision",
    "stage_id",
    "owner_id",
    "workstream_id",
    "parent_work_id",
    "status",
    "depends_on",
    "write_scope",
    "risk",
    "created_at",
    "started_at",
    "updated_at",
    "closed_at",
)
WORK_FIELDS_V2 = (
    "eidos_version",
    "document_type",
    "project_id",
    "work_id",
    "planner_work_id",
    "direction_revision",
    "stage_id",
    "owner_id",
    "status",
    "risk",
    "created_at",
    "started_at",
    "updated_at",
    "closed_at",
)
STAGE_STATUSES = {"planned", "active", "blocked", "done", "cancelled"}
WORK_STATUSES = {"planned", "in_progress", "blocked", "done", "failed", "cancelled"}
OPEN_STATUSES = {"planned", "in_progress", "blocked"}
CLOSED_STATUSES = {"done", "failed", "cancelled"}
RISKS = {"R0", "R1", "R2", "R3"}
PLACEHOLDERS = {"", "pending", "none", "n/a", "todo", "not applicable"}
INTENT_PROMPT = (
    "State the independently owned outcome and the Direction Stage it supports."
)


class EidosError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str
    path: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }
        if self.path is not None:
            result["path"] = self.path
        return result


@dataclass(frozen=True)
class MarkdownDocument:
    metadata: dict[str, str]
    body: str
    text: str


@dataclass
class ProjectModel:
    root: Path
    context: dict[str, Any]
    identity: dict[str, Any]
    direction: MarkdownDocument | None
    stages_by_revision: dict[str, list[dict[str, str]]]
    work: list[dict[str, Any]]
    findings: list[Finding]

    @property
    def errors(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity == "error"]


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _add(
    findings: list[Finding],
    severity: str,
    code: str,
    message: str,
    path: Path | None = None,
    root: Path | None = None,
) -> None:
    findings.append(
        Finding(
            severity,
            code,
            message,
            _relative(path, root) if path is not None and root is not None else None,
        )
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise EidosError("read_failed", f"Cannot read UTF-8 file: {path}") from exc


def _parse_markdown(path: Path) -> MarkdownDocument:
    text = _read_text(path)
    return _parse_markdown_text(text, path)


def _parse_markdown_text(text: str, path: Path) -> MarkdownDocument:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise EidosError(
            "frontmatter_missing", f"YAML scalar frontmatter is missing: {path}"
        )
    try:
        closing = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        )
    except StopIteration as exc:
        raise EidosError(
            "frontmatter_unclosed", f"Frontmatter is not closed: {path}"
        ) from exc
    metadata: dict[str, str] = {}
    for number, line in enumerate(lines[1:closing], start=2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[:1].isspace() or ":" not in line:
            raise EidosError(
                "frontmatter_not_scalar",
                f"Only top-level scalar frontmatter is supported: {path}:{number}",
            )
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not re.fullmatch(r"[a-z][a-z0-9_]*", key) or key in metadata:
            raise EidosError(
                "frontmatter_key",
                f"Invalid or duplicate frontmatter key: {path}:{number}",
            )
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        metadata[key] = value
    return MarkdownDocument(
        metadata, "\n".join(lines[closing + 1 :]).strip() + "\n", text
    )


def _sections(body: str) -> dict[str, str]:
    result: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            current = match.group(1)
            result.setdefault(current, [])
        elif current is not None:
            result[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in result.items()}


def _section_names(body: str) -> list[str]:
    return [
        match.group(1)
        for line in body.splitlines()
        if (match := re.match(r"^##\s+(.+?)\s*$", line))
    ]


def _title(body: str, fallback: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip() or fallback
    return fallback


def _parse_date(raw: str) -> date | None:
    try:
        parsed = date.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == raw else None


def _parse_timestamp(raw: str) -> datetime | None:
    if not TIMESTAMP_RE.fullmatch(raw):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.utcoffset() is None or abs(parsed.utcoffset()) > timedelta(
        hours=23, minutes=59
    ):
        return None
    return parsed


def _now() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _format_utc(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _csv(raw: str) -> list[str]:
    if raw.strip().casefold() == "none" or not raw.strip():
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _normalize_scope(raw: str) -> str | None:
    value = raw.replace("\\", "/")
    if value != value.strip():
        return None
    if value in {"", "/"} or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        return None
    if value == ".":
        return value
    for component in value.split("/"):
        if component in {"", "."}:
            continue
        if (
            component == ".."
            or component.endswith((".", " "))
            or ":" in component
            or any(character in component for character in "*?[]")
            or any(
                ord(character) < 32 or ord(character) == 127 for character in component
            )
        ):
            return None
    pure = PurePosixPath(value)
    return pure.as_posix().rstrip("/")


_SCOPE_CASE_CACHE: dict[str, bool] = {}


def _scope_case_insensitive(root: Path) -> bool:
    key = str(root.resolve())
    cached = _SCOPE_CASE_CACHE.get(key)
    if cached is not None:
        return cached
    result = _run_git_result(root, "config", "--bool", "core.ignorecase")
    if result.returncode == 0 and result.stdout.strip() in {"true", "false"}:
        value = result.stdout.strip() == "true"
    else:
        value = os.path.normcase("EIDOS") == os.path.normcase("eidos")
    _SCOPE_CASE_CACHE[key] = value
    return value


def _scope_key(value: str, root: Path) -> tuple[str, ...]:
    normalized = _normalize_scope(value)
    if normalized is None:
        normalized = value
    parts = PurePosixPath(normalized).parts
    if _scope_case_insensitive(root):
        return tuple(part.casefold() for part in parts)
    return parts


def _scope_overlap(left: str, right: str, root: Path) -> bool:
    if _normalize_scope(left) == "." or _normalize_scope(right) == ".":
        return True
    a = _scope_key(left, root)
    b = _scope_key(right, root)
    return a[: min(len(a), len(b))] == b[: min(len(a), len(b))]


def _scope_contains(parent: str, child: str, root: Path) -> bool:
    if _normalize_scope(parent) == ".":
        return True
    if _normalize_scope(child) == ".":
        return _normalize_scope(parent) == "."
    parent_parts = _scope_key(parent, root)
    child_parts = _scope_key(child, root)
    return (
        len(parent_parts) <= len(child_parts)
        and child_parts[: len(parent_parts)] == parent_parts
    )


def _required(
    metadata: dict[str, str],
    fields: Sequence[str],
    findings: list[Finding],
    path: Path,
    root: Path,
) -> None:
    for key in fields:
        if not metadata.get(key):
            _add(
                findings,
                "error",
                "metadata_missing",
                f"Required metadata is missing: {key}",
                path,
                root,
            )


def _required_sections(
    body: str, names: Sequence[str], findings: list[Finding], path: Path, root: Path
) -> dict[str, str]:
    sections = _sections(body)
    for name in names:
        if name not in sections:
            _add(
                findings,
                "error",
                "section_missing",
                f"Required section is missing: {name}",
                path,
                root,
            )
    return sections


def _parse_stages(
    body: str, findings: list[Finding], path: Path, root: Path
) -> list[dict[str, str]]:
    lines = _sections(body).get("Stages", "").splitlines()
    stages: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in lines:
        heading = STAGE_HEADING_RE.match(line)
        if heading:
            if current is not None:
                stages.append(current)
            current = {"id": heading.group(1), "title": heading.group(2).strip()}
            continue
        field = STAGE_FIELD_RE.match(line)
        if field and current is not None:
            key = {
                "Status": "status",
                "Outcome": "outcome",
                "Gate": "gate",
                "Depends on": "depends_on",
            }[field.group(1)]
            if key in current:
                _add(
                    findings,
                    "error",
                    "stage_field_duplicate",
                    f"Duplicate Stage field: {current['id']}.{key}",
                    path,
                    root,
                )
            current[key] = field.group(2).strip()
    if current is not None:
        stages.append(current)
    if not stages:
        _add(
            findings,
            "error",
            "stage_missing",
            "At least one Stage is required.",
            path,
            root,
        )
    seen: set[str] = set()
    for stage in stages:
        if stage["id"] in seen:
            _add(
                findings,
                "error",
                "stage_duplicate",
                f"Duplicate Stage ID: {stage['id']}",
                path,
                root,
            )
        seen.add(stage["id"])
        for field in ("status", "outcome", "depends_on"):
            if not stage.get(field):
                _add(
                    findings,
                    "error",
                    "stage_field_missing",
                    f"{stage['id']} is missing {field}.",
                    path,
                    root,
                )
        if stage.get("status") not in STAGE_STATUSES:
            _add(
                findings,
                "error",
                "stage_status",
                f"{stage['id']} has an invalid status.",
                path,
                root,
            )
    return stages


def _validate_gates(
    body: str,
    stages: list[dict[str, str]],
    findings: list[Finding],
    path: Path,
    root: Path,
) -> None:
    lines = _sections(body).get("Gates", "").splitlines()
    gates: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in lines:
        heading = GATE_HEADING_RE.match(line)
        if heading:
            if current is not None:
                gates.append(current)
            current = {"id": heading.group(1), "title": heading.group(2).strip()}
            continue
        field = GATE_FIELD_RE.match(line)
        if field and current is not None:
            key = field.group(1).casefold()
            if key in current:
                _add(
                    findings,
                    "error",
                    "gate_field_duplicate",
                    f"Duplicate Gate field: {current['id']}.{key}",
                    path,
                    root,
                )
            current[key] = field.group(2).strip()
    if current is not None:
        gates.append(current)
    if not gates:
        _add(
            findings,
            "error",
            "gate_missing",
            "At least one Gate is required.",
            path,
            root,
        )
        return
    stage_ids = {stage["id"] for stage in stages}
    seen: set[str] = set()
    for gate in gates:
        if gate["id"] in seen:
            _add(
                findings,
                "error",
                "gate_duplicate",
                f"Duplicate Gate ID: {gate['id']}",
                path,
                root,
            )
        seen.add(gate["id"])
        for field in ("stage", "criteria", "evidence"):
            if not gate.get(field):
                _add(
                    findings,
                    "error",
                    "gate_field_missing",
                    f"{gate['id']} is missing {field}.",
                    path,
                    root,
                )
        if gate.get("stage") not in stage_ids:
            _add(
                findings,
                "error",
                "gate_stage",
                f"{gate['id']} references an unknown Stage: {gate.get('stage', '')}",
                path,
                root,
            )


def _load_context(root: Path, findings: list[Finding]) -> dict[str, Any]:
    path = root / ".agents" / "context.json"
    for component in (root / ".agents", path):
        if (component.exists() or component.is_symlink()) and _is_reparse(component):
            _add(
                findings,
                "error",
                "context_path",
                "Context path traverses a symlink, junction, or reparse point.",
                component,
                root,
            )
            return {}
    if not path.is_file():
        _add(
            findings,
            "error",
            "context_missing",
            ".agents/context.json is missing.",
            path,
            root,
        )
        return {}
    try:
        context = json.loads(_read_text(path))
    except (json.JSONDecodeError, EidosError) as exc:
        _add(
            findings,
            "error",
            "context_invalid",
            f"Invalid context JSON: {exc}",
            path,
            root,
        )
        return {}
    if not isinstance(context, dict):
        _add(
            findings,
            "error",
            "context_invalid",
            "Context must be a JSON object.",
            path,
            root,
        )
        return {}
    if context.get("schema_version") != 2:
        _add(
            findings,
            "error",
            "context_version",
            "context schema_version must be 2.",
            path,
            root,
        )
    project = context.get("project")
    if not isinstance(project, dict) or not PROJECT_RE.fullmatch(
        str(project.get("id", ""))
    ):
        _add(
            findings,
            "error",
            "project_id",
            "context project.id is invalid.",
            path,
            root,
        )
    if not isinstance(project, dict) or not str(project.get("name", "")).strip():
        _add(
            findings,
            "error",
            "project_name",
            "context project.name is required.",
            path,
            root,
        )
    eidos = context.get("eidos")
    if not isinstance(eidos, dict) or str(eidos.get("version", "")) != VERSION:
        _add(
            findings,
            "error",
            "eidos_version",
            "context eidos.version must be 3.",
            path,
            root,
        )
    return context


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


def _configured_path(
    root: Path, context: dict[str, Any], key: str, fallback: str
) -> Path:
    raw = (
        context.get("eidos", {}).get(key, fallback)
        if isinstance(context.get("eidos"), dict)
        else fallback
    )
    if not isinstance(raw, str) or not raw.strip():
        raise EidosError(
            "context_path", f"context eidos.{key} must be a repository-relative path."
        )
    candidate = Path(raw.replace("\\", "/"))
    if candidate.is_absolute() or any(
        part in {"", ".", ".."} for part in candidate.parts
    ):
        raise EidosError(
            "context_path",
            f"context eidos.{key} must be a safe repository-relative path.",
        )
    current = root
    for part in candidate.parts:
        current = current / part
        if current.exists() or current.is_symlink():
            if _is_reparse(current):
                raise EidosError(
                    "context_path",
                    f"context eidos.{key} traverses a symlink, junction, or reparse point.",
                )
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise EidosError(
            "context_path", f"context eidos.{key} points outside the repository."
        ) from exc
    return resolved


def _load_identity(
    root: Path, context: dict[str, Any], findings: list[Finding]
) -> dict[str, Any]:
    try:
        path = _configured_path(
            root, context, "identity_path", ".agents/eidos/identity.json"
        )
    except EidosError as exc:
        _add(
            findings,
            "error",
            exc.code,
            exc.message,
            root / ".agents/context.json",
            root,
        )
        return {}
    if not path.is_file():
        _add(
            findings,
            "error",
            "identity_missing",
            "Eidos identity registry is missing.",
            path,
            root,
        )
        return {}
    try:
        value = json.loads(_read_text(path))
    except (json.JSONDecodeError, EidosError) as exc:
        _add(
            findings,
            "error",
            "identity_invalid",
            f"Invalid identity registry: {exc}",
            path,
            root,
        )
        return {}
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "status",
        "members",
        "aliases",
    }:
        _add(
            findings,
            "error",
            "identity_schema",
            "Identity fields do not match schema version 1.",
            path,
            root,
        )
        return {}
    if value.get("schema_version") != 1 or value.get("status") not in {
        "unconfigured",
        "configured",
    }:
        _add(
            findings,
            "error",
            "identity_schema",
            "Identity schema_version/status is invalid.",
            path,
            root,
        )
    members = value.get("members")
    aliases = value.get("aliases")
    if not isinstance(members, list) or not isinstance(aliases, list):
        _add(
            findings,
            "error",
            "identity_schema",
            "Identity members and aliases must be lists.",
            path,
            root,
        )
        return value
    member_ids: set[str] = set()
    display_names: set[str] = set()
    for member in members:
        if not isinstance(member, dict) or set(member) != {
            "id",
            "display_name",
            "status",
        }:
            _add(
                findings,
                "error",
                "identity_member",
                "Identity member fields are invalid.",
                path,
                root,
            )
            continue
        member_id = member.get("id")
        display_name = member.get("display_name")
        if not isinstance(member_id, str) or not re.fullmatch(
            r"member:[a-z0-9][a-z0-9-]*", member_id
        ):
            _add(
                findings,
                "error",
                "identity_member",
                "Canonical identity must use member:<id>.",
                path,
                root,
            )
        if not isinstance(display_name, str) or not display_name.strip():
            _add(
                findings,
                "error",
                "identity_member",
                "Identity display_name is required.",
                path,
                root,
            )
        if member.get("status") not in {"active", "inactive"}:
            _add(
                findings,
                "error",
                "identity_member",
                "Identity member status is invalid.",
                path,
                root,
            )
        if member_id in member_ids or display_name in display_names:
            _add(
                findings,
                "error",
                "identity_duplicate",
                "Identity member IDs and display names must be unique.",
                path,
                root,
            )
        if isinstance(member_id, str):
            member_ids.add(member_id)
        if isinstance(display_name, str):
            display_names.add(display_name)
    alias_sources: set[str] = set()
    alias_map: dict[str, str] = {}
    for alias in aliases:
        if not isinstance(alias, dict) or set(alias) != {"from", "to"}:
            _add(
                findings,
                "error",
                "identity_alias",
                "Identity alias fields are invalid.",
                path,
                root,
            )
            continue
        source, target = alias.get("from"), alias.get("to")
        if (
            not isinstance(source, str)
            or re.fullmatch(r"member:[a-z0-9][a-z0-9-]*", source) is None
            or not isinstance(target, str)
            or target not in member_ids
            or source in member_ids
            or source in alias_sources
        ):
            _add(
                findings,
                "error",
                "identity_alias",
                "Alias source must be unique and target a canonical member.",
                path,
                root,
            )
            continue
        alias_sources.add(source)
        alias_map[source] = target
    if value.get("status") == "unconfigured" and (members or aliases):
        _add(
            findings,
            "error",
            "identity_unconfigured",
            "An unconfigured identity registry must be empty.",
            path,
            root,
        )
    if value.get("status") == "configured" and not any(
        isinstance(item, dict) and item.get("status") == "active" for item in members
    ):
        _add(
            findings,
            "error",
            "identity_empty",
            "A configured identity registry needs an active member.",
            path,
            root,
        )
    return value


def _canonical_member(identity: dict[str, Any], owner_id: Any) -> str | None:
    if not isinstance(owner_id, str):
        return None
    members = identity.get("members", [])
    if any(isinstance(item, dict) and item.get("id") == owner_id for item in members):
        return owner_id
    for alias in identity.get("aliases", []):
        if isinstance(alias, dict) and alias.get("from") == owner_id:
            return str(alias.get("to"))
    return None


def _active_canonical_member(identity: dict[str, Any], member_id: str) -> bool:
    return any(
        isinstance(item, dict)
        and item.get("id") == member_id
        and item.get("status") == "active"
        for item in identity.get("members", [])
    )


def _validate_direction_document(
    path: Path,
    document: MarkdownDocument,
    project_id: str | None,
    findings: list[Finding],
    root: Path,
    *,
    current: bool,
) -> list[dict[str, str]]:
    metadata = document.metadata
    _required(metadata, DIRECTION_FIELDS, findings, path, root)
    version = metadata.get("eidos_version")
    if version not in {"1", "2", "3"} or metadata.get("document_type") != "direction":
        _add(
            findings,
            "error",
            "direction_type",
            "Direction version or document_type is invalid.",
            path,
            root,
        )
    if current and version != VERSION:
        _add(
            findings,
            "error",
            "current_direction_version",
            "The current Direction must use Eidos v3.",
            path,
            root,
        )
    expected_sections = (
        DIRECTION_SECTIONS_V3 if version == "3" else DIRECTION_SECTIONS_V2
    )
    actual_sections = _required_sections(
        document.body, expected_sections, findings, path, root
    )
    if version == "3":
        section_names = _section_names(document.body)
        duplicates = sorted(
            {name for name in section_names if section_names.count(name) > 1}
        )
        for section_name in duplicates:
            _add(
                findings,
                "error",
                "direction_section_duplicate",
                f"Eidos v3 Direction contains a duplicate section: {section_name}",
                path,
                root,
            )
        if tuple(section_names) != tuple(DIRECTION_SECTIONS_V3):
            _add(
                findings,
                "error",
                "direction_section_order",
                "Eidos v3 Direction sections must appear exactly once in this order: "
                + ", ".join(DIRECTION_SECTIONS_V3),
                path,
                root,
            )
        if "Current Focus" in actual_sections:
            _add(
                findings,
                "error",
                "current_focus_forbidden",
                "Eidos v3 derives focus; Current Focus is forbidden.",
                path,
                root,
            )
        for section_name in sorted(set(actual_sections) - set(DIRECTION_SECTIONS_V3)):
            _add(
                findings,
                "error",
                "direction_section_extra",
                f"Eidos v3 Direction has an unsupported section: {section_name}",
                path,
                root,
            )
    if metadata.get("project_id") != project_id:
        _add(
            findings,
            "error",
            "project_id_mismatch",
            "Context and Direction project_id differ.",
            path,
            root,
        )
    revision = metadata.get("revision", "")
    if not REVISION_RE.fullmatch(revision):
        _add(
            findings,
            "error",
            "direction_revision",
            "Direction revision must use D0001 format.",
            path,
            root,
        )
    if _parse_date(metadata.get("updated_at", "")) is None:
        _add(
            findings,
            "error",
            "direction_date",
            "Direction updated_at must be a valid ISO date.",
            path,
            root,
        )
    stages = _parse_stages(document.body, findings, path, root)
    if version == "3":
        for stage in stages:
            if "gate" in stage:
                _add(
                    findings,
                    "error",
                    "stage_gate_forbidden",
                    f"{stage['id']} must define its Gate in the Gates section.",
                    path,
                    root,
                )
        _validate_gates(document.body, stages, findings, path, root)
    return stages


def _validate_timestamps(
    metadata: dict[str, str],
    sections: dict[str, str],
    findings: list[Finding],
    path: Path,
    root: Path,
) -> None:
    status = metadata.get("status", "")
    created = _parse_timestamp(metadata.get("created_at", ""))
    updated = _parse_timestamp(metadata.get("updated_at", ""))
    started_raw = metadata.get("started_at", "")
    closed_raw = metadata.get("closed_at", "")
    started = None if started_raw == "none" else _parse_timestamp(started_raw)
    closed = None if closed_raw == "none" else _parse_timestamp(closed_raw)
    if (
        created is None
        or updated is None
        or (started_raw != "none" and started is None)
        or (closed_raw != "none" and closed is None)
    ):
        _add(
            findings,
            "error",
            "work_timestamp",
            "Work timestamps require seconds and timezone, or none where allowed.",
            path,
            root,
        )
        return
    instants = [created, updated]
    if started is not None:
        instants.append(started)
    if closed is not None:
        instants.append(closed)
    if (
        updated < created
        or (started and started < created)
        or (closed and closed < created)
        or (started and closed and closed < started)
        or (started and updated < started)
        or (closed and updated < closed)
    ):
        _add(
            findings,
            "error",
            "work_timestamp_order",
            "Work timestamp order is invalid.",
            path,
            root,
        )
    if status == "planned" and started_raw != "none":
        _add(
            findings,
            "error",
            "work_started_state",
            "planned Work must not have started_at.",
            path,
            root,
        )
    if status in {"in_progress", "blocked", "done", "failed"} and started is None:
        _add(
            findings,
            "error",
            "work_started_required",
            f"{status} Work requires started_at.",
            path,
            root,
        )
    if status in OPEN_STATUSES and closed_raw != "none":
        _add(
            findings,
            "error",
            "work_closed_state",
            "Open Work must not have closed_at.",
            path,
            root,
        )
    if status in CLOSED_STATUSES and closed is None:
        _add(
            findings,
            "error",
            "work_closed_required",
            f"{status} Work requires closed_at.",
            path,
            root,
        )
    progress: list[datetime] = []
    invalid = False
    for line in sections.get("Progress", "").splitlines():
        if not line.startswith("-") or line.startswith("  "):
            continue
        match = PROGRESS_RE.match(line)
        if not match:
            invalid = True
            continue
        parsed = _parse_timestamp(match.group(1))
        if parsed is None:
            invalid = True
        else:
            progress.append(parsed)
    if invalid:
        _add(
            findings,
            "error",
            "work_progress_format",
            "Progress entries must use '- ISO_TIMESTAMP — content'.",
            path,
            root,
        )
    if not progress:
        _add(
            findings,
            "error",
            "work_progress_timestamp",
            "Work needs at least one timestamped Progress entry.",
            path,
            root,
        )
    if any(b < a for a, b in zip(progress, progress[1:])):
        _add(
            findings,
            "error",
            "work_progress_order",
            "Progress entries must be chronological.",
            path,
            root,
        )
    upper = closed or updated
    if any(item < created or item > upper for item in progress):
        _add(
            findings,
            "error",
            "work_progress_bounds",
            "Progress is outside Work timestamp bounds.",
            path,
            root,
        )


def _validate_work_document(
    path: Path,
    document: MarkdownDocument,
    project_id: str | None,
    current_revision: str | None,
    stage_ids: dict[str, set[str]],
    findings: list[Finding],
    root: Path,
) -> dict[str, Any]:
    metadata = document.metadata
    version = metadata.get("eidos_version")
    fields = WORK_FIELDS_V3 if version == "3" else WORK_FIELDS_V2
    _required(metadata, fields, findings, path, root)
    sections = _required_sections(document.body, WORK_SECTIONS, findings, path, root)
    intent = " ".join(sections.get("Intent", "").split()).casefold()
    plan = sections.get("Plan", "")
    if (
        intent in PLACEHOLDERS | {INTENT_PROMPT.casefold()}
        or not plan.strip()
        or any(
            re.search(rf"(?m)^- {label}:\s*$", plan)
            for label in ("Completion criteria", "Verification plan")
        )
        or " ".join(plan.split()).casefold() in PLACEHOLDERS
    ):
        _add(
            findings,
            "warning",
            "work_content_incomplete",
            "Work should state its purpose, completion criteria, and verification plan.",
            path,
            root,
        )
    if version not in {"2", "3"} or metadata.get("document_type") != "work":
        _add(
            findings,
            "error",
            "work_type",
            "Work version or document_type is invalid.",
            path,
            root,
        )
    if metadata.get("project_id") != project_id:
        _add(
            findings,
            "error",
            "project_id_mismatch",
            "Context and Work project_id differ.",
            path,
            root,
        )
    work_id = metadata.get("work_id", "")
    if not WORK_RE.fullmatch(work_id) or path.stem != work_id:
        _add(
            findings,
            "error",
            "work_id",
            "Work ID and filename must match a legacy or member-qualified Work ID.",
            path,
            root,
        )
    status = metadata.get("status", "")
    if status not in WORK_STATUSES:
        _add(findings, "error", "work_status", "Work status is invalid.", path, root)
    if version == "2" and status not in CLOSED_STATUSES:
        _add(
            findings,
            "error",
            "legacy_open_work",
            "Eidos v2 Work must be closed before v3 migration.",
            path,
            root,
        )
    if version == "3" and "planner_work_id" in metadata:
        _add(
            findings,
            "error",
            "planner_work_id_forbidden",
            "Eidos v3 Work must not contain planner_work_id.",
            path,
            root,
        )
    if not IDENTITY_RE.fullmatch(metadata.get("owner_id", "")):
        _add(
            findings,
            "error",
            "owner_id",
            "owner_id must be unassigned or a namespaced stable ID.",
            path,
            root,
        )
    if version == "3" and metadata.get("owner_id") == "unassigned":
        _add(
            findings,
            "error",
            "owner_required",
            f"{status} Work requires an assigned namespaced owner_id.",
            path,
            root,
        )
    if version == "3":
        if not WORKSTREAM_RE.fullmatch(metadata.get("workstream_id", "")):
            _add(
                findings,
                "error",
                "workstream_id",
                "workstream_id must use workstream:<id>.",
                path,
                root,
            )
        parent = metadata.get("parent_work_id", "")
        if parent != "none" and not WORK_RE.fullmatch(parent):
            _add(
                findings,
                "error",
                "parent_work_id",
                "parent_work_id must be none or a Work ID.",
                path,
                root,
            )
        for dependency in _csv(metadata.get("depends_on", "")):
            if not WORK_RE.fullmatch(dependency):
                _add(
                    findings,
                    "error",
                    "depends_on",
                    f"Invalid Work dependency: {dependency}",
                    path,
                    root,
                )
        scopes = _csv(metadata.get("write_scope", ""))
        normalized = [_normalize_scope(scope) for scope in scopes]
        normalized_keys = [
            _scope_key(scope, root) for scope in normalized if scope is not None
        ]
        if (
            any(scope is None for scope in normalized)
            or scopes != normalized
            or len(set(normalized_keys)) != len(normalized_keys)
        ):
            _add(
                findings,
                "error",
                "write_scope",
                "write_scope must contain comma-separated repository-relative paths or none.",
                path,
                root,
            )
    if metadata.get("risk") not in RISKS:
        _add(
            findings,
            "error",
            "work_risk",
            "Work risk must be R0 through R3.",
            path,
            root,
        )
    revision = metadata.get("direction_revision", "")
    if revision not in stage_ids:
        _add(
            findings,
            "error",
            "work_revision",
            f"Direction revision was not found: {revision}",
            path,
            root,
        )
    elif status in OPEN_STATUSES and revision != current_revision:
        _add(
            findings,
            "warning",
            "work_revision_stale",
            "Open Work retains an archived Direction; new Work uses the current revision.",
            path,
            root,
        )
    stage = metadata.get("stage_id", "")
    if not STAGE_RE.fullmatch(stage) or stage not in stage_ids.get(revision, set()):
        _add(
            findings,
            "error",
            "work_stage",
            f"Stage is absent from Direction {revision}: {stage}",
            path,
            root,
        )
    _validate_timestamps(metadata, sections, findings, path, root)
    if (
        WORK_RE.fullmatch(work_id)
        and _parse_timestamp(metadata.get("created_at", "")) is not None
    ):
        if work_id[2:10] != metadata["created_at"][:10].replace("-", ""):
            _add(
                findings,
                "error",
                "work_id_date",
                "Work ID date must match created_at's raw date.",
                path,
                root,
            )
    if status in {"done", "failed"}:
        for section_name, code in (
            ("Result", "work_result_missing"),
            ("Evidence", "work_evidence_missing"),
        ):
            if (
                " ".join(sections.get(section_name, "").split()).casefold()
                in PLACEHOLDERS
            ):
                _add(
                    findings,
                    "error",
                    code,
                    f"{status} Work requires actual {section_name}.",
                    path,
                    root,
                )
    return {
        **metadata,
        "title": _title(document.body, work_id),
        "path": _relative(path, root),
        "depends_on_list": _csv(metadata.get("depends_on", "none"))
        if version == "3"
        else [],
        "write_scope_list": _csv(metadata.get("write_scope", "none"))
        if version == "3"
        else [],
        "workstream_id": metadata.get("workstream_id") if version == "3" else None,
        "parent_work_id": None
        if metadata.get("parent_work_id", "none") == "none"
        else metadata.get("parent_work_id"),
    }


def inspect_project(root: Path) -> ProjectModel:
    root = root.resolve()
    findings: list[Finding] = []
    context = _load_context(root, findings)
    identity = _load_identity(root, context, findings)
    project = context.get("project") if isinstance(context.get("project"), dict) else {}
    project_id = project.get("id") if isinstance(project, dict) else None

    def configured(key: str, fallback: str) -> Path:
        try:
            return _configured_path(root, context, key, fallback)
        except EidosError as exc:
            _add(
                findings,
                "error",
                exc.code,
                exc.message,
                root / ".agents/context.json",
                root,
            )
            return root / ".eidos-invalid-context-path" / key

    direction_path = configured("direction_path", ".agents/eidos/direction.md")
    archive_root = configured("archive_root", ".agents/eidos/archive")
    work_root = configured("work_root", ".agents/eidos/work")
    stages_by_revision: dict[str, list[dict[str, str]]] = {}
    if archive_root.is_dir():
        for path in sorted(archive_root.glob("D*.md")):
            try:
                document = _parse_markdown(path)
            except EidosError as exc:
                _add(findings, "error", exc.code, exc.message, path, root)
                continue
            stages = _validate_direction_document(
                path, document, project_id, findings, root, current=False
            )
            revision = document.metadata.get("revision", "")
            if path.name != f"{revision}.md":
                _add(
                    findings,
                    "error",
                    "direction_archive_name",
                    "Archive filename must match revision.",
                    path,
                    root,
                )
            if revision in stages_by_revision:
                _add(
                    findings,
                    "error",
                    "direction_revision_duplicate",
                    f"Duplicate revision: {revision}",
                    path,
                    root,
                )
            stages_by_revision[revision] = stages
    else:
        _add(
            findings,
            "error",
            "direction_archive_missing",
            "Direction archive directory is missing.",
            archive_root,
            root,
        )
    direction: MarkdownDocument | None = None
    current_revision: str | None = None
    if not direction_path.is_file():
        _add(
            findings,
            "error",
            "direction_missing",
            "Current Direction is missing.",
            direction_path,
            root,
        )
    else:
        try:
            direction = _parse_markdown(direction_path)
        except EidosError as exc:
            _add(findings, "error", exc.code, exc.message, direction_path, root)
        if direction is not None:
            stages = _validate_direction_document(
                direction_path, direction, project_id, findings, root, current=True
            )
            current_revision = direction.metadata.get("revision")
            if current_revision in stages_by_revision:
                _add(
                    findings,
                    "error",
                    "direction_revision_duplicate",
                    "Current Direction also exists in archive.",
                    direction_path,
                    root,
                )
            if current_revision:
                stages_by_revision[current_revision] = stages
    stage_ids = {
        revision: {stage["id"] for stage in stages}
        for revision, stages in stages_by_revision.items()
    }
    work: list[dict[str, Any]] = []
    if not work_root.is_dir():
        _add(
            findings,
            "error",
            "work_root_missing",
            "Work directory is missing.",
            work_root,
            root,
        )
    else:
        for nested in sorted(work_root.rglob("W-*.md")):
            if nested.parent != work_root:
                _add(
                    findings,
                    "error",
                    "work_not_flat",
                    "Work documents must remain directly under work_root.",
                    nested,
                    root,
                )
        seen: set[str] = set()
        for path in sorted(work_root.glob("W-*.md")):
            try:
                document = _parse_markdown(path)
            except EidosError as exc:
                _add(findings, "error", exc.code, exc.message, path, root)
                continue
            item = _validate_work_document(
                path, document, project_id, current_revision, stage_ids, findings, root
            )
            work_id = str(item.get("work_id", ""))
            if work_id in seen:
                _add(
                    findings,
                    "error",
                    "work_duplicate",
                    f"Duplicate Work ID: {work_id}",
                    path,
                    root,
                )
            seen.add(work_id)
            work.append(item)
    ids = {str(item.get("work_id")) for item in work}
    for item in work:
        path = root / str(item["path"])
        owner = str(item.get("owner_id", ""))
        if (
            identity.get("status") == "configured"
            and _canonical_member(identity, owner) is None
        ):
            _add(
                findings,
                "error",
                "owner_unknown",
                f"Work owner is not canonical or declared as an alias: {owner}",
                path,
                root,
            )
        parent = item.get("parent_work_id")
        if parent is not None and parent not in ids:
            _add(
                findings,
                "error",
                "parent_missing",
                f"Parent Work was not found: {parent}",
                path,
                root,
            )
        if parent == item.get("work_id"):
            _add(
                findings,
                "error",
                "parent_self",
                "Work cannot be its own parent.",
                path,
                root,
            )
        for dependency in item.get("depends_on_list", []):
            if dependency not in ids:
                _add(
                    findings,
                    "error",
                    "dependency_missing",
                    f"Dependency Work was not found: {dependency}",
                    path,
                    root,
                )
            if dependency == item.get("work_id"):
                _add(
                    findings,
                    "error",
                    "dependency_self",
                    "Work cannot depend on itself.",
                    path,
                    root,
                )

    def report_cycles(field: str, code: str) -> None:
        graph: dict[str, list[str]] = {}
        for item in work:
            work_id = str(item.get("work_id"))
            if field == "parent_work_id":
                value = item.get(field)
                graph[work_id] = [str(value)] if value in ids else []
            else:
                graph[work_id] = [
                    str(value) for value in item.get(field, []) if value in ids
                ]
        visiting: list[str] = []
        visited: set[str] = set()
        reported: set[frozenset[str]] = set()

        def visit(node: str) -> None:
            if node in visiting:
                cycle = visiting[visiting.index(node) :] + [node]
                identity = frozenset(cycle)
                if identity not in reported:
                    reported.add(identity)
                    _add(
                        findings,
                        "error",
                        code,
                        f"Work graph contains a cycle: {' -> '.join(cycle)}",
                    )
                return
            if node in visited:
                return
            visiting.append(node)
            for target in graph.get(node, []):
                visit(target)
            visiting.pop()
            visited.add(node)

        for node in sorted(graph):
            visit(node)

    report_cycles("depends_on_list", "dependency_cycle")
    report_cycles("parent_work_id", "parent_cycle")
    active = [
        item
        for item in work
        if item.get("eidos_version") == "3"
        and item.get("status") in {"in_progress", "blocked"}
    ]
    for index, left in enumerate(active):
        for right in active[index + 1 :]:
            overlaps = [
                (a, b)
                for a in left.get("write_scope_list", [])
                for b in right.get("write_scope_list", [])
                if _scope_overlap(a, b, root)
            ]
            if overlaps:
                _add(
                    findings,
                    "warning",
                    "active_write_scope_overlap",
                    f"Active Work scopes overlap: {left['work_id']} and {right['work_id']} ({overlaps[0][0]} / {overlaps[0][1]}).",
                )
    findings.sort(
        key=lambda item: (
            item.severity != "error",
            item.path or "",
            item.code,
            item.message,
        )
    )
    work.sort(
        key=lambda item: (
            _parse_timestamp(str(item.get("created_at", "")))
            or datetime.min.replace(tzinfo=timezone.utc),
            str(item.get("work_id", "")),
        )
    )
    return ProjectModel(
        root, context, identity, direction, stages_by_revision, work, findings
    )


def _public_work(model: ProjectModel, item: dict[str, Any]) -> dict[str, Any]:
    stages = model.stages_by_revision.get(str(item.get("direction_revision")), [])
    stage_title = next(
        (stage["title"] for stage in stages if stage["id"] == item.get("stage_id")),
        None,
    )

    def nullable(value: Any) -> Any:
        return None if value in {None, "none"} else value

    return {
        "work_id": item.get("work_id"),
        "eidos_version": int(item.get("eidos_version", 0))
        if str(item.get("eidos_version", "")).isdigit()
        else item.get("eidos_version"),
        "title": item.get("title"),
        "direction_revision": item.get("direction_revision"),
        "stage_id": item.get("stage_id"),
        "stage_title": stage_title,
        "owner_id": item.get("owner_id"),
        "canonical_owner_id": _canonical_member(model.identity, item.get("owner_id")),
        "workstream_id": item.get("workstream_id"),
        "parent_work_id": nullable(item.get("parent_work_id")),
        "status": item.get("status"),
        "depends_on": item.get("depends_on_list", []),
        "write_scope": item.get("write_scope_list", []),
        "risk": item.get("risk"),
        "created_at": item.get("created_at"),
        "started_at": nullable(item.get("started_at")),
        "updated_at": item.get("updated_at"),
        "closed_at": nullable(item.get("closed_at")),
        "path": item.get("path"),
    }


def _envelope(command: str, model: ProjectModel, data: Any) -> dict[str, Any]:
    return {
        "ok": not model.errors,
        "command": command,
        "data": data,
        "error": None
        if not model.errors
        else {
            "code": "validation_failed",
            "findings": [item.as_dict() for item in model.findings],
        },
    }


def _emit(payload: Any, json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    elif isinstance(payload, str):
        print(payload)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _require_valid(root: Path) -> ProjectModel:
    model = inspect_project(root)
    if model.errors:
        raise EidosError(
            "validation_failed", f"Project has {len(model.errors)} validation error(s)."
        )
    return model


def _command_validate(args: argparse.Namespace) -> int:
    model = inspect_project(args.root)
    if args.json:
        _emit(
            _envelope(
                "validate",
                model,
                {"findings": [item.as_dict() for item in model.findings]},
            ),
            True,
        )
    else:
        for item in model.findings:
            location = f" [{item.path}]" if item.path else ""
            print(f"{item.severity.upper()} {item.code}{location}: {item.message}")
        print(
            f"Eidos v3 validation: errors={len(model.errors)}, warnings={len(model.findings) - len(model.errors)}"
        )
    return 2 if model.errors else 0


def _command_catalog(args: argparse.Namespace) -> int:
    model = inspect_project(args.root)
    items = [_public_work(model, item) for item in model.work]
    if args.status:
        items = [item for item in items if item["status"] in args.status]
    if args.stage:
        items = [item for item in items if item["stage_id"] in args.stage]
    if args.owner:
        items = [
            item
            for item in items
            if item["owner_id"] in args.owner
            or item["canonical_owner_id"] in args.owner
        ]
    if args.workstream:
        items = [item for item in items if item["workstream_id"] in args.workstream]
    if args.recent is not None and args.recent < 0:
        raise EidosError("recent", "--recent must be zero or greater.")
    if args.recent is not None:
        items = sorted(
            items,
            key=lambda item: _parse_timestamp(str(item["updated_at"]))
            or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )[: args.recent]
    data = {
        "timeline": [item["work_id"] for item in items],
        "items": {item["work_id"]: item for item in items},
    }
    payload = _envelope("catalog", model, data)
    if args.json:
        _emit(payload, True)
    elif model.errors:
        print(f"validation_failed: {len(model.errors)} error(s)", file=sys.stderr)
    else:
        print("WORK ID | STATUS | STAGE | OWNER | WORKSTREAM | TITLE")
        for item in items:
            print(
                f"{item['work_id']} | {item['status']} | {item['stage_id']} | {item['owner_id']} | {item['workstream_id'] or '-'} | {item['title']}"
            )
    return 2 if model.errors else 0


def _aggregate_state(values: Sequence[Any], *, dirty: bool = False) -> Any:
    if dirty:
        if "dirty" in values:
            return "dirty"
        if "unknown" in values:
            return "unknown"
        return "clean"
    if True in values:
        return True
    if "unknown" in values:
        return "unknown"
    return False


def _claim_custodies(claim: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    references: list[dict[str, Any]] = []
    complete = claim.get("schema_version") in {2, 3}
    if complete:
        origin_id = claim["origin"]["worktree_id"]
        for index, entry in enumerate(claim.get("history", [])):
            references.append(
                {
                    "worktree_id": entry["worktree_id"],
                    "worktree_root_ref": entry["worktree_root_ref"],
                    "actor_id": entry["actor_id"],
                    "origin": index == 0 and entry["worktree_id"] == origin_id,
                    "historical": True,
                    "current": False,
                }
            )
    elif claim.get("history"):
        references.append(
            {
                "worktree_id": "unknown",
                "worktree_root_ref": "unknown",
                "actor_id": "unknown",
                "origin": True,
                "historical": True,
                "current": False,
            }
        )
    references.append(
        {
            "worktree_id": claim["worktree_id"],
            "worktree_root_ref": claim["worktree_root_ref"],
            "actor_id": claim["actor_id"],
            "origin": not claim.get("history")
            or (complete and claim["worktree_id"] == claim["origin"]["worktree_id"]),
            "historical": False,
            "current": True,
        }
    )
    grouped: dict[str, dict[str, Any]] = {}
    for reference in references:
        identity = str(reference["worktree_id"])
        group = grouped.setdefault(
            identity,
            {
                "worktree_id": identity,
                "worktree_root_ref": reference["worktree_root_ref"],
                "actor_ids": [],
                "origin": False,
                "historical": False,
                "current": False,
            },
        )
        actor = str(reference["actor_id"])
        if actor not in group["actor_ids"]:
            group["actor_ids"].append(actor)
        for field in ("origin", "historical", "current"):
            group[field] = bool(group[field] or reference[field])
    return list(grouped.values()), complete


def _claim_summary(
    root: Path,
    *,
    active_only: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    claims, claim_findings = _scan_claims(root)
    if active_only:
        claims = [claim for claim in claims if claim.get("status") == "active"]
    now = _utc_now()
    try:
        worktrees = _available_worktrees(root)
    except EidosError as exc:
        worktrees = {}
        claim_findings.append(
            {
                "severity": "error",
                "code": exc.code,
                "message": exc.message,
                "path": None,
            }
        )
    models: dict[str, ProjectModel] = {}
    public: list[dict[str, Any]] = []
    active: list[dict[str, Any]] = []
    for claim in claims:
        expires = _parse_timestamp(str(claim.get("expires_at", "")))
        expired = expires is None or expires <= now
        custodies, provenance_complete = _claim_custodies(claim)
        worktree_states: list[dict[str, Any]] = []
        for custody in custodies:
            identity = str(custody["worktree_id"])
            claim_root = worktrees.get(identity) if identity != "unknown" else None
            availability = "available" if claim_root is not None else "unknown"
            durable_work: dict[str, Any] | None = None
            if claim_root is not None:
                if identity not in models:
                    models[identity] = inspect_project(claim_root)
                durable_work = next(
                    (
                        work
                        for work in models[identity].work
                        if work.get("work_id") == claim.get("work_id")
                    ),
                    None,
                )
            work_orphaned: bool | str = (
                "unknown"
                if claim_root is None
                else durable_work is None
                or durable_work.get("status") in CLOSED_STATUSES
            )
            if claim_root is not None and durable_work is not None:
                declared = list(durable_work.get("write_scope_list", []))
                if not declared or any(
                    not any(_scope_contains(scope, path, root) for scope in declared)
                    for path in claim["paths"]
                ):
                    claim_findings.append(
                        {
                            "severity": "error",
                            "code": "claim_scope_expansion",
                            "message": (
                                "Claim paths exceed durable Work scope in a retained "
                                f"worktree: {claim['claim_id']}"
                            ),
                            "path": f"{claim['claim_id']}.json",
                        }
                    )
            scope_states = (
                {path: _scope_dirty(claim_root, path) for path in claim["paths"]}
                if claim_root is not None
                else {path: "unknown" for path in claim["paths"]}
            )
            dirty_paths = [
                path for path, state in scope_states.items() if state == "dirty"
            ]
            dirty_state = _aggregate_state(list(scope_states.values()), dirty=True)
            custody_retired = bool(custody["historical"] and not custody["current"])
            orphan_condition = (
                custody_retired
                or work_orphaned is True
                or expired
                or claim.get("status") != "active"
            )
            orphaned_dirty: bool | str = (
                True
                if dirty_state == "dirty" and orphan_condition
                else "unknown"
                if dirty_state == "unknown"
                else False
            )
            worktree_states.append(
                {
                    **custody,
                    "availability": availability,
                    "scope_states": scope_states,
                    "dirty_state": dirty_state,
                    "dirty_paths": dirty_paths,
                    "work_orphaned": work_orphaned,
                    "custody_retired": custody_retired,
                    "orphaned_dirty": orphaned_dirty,
                }
            )
        aggregate_scope = {
            path: _aggregate_state(
                [state["scope_states"][path] for state in worktree_states],
                dirty=True,
            )
            for path in claim["paths"]
        }
        dirty_state = _aggregate_state(list(aggregate_scope.values()), dirty=True)
        dirty_paths = [
            path for path, state in aggregate_scope.items() if state == "dirty"
        ]
        orphaned = _aggregate_state(
            [state["work_orphaned"] for state in worktree_states]
        )
        orphaned_dirty = _aggregate_state(
            [state["orphaned_dirty"] for state in worktree_states]
        )
        current_state = next(state for state in worktree_states if state["current"])
        item = {
            **claim,
            "expired": expired,
            "orphaned": orphaned,
            "worktree_availability": current_state["availability"],
            "provenance_complete": provenance_complete,
            "worktree_states": worktree_states,
            "scope_states": aggregate_scope,
            "dirty_state": dirty_state,
            "dirty_paths": dirty_paths,
            "orphaned_dirty": orphaned_dirty,
        }
        public.append(item)
        if current_state["work_orphaned"] is True and claim.get("status") == "active":
            claim_findings.append(
                {
                    "severity": "error",
                    "code": "claim_closed_work",
                    "message": f"Active claim references missing or closed Work: {claim['work_id']}",
                    "path": f"{claim['claim_id']}.json",
                }
            )
        if claim.get("status") == "active" and not expired:
            active.append(item)
    conflicts: list[dict[str, Any]] = []
    for index, left in enumerate(active):
        for right in active[index + 1 :]:
            overlap = next(
                (
                    (a, b)
                    for a in left.get("paths", [])
                    for b in right.get("paths", [])
                    if _scope_overlap(a, b, root)
                ),
                None,
            )
            if overlap:
                conflicts.append(
                    {
                        "left_claim_id": left["claim_id"],
                        "right_claim_id": right["claim_id"],
                        "left_path": overlap[0],
                        "right_path": overlap[1],
                    }
                )
    return public, conflicts, claim_findings


def _command_focus(args: argparse.Namespace) -> int:
    if args.limit is not None and (args.limit <= 0 or not args.summary):
        raise EidosError(
            "focus_limit", "--limit requires --summary and a positive integer."
        )
    model = inspect_project(args.root)
    public = [_public_work(model, item) for item in model.work]
    claims, conflicts, claim_findings = _claim_summary(model.root, active_only=True)
    data = {
        "direction_revision": model.direction.metadata.get("revision")
        if model.direction
        else None,
        "active_work": [item for item in public if item["status"] == "in_progress"],
        "blocked_work": [item for item in public if item["status"] == "blocked"],
        "planned_work": [item for item in public if item["status"] == "planned"],
        "claims": claims,
        "claim_conflicts": conflicts,
        "claim_findings": claim_findings,
        "remote_activity": "unknown",
    }
    payload = _envelope("focus", model, data)
    runtime_findings = list(claim_findings)
    runtime_findings.extend(
        {
            "severity": "error",
            "code": "claim_conflict",
            "message": (
                f"{item.get('left_claim_id')} conflicts with "
                f"{item.get('right_claim_id')}."
            ),
            "path": None,
        }
        for item in conflicts
    )
    if runtime_findings:
        payload["ok"] = False
        payload["error"] = {
            "code": "claim_validation_failed" if claim_findings else "claim_conflict",
            "findings": [item.as_dict() for item in model.findings] + runtime_findings,
        }
    if args.summary:
        keys = (
            "work_id",
            "title",
            "status",
            "owner_id",
            "direction_revision",
            "stage_id",
            "path",
        )
        summary = {
            "direction_revision": data["direction_revision"],
            "remote_activity": "unknown",
            "counts": {},
            "omitted": {},
            "diagnostics": [item.as_dict() for item in model.findings]
            + runtime_findings,
            "claim_alerts": [
                {
                    key: claim.get(key)
                    for key in (
                        "claim_id",
                        "work_id",
                        "expired",
                        "orphaned_dirty",
                        "work_orphaned",
                    )
                }
                for claim in claims
                if claim.get("expired")
                or claim.get("orphaned_dirty") is True
                or claim.get("work_orphaned") is True
            ],
        }
        for group in ("active_work", "blocked_work", "planned_work"):
            ordered = sorted(
                data[group], key=lambda item: str(item.get("work_id") or "")
            )
            ordered.sort(
                key=lambda item: _parse_timestamp(str(item.get("updated_at", "")))
                or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )
            chosen = ordered[: args.limit or 5]
            summary[group] = [
                {
                    **{key: item[key] for key in keys},
                    "previous_direction": item["direction_revision"]
                    != data["direction_revision"],
                }
                for item in chosen
            ]
            summary["counts"][group] = len(ordered)
            summary["omitted"][group] = len(ordered) - len(chosen)
        payload["data"] = data = summary
    _emit(payload if args.json else data, args.json)
    return 2 if model.errors or claim_findings or conflicts else 0


def _exclusive_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise EidosError("target_exists", f"Refusing to overwrite: {path}") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def _prepare_new_work(
    args: argparse.Namespace, model: ProjectModel
) -> tuple[Path, str]:
    if model.direction is None:
        raise EidosError("direction_missing", "Current Direction is required.")
    project_id = model.context["project"]["id"]
    timestamp = _now()
    day = timestamp[:10].replace("-", "")
    work_root = _configured_path(
        model.root, model.context, "work_root", ".agents/eidos/work"
    )
    if model.identity.get("status") != "configured":
        raise EidosError(
            "identity_unconfigured", "Configure Eidos identity before creating Work."
        )
    if args.owner == "unassigned":
        raise EidosError(
            "owner_required", "Work requires an active canonical member owner."
        )
    if not _active_canonical_member(model.identity, args.owner):
        raise EidosError(
            "owner_id", "New Work owner must be an active canonical member:* ID."
        )
    if args.id:
        work_id = args.id
    else:
        if not args.slug:
            raise EidosError(
                "slug_required", "--slug is required when --id is omitted."
            )
        if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", args.slug) is None:
            raise EidosError(
                "work_slug", "Work slug must use lowercase ASCII kebab-case."
            )
        prefix = f"W-{day}-m-{args.owner.removeprefix('member:')}-"
        budget = min(MAX_WORK_SLUG, MAX_WORK_FILENAME - len(prefix) - 12 - 1 - 3)
        if budget < 1:
            raise EidosError(
                "work_id_length",
                "Member key leaves no room in an 80-character Work filename.",
            )
        short_slug = args.slug[:budget].rstrip("-")
        for _ in range(8):
            work_id = f"{prefix}{uuid.uuid4().hex[:12]}-{short_slug}"
            if not (work_root / f"{work_id}.md").exists():
                break
        else:
            raise EidosError("work_id_collision", "Could not allocate a fresh Work ID.")
    if not WORK_RE.fullmatch(work_id) or work_id[2:10] != day:
        raise EidosError(
            "work_id", "Work ID must use today's legacy or member-qualified format."
        )
    if not LEGACY_WORK_RE.fullmatch(work_id):
        prefix = f"W-{day}-m-{args.owner.removeprefix('member:')}-"
        if (
            re.fullmatch(
                re.escape(prefix) + r"[a-f0-9]{12}-[a-z0-9]+(?:-[a-z0-9]+)*", work_id
            )
            is None
        ):
            raise EidosError(
                "work_id_owner",
                "New Work ID must contain the initial owner's member key.",
            )
        if len(work_id + ".md") > MAX_WORK_FILENAME:
            raise EidosError(
                "work_id_length",
                "New member-qualified Work filenames are limited to 80 characters.",
            )
    stages = model.stages_by_revision.get(model.direction.metadata["revision"], [])
    if args.stage not in {stage["id"] for stage in stages}:
        raise EidosError(
            "work_stage", f"Stage does not exist in current Direction: {args.stage}"
        )
    if not WORKSTREAM_RE.fullmatch(args.workstream):
        raise EidosError("workstream_id", "Invalid workstream ID.")
    if args.parent != "none" and args.parent not in {
        item["work_id"] for item in model.work
    }:
        raise EidosError("parent_missing", f"Parent Work not found: {args.parent}")
    dependencies = args.depends_on or []
    missing = [
        item
        for item in dependencies
        if item not in {work["work_id"] for work in model.work}
    ]
    if missing:
        raise EidosError(
            "dependency_missing", f"Dependency Work not found: {missing[0]}"
        )
    scopes = args.write_scope or []
    normalized_scopes = [_normalize_scope(item) for item in scopes]
    normalized_keys = [
        _scope_key(scope, model.root)
        for scope in normalized_scopes
        if scope is not None
    ]
    if any(item is None for item in normalized_scopes) or len(
        set(normalized_keys)
    ) != len(normalized_keys):
        raise EidosError("write_scope", "Invalid repository-relative write scope.")
    scopes = [item for item in normalized_scopes if item is not None]
    status = "in_progress" if args.start else "planned"
    started = timestamp if args.start else "none"
    content = f"""---
eidos_version: 3
document_type: work
project_id: {project_id}
work_id: {work_id}
direction_revision: {model.direction.metadata["revision"]}
stage_id: {args.stage}
owner_id: {args.owner}
workstream_id: {args.workstream}
parent_work_id: {args.parent}
status: {status}
depends_on: {", ".join(dependencies) if dependencies else "none"}
write_scope: {", ".join(scopes) if scopes else "none"}
risk: {args.risk}
created_at: {timestamp}
started_at: {started}
updated_at: {timestamp}
closed_at: none
---

# {args.title}

## Intent

State the independently owned outcome and the Direction Stage it supports.

## Plan

- Included scope:
- Excluded scope:
- Completion criteria:
- Verification plan:

## Progress

- {timestamp} — Work record created.

## Result

pending

## Evidence

pending

## Deviation and Next

- Plan deviation: none
- Residual risk: none
- Next work candidate: none
- Decision required: none
"""
    target = work_root / f"{work_id}.md"
    return target, content


def _command_new_work(args: argparse.Namespace) -> int:
    model = _require_valid(args.root)
    target, content = _prepare_new_work(args, model)
    _exclusive_write(target, content)
    print(_relative(target, model.root))
    return 0


def _run_git_result(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    for variable in (
        "GIT_GLOB_PATHSPECS",
        "GIT_NOGLOB_PATHSPECS",
        "GIT_ICASE_PATHSPECS",
    ):
        environment.pop(variable, None)
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    environment["GIT_LITERAL_PATHSPECS"] = "1"
    try:
        result = subprocess.run(
            [
                "git",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.untrackedCache=false",
                "-C",
                str(root),
                *arguments,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
        )
    except OSError as exc:
        raise EidosError("git_unavailable", "Git is unavailable.") from exc
    return result


def _run_git(root: Path, *arguments: str) -> str:
    result = _run_git_result(root, *arguments)
    if result.returncode != 0:
        raise EidosError("git_failed", result.stderr.strip() or "Git command failed.")
    return result.stdout.strip()


def _git_common_dir(root: Path) -> Path:
    raw = _run_git(root, "rev-parse", "--git-common-dir")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate.resolve()


def _git_dir(root: Path) -> Path:
    raw = _run_git(root, "rev-parse", "--absolute-git-dir")
    return Path(raw).resolve()


def _worktree_instance_id(git_dir: Path, *, create: bool) -> str | None:
    """Read or create a nonce that lives only as long as this worktree instance."""

    marker = git_dir / WORKTREE_INSTANCE_PATH
    if marker.exists() or marker.is_symlink():
        if not marker.is_file() or _is_reparse(marker):
            raise EidosError(
                "worktree_identity",
                "The worktree instance marker is not a regular local file.",
            )
        try:
            identity = marker.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            raise EidosError(
                "worktree_identity", "Cannot read the worktree instance marker."
            ) from exc
        if not WORKTREE_ID_RE.fullmatch(identity):
            raise EidosError(
                "worktree_identity", "The worktree instance marker is malformed."
            )
        return identity
    if not create:
        return None
    state = marker.parent
    if state.exists() or state.is_symlink():
        if not state.is_dir() or _is_reparse(state):
            raise EidosError(
                "worktree_identity",
                "The worktree-local Eidos state is not a regular directory.",
            )
    else:
        state.mkdir()
    identity = f"worktree-{uuid.uuid4().hex}"
    _exclusive_write(marker, identity + "\n")
    return identity


def _current_worktree_fields(root: Path, *, create: bool) -> dict[str, str]:
    identity = _worktree_instance_id(_git_dir(root), create=create)
    if identity is None:
        raise EidosError(
            "worktree_identity",
            "This worktree has no claim instance identity; acquire or adopt a claim first.",
        )
    return {
        "worktree_id": identity,
        "worktree_root_ref": f"git-common:{identity}",
    }


def _available_worktrees(root: Path) -> dict[str, Path]:
    """Resolve opaque claim identities locally without exposing stored absolute paths."""

    common = _git_common_dir(root)
    result: dict[str, Path] = {}

    def add(identity: str | None, candidate: Path) -> None:
        if identity is None:
            return
        resolved = candidate.resolve()
        previous = result.get(identity)
        if previous is not None and previous != resolved:
            raise EidosError(
                "worktree_identity_conflict",
                "One opaque worktree instance identity maps to multiple worktrees.",
            )
        result[identity] = resolved

    current_id = _worktree_instance_id(_git_dir(root), create=False)
    if current_id is not None:
        add(current_id, root)

    main_root = common.parent
    if main_root.is_dir():
        try:
            main_git_dir = _git_dir(main_root)
        except EidosError:
            main_id = None
        else:
            main_id = _worktree_instance_id(main_git_dir, create=False)
        add(main_id, main_root)

    administrative = common / "worktrees"
    if administrative.is_dir():
        for entry in sorted(administrative.iterdir()):
            if not entry.is_dir() or _is_reparse(entry):
                continue
            gitdir_file = entry / "gitdir"
            try:
                raw_gitdir = gitdir_file.read_text(encoding="utf-8").strip()
            except (OSError, UnicodeError):
                continue
            if not raw_gitdir:
                continue
            candidate = Path(raw_gitdir).parent
            if not candidate.is_dir():
                continue
            try:
                if _git_dir(candidate) != entry.resolve():
                    continue
            except EidosError:
                continue
            identity = _worktree_instance_id(entry.resolve(), create=False)
            add(identity, candidate)
    return result


def _scope_dirty(root: Path, scope: str) -> str:
    for arguments in (
        ("diff", "--no-ext-diff", "--quiet", "--", scope),
        (
            "diff",
            "--no-ext-diff",
            "--quiet",
            "--cached",
            "HEAD",
            "--",
            scope,
        ),
    ):
        result = _run_git_result(root, *arguments)
        if result.returncode == 1:
            return "dirty"
        if result.returncode != 0:
            return "unknown"
    try:
        untracked = _run_git(
            root,
            "ls-files",
            "--others",
            "--exclude-standard",
            "--",
            scope,
        )
    except EidosError:
        return "unknown"
    return "dirty" if untracked else "clean"


def _claims_root(root: Path) -> Path:
    return _git_common_dir(root) / "eidos" / "claims"


@contextmanager
def _claim_lock(root: Path) -> Iterator[None]:
    common = _git_common_dir(root)
    state = common / "eidos"
    state.mkdir(parents=True, exist_ok=True)
    lock = state / "claims.lock"
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise EidosError(
            "claim_store_busy", "Another claim operation is in progress."
        ) from exc
    os.close(descriptor)
    try:
        yield
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def _load_claims(root: Path) -> list[dict[str, Any]]:
    claims, findings = _scan_claims(root)
    if findings:
        first = findings[0]
        raise EidosError(str(first["code"]), str(first["message"]))
    return claims


def _validate_claim(path: Path, value: object, root: Path) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EidosError("claim_schema", f"Claim must be a JSON object: {path.name}")
    base_required = {
        "schema_version",
        "claim_id",
        "work_id",
        "actor_id",
        "worktree_id",
        "worktree_root_ref",
        "paths",
        "base_commit",
        "acquired_at",
        "heartbeat_at",
        "expires_at",
        "status",
        "history",
    }
    schema_version = value.get("schema_version")
    if schema_version not in {1, 2, 3}:
        raise EidosError(
            "claim_schema", f"Claim schema_version must be 1, 2, or 3: {path.name}"
        )
    required = base_required | ({"origin"} if schema_version >= 2 else set())
    if schema_version == 3:
        required.add("member_id")
    allowed = required | {"released_at"}
    if set(value) - allowed or required - set(value):
        raise EidosError(
            "claim_schema",
            f"Claim fields do not match schema_version {schema_version}: {path.name}",
        )
    claim_id = value.get("claim_id")
    if not isinstance(claim_id, str) or not CLAIM_RE.fullmatch(claim_id):
        raise EidosError("claim_schema", f"Claim ID is invalid: {path.name}")
    if claim_id != path.stem:
        raise EidosError(
            "claim_identity", f"Claim identity does not match filename: {path.name}"
        )
    if not isinstance(value.get("work_id"), str) or not WORK_RE.fullmatch(
        value["work_id"]
    ):
        raise EidosError("claim_schema", f"Claim work_id is invalid: {path.name}")
    actor = value.get("actor_id")
    if (
        not isinstance(actor, str)
        or not IDENTITY_RE.fullmatch(actor)
        or actor == "unassigned"
    ):
        raise EidosError("claim_schema", f"Claim actor_id is invalid: {path.name}")
    if schema_version == 3:
        member_id = value.get("member_id")
        if (
            not isinstance(member_id, str)
            or re.fullmatch(r"member:[a-z0-9][a-z0-9-]*", member_id) is None
            or not actor.startswith("agent:")
        ):
            raise EidosError(
                "claim_schema",
                f"Claim v3 requires member:* responsibility and agent:* actor: {path.name}",
            )
    worktree_id = value.get("worktree_id")
    if not isinstance(worktree_id, str) or not WORKTREE_ID_RE.fullmatch(worktree_id):
        raise EidosError("claim_schema", f"Claim worktree_id is invalid: {path.name}")
    if value.get("worktree_root_ref") != f"git-common:{worktree_id}":
        raise EidosError(
            "claim_schema", f"Claim worktree_root_ref is invalid: {path.name}"
        )
    paths = value.get("paths")
    if (
        not isinstance(paths, list)
        or not paths
        or any(not isinstance(item, str) for item in paths)
    ):
        raise EidosError(
            "claim_schema", f"Claim paths must be non-empty strings: {path.name}"
        )
    normalized = [_normalize_scope(item) for item in paths]
    normalized_keys = [
        _scope_key(item, root) for item in normalized if item is not None
    ]
    if (
        any(item is None for item in normalized)
        or list(paths) != sorted(item for item in normalized if item is not None)
        or len(set(normalized_keys)) != len(normalized_keys)
    ):
        raise EidosError(
            "claim_schema",
            f"Claim paths must be normalized, sorted, and unique: {path.name}",
        )
    base_commit = value.get("base_commit")
    if not isinstance(base_commit, str) or not COMMIT_RE.fullmatch(base_commit):
        raise EidosError("claim_schema", f"Claim base_commit is invalid: {path.name}")
    timestamps = {
        key: _parse_timestamp(str(value.get(key, "")))
        for key in ("acquired_at", "heartbeat_at", "expires_at")
    }
    if any(item is None for item in timestamps.values()):
        raise EidosError("claim_schema", f"Claim timestamp is invalid: {path.name}")
    acquired = timestamps["acquired_at"]
    heartbeat = timestamps["heartbeat_at"]
    expires = timestamps["expires_at"]
    if (
        acquired is None
        or heartbeat is None
        or expires is None
        or not (acquired <= heartbeat < expires)
    ):
        raise EidosError(
            "claim_schema", f"Claim timestamp order is invalid: {path.name}"
        )
    status = value.get("status")
    if status not in {"active", "released"}:
        raise EidosError("claim_schema", f"Claim status is invalid: {path.name}")
    released_at = value.get("released_at")
    if status == "active" and released_at is not None:
        raise EidosError(
            "claim_schema", f"Active claim cannot have released_at: {path.name}"
        )
    if status == "released":
        released = _parse_timestamp(str(released_at or ""))
        if released is None or released < heartbeat:
            raise EidosError(
                "claim_schema",
                f"Released claim requires valid released_at: {path.name}",
            )
    history = value.get("history")
    if not isinstance(history, list):
        raise EidosError("claim_schema", f"Claim history must be a list: {path.name}")
    origin: dict[str, Any] | None = None
    if schema_version >= 2:
        raw_origin = value.get("origin")
        origin_fields = {
            "actor_id",
            "worktree_id",
            "worktree_root_ref",
            "acquired_at",
        }
        if schema_version == 3:
            origin_fields.add("member_id")
        if not isinstance(raw_origin, dict) or set(raw_origin) != origin_fields:
            raise EidosError("claim_schema", f"Claim origin is invalid: {path.name}")
        origin_actor = raw_origin.get("actor_id")
        origin_worktree = raw_origin.get("worktree_id")
        if (
            not isinstance(origin_actor, str)
            or not IDENTITY_RE.fullmatch(origin_actor)
            or origin_actor == "unassigned"
            or not isinstance(origin_worktree, str)
            or not WORKTREE_ID_RE.fullmatch(origin_worktree)
            or raw_origin.get("worktree_root_ref") != f"git-common:{origin_worktree}"
            or raw_origin.get("acquired_at") != value.get("acquired_at")
            or (
                schema_version == 3
                and raw_origin.get("member_id") != value.get("member_id")
            )
        ):
            raise EidosError("claim_schema", f"Claim origin is invalid: {path.name}")
        origin = raw_origin
    previous = acquired
    for entry in history:
        expected_history_fields = {
            "actor_id",
            "status",
            "adopted_at",
        }
        if schema_version >= 2:
            expected_history_fields |= {"worktree_id", "worktree_root_ref"}
        if schema_version == 3:
            expected_history_fields.add("member_id")
        if not isinstance(entry, dict) or set(entry) != expected_history_fields:
            raise EidosError(
                "claim_schema", f"Claim history entry is invalid: {path.name}"
            )
        history_actor = entry.get("actor_id")
        adopted = _parse_timestamp(str(entry.get("adopted_at", "")))
        history_worktree = entry.get("worktree_id")
        if (
            not isinstance(history_actor, str)
            or not IDENTITY_RE.fullmatch(history_actor)
            or history_actor == "unassigned"
            or entry.get("status") not in {"active", "released"}
            or adopted is None
            or adopted < previous
            or adopted > heartbeat
            or (
                schema_version >= 2
                and (
                    not isinstance(history_worktree, str)
                    or not WORKTREE_ID_RE.fullmatch(history_worktree)
                    or entry.get("worktree_root_ref")
                    != f"git-common:{history_worktree}"
                )
            )
            or (
                schema_version == 3 and entry.get("member_id") != value.get("member_id")
            )
        ):
            raise EidosError(
                "claim_schema", f"Claim history entry is invalid: {path.name}"
            )
        previous = adopted
    if schema_version >= 2 and origin is not None:
        first_custody = history[0] if history else value
        fields = ["actor_id", "worktree_id", "worktree_root_ref"]
        if schema_version == 3:
            fields.append("member_id")
        for field in fields:
            if first_custody.get(field) != origin.get(field):
                raise EidosError(
                    "claim_schema",
                    f"Claim origin and custody history diverge: {path.name}",
                )
    return value


def _scan_claims(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    claims_root = _claims_root(root)
    if not claims_root.exists():
        return [], []
    claims: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for path in sorted(claims_root.glob("*.json")):
        try:
            value = json.loads(_read_text(path))
            claim = _validate_claim(path, value, root)
            _run_git(
                root,
                "cat-file",
                "-e",
                f"{claim['base_commit']}^{{commit}}",
            )
            claims.append(claim)
        except (json.JSONDecodeError, EidosError) as exc:
            if isinstance(exc, EidosError) and exc.code == "git_failed":
                code = "claim_base_commit"
                message = f"Claim base_commit is not available: {path.name}"
            else:
                code = exc.code if isinstance(exc, EidosError) else "claim_invalid_json"
                message = (
                    exc.message
                    if isinstance(exc, EidosError)
                    else f"Invalid claim JSON: {path.name}"
                )
            findings.append(
                {
                    "severity": "error",
                    "code": code,
                    "message": message,
                    "path": path.name,
                }
            )
    return claims, findings


def _write_claim(root: Path, claim: dict[str, Any], *, create: bool) -> None:
    claims_root = _claims_root(root)
    claims_root.mkdir(parents=True, exist_ok=True)
    target = claims_root / f"{claim['claim_id']}.json"
    content = json.dumps(claim, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if create:
        _exclusive_write(target, content)
        return
    temporary = target.with_suffix(f".tmp-{os.getpid()}-{uuid.uuid4().hex}")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def _find_claim(claims: list[dict[str, Any]], claim_id: str) -> dict[str, Any]:
    claim = next((item for item in claims if item.get("claim_id") == claim_id), None)
    if claim is None:
        raise EidosError("claim_not_found", f"Claim not found: {claim_id}")
    return claim


def _claim_paths(args: argparse.Namespace, model: ProjectModel) -> list[str]:
    work = next(
        (item for item in model.work if item.get("work_id") == args.work_id), None
    )
    if work is None:
        raise EidosError("work_not_found", f"Work not found: {args.work_id}")
    if work.get("status") in CLOSED_STATUSES:
        raise EidosError(
            "claim_closed_work", f"Closed Work cannot receive a claim: {args.work_id}"
        )
    declared = list(work.get("write_scope_list", []))
    paths = args.path or declared
    normalized = [_normalize_scope(path) for path in paths]
    if not normalized or any(path is None for path in normalized):
        raise EidosError(
            "claim_path",
            "A claim requires valid paths from --path or Work write_scope.",
        )
    normalized_paths = sorted(path for path in normalized if path is not None)
    normalized_keys = [_scope_key(path, model.root) for path in normalized_paths]
    if len(set(normalized_keys)) != len(normalized_keys):
        raise EidosError("claim_path", "Claim paths contain physical aliases.")
    if not declared or any(
        not any(_scope_contains(scope, path, model.root) for scope in declared)
        for path in normalized_paths
    ):
        raise EidosError(
            "claim_scope_expansion",
            "Claim paths must remain within the Work write_scope.",
        )
    return normalized_paths


def _claim_member(model: ProjectModel, work_id: str, supplied: str | None) -> str:
    work = next((item for item in model.work if item.get("work_id") == work_id), None)
    if work is None:
        raise EidosError("work_not_found", f"Work not found: {work_id}")
    canonical = _canonical_member(model.identity, work.get("owner_id"))
    if canonical is None or not _active_canonical_member(model.identity, canonical):
        raise EidosError(
            "claim_member", "Claimed Work has no active canonical member owner."
        )
    if supplied is not None and supplied != canonical:
        raise EidosError(
            "claim_member", "Claim member must match the Work's canonical owner."
        )
    return canonical


def _require_claimable_work(model: ProjectModel, claim: dict[str, Any]) -> None:
    work = next(
        (item for item in model.work if item.get("work_id") == claim.get("work_id")),
        None,
    )
    if work is None or work.get("status") in CLOSED_STATUSES:
        raise EidosError(
            "claim_closed_work",
            f"Claim references missing or closed Work: {claim.get('work_id')}",
        )


def _require_claim_worktree(root: Path, claim: dict[str, Any]) -> None:
    current = _current_worktree_fields(root, create=False)
    if claim.get("worktree_id") != current["worktree_id"]:
        raise EidosError(
            "claim_worktree_mismatch",
            "Renew or release the claim from its recorded worktree, or adopt it explicitly.",
        )


def _command_claim_acquire(args: argparse.Namespace) -> int:
    model = _require_valid(args.root)
    if not re.fullmatch(r"agent:[a-z0-9][a-z0-9-]*", args.actor):
        raise EidosError("actor_id", "New claim actor must use an agent:* ID.")
    if args.ttl_seconds < 60:
        raise EidosError("claim_ttl", "Claim TTL must be at least 60 seconds.")
    if args.work_id not in {item["work_id"] for item in model.work}:
        raise EidosError("work_not_found", f"Work not found: {args.work_id}")
    paths = _claim_paths(args, model)
    member_id = _claim_member(model, args.work_id, args.member)
    with _claim_lock(model.root):
        claims = _load_claims(model.root)
        now = _utc_now()
        for existing in claims:
            expires = _parse_timestamp(str(existing.get("expires_at", "")))
            if existing.get("status") != "active" or expires is None or expires <= now:
                continue
            overlap = next(
                (
                    (a, b)
                    for a in paths
                    for b in existing.get("paths", [])
                    if _scope_overlap(a, b, model.root)
                ),
                None,
            )
            if overlap:
                raise EidosError(
                    "claim_conflict",
                    f"Write scope conflicts with {existing.get('claim_id')} ({overlap[0]} / {overlap[1]}).",
                )
        claim_id = args.claim_id or f"claim-{uuid.uuid4().hex}"
        if not CLAIM_RE.fullmatch(claim_id):
            raise EidosError(
                "claim_id",
                "claim_id must use claim- followed by 16-64 lowercase hex characters.",
            )
        acquired = _format_utc(now)
        if args.base_commit:
            base_commit = _run_git(
                model.root, "rev-parse", "--verify", f"{args.base_commit}^{{commit}}"
            )
        else:
            base_commit = _run_git(model.root, "rev-parse", "HEAD")
        worktree = _current_worktree_fields(model.root, create=True)
        claim = {
            "schema_version": 3,
            "claim_id": claim_id,
            "work_id": args.work_id,
            "member_id": member_id,
            "actor_id": args.actor,
            **worktree,
            "origin": {
                "member_id": member_id,
                "actor_id": args.actor,
                **worktree,
                "acquired_at": acquired,
            },
            "paths": paths,
            "base_commit": base_commit,
            "acquired_at": acquired,
            "heartbeat_at": acquired,
            "expires_at": _format_utc(now + timedelta(seconds=args.ttl_seconds)),
            "status": "active",
            "history": [],
        }
        _write_claim(model.root, claim, create=True)
    _emit(claim, args.json)
    return 0


def _command_claim_renew(args: argparse.Namespace) -> int:
    if args.ttl_seconds < 60:
        raise EidosError("claim_ttl", "Claim TTL must be at least 60 seconds.")
    if not IDENTITY_RE.fullmatch(args.actor) or args.actor == "unassigned":
        raise EidosError("actor_id", "Claim actor must be a namespaced stable ID.")
    model = _require_valid(args.root)
    root = model.root
    with _claim_lock(root):
        claim = _find_claim(_load_claims(root), args.claim_id)
        _require_claimable_work(model, claim)
        _require_claim_worktree(root, claim)
        if claim.get("status") != "active":
            raise EidosError("claim_not_active", "Only an active claim can be renewed.")
        if claim.get("actor_id") != args.actor:
            raise EidosError(
                "claim_actor_mismatch", "Only the current actor can renew this claim."
            )
        expires = _parse_timestamp(str(claim.get("expires_at", "")))
        now = _utc_now()
        if expires is None or expires <= now:
            raise EidosError(
                "claim_expired", "Expired claims must be adopted explicitly."
            )
        claim["heartbeat_at"] = _format_utc(now)
        claim["expires_at"] = _format_utc(now + timedelta(seconds=args.ttl_seconds))
        _write_claim(root, claim, create=False)
    _emit(claim, args.json)
    return 0


def _command_claim_release(args: argparse.Namespace) -> int:
    if not IDENTITY_RE.fullmatch(args.actor) or args.actor == "unassigned":
        raise EidosError("actor_id", "Claim actor must be a namespaced stable ID.")
    root = args.root.resolve()
    with _claim_lock(root):
        claim = _find_claim(_load_claims(root), args.claim_id)
        _require_claim_worktree(root, claim)
        if claim.get("status") != "active":
            raise EidosError(
                "claim_not_active", "Only an active claim can be released."
            )
        if claim.get("actor_id") != args.actor:
            raise EidosError(
                "claim_actor_mismatch", "Only the current actor can release this claim."
            )
        instant = _utc_now()
        expires = _parse_timestamp(str(claim.get("expires_at", "")))
        if expires is None or expires <= instant:
            raise EidosError(
                "claim_expired", "Expired claims must be adopted explicitly."
            )
        now = _format_utc(instant)
        claim["status"] = "released"
        claim["heartbeat_at"] = now
        claim["released_at"] = now
        _write_claim(root, claim, create=False)
    _emit(claim, args.json)
    return 0


def _command_claim_adopt(args: argparse.Namespace) -> int:
    if args.ttl_seconds < 60:
        raise EidosError("claim_ttl", "Claim TTL must be at least 60 seconds.")
    if not re.fullmatch(r"agent:[a-z0-9][a-z0-9-]*", args.actor):
        raise EidosError("actor_id", "Adopting claim actor must use an agent:* ID.")
    model = _require_valid(args.root)
    root = model.root
    with _claim_lock(root):
        claims = _load_claims(root)
        claim = _find_claim(claims, args.claim_id)
        _require_claimable_work(model, claim)
        member_id = _claim_member(model, str(claim.get("work_id")), args.member)
        if claim.get("schema_version") == 3 and claim.get("member_id") != member_id:
            raise EidosError(
                "claim_member_transfer",
                "A v3 claim cannot be adopted after Work ownership changes; acquire a new claim.",
            )
        now = _utc_now()
        expires = _parse_timestamp(str(claim.get("expires_at", "")))
        if claim.get("status") == "active" and expires is not None and expires > now:
            raise EidosError(
                "claim_not_adoptable", "An unexpired active claim cannot be adopted."
            )
        for other in claims:
            other_expires = _parse_timestamp(str(other.get("expires_at", "")))
            if (
                other.get("claim_id") == args.claim_id
                or other.get("status") != "active"
                or other_expires is None
                or other_expires <= now
            ):
                continue
            if any(
                _scope_overlap(a, b, root)
                for a in claim.get("paths", [])
                for b in other.get("paths", [])
            ):
                raise EidosError(
                    "claim_conflict",
                    f"Adoption conflicts with active claim {other.get('claim_id')}.",
                )
        if claim.get("schema_version") == 1:
            if claim.get("history"):
                raise EidosError(
                    "claim_provenance_incomplete",
                    "A legacy adopted claim has unknown prior worktree provenance and cannot be adopted again.",
                )
            claim["schema_version"] = 2
            claim["origin"] = {
                "actor_id": claim.get("actor_id"),
                "worktree_id": claim.get("worktree_id"),
                "worktree_root_ref": claim.get("worktree_root_ref"),
                "acquired_at": claim.get("acquired_at"),
            }
        history = claim.setdefault("history", [])
        history.append(
            {
                **(
                    {"member_id": claim.get("member_id")}
                    if claim.get("schema_version") == 3
                    else {}
                ),
                "actor_id": claim.get("actor_id"),
                "worktree_id": claim.get("worktree_id"),
                "worktree_root_ref": claim.get("worktree_root_ref"),
                "status": claim.get("status"),
                "adopted_at": _format_utc(now),
            }
        )
        claim["actor_id"] = args.actor
        if claim.get("schema_version") == 3:
            claim["member_id"] = member_id
        claim.update(_current_worktree_fields(model.root, create=True))
        claim["status"] = "active"
        claim["heartbeat_at"] = _format_utc(now)
        claim["expires_at"] = _format_utc(now + timedelta(seconds=args.ttl_seconds))
        claim.pop("released_at", None)
        _write_claim(root, claim, create=False)
    _emit(claim, args.json)
    return 0


def _command_claim_list(args: argparse.Namespace) -> int:
    model = inspect_project(args.root)
    claims, conflicts, findings = _claim_summary(model.root)
    payload = {"claims": claims, "conflicts": conflicts, "findings": findings}
    _emit(payload, args.json)
    return 2 if conflicts or findings or model.errors else 0


def _add_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--root", type=Path, default=Path.cwd(), help="project repository root"
    )


def _work_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or " ".join(
        value.split()
    ).casefold() in PLACEHOLDERS | {INTENT_PROMPT.casefold()}:
        raise EidosError("work_input", f"{name} requires actual content.")
    if any(ord(char) < 32 and char not in "\n\t" for char in value) or re.search(
        r"(?m)^#{1,2}\s|^---\s*$", value
    ):
        raise EidosError(
            "work_input", f"{name} cannot inject document headings or frontmatter."
        )
    return value.strip()


def _work_input(args: argparse.Namespace) -> dict[str, Any]:
    try:
        raw = (
            sys.stdin.read()
            if args.input == "-"
            else Path(args.input).read_text(encoding="utf-8")
        )
        value = json.loads(raw)
    except (OSError, UnicodeError, ValueError) as exc:
        raise EidosError("work_input", "Expected a UTF-8 JSON object.") from exc
    if not isinstance(value, dict):
        raise EidosError("work_input", "Expected a JSON object.")
    allowed = (
        {
            "id",
            "slug",
            "title",
            "owner",
            "stage",
            "write_scope",
            "risk",
            "intent",
            "completion_criteria",
            "verification_plan",
            "actor",
            "workstream",
            "parent",
            "depends_on",
        }
        if args.operation == "start"
        else {"work_id", "claim_id", "actor", "status", "result", "evidence"}
    )
    if set(value) - allowed:
        raise EidosError(
            "work_input",
            "Unknown input fields: " + ", ".join(sorted(set(value) - allowed)),
        )
    required = (
        {
            "title",
            "owner",
            "stage",
            "write_scope",
            "risk",
            "intent",
            "completion_criteria",
            "verification_plan",
            "actor",
        }
        if args.operation == "start"
        else allowed
    )
    if not required <= set(value):
        raise EidosError(
            "work_input",
            "Missing input fields: " + ", ".join(sorted(required - set(value))),
        )
    for key, item in value.items():
        if key in {"write_scope", "depends_on"}:
            if (
                not isinstance(item, list)
                or not item
                or not all(
                    isinstance(part, str)
                    and part.strip()
                    and "\n" not in part
                    and "," not in part
                    for part in item
                )
            ):
                raise EidosError(
                    "work_input", f"{key} requires a nonempty string array."
                )
        else:
            value[key] = _work_text(item, key)
            if (
                key
                not in {
                    "intent",
                    "completion_criteria",
                    "verification_plan",
                    "result",
                    "evidence",
                }
                and "\n" in value[key]
            ):
                raise EidosError("work_input", f"{key} must be a single line.")
    if not re.fullmatch(r"agent:[a-z0-9][a-z0-9-]*", value["actor"]):
        raise EidosError("actor_id", "actor must use agent:*.")
    if args.operation == "start":
        if ("id" in value) == ("slug" in value):
            raise EidosError("work_input", "Provide exactly one of id or slug.")
        if value["risk"] not in {"R1", "R2", "R3"}:
            raise EidosError("work_input", "Writing Work requires risk R1, R2, or R3.")
    elif (
        value["status"] not in CLOSED_STATUSES
        or not WORK_RE.fullmatch(value["work_id"])
        or not CLAIM_RE.fullmatch(value["claim_id"])
    ):
        raise EidosError("work_input", "Invalid Work ID, claim ID, or terminal status.")
    return value


def _replace_section(text: str, name: str, content: str) -> str:
    return re.sub(
        rf"(?ms)(^## {re.escape(name)}\n).*?(?=^## |\Z)",
        lambda match: match[1] + "\n" + content.rstrip() + "\n\n",
        text,
        count=1,
    )


def _candidate_work(model: ProjectModel, target: Path, content: str) -> dict[str, Any]:
    findings: list[Finding] = []
    work = _validate_work_document(
        target,
        _parse_markdown_text(content, target),
        model.context["project"]["id"],
        model.direction.metadata["revision"],
        {
            revision: {stage["id"] for stage in stages}
            for revision, stages in model.stages_by_revision.items()
        },
        findings,
        model.root,
    )
    errors = [item for item in findings if item.severity == "error"]
    if errors:
        raise EidosError("work_invalid", "; ".join(item.code for item in errors))
    return work


def _file_snapshot(path: Path) -> dict[str, Any] | None:
    if _is_reparse(path):
        raise EidosError("work_path", "Operation paths cannot be reparse points.")
    if not path.exists():
        return None
    info = path.stat()
    return {
        "bytes": base64.b64encode(path.read_bytes()).decode("ascii"),
        "mode": stat.S_IMODE(info.st_mode),
        "mtime_ns": info.st_mtime_ns,
    }


def _work_guards(model: ProjectModel, target: Path) -> dict[str, Any]:
    paths = [model.root / ".agents/context.json"]
    for key, default in (
        ("identity_path", ".agents/eidos/identity.json"),
        ("direction_path", ".agents/eidos/direction.md"),
    ):
        paths.append(_configured_path(model.root, model.context, key, default))
    for key, default in (
        ("work_root", ".agents/eidos/work"),
        ("archive_root", ".agents/eidos/archive"),
    ):
        paths.extend(
            _configured_path(model.root, model.context, key, default).glob("*.md")
        )
    result = {}
    for path in paths:
        if path == target:
            continue
        if _is_reparse(path):
            raise EidosError("work_path", "Guard paths cannot be reparse points.")
        info = path.stat()
        result[_relative(path, model.root)] = {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "mode": stat.S_IMODE(info.st_mode),
            "mtime_ns": info.st_mtime_ns,
        }
    return result


def _atomic_bytes(path: Path, content: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _journal_write(path: Path, journal: dict[str, Any]) -> None:
    _atomic_bytes(
        path,
        (json.dumps(journal, ensure_ascii=False, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
        0o600,
    )


def _new_work_operation(
    model: ProjectModel, request: dict[str, Any]
) -> tuple[Path, str, dict[str, Any]]:
    args = argparse.Namespace(
        id=request.get("id"),
        slug=request.get("slug"),
        stage=request["stage"],
        title=request["title"],
        owner=request["owner"],
        write_scope=request["write_scope"],
        risk=request["risk"],
        workstream=request.get("workstream", "workstream:default"),
        parent=request.get("parent", "none"),
        depends_on=request.get("depends_on", []),
        start=True,
    )
    target, content = _prepare_new_work(args, model)
    if target.exists() or _is_reparse(target):
        raise EidosError(
            "target_exists", "Work already exists; use its original request to retry."
        )
    scope = _relative(target, model.root)
    declared = [_normalize_scope(item) for item in args.write_scope]
    if not any(_scope_contains(item, scope, model.root) for item in declared):
        declared.append(scope)
    content = re.sub(
        r"(?m)^write_scope:.*$",
        lambda _: "write_scope: " + ", ".join(declared),
        content,
    )
    content = _replace_section(content, "Intent", request["intent"])
    content = _replace_section(
        content,
        "Plan",
        "- Included scope: "
        + ", ".join(declared)
        + "\n- Excluded scope: changes outside the declared scope.\n- Completion criteria: "
        + request["completion_criteria"].replace("\n", "\n  ")
        + "\n- Verification plan: "
        + request["verification_plan"].replace("\n", "\n  "),
    )
    work = _candidate_work(model, target, content)
    claim_id = "claim-" + uuid.uuid4().hex
    now = _utc_now()
    timestamp = _format_utc(now)
    worktree = _current_worktree_fields(model.root, create=True)
    claim = {
        "schema_version": 3,
        "claim_id": claim_id,
        "work_id": work["work_id"],
        "member_id": request["owner"],
        "actor_id": request["actor"],
        **worktree,
        "origin": {
            "member_id": request["owner"],
            "actor_id": request["actor"],
            **worktree,
            "acquired_at": timestamp,
        },
        "paths": sorted(declared),
        "base_commit": _run_git(model.root, "rev-parse", "HEAD"),
        "acquired_at": timestamp,
        "heartbeat_at": timestamp,
        "expires_at": _format_utc(now + timedelta(hours=1)),
        "released_at": None,
        "status": "active",
        "history": [],
    }
    # Keep the established claim wire shape: active claims have no released_at field.
    claim.pop("released_at")
    return target, content, claim


def _finish_work_operation(
    model: ProjectModel, request: dict[str, Any]
) -> tuple[Path, str, dict[str, Any]]:
    work = next(
        (item for item in model.work if item["work_id"] == request["work_id"]), None
    )
    if work is None or work["status"] in CLOSED_STATUSES:
        raise EidosError(
            "work_closed",
            "Work must exist and be open; retry completed operations with the original request.",
        )
    target = model.root / work["path"]
    content = target.read_text(encoding="utf-8")
    claim = dict(_find_claim(_load_claims(model.root), request["claim_id"]))
    if claim["work_id"] != request["work_id"] or claim["actor_id"] != request["actor"]:
        raise EidosError(
            "claim_actor_mismatch", "Claim must match this Work and actor."
        )
    _require_claim_worktree(model.root, claim)
    if claim["member_id"] != _claim_member(model, request["work_id"], None):
        raise EidosError("claim_member", "Claim member no longer matches Work owner.")
    if (
        claim["status"] != "active"
        or _parse_timestamp(claim["expires_at"]) <= _utc_now()
    ):
        raise EidosError(
            "claim_expired",
            "An active unexpired claim is required; adopt explicitly first.",
        )
    if not any(
        _scope_contains(scope, work["path"], model.root) for scope in claim["paths"]
    ):
        raise EidosError("claim_scope", "Claim must cover the Work document.")
    if any(
        not any(
            _scope_contains(scope, path, model.root)
            for scope in work["write_scope_list"]
        )
        for path in claim["paths"]
    ):
        raise EidosError("claim_scope", "Claim exceeds declared Work scope.")
    sections = _sections(_parse_markdown_text(content, target).body)
    _work_text(sections["Intent"], "Intent")
    for label in ("Completion criteria", "Verification plan"):
        match = re.search(rf"(?m)^- {label}:[ \t]*(.*)$", sections["Plan"])
        if match is None:
            raise EidosError("work_input", f"Plan must state {label} before finishing.")
        _work_text(match[1], label)
    now = _now()
    for field, value in (
        ("status", request["status"]),
        ("updated_at", now),
        ("closed_at", now),
    ):
        content = re.sub(
            rf"(?m)^{field}:.*$", lambda _: f"{field}: {value}", content, count=1
        )
    if work.get("started_at") == "none" and request["status"] != "cancelled":
        content = re.sub(r"(?m)^started_at: none$", f"started_at: {now}", content)
    content = _replace_section(
        content,
        "Progress",
        sections["Progress"]
        + f"\n- {now} — Work {request['status']}; submitted result and evidence recorded.",
    )
    for section in ("Result", "Evidence"):
        previous = sections[section]
        value = request[section.lower()]
        if " ".join(previous.split()).casefold() not in PLACEHOLDERS:
            value = previous + "\n\n" + value
        content = _replace_section(content, section, value)
    _candidate_work(model, target, content)
    claim.update(
        status="released",
        heartbeat_at=_format_utc(_utc_now()),
        released_at=_format_utc(_utc_now()),
    )
    return target, content, claim


def _check_operation_claim(
    model: ProjectModel, claim: dict[str, Any], start: bool
) -> None:
    _validate_claim(
        _claims_root(model.root) / f"{claim['claim_id']}.json", claim, model.root
    )
    _require_claim_worktree(model.root, claim)
    if start and _parse_timestamp(claim["expires_at"]) <= _utc_now():
        raise EidosError(
            "claim_expired",
            "Pending start expired; inspect its recovery receipt before resuming.",
        )
    for other in _load_claims(model.root):
        if (
            other["claim_id"] == claim["claim_id"]
            or other["status"] != "active"
            or _parse_timestamp(other["expires_at"]) <= _utc_now()
        ):
            continue
        if any(
            _scope_overlap(a, b, model.root)
            for a in claim["paths"]
            for b in other["paths"]
        ):
            raise EidosError(
                "claim_conflict", f"Scope conflicts with {other['claim_id']}."
            )


def _matches_work_after(
    snapshot: dict[str, Any] | None, before: dict[str, Any] | None, after: bytes
) -> bool:
    mode = before["mode"] if before else (0o666 if os.name == "nt" else 0o644)
    return (
        snapshot is not None
        and snapshot["bytes"] == base64.b64encode(after).decode("ascii")
        and snapshot["mode"] == mode
    )


def _apply_work_operation(
    model: ProjectModel, receipt: Path, journal: dict[str, Any]
) -> None:
    work_id = journal["claim"]["work_id"]
    if not WORK_RE.fullmatch(work_id) or not CLAIM_RE.fullmatch(
        journal["claim"]["claim_id"]
    ):
        raise EidosError("work_recovery", "Invalid operation receipt identity.")
    target = (
        _configured_path(model.root, model.context, "work_root", ".agents/eidos/work")
        / f"{work_id}.md"
    )
    claim_path = _claims_root(model.root) / f"{journal['claim']['claim_id']}.json"
    for path in (target, claim_path, receipt):
        for parent in [path, *path.parents]:
            if _is_reparse(parent):
                raise EidosError(
                    "work_path", "Operation paths cannot traverse reparse points."
                )
    after_work = journal["content"].encode("utf-8")
    after_claim = (
        json.dumps(journal["claim"], ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")
    pairs = [
        (target, journal["before_work"], after_work),
        (claim_path, journal["before_claim"], after_claim),
    ]
    all_published = all(
        _matches_work_after(_file_snapshot(path), before, after)
        for path, before, after in pairs
    )
    if journal["state"] == "complete":
        if not all_published:
            raise EidosError(
                "work_changed",
                "Completed operation bytes changed; refusing to overwrite them.",
            )
        return
    _candidate_work(model, target, journal["content"])
    if all_published:
        # A crash after both publications only needs acknowledgement, not a new lease.
        _require_claim_worktree(model.root, journal["claim"])
        journal["state"] = "complete"
        _journal_write(receipt, journal)
        return
    if journal["operation"] == "finish":
        prior_claim = json.loads(base64.b64decode(journal["before_claim"]["bytes"]))
        prior_claim = _validate_claim(claim_path, prior_claim, model.root)
        if (
            prior_claim["status"] != "active"
            or prior_claim["claim_id"] != journal["claim"]["claim_id"]
            or prior_claim["actor_id"] != journal["request"]["actor"]
            or _parse_timestamp(prior_claim["expires_at"]) <= _utc_now()
        ):
            raise EidosError(
                "claim_expired",
                "Pending finish requires its original active unexpired lease; inspect recovery before adopting.",
            )
    _check_operation_claim(model, journal["claim"], journal["operation"] == "start")
    # An interrupted operation can contain only its recorded before/after bytes.
    for path, before, after in pairs:
        current = _file_snapshot(path)
        if current != before and not _matches_work_after(current, before, after):
            raise EidosError(
                "work_changed",
                "Concurrent edit conflicts with pending operation; receipt retained.",
            )
    guards = {
        key: value
        for key, value in journal["guards"].items()
        if key != _relative(target, model.root)
    }
    head = journal["head"]
    if (
        _work_guards(model, target) != guards
        or _run_git(model.root, "rev-parse", "HEAD") != head
    ):
        raise EidosError(
            "work_changed",
            "Project inputs changed since operation preparation; receipt retained.",
        )
    try:
        for path, before, after in pairs:
            if (
                _work_guards(model, target) != guards
                or _run_git(model.root, "rev-parse", "HEAD") != head
            ):
                raise EidosError("work_changed", "Project changed during operation.")
            current = _file_snapshot(path)
            if current != before and not _matches_work_after(current, before, after):
                raise EidosError("work_changed", "Target changed during operation.")
            if current is None or current["bytes"] != base64.b64encode(after).decode(
                "ascii"
            ):
                _atomic_bytes(path, after, before["mode"] if before else 0o644)
        if (
            _work_guards(model, target) != guards
            or _run_git(model.root, "rev-parse", "HEAD") != head
        ):
            raise EidosError(
                "work_changed", "Project changed before operation completion."
            )
        for path, before, after in pairs:
            current = _file_snapshot(path)
            if not _matches_work_after(current, before, after):
                raise EidosError(
                    "work_changed", "Published Work or claim changed before completion."
                )
        journal["state"] = "complete"
        _journal_write(receipt, journal)
    except (OSError, EidosError):
        journal["state"] = "pending"
        recovered = True
        for path, before, after in reversed(pairs):
            try:
                current = _file_snapshot(path)
                if current == before:
                    continue
                if not _matches_work_after(current, before, after):
                    recovered = False
                    continue
                if before is None:
                    path.unlink()
                else:
                    _atomic_bytes(
                        path, base64.b64decode(before["bytes"]), before["mode"]
                    )
                    os.utime(path, ns=(path.stat().st_atime_ns, before["mtime_ns"]))
            except OSError:
                recovered = False
        raise EidosError(
            "work_retry" if recovered else "work_recovery_required",
            "Operation failed; original request can retry. Recovery receipt retained."
            if recovered
            else "Operation failed and recovery is incomplete; inspect retained receipt and conflicting paths.",
        )


def _validate_operation_receipt(
    journal: Any, request: dict[str, Any], operation: str, root: Path
) -> None:
    required = {
        "operation",
        "request",
        "state",
        "content",
        "claim",
        "guards",
        "head",
        "before_work",
        "before_claim",
    }
    if not isinstance(journal, dict) or set(journal) != required:
        raise EidosError("work_recovery", "Malformed operation receipt.")
    if (
        journal["request"] != request
        or journal["operation"] != operation
        or journal["state"] not in {"pending", "complete"}
        or not isinstance(journal["content"], str)
        or not isinstance(journal["head"], str)
        or not COMMIT_RE.fullmatch(journal["head"])
        or not isinstance(journal["guards"], dict)
    ):
        raise EidosError("work_recovery", "Operation receipt does not match request.")
    raw_claim = journal["claim"]
    if (
        not isinstance(raw_claim, dict)
        or not isinstance(raw_claim.get("claim_id"), str)
        or not CLAIM_RE.fullmatch(raw_claim["claim_id"])
    ):
        raise EidosError("work_recovery", "Malformed receipt claim identity.")
    claim = _validate_claim(Path(f"{raw_claim['claim_id']}.json"), raw_claim, root)
    if (
        claim["actor_id"] != request["actor"]
        or (
            operation == "finish"
            and (
                claim["work_id"] != request["work_id"]
                or claim["claim_id"] != request["claim_id"]
            )
        )
        or (
            operation == "start"
            and (
                claim["member_id"] != request["owner"]
                or ("id" in request and claim["work_id"] != request["id"])
            )
        )
    ):
        raise EidosError(
            "work_recovery", "Receipt claim identity differs from request."
        )
    for name in ("before_work", "before_claim"):
        snapshot = journal[name]
        if snapshot is None:
            if operation != "start":
                raise EidosError(
                    "work_recovery", "Finish receipt requires prior snapshots."
                )
            continue
        if (
            operation == "start"
            or not isinstance(snapshot, dict)
            or set(snapshot) != {"bytes", "mode", "mtime_ns"}
        ):
            raise EidosError("work_recovery", "Malformed prior snapshot.")
        if not isinstance(snapshot["bytes"], str) or any(
            type(snapshot[k]) is not int or snapshot[k] < 0
            for k in ("mode", "mtime_ns")
        ):
            raise EidosError("work_recovery", "Invalid snapshot bytes or metadata.")
        base64.b64decode(snapshot["bytes"], validate=True)
    for path, guard in journal["guards"].items():
        if (
            not isinstance(path, str)
            or not isinstance(guard, dict)
            or set(guard) != {"sha256", "mode", "mtime_ns"}
        ):
            raise EidosError("work_recovery", "Malformed project guard.")
        if (
            not isinstance(guard["sha256"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", guard["sha256"])
            or any(
                type(guard[k]) is not int or guard[k] < 0 for k in ("mode", "mtime_ns")
            )
        ):
            raise EidosError("work_recovery", "Invalid project guard.")


def _command_work(args: argparse.Namespace) -> int:
    command = "work " + args.operation
    try:
        request = _work_input(args)
        model = _require_valid(args.root)
        digest = hashlib.sha256(
            json.dumps(
                [args.operation, request], sort_keys=True, ensure_ascii=False
            ).encode("utf-8")
        ).hexdigest()
        # Receipts are local to this worktree; claims remain common-directory leases.
        receipt = _git_dir(model.root) / "eidos" / "operations" / f"{digest}.json"
        for runtime in (receipt, _claims_root(model.root)):
            for parent in (runtime, *runtime.parents):
                if _is_reparse(parent):
                    raise EidosError(
                        "work_path", "Runtime paths cannot traverse reparse points."
                    )
        with _claim_lock(model.root):
            if _is_reparse(receipt) or _is_reparse(receipt.parent):
                raise EidosError(
                    "work_path", "Operation receipt cannot be a reparse point."
                )
            if receipt.exists():
                journal = json.loads(receipt.read_text(encoding="utf-8"))
                _validate_operation_receipt(
                    journal, request, args.operation, model.root
                )
            else:
                guards = _work_guards(model, model.root)
                before_work = (
                    None
                    if args.operation == "start"
                    else _file_snapshot(
                        _configured_path(
                            model.root, model.context, "work_root", ".agents/eidos/work"
                        )
                        / f"{request['work_id']}.md"
                    )
                )
                before_claim = (
                    None
                    if args.operation == "start"
                    else _file_snapshot(
                        _claims_root(model.root) / f"{request['claim_id']}.json"
                    )
                )
                head = _run_git(model.root, "rev-parse", "HEAD")
                model = _require_valid(args.root)
                if _work_guards(model, model.root) != guards:
                    raise EidosError(
                        "work_changed",
                        "Project changed while reading operation inputs.",
                    )
                if args.operation == "start":
                    target, content, claim = _new_work_operation(model, request)
                else:
                    target, content, claim = _finish_work_operation(model, request)
                _check_operation_claim(model, claim, args.operation == "start")
                if (
                    _file_snapshot(
                        _claims_root(model.root) / f"{claim['claim_id']}.json"
                    )
                    != before_claim
                ):
                    raise EidosError(
                        "work_changed", "Claim changed during operation preparation."
                    )
                if (
                    _work_guards(model, model.root) != guards
                    or _run_git(model.root, "rev-parse", "HEAD") != head
                ):
                    raise EidosError(
                        "work_changed", "Project changed during operation preparation."
                    )
                journal = {
                    "operation": args.operation,
                    "request": request,
                    "state": "pending",
                    "content": content,
                    "claim": claim,
                    "guards": guards,
                    "head": head,
                    "before_work": before_work,
                    "before_claim": before_claim,
                }
                _journal_write(receipt, journal)
            _apply_work_operation(model, receipt, journal)
        data = {
            "work_id": journal["claim"]["work_id"],
            "claim_id": journal["claim"]["claim_id"],
            "path": _relative(
                _configured_path(
                    model.root, model.context, "work_root", ".agents/eidos/work"
                )
                / f"{journal['claim']['work_id']}.md",
                model.root,
            ),
            "status": _parse_markdown_text(journal["content"], receipt).metadata[
                "status"
            ],
        }
        _emit({"ok": True, "command": command, "data": data, "error": None}, True)
        return 0
    except (EidosError, OSError, ValueError, KeyError, TypeError) as exc:
        code = exc.code if isinstance(exc, EidosError) else "work_operation_failed"
        message = (
            exc.message
            if isinstance(exc, EidosError)
            else "Invalid input, recovery receipt, or filesystem operation."
        )
        _emit(
            {
                "ok": False,
                "command": command,
                "data": None,
                "error": {"code": code, "message": message},
            },
            True,
        )
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Eidos v3 project harness")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    _add_root(validate)
    validate.add_argument("--json", action="store_true")
    validate.set_defaults(handler=_command_validate)
    catalog = sub.add_parser("catalog")
    _add_root(catalog)
    catalog.add_argument("--json", action="store_true")
    catalog.add_argument("--status", action="append")
    catalog.add_argument("--stage", action="append")
    catalog.add_argument("--owner", action="append")
    catalog.add_argument("--workstream", action="append")
    catalog.add_argument("--recent", type=int)
    catalog.set_defaults(handler=_command_catalog)
    focus = sub.add_parser("focus")
    _add_root(focus)
    focus.add_argument("--json", action="store_true")
    focus.add_argument("--summary", action="store_true")
    focus.add_argument("--limit", type=int)
    focus.set_defaults(handler=_command_focus)
    new_work = sub.add_parser("new-work")
    _add_root(new_work)
    new_work.add_argument("--id")
    new_work.add_argument("--slug")
    new_work.add_argument("--stage", required=True)
    new_work.add_argument("--title", required=True)
    new_work.add_argument("--owner", required=True)
    new_work.add_argument("--workstream", default="workstream:default")
    new_work.add_argument("--parent", default="none")
    new_work.add_argument("--depends-on", action="append")
    new_work.add_argument("--write-scope", action="append")
    new_work.add_argument("--risk", choices=sorted(RISKS), default="R1")
    new_work.add_argument("--start", action="store_true")
    new_work.set_defaults(handler=_command_new_work)
    work = sub.add_parser("work")
    operations = work.add_subparsers(dest="operation", required=True)
    for operation in ("start", "finish"):
        command = operations.add_parser(operation)
        _add_root(command)
        command.add_argument("--input", required=True)
        command.set_defaults(handler=_command_work)
    claim = sub.add_parser("claim")
    claim_sub = claim.add_subparsers(dest="claim_command", required=True)
    acquire = claim_sub.add_parser("acquire")
    _add_root(acquire)
    acquire.add_argument("--work-id", required=True)
    acquire.add_argument("--actor", required=True)
    acquire.add_argument("--member")
    acquire.add_argument("--path", action="append")
    acquire.add_argument("--base-commit")
    acquire.add_argument("--claim-id")
    acquire.add_argument("--ttl-seconds", type=int, default=1800)
    acquire.add_argument("--json", action="store_true")
    acquire.set_defaults(handler=_command_claim_acquire)
    for name, handler in (
        ("renew", _command_claim_renew),
        ("adopt", _command_claim_adopt),
    ):
        operation = claim_sub.add_parser(name)
        _add_root(operation)
        operation.add_argument("--claim-id", required=True)
        operation.add_argument("--actor", required=True)
        if name == "adopt":
            operation.add_argument("--member")
        operation.add_argument("--ttl-seconds", type=int, default=1800)
        operation.add_argument("--json", action="store_true")
        operation.set_defaults(handler=handler)
    release = claim_sub.add_parser("release")
    _add_root(release)
    release.add_argument("--claim-id", required=True)
    release.add_argument("--actor", required=True)
    release.add_argument("--json", action="store_true")
    release.set_defaults(handler=_command_claim_release)
    listing = claim_sub.add_parser("list", aliases=["conflicts"])
    _add_root(listing)
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(handler=_command_claim_list)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.handler(args))
    except EidosError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
