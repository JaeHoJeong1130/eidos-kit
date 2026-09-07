#!/usr/bin/env python3
"""Validate an installed Harness Kit and manage append-only failure knowledge."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


FAILURE_ID = re.compile(
    r"^F-(?P<date>\d{8})-(?P<ordinal>\d{2})-[a-z0-9]+(?:-[a-z0-9]+)*$"
)
WORK_ID = re.compile(r"^W-\d{8}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*$")
WORK_FIELDS = {
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
}
WORK_SECTIONS = [
    "Intent",
    "Plan",
    "Progress",
    "Result",
    "Evidence",
    "Deviation and Next",
]
REVISION_ID = re.compile(r"^D\d{4}$")
STAGE_ID = re.compile(r"^S\d{2,}$")
IDENTITY_ID = re.compile(r"^[a-z][a-z0-9-]*:[a-z0-9][a-z0-9-]*$")
WORKSTREAM_ID = re.compile(r"^workstream:[a-z0-9][a-z0-9-]*$")
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})$")
EIDOS_TOOL_SHA256 = "{{EIDOS_TOOL_SHA256}}"
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SECTIONS = ["Failed Assumption", "Root Cause", "Prevention", "Evidence"]
STATUSES = {"open", "mitigated", "resolved"}
FRONTMATTER = {
    "failure_id",
    "observed_on",
    "area",
    "tags",
    "status",
    "source_work_id",
    "enforced_by",
    "supersedes_id",
}
ABSOLUTE_PATH = re.compile(
    r"(?i)(?:[a-z]:[\\/]|(?<![:\w])/(?:[a-z0-9._-]+/)+[a-z0-9._-]+)[^\s]*"
)
UNC_PATH = re.compile(r"\\\\[a-z0-9._-]+\\[^\s]+", re.IGNORECASE)
SECRET = re.compile(
    r"(?i)(?:(?:password|passwd|secret|token|api[_-]?key|access[_-]?token|private[_-]?key)"
    r"\s*[:=]\s*\S+|authorization\s*:\s*bearer\s+\S+|\bsk-[a-z0-9_-]{8,}"
    r"|\bgh[pousr]_[a-z0-9]{16,}|\bglpat-[a-z0-9_-]{12,}|\bAKIA[A-Z0-9]{12,}"
    r"|\bxox[baprs]-[a-z0-9-]{10,}|\bAIza[a-z0-9_-]{20,}"
    r"|\bsk_(?:live|test)_[a-z0-9]{10,}|\bnpm_[a-z0-9]{16,}"
    r"|\beyJ[a-z0-9_-]{8,}\.[a-z0-9_-]{8,}\.[a-z0-9_-]{8,}"
    r"|-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----)"
)
PERSONAL = re.compile(
    r"(?i)(?:salary|health|family|주민등록|급여|건강|가족|\b\d{3}[- ]\d{3}[- ]\d{4}\b)"
)
RAW_MATERIAL = re.compile(
    r"(?i)(?:raw[-_ ]?(?:log|chat|conversation|transcript)|원문\s*(?:로그|대화|채팅))"
)


class HarnessError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Failure:
    path: Path
    metadata: dict[str, str]
    title: str
    sections: dict[str, str]


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


def _root(raw: Path) -> Path:
    absolute = Path(os.path.abspath(raw))
    for component in (absolute, *absolute.parents):
        if (component.exists() or component.is_symlink()) and _is_reparse(component):
            raise HarnessError(
                "root_reparse", f"--root traverses a reparse point: {component}"
            )
    root = absolute.resolve()
    if not root.is_dir():
        raise HarnessError("root_missing", f"Root does not exist: {root}")
    return root


def _safe(root: Path, relative: str, label: str) -> Path:
    raw = relative.replace("\\", "/")
    candidate = Path(raw)
    if (
        not raw.strip()
        or candidate.is_absolute()
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise HarnessError("path_invalid", f"Unsafe {label}: {relative}")
    current = root
    for part in candidate.parts:
        current /= part
        if (current.exists() or current.is_symlink()) and _is_reparse(current):
            raise HarnessError("path_reparse", f"{label} traverses a reparse point.")
    try:
        (root / candidate).resolve().relative_to(root)
    except ValueError as exc:
        raise HarnessError("path_escape", f"{label} escapes the repository.") from exc
    return root / candidate


def _load_context(root: Path) -> dict[str, Any]:
    path = _safe(root, ".agents/context.json", "context")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HarnessError(
            "context_invalid", "Context must be a UTF-8 JSON object."
        ) from exc
    if not isinstance(value, dict) or not isinstance(value.get("harness"), dict):
        raise HarnessError("context_invalid", "Context harness object is required.")
    harness = value["harness"]
    if harness.get("version") != 1 or not isinstance(
        harness.get("eidos_enabled"), bool
    ):
        raise HarnessError("context_invalid", "Harness context version is invalid.")
    return value


def _work_metadata(root: Path, work_id: str, project_id: str) -> dict[str, str]:
    work = _safe(root, f".agents/eidos/work/{work_id}.md", "referenced Work")
    if not work.is_file():
        raise HarnessError("failure_work", f"Referenced Work is missing: {work_id}")
    try:
        lines = work.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise HarnessError("failure_work", f"Cannot read Work: {work_id}") from exc
    if not lines or lines[0] != "---":
        raise HarnessError("failure_work", f"Work frontmatter is missing: {work_id}")
    try:
        closing = lines[1:].index("---") + 1
    except ValueError as exc:
        raise HarnessError(
            "failure_work", f"Work frontmatter is unclosed: {work_id}"
        ) from exc
    metadata: dict[str, str] = {}
    for line in lines[1:closing]:
        if not line or line[:1].isspace() or ":" not in line:
            raise HarnessError(
                "failure_work", f"Work frontmatter is not scalar: {work_id}"
            )
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip()
        if key in metadata:
            raise HarnessError("failure_work", f"Duplicate Work field: {work_id}")
        metadata[key] = value
    if (
        set(metadata) != WORK_FIELDS
        or metadata.get("eidos_version") != "3"
        or metadata.get("document_type") != "work"
        or metadata.get("project_id") != project_id
        or metadata.get("work_id") != work_id
        or metadata.get("status")
        not in {"planned", "in_progress", "blocked", "done", "failed", "cancelled"}
        or not REVISION_ID.fullmatch(metadata.get("direction_revision", ""))
        or not STAGE_ID.fullmatch(metadata.get("stage_id", ""))
        or not IDENTITY_ID.fullmatch(metadata.get("owner_id", ""))
        or not WORKSTREAM_ID.fullmatch(metadata.get("workstream_id", ""))
        or (
            metadata.get("parent_work_id") != "none"
            and not WORK_ID.fullmatch(metadata.get("parent_work_id", ""))
        )
        or metadata.get("risk") not in {"R0", "R1", "R2", "R3"}
        or not TIMESTAMP.fullmatch(metadata.get("created_at", ""))
        or not TIMESTAMP.fullmatch(metadata.get("updated_at", ""))
        or (
            metadata.get("started_at") != "none"
            and not TIMESTAMP.fullmatch(metadata.get("started_at", ""))
        )
        or (
            metadata.get("closed_at") != "none"
            and not TIMESTAMP.fullmatch(metadata.get("closed_at", ""))
        )
    ):
        raise HarnessError(
            "failure_work", f"Referenced Work is not canonical: {work_id}"
        )
    body = lines[closing + 1 :]
    headings = [line[3:].strip() for line in body if line.startswith("## ")]
    if headings != WORK_SECTIONS:
        raise HarnessError(
            "failure_work", f"Work sections are not canonical: {work_id}"
        )
    section_values: dict[str, list[str]] = {name: [] for name in WORK_SECTIONS}
    current: str | None = None
    for line in body:
        if line.startswith("## "):
            current = line[3:].strip()
        elif current is not None:
            section_values[current].append(line)
    if any(not "\n".join(values).strip() for values in section_values.values()):
        raise HarnessError("failure_work", f"Work sections are empty: {work_id}")
    return metadata


def _validate_enforcement(root: Path, raw: str, failure_name: str) -> None:
    values = [item.strip() for item in raw.split(",")]
    if not values or "none" in values:
        raise HarnessError(
            "failure_enforcement", f"Failure has no enforcement link: {failure_name}"
        )
    for relative in values:
        target = _safe(root, relative, "failure enforcement")
        normalized = Path(relative.replace("\\", "/")).as_posix()
        allowed = normalized.startswith(
            (
                ".agents/tools/",
                ".agents/workflows/",
                ".agents/routes/",
                "src/",
                "tests/",
                "scripts/",
            )
        ) or normalized in {
            ".agents/routing.md",
            "pyproject.toml",
            "Cargo.toml",
            "package.json",
            "Makefile",
        }
        if not allowed or not target.is_file():
            raise HarnessError(
                "failure_enforcement",
                f"Enforcement target is not an executable guard: {relative}",
            )


def _validate_eidos_repository(root: Path) -> None:
    """Run only the manifest-bound Eidos validator, never arbitrary project code."""

    harness_manifest_path = _safe(
        root, ".agents/harness/kit-manifest.json", "Harness manifest"
    )
    eidos_manifest_path = _safe(
        root, ".agents/eidos/kit-manifest.json", "Eidos manifest"
    )
    eidos_tool = _safe(root, ".agents/tools/eidos.py", "Eidos validator")
    try:
        harness_manifest = json.loads(harness_manifest_path.read_text(encoding="utf-8"))
        eidos_manifest_bytes = eidos_manifest_path.read_bytes()
        eidos_manifest = json.loads(eidos_manifest_bytes)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HarnessError(
            "failure_work", "Eidos trust manifests are invalid."
        ) from exc
    eidos_identity = harness_manifest.get("eidos")
    tool_record = eidos_manifest.get("files", {}).get(".agents/tools/eidos.py")
    if (
        not isinstance(eidos_identity, dict)
        or eidos_identity.get("enabled") is not True
        or eidos_identity.get("manifest_sha256")
        != hashlib.sha256(eidos_manifest_bytes).hexdigest()
        or not isinstance(tool_record, dict)
        or tool_record.get("ownership") != "kit"
        or not eidos_tool.is_file()
        or _is_reparse(eidos_tool)
        or tool_record.get("sha256")
        != hashlib.sha256(eidos_tool.read_bytes()).hexdigest()
        or tool_record.get("sha256") != EIDOS_TOOL_SHA256
    ):
        raise HarnessError("failure_work", "Eidos validator trust binding is invalid.")
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(eidos_tool),
            "validate",
            "--json",
            "--root",
            str(root),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        check=False,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise HarnessError(
            "failure_work", "Eidos validation output is invalid."
        ) from exc
    if result.returncode != 0 or payload.get("ok") is not True:
        raise HarnessError("failure_work", "Referenced Work fails Eidos validation.")


def _parse_failure(root: Path, path: Path) -> Failure:
    if _is_reparse(path):
        raise HarnessError(
            "failure_reparse", f"Failure record is a reparse point: {path.name}"
        )
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise HarnessError(
            "failure_read", f"Cannot read failure record: {path.name}"
        ) from exc
    if (
        ABSOLUTE_PATH.search(text)
        or UNC_PATH.search(text)
        or SECRET.search(text)
        or PERSONAL.search(text)
        or RAW_MATERIAL.search(text)
    ):
        raise HarnessError(
            "failure_privacy", f"Private or machine-local text: {path.name}"
        )
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise HarnessError("failure_frontmatter", f"Missing frontmatter: {path.name}")
    try:
        closing = lines[1:].index("---") + 1
    except ValueError as exc:
        raise HarnessError(
            "failure_frontmatter", f"Unclosed frontmatter: {path.name}"
        ) from exc
    metadata: dict[str, str] = {}
    for line in lines[1:closing]:
        if not line or line[:1].isspace() or ":" not in line:
            raise HarnessError(
                "failure_frontmatter", f"Scalar frontmatter required: {path.name}"
            )
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip()
        if key in metadata:
            raise HarnessError(
                "failure_frontmatter", f"Duplicate field {key}: {path.name}"
            )
        metadata[key] = value
    if set(metadata) != FRONTMATTER or any(not metadata[key] for key in metadata):
        raise HarnessError(
            "failure_schema", f"Failure fields are not exact: {path.name}"
        )
    failure_id = metadata["failure_id"]
    match = FAILURE_ID.fullmatch(failure_id)
    if match is None or path.stem != failure_id:
        raise HarnessError("failure_id", f"Failure ID/path mismatch: {path.name}")
    try:
        observed = date.fromisoformat(metadata["observed_on"])
    except ValueError as exc:
        raise HarnessError("failure_date", f"Invalid observed_on: {path.name}") from exc
    if observed.strftime("%Y%m%d") != match.group("date"):
        raise HarnessError(
            "failure_date", f"ID date differs from observed_on: {path.name}"
        )
    if path.parent.name != observed.strftime("%Y"):
        raise HarnessError(
            "failure_path", f"Failure year directory is incorrect: {path.name}"
        )
    if metadata["status"] not in STATUSES:
        raise HarnessError("failure_status", f"Invalid status: {path.name}")
    for key in ("tags", "enforced_by"):
        values = [item.strip() for item in metadata[key].split(",")]
        if (
            not values
            or any(not item for item in values)
            or len(values) != len(set(values))
        ):
            raise HarnessError("failure_csv", f"Invalid {key}: {path.name}")
    body = lines[closing + 1 :]
    title_lines = [line[2:].strip() for line in body if line.startswith("# ")]
    headings = [line[3:].strip() for line in body if line.startswith("## ")]
    if len(title_lines) != 1 or headings != SECTIONS:
        raise HarnessError(
            "failure_sections", f"Failure sections are not exact: {path.name}"
        )
    sections: dict[str, list[str]] = {name: [] for name in SECTIONS}
    current: str | None = None
    for line in body:
        if line.startswith("## "):
            current = line[3:].strip()
        elif current is not None:
            sections[current].append(line)
    normalized = {name: "\n".join(values).strip() for name, values in sections.items()}
    if any(not value for value in normalized.values()):
        raise HarnessError("failure_sections", f"Empty failure section: {path.name}")
    return Failure(path, metadata, title_lines[0], normalized)


def _failure_paths(root: Path) -> list[Path]:
    base = _safe(root, ".agents/failures", "failure root")
    if not base.is_dir():
        return []
    paths: list[Path] = []
    for year in sorted(base.iterdir()):
        if year.name.startswith("_"):
            continue
        if _is_reparse(year):
            raise HarnessError(
                "failure_reparse", f"Failure year is a reparse point: {year.name}"
            )
        if not year.is_dir() or re.fullmatch(r"\d{4}", year.name) is None:
            raise HarnessError("failure_path", f"Unexpected failure entry: {year.name}")
        paths.extend(sorted(year.glob("F-*.md")))
        unexpected = [path.name for path in year.iterdir() if path not in paths]
        if unexpected:
            raise HarnessError(
                "failure_path", f"Unexpected failure entry: {unexpected[0]}"
            )
    return paths


def _peek_failure_metadata(path: Path) -> dict[str, str]:
    """Read only bounded frontmatter so search never loads unrelated bodies."""

    if _is_reparse(path):
        raise HarnessError(
            "failure_reparse", f"Failure record is a reparse point: {path.name}"
        )
    try:
        with path.open("r", encoding="utf-8") as handle:
            lines: list[str] = []
            size = 0
            for line in handle:
                size += len(line.encode("utf-8"))
                if size > 16_384 or len(lines) >= 64:
                    raise HarnessError(
                        "failure_frontmatter",
                        f"Failure frontmatter is oversized: {path.name}",
                    )
                lines.append(line.rstrip("\r\n"))
                if len(lines) > 1 and lines[-1] == "---":
                    break
    except (OSError, UnicodeError) as exc:
        raise HarnessError(
            "failure_read", f"Cannot read failure record: {path.name}"
        ) from exc
    if len(lines) < 3 or lines[0] != "---" or lines[-1] != "---":
        raise HarnessError("failure_frontmatter", f"Invalid frontmatter: {path.name}")
    metadata: dict[str, str] = {}
    for line in lines[1:-1]:
        if not line or line[:1].isspace() or ":" not in line:
            raise HarnessError(
                "failure_frontmatter", f"Scalar frontmatter required: {path.name}"
            )
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip()
        if key in metadata:
            raise HarnessError(
                "failure_frontmatter", f"Duplicate field {key}: {path.name}"
            )
        metadata[key] = value
    if set(metadata) != FRONTMATTER:
        raise HarnessError(
            "failure_schema", f"Failure fields are not exact: {path.name}"
        )
    failure_id = metadata["failure_id"]
    match = FAILURE_ID.fullmatch(failure_id)
    if match is None or path.stem != failure_id:
        raise HarnessError("failure_id", f"Failure ID/path mismatch: {path.name}")
    try:
        observed = date.fromisoformat(metadata["observed_on"])
    except ValueError as exc:
        raise HarnessError("failure_date", f"Invalid observed_on: {path.name}") from exc
    if observed.strftime("%Y%m%d") != match.group(
        "date"
    ) or path.parent.name != observed.strftime("%Y"):
        raise HarnessError("failure_date", f"Failure date/path mismatch: {path.name}")
    if metadata["status"] not in STATUSES:
        raise HarnessError("failure_status", f"Invalid status: {path.name}")
    for key in ("tags", "enforced_by"):
        values = [item.strip() for item in metadata[key].split(",")]
        if (
            not values
            or any(not item for item in values)
            or len(values) != len(set(values))
        ):
            raise HarnessError("failure_csv", f"Invalid {key}: {path.name}")
    return metadata


def _validate_failure_graph(
    root: Path,
    entries: list[tuple[Path, dict[str, str]]],
    *,
    verify_references: bool = True,
) -> None:
    context = _load_context(root)
    eidos = context["harness"]["eidos_enabled"]
    project = context.get("project")
    project_id = project.get("id") if isinstance(project, dict) else None
    if eidos:
        _validate_eidos_repository(root)
    by_id: dict[str, tuple[Path, dict[str, str]]] = {}
    for path, metadata in entries:
        failure_id = metadata["failure_id"]
        if failure_id in by_id:
            raise HarnessError(
                "failure_duplicate", f"Duplicate failure ID: {failure_id}"
            )
        by_id[failure_id] = (path, metadata)
    superseded_by: set[str] = set()
    for path, metadata in entries:
        source = metadata["source_work_id"]
        if eidos:
            if not WORK_ID.fullmatch(source):
                raise HarnessError(
                    "failure_work", f"Eidos failure needs Work: {path.name}"
                )
            if verify_references:
                if not isinstance(project_id, str):
                    raise HarnessError("failure_work", "Context project ID is missing.")
                _work_metadata(root, source, project_id)
        elif source != "none":
            raise HarnessError(
                "failure_work", "Eidos-disabled failures require source_work_id: none"
            )
        _validate_enforcement(root, metadata["enforced_by"], path.name)
        supersedes = metadata["supersedes_id"]
        if supersedes != "none":
            previous = by_id.get(supersedes)
            if previous is None or supersedes in superseded_by:
                raise HarnessError(
                    "failure_supersession", f"Invalid supersession: {path.name}"
                )
            if previous[1]["area"] != metadata["area"]:
                raise HarnessError(
                    "failure_supersession",
                    f"Supersession area differs: {path.name}",
                )
            superseded_by.add(supersedes)
    for path, metadata in entries:
        seen: set[str] = set()
        current = metadata
        while current["supersedes_id"] != "none":
            target = current["supersedes_id"]
            if target in seen or target == metadata["failure_id"]:
                raise HarnessError(
                    "failure_supersession", f"Supersession cycle: {path.name}"
                )
            seen.add(target)
            current = by_id[target][1]
            if current["observed_on"] > metadata["observed_on"]:
                raise HarnessError(
                    "failure_supersession",
                    f"Correction predates its target: {path.name}",
                )


def _load_failures(root: Path, *, verify_references: bool = True) -> list[Failure]:
    failures = [_parse_failure(root, path) for path in _failure_paths(root)]
    _validate_failure_graph(
        root,
        [(failure.path, failure.metadata) for failure in failures],
        verify_references=verify_references,
    )
    return failures


def _table_rows(text: str, expected_header: list[str], label: str) -> list[list[str]]:
    lines = [line.strip() for line in text.splitlines() if line.strip().startswith("|")]
    if len(lines) < 3:
        raise HarnessError("table_schema", f"Missing table rows: {label}")

    def cells(line: str) -> list[str]:
        return [item.strip() for item in line.strip("|").split("|")]

    if cells(lines[0]) != expected_header:
        raise HarnessError("table_schema", f"Unexpected table header: {label}")
    separator = cells(lines[1])
    if len(separator) != len(expected_header) or any(
        re.fullmatch(r":?-{3,}:?", item) is None for item in separator
    ):
        raise HarnessError("table_schema", f"Invalid table separator: {label}")
    rows = [cells(line) for line in lines[2:]]
    if any(len(row) != len(expected_header) for row in rows):
        raise HarnessError("table_schema", f"Invalid table row: {label}")
    return rows


def _validate_route_rows(
    root: Path, text: str, label: str, *, builtin: bool
) -> set[str]:
    rows = _table_rows(
        text,
        ["Route", "Use when", "Risk", "Rubrics", "Failure tags"],
        label,
    )
    route_names: set[str] = set()
    expected_builtin = {
        "read-only": ("R0", ["none"]),
        "change": ("R1", ["common-change"]),
        "public-contract": ("R2", ["common-change", "public-contract"]),
        "artifact-or-model": ("R2", ["common-change", "artifact-or-model"]),
        "release-or-external": (
            "R3",
            ["common-change", "release-or-external"],
        ),
    }
    for route, use_when, risk, rubrics, tags in rows:
        names = [item.strip() for item in rubrics.split(",")]
        if (
            not route
            or route in route_names
            or not use_when
            or risk not in {"R0", "R1", "R2", "R3"}
            or not tags
            or any(not name for name in names)
        ):
            raise HarnessError("routing_schema", f"Invalid route: {route}")
        route_names.add(route)
        if risk == "R0" and names != ["none"]:
            raise HarnessError("routing_schema", "R0 route must use no rubric.")
        if risk == "R1" and "common-change" not in names:
            raise HarnessError("routing_schema", "R1 route requires common-change.")
        if risk == "R2" and (
            "common-change" not in names or len(set(names) - {"common-change"}) < 1
        ):
            raise HarnessError(
                "routing_schema", "R2 route requires common-change and a profile."
            )
        if risk == "R3" and set(names) != {
            "common-change",
            "release-or-external",
        }:
            raise HarnessError(
                "routing_schema", "R3 route requires the release/external profile."
            )
        for name in names:
            if (
                name != "none"
                and not (root / ".agents/rubrics" / f"{name}.md").is_file()
            ):
                raise HarnessError("routing_rubric", f"Unknown rubric: {name}")
    if (
        builtin
        and {
            route: (risk, [item.strip() for item in rubrics.split(",")])
            for route, _use_when, risk, rubrics, _tags in rows
        }
        != expected_builtin
    ):
        raise HarnessError("routing_schema", "Built-in route contract changed.")
    return route_names


def _validate_structure(root: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    required = [
        "AGENTS.md",
        "CLAUDE.md",
        "FAILURE_LOG.md",
        ".agents/context.json",
        ".agents/routing.md",
        ".agents/harness/contract.md",
        ".agents/harness/kit-manifest.json",
        ".agents/failures/_template.md",
        ".agents/routes/_template.md",
        ".agents/rubrics/common-change.md",
        ".agents/rubrics/public-contract.md",
        ".agents/rubrics/artifact-or-model.md",
        ".agents/rubrics/release-or-external.md",
        ".agents/workflows/change.md",
        ".agents/workflows/verification.md",
        ".agents/skills/project-harness/SKILL.md",
        ".agents/tools/harness.py",
        ".claude/skills/project-harness/SKILL.md",
    ]
    for relative in required:
        try:
            path = _safe(root, relative, relative)
        except HarnessError as exc:
            findings.append(
                {"severity": "error", "code": exc.code, "message": exc.message}
            )
            continue
        if not path.is_file():
            findings.append(
                {"severity": "error", "code": "required_missing", "message": relative}
            )
    for adapter in (
        root / "CLAUDE.md",
        root / ".agents/skills/project-harness/SKILL.md",
        root / ".claude/skills/project-harness/SKILL.md",
    ):
        if adapter.is_file() and not _is_reparse(adapter):
            text = adapter.read_text(encoding="utf-8")
            duplicated_policy = re.search(
                r"\bR[0-3]\b|NEEDS_REVISION|INCONCLUSIVE|\bapproval\b|independent review"
                r"|\b(?:push|release|deploy|delete|commit|stage)\b|write[- ]scope"
                r"|read[- ]only|self[- ]check|public[- ]contract|external system",
                text,
                re.IGNORECASE,
            )
            manifest_bound = False
            try:
                manifest = json.loads(
                    (root / ".agents/harness/kit-manifest.json").read_text(
                        encoding="utf-8"
                    )
                )
                relative = adapter.relative_to(root).as_posix()
                record = manifest.get("files", {}).get(relative)
                manifest_bound = (
                    isinstance(record, dict)
                    and record.get("ownership") == "kit"
                    and record.get("sha256")
                    == hashlib.sha256(adapter.read_bytes()).hexdigest()
                )
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                manifest_bound = False
            if (
                "AGENTS.md" not in text
                or len(text.splitlines()) > 16
                or duplicated_policy is not None
                or not manifest_bound
            ):
                findings.append(
                    {
                        "severity": "error",
                        "code": "adapter_not_thin",
                        "message": adapter.as_posix(),
                    }
                )
    routing = root / ".agents/routing.md"
    route_names: set[str] = set()
    if routing.is_file() and not _is_reparse(routing):
        try:
            route_names = _validate_route_rows(
                root,
                routing.read_text(encoding="utf-8"),
                ".agents/routing.md",
                builtin=True,
            )
        except HarnessError as exc:
            findings.append(
                {"severity": "error", "code": exc.code, "message": exc.message}
            )
    route_root = root / ".agents/routes"
    if route_root.is_dir() and not _is_reparse(route_root):
        for route_path in sorted(route_root.glob("*.md")):
            try:
                if _is_reparse(route_path):
                    raise HarnessError(
                        "route_reparse",
                        f"Project route is a reparse point: {route_path.name}",
                    )
                project_names = _validate_route_rows(
                    root,
                    route_path.read_text(encoding="utf-8"),
                    route_path.name,
                    builtin=False,
                )
                duplicate = route_names.intersection(project_names)
                if duplicate:
                    raise HarnessError(
                        "routing_duplicate",
                        f"Project route shadows another route: {sorted(duplicate)[0]}",
                    )
                route_names.update(project_names)
            except (OSError, UnicodeError, HarnessError) as exc:
                if isinstance(exc, HarnessError):
                    code, message = exc.code, exc.message
                else:
                    code, message = (
                        "route_read",
                        f"Cannot read route: {route_path.name}",
                    )
                findings.append({"severity": "error", "code": code, "message": message})
    rubric_root = root / ".agents/rubrics"
    for rubric in (
        rubric_root.glob("*.md")
        if rubric_root.is_dir() and not _is_reparse(rubric_root)
        else []
    ):
        try:
            rows = _table_rows(
                rubric.read_text(encoding="utf-8"),
                [
                    "Blocking",
                    "Criterion",
                    "Evaluation",
                    "Required evidence",
                    "N/A condition",
                ],
                rubric.name,
            )
            criteria: set[str] = set()
            for blocking, criterion, evaluation, evidence, na_condition in rows:
                if (
                    blocking not in {"yes", "no"}
                    or not criterion
                    or criterion in criteria
                    or not evaluation
                    or not evidence
                    or not na_condition
                ):
                    raise HarnessError(
                        "rubric_schema", f"Invalid rubric row: {rubric.name}"
                    )
                criteria.add(criterion)
        except HarnessError as exc:
            findings.append(
                {"severity": "error", "code": exc.code, "message": exc.message}
            )
    contract = root / ".agents/harness/contract.md"
    if contract.is_file() and not _is_reparse(contract):
        contract_text = contract.read_text(encoding="utf-8")
        for verdict in ("PASS", "NEEDS_REVISION", "INCONCLUSIVE"):
            if verdict not in contract_text:
                findings.append(
                    {
                        "severity": "error",
                        "code": "verdict_missing",
                        "message": verdict,
                    }
                )
    return findings


def _command_validate(args: argparse.Namespace) -> int:
    findings: list[dict[str, str]] = []
    try:
        root = _root(args.root)
        _load_context(root)
        findings.extend(_validate_structure(root))
        _load_failures(root)
    except HarnessError as exc:
        findings.append({"severity": "error", "code": exc.code, "message": exc.message})
    payload = {"ok": not findings, "findings": findings}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for finding in findings:
            print(f"ERROR {finding['code']}: {finding['message']}")
        print(
            "Harness validation: PASS"
            if payload["ok"]
            else "Harness validation: FAILED"
        )
    return 0 if payload["ok"] else 2


def _failure_row(root: Path, failure: Failure) -> dict[str, Any]:
    return {
        "failure_id": failure.metadata["failure_id"],
        "observed_on": failure.metadata["observed_on"],
        "area": failure.metadata["area"],
        "tags": [item.strip() for item in failure.metadata["tags"].split(",")],
        "status": failure.metadata["status"],
        "source_work_id": failure.metadata["source_work_id"],
        "enforced_by": [
            item.strip() for item in failure.metadata["enforced_by"].split(",")
        ],
        "supersedes_id": failure.metadata["supersedes_id"],
        "title": failure.title,
        "path": failure.path.relative_to(root).as_posix(),
    }


def _command_failure_list(args: argparse.Namespace) -> int:
    root = _root(args.root)
    failures = _load_failures(root)
    rows = [_failure_row(root, failure) for failure in failures]
    print(
        json.dumps(
            {"ok": True, "failures": rows}, ensure_ascii=False, indent=2, sort_keys=True
        )
    )
    return 0


def _command_failure_search(args: argparse.Namespace) -> int:
    root = _root(args.root)
    wanted = {
        item.strip() for value in args.tag for item in value.split(",") if item.strip()
    }
    rows = []
    metadata_entries = [
        (path, _peek_failure_metadata(path)) for path in _failure_paths(root)
    ]
    _validate_failure_graph(root, metadata_entries)
    for path, metadata in metadata_entries:
        tags = {item.strip() for item in metadata["tags"].split(",")}
        if wanted and not wanted.intersection(tags):
            continue
        if args.area and metadata["area"] != args.area:
            continue
        failure = _parse_failure(root, path)
        rows.append(_failure_row(root, failure))
    print(
        json.dumps(
            {"ok": True, "failures": rows}, ensure_ascii=False, indent=2, sort_keys=True
        )
    )
    return 0


def _input_object(args: argparse.Namespace) -> dict[str, Any]:
    if args.input_json:
        raw = args.input_json
    elif args.input:
        raw = Path(args.input).read_text(encoding="utf-8")
    else:
        raw = sys.stdin.read()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HarnessError("input_json", "Failure input must be JSON.") from exc
    if not isinstance(value, dict):
        raise HarnessError("input_schema", "Failure input must be an object.")
    return value


def _command_failure_new(args: argparse.Namespace) -> int:
    root = _root(args.root)
    context = _load_context(root)
    value = _input_object(args)
    required = {
        "observed_on",
        "area",
        "tags",
        "status",
        "source_work_id",
        "enforced_by",
        "title",
        "failed_assumption",
        "root_cause",
        "prevention",
        "evidence",
        "slug",
    }
    allowed = required | {"supersedes_id"}
    if set(value) != required and set(value) != allowed:
        raise HarnessError("input_schema", "Failure input fields are not exact.")
    if not SLUG.fullmatch(str(value["slug"])):
        raise HarnessError("input_slug", "slug must be kebab-case.")
    try:
        observed = date.fromisoformat(str(value["observed_on"]))
    except ValueError as exc:
        raise HarnessError("input_date", "observed_on must be YYYY-MM-DD.") from exc
    existing = _load_failures(root)
    ordinal = 1 + max(
        (
            int(match.group("ordinal"))
            for failure in existing
            if (match := FAILURE_ID.fullmatch(failure.metadata["failure_id"]))
            and match.group("date") == observed.strftime("%Y%m%d")
        ),
        default=0,
    )
    if ordinal > 99:
        raise HarnessError(
            "failure_id_exhausted", "Daily failure ordinal is exhausted."
        )
    failure_id = f"F-{observed:%Y%m%d}-{ordinal:02d}-{value['slug']}"
    tags = value["tags"]
    enforced = value["enforced_by"]
    if not isinstance(tags, list) or not isinstance(enforced, list):
        raise HarnessError("input_schema", "tags and enforced_by must be arrays.")
    if any(not isinstance(item, str) or not item.strip() for item in tags + enforced):
        raise HarnessError(
            "input_schema", "tags and enforced_by require non-empty strings."
        )
    source = str(value["source_work_id"])
    if context["harness"]["eidos_enabled"] and not WORK_ID.fullmatch(source):
        raise HarnessError("failure_work", "Eidos-enabled failures require a Work ID.")
    metadata = {
        "failure_id": failure_id,
        "observed_on": observed.isoformat(),
        "area": str(value["area"]),
        "tags": ", ".join(tags),
        "status": str(value["status"]),
        "source_work_id": source,
        "enforced_by": ", ".join(enforced),
        "supersedes_id": str(value.get("supersedes_id", "none")),
    }
    body = (
        """---
