#!/usr/bin/env python3
"""Read-only repository layout inspection. No content classification is inferred as truth."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

POLICY = "_meta/layout.json"
ROLES = {
    "docs": "_docs",
    "blueprint": "_blueprint",
    "notes": "_note",
    "references": "_reference",
    "evidence": "_evidence",
    "metadata": "_meta",
    "cache": ".cache",
    "config": "config",
}
DETAIL_DIRS = {"adr", "plans", "rnd", "design", "blueprint", "roadmap"}
WINDOWS_DEVICES = {"con", "prn", "aux", "nul", "conin$", "conout$"} | {
    prefix + suffix for prefix in ("com", "lpt") for suffix in "123456789¹²³"
}


def safe(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError(
            "Layout paths must be nonempty repository-relative POSIX paths."
        )
    parts = relative.split("/")
    if any(
        p.casefold() in {"", ".", "..", ".git"}
        or p.endswith((".", " "))
        or any(c in p for c in ':*?<>|"')
        or any(ord(c) < 32 for c in p)
        or p.split(".", 1)[0].casefold() in WINDOWS_DEVICES
        for p in parts
    ):
        raise ValueError("Unsafe layout path: " + relative)
    target = root
    for part in parts:
        target /= part
        if target.is_symlink() or getattr(target, "is_junction", lambda: False)():
            raise ValueError("Layout path traverses a link: " + relative)
        if target.exists() and getattr(target.stat(), "st_file_attributes", 0) & 0x400:
            raise ValueError("Layout path traverses a reparse point: " + relative)
    return target


def default_policy() -> dict:
    return {
        "schema_version": 1,
        "roles": dict(ROLES),
        "docs_entrypoints": ["_docs/README.md"],
        "docs_max_files": 7,
        "exceptions": [],
    }


def load_policy(root: Path) -> dict | None:
    path = safe(root, POLICY)
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > 262144:
        raise ValueError("Invalid layout policy file.")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != set(default_policy()):
        raise ValueError("Layout policy fields are not exact.")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("Unsupported layout policy version.")
    if not isinstance(value["roles"], dict) or set(value["roles"]) != set(ROLES):
        raise ValueError("Declare all layout roles.")
    roots = list(value["roles"].values())
    for item in roots:
        safe(root, item)
    roots = [item.casefold() for item in roots]
    if any(
        a == b or a.startswith(b + "/") or b.startswith(a + "/")
        for i, a in enumerate(roots)
        for b in roots[i + 1 :]
    ):
        raise ValueError("Layout role roots must not overlap.")
    entries = value["docs_entrypoints"]
    if not isinstance(entries, list) or not entries or len(entries) > 100:
        raise ValueError("Declare a bounded, nonempty docs entrypoint list.")
    for entry in entries:
        safe(root, entry)
        if not entry.startswith(value["roles"]["docs"] + "/") or not entry.endswith(
            ".md"
        ):
            raise ValueError("Docs entrypoints must be Markdown inside the docs root.")
    if len(entries) != len({entry.casefold() for entry in entries}):
        raise ValueError("Duplicate docs entrypoint.")
    if (
        type(value["docs_max_files"]) is not int
        or not 1 <= value["docs_max_files"] <= 100
    ):
        raise ValueError("docs_max_files must be 1..100.")
    if not isinstance(value["exceptions"], list) or len(value["exceptions"]) > 100:
        raise ValueError("Invalid layout exceptions.")
    for exception in value["exceptions"]:
        if not isinstance(exception, dict) or set(exception) != {"path", "reason"}:
            raise ValueError("An exception requires an exact path and reason.")
        safe(root, exception["path"])
        if not isinstance(exception["reason"], str) or not exception["reason"].strip():
            raise ValueError("An exception requires a nonempty reason.")
    return value


def inspect(root: Path) -> dict:
    findings = []

    def add(severity, code, message):
        findings.append({"severity": severity, "code": code, "message": message})

    try:
        if not root.is_dir():
            raise ValueError("Repository root is not a directory.")
        for component in (root, *root.parents):
            if (
                component.is_symlink()
                or getattr(component, "is_junction", lambda: False)()
            ):
                raise ValueError("Root traverses a link.")
        policy = load_policy(root)
        configured = policy is not None
        policy = policy or default_policy()
        docs = policy["roles"]["docs"]
        doc_root = safe(root, docs)
        exceptions = [e["path"] for e in policy["exceptions"]]
        files = []
        if doc_root.exists():
            if not doc_root.is_dir():
                raise ValueError("Docs root is not a directory.")
            pending = [doc_root]
            visited = 0
            while pending:
                directory = pending.pop()
                for item in sorted(directory.iterdir()):
                    visited += 1
                    if visited > 20000:
                        raise ValueError("Layout inventory exceeds 20000 entries.")
                    relative = item.relative_to(root).as_posix()
                    safe(root, relative)
                    if any(
                        relative == e or relative.startswith(e + "/")
                        for e in exceptions
                    ):
                        continue
                    if item.is_dir():
                        pending.append(item)
                    elif item.is_file():
                        files.append(relative)
        if configured:
            for entry in policy["docs_entrypoints"]:
                if not safe(root, entry).is_file():
                    add("error", "docs_entrypoint_missing", entry)
            for entry in files:
                if entry.endswith(".md") and entry not in policy["docs_entrypoints"]:
                    add("warning", "docs_unlisted", entry)
        else:
            add(
                "warning",
                "layout_unconfigured",
                "Declare reviewed roles and entrypoints in " + POLICY,
            )
        if len([p for p in files if p.endswith(".md")]) > policy["docs_max_files"]:
            add(
                "warning",
                "docs_too_large",
                "Review newcomer reading set; move detail to "
                + policy["roles"]["blueprint"],
            )
        proposals = []
        for entry in files:
            tail = entry[len(docs) + 1 :]
            name = Path(entry).stem.lower()
            if set(tail.split("/")[:-1]) & DETAIL_DIRS or any(
                marker in name
                for marker in ("blueprint", "roadmap", "-design", "-plan", "adr-")
            ):
                destination = policy["roles"]["blueprint"] + "/" + tail
                add("warning", "blueprint_in_docs", entry + " -> " + destination)
                proposals.append(
                    {
                        "source": entry,
                        "destination": destination,
                        "basis": "path heuristic; content and consumers require review",
                    }
                )
        return {
            "ok": not any(f["severity"] == "error" for f in findings),
            "configured": configured,
            "findings": findings,
            "proposals": proposals,
            "files": sorted(files),
        }
    except (OSError, ValueError, TypeError) as exc:
        add("error", "layout_invalid", str(exc))
        return {"ok": False, "findings": findings, "proposals": [], "files": []}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "preview"])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = Path(os.path.abspath(args.root))
    for component in (root, *root.parents):
        if component.is_symlink() or getattr(component, "is_junction", lambda: False)():
            parser.error("Root traverses a link.")
    result = inspect(root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