"""
        + "\n".join(f"{key}: {item}" for key, item in metadata.items())
        + f"""
---

# {value["title"]}

## Failed Assumption

{value["failed_assumption"]}

## Root Cause

{value["root_cause"]}

## Prevention

{value["prevention"]}

## Evidence

{value["evidence"]}
"""
    )
    target = _safe(
        root,
        f".agents/failures/{observed:%Y}/{failure_id}.md",
        "new failure record",
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise HarnessError(
            "failure_exists", f"Failure already exists: {failure_id}"
        ) from exc
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(body)
    try:
        _parse_failure(root, target)
        _load_failures(root)
    except Exception:
        target.unlink(missing_ok=True)
        try:
            target.parent.rmdir()
        except OSError:
            pass
        raise
    print(target.relative_to(root).as_posix())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Installed Harness Kit tool")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--root", type=Path, default=Path.cwd())
    validate.add_argument("--json", action="store_true")
    validate.set_defaults(handler=_command_validate)
    failure = commands.add_parser("failure")
    failure_commands = failure.add_subparsers(dest="failure_command", required=True)
    for name, handler in (
        ("list", _command_failure_list),
        ("search", _command_failure_search),
        ("validate", _command_validate),
    ):
        command = failure_commands.add_parser(name)
        command.add_argument("--root", type=Path, default=Path.cwd())
        if name == "search":
            command.add_argument("--tag", action="append", default=[])
            command.add_argument("--area")
        elif name == "validate":
            command.add_argument("--json", action="store_true")
        command.set_defaults(handler=handler)
    new = failure_commands.add_parser("new")
    new.add_argument("--root", type=Path, default=Path.cwd())
    inputs = new.add_mutually_exclusive_group()
    inputs.add_argument("--input")
    inputs.add_argument("--input-json")
    new.set_defaults(handler=_command_failure_new)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.handler(args))
    except HarnessError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
