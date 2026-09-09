"""Read-only portable requirement selection and preservation checks.

This checks traceability, not semantic correctness. It never executes references,
resolves external repository locations, runs tests, or writes a catalog/index.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

REGISTRY = "_meta/requirements/registry.json"
CLASSIFICATIONS = {"common", "project-only", "retired", "gap", "unknown"}
LABELS = {
    "common": "공통 반영됨",
    "project-only": "프로젝트 전용",
    "retired": "의도적 폐기",
    "gap": "누락",
    "unknown": "미확인",
}
MAX_BYTES = 4 * 1024 * 1024


class RequirementError(ValueError):
    pass


def relative(value: str) -> str:
    if not isinstance(value, str):
        raise RequirementError("A repository-relative path is required.")
    value = value.replace("\\", "/").rstrip("/")
    parts = value.split("/")
    if (
        not value
        or value.startswith("/")
        or ":" in value
        or any(c in value for c in "\x00\r\n*?[")
        or any(p in {"", ".", ".."} or p.endswith((".", " ")) for p in parts)
        or parts[0].casefold() == ".git"
    ):
        raise RequirementError("Invalid repository-relative path.")
    return value


def overlaps(left: str, right: str) -> bool:
    left, right = left.casefold(), right.casefold()
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RequirementError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def decode(data: bytes) -> dict:
    if len(data) > MAX_BYTES:
        raise RequirementError("Metadata exceeds size limit.")
    value = json.loads(data, object_pairs_hook=no_duplicates)
    if not isinstance(value, dict):
        raise RequirementError("Metadata must be an object.")
    return value


class Reader:
    def __init__(self, root: Path):
        self.root = root.absolute()
        self.cache: dict[str, bytes] = {}
        self.hash_files = 0
        self.hash_bytes = 0
        self._guard(self.root)

    @staticmethod
    def _guard(path: Path) -> None:
        for parent in (path, *path.parents):
            try:
                info = parent.lstat()
            except FileNotFoundError:
                continue
            if (
                stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 0x400
            ):
                raise RequirementError("Reparse/symlink paths are not read.")

    def read(self, path: str) -> bytes:
        path = relative(path)
        target = self.root / path
        self._guard(target)
        if path not in self.cache:
            if not target.is_file() or target.stat().st_size > MAX_BYTES:
                raise RequirementError(
                    f"Missing, nonregular or oversized reference: {path}"
                )
            with target.open("rb") as handle:
                data = handle.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise RequirementError(f"Oversized reference: {path}")
            self.cache[path] = data
        return self.cache[path]

    def text(self, path: str) -> str:
        return self.read(path).decode("utf-8")

    def metrics(self) -> dict:
        return {
            "files_read": len(self.cache),
            "bytes_read": sum(map(len, self.cache.values())),
            "baseline_files_hashed": self.hash_files,
            "baseline_bytes_hashed": self.hash_bytes,
        }


def git(root: Path, *args: str) -> bytes:
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_LITERAL_PATHSPECS="1")
    # Suppress optional index refresh and external diff/text conversion helpers.
    command = [
        "git",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.untrackedCache=false",
        "-c",
        "core.quotePath=false",
        "-C",
        str(root),
        *args,
    ]
    result = subprocess.run(command, env=env, capture_output=True, check=False)
    if result.returncode:
        raise RequirementError(f"Git read failed: {args[0]}")
    return result.stdout


def revision(root: Path, value: str) -> str:
    if not value or value.startswith("-") or any(c in value for c in "\x00\r\n"):
        raise RequirementError("Invalid base revision.")
    return (
        git(root, "rev-parse", "--verify", "--end-of-options", value + "^{commit}")
        .decode()
        .strip()
    )


def base_registry(root: Path, base: str) -> dict | None:
    entry = git(root, "ls-tree", "-z", base, "--", REGISTRY)
    if not entry:
        return None
    return decode(git(root, "cat-file", "blob", f"{base}:{REGISTRY}"))


def file_paths(root: Path) -> set[str]:
    return {
        relative(p)
        for p in git(root, "ls-files", "-co", "--exclude-standard", "-z")
        .decode()
        .split("\0")
        if p
    }


def changes(
    reader: Reader, base: str, baseline: str | None
) -> tuple[list[str], dict | None]:
    old = base_registry(reader.root, base)
    if baseline:
        snapshot = decode(reader.read(baseline))
        if snapshot.get("head") != base or not isinstance(snapshot.get("files"), dict):
            raise RequirementError(
                "Baseline must bind the selected base and pre-work file hashes."
            )
        previous = snapshot["files"]
        if len(previous) > 10000:
            raise RequirementError("Baseline has too many paths.")
        for path, digest in previous.items():
            relative(path)
            if not isinstance(digest, str) or not re.fullmatch("[a-f0-9]{64}", digest):
                raise RequirementError("Invalid baseline digest.")
        observed = None
        if REGISTRY in previous:
            raw = snapshot.get("registry_text")
            if (
                not isinstance(raw, str)
                or hashlib.sha256(raw.encode()).hexdigest() != previous[REGISTRY]
            ):
                raise RequirementError(
                    "Baseline must retain exact prior registry_text."
                )
            observed = decode(raw.encode())
            # Both committed and reviewed dirty baselines are checked by the caller.
        current = file_paths(reader.root)
        affected = []
        for path in sorted(current | set(previous)):
            target = reader.root / path
            Reader._guard(target)
            if not target.exists():
                digest = None
            elif not target.is_file():
                raise RequirementError(f"Nonregular baseline path: {path}")
            else:
                # Source files can exceed the metadata limit; hash without loading their bodies.
                with target.open("rb") as handle:
                    digest = hashlib.file_digest(handle, "sha256").hexdigest()
                    reader.hash_files += 1
                    reader.hash_bytes += handle.tell()
            if digest != previous.get(path):
                affected.append(path)
        return affected, observed
    changed = git(
        reader.root,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--name-only",
        "-z",
        base,
        "--",
    )
    untracked = git(reader.root, "ls-files", "--others", "--exclude-standard", "-z")
    return sorted(
        {relative(p) for p in (changed + untracked).decode().split("\0") if p}
    ), old


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RequirementError(message)


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_registry(registry: dict) -> None:
    require(
        type(registry.get("schema_version")) is int and registry["schema_version"] == 1,
        "Unsupported registry version.",
    )
    audit = registry.get("audit", {})
    require(isinstance(audit, dict), "Invalid audit.")
    require(
        isinstance(audit.get("repositories"), list)
        and bool(audit["repositories"])
        and all(nonempty(r) for r in audit["repositories"]),
        "Invalid audit repositories.",
    )
    require(
        isinstance(audit.get("categories"), list)
        and bool(audit["categories"])
        and all(nonempty(c) for c in audit["categories"])
        and len(set(audit["categories"])) == len(audit["categories"]),
        "Declare unique, nonempty audit categories.",
    )
    require(
        nonempty(audit.get("local_repository"))
        and audit["local_repository"] in audit["repositories"],
        "Declare local_repository as one audited repository.",
    )
    declared_categories = set(audit["categories"])
    observations = registry.get("observations")
    rules = registry.get("rules")
    require(
        isinstance(observations, dict) and 0 < len(observations) <= 256,
        "Invalid observations.",
    )
    require(isinstance(rules, list) and 0 < len(rules) <= 256, "Invalid rules.")
    for key, obs in observations.items():
        require(nonempty(key) and isinstance(obs, dict), "Invalid observation.")
        require(
            obs.get("repository") in audit.get("repositories", []),
            "Unknown repository key.",
        )
        relative(obs.get("path"))
        require(
            isinstance(obs.get("sha256"), str)
            and bool(re.fullmatch("[a-f0-9]{64}", obs["sha256"])),
            "Missing observed digest.",
        )
        require(
            obs.get("observation") in {"committed", "working-tree", "unborn"},
            "Unknown observation kind.",
        )
        rev = obs.get("revision")
        require(
            (rev is None and obs["observation"] == "unborn")
            or (isinstance(rev, str) and bool(re.fullmatch("[a-f0-9]{40,64}", rev))),
            "Invalid observed revision.",
        )

    def refs(values):
        require(
            isinstance(values, list) and bool(values),
            "At least one source is required.",
        )
        for ref in values:
            require(
                isinstance(ref, dict)
                and ref.get("observation") in observations
                and nonempty(ref.get("locator")),
                "Broken source reference.",
            )

    ids = set()
    categories = set()
    for rule in rules:
        require(isinstance(rule, dict), "Invalid rule.")
        rid = rule.get("id")
        require(
            isinstance(rid, str)
            and bool(re.fullmatch("REQ-[A-Z0-9-]+", rid))
            and rid not in ids,
            "Duplicate or invalid rule ID.",
        )
        ids.add(rid)
        require(rule.get("category") in declared_categories, "Invalid category.")
        categories.add(rule["category"])
        require(nonempty(rule.get("summary")), "Missing requirement summary.")
        require(
            rule.get("classification") in CLASSIFICATIONS, "Invalid classification."
        )
        require(
            type(rule.get("common")) is bool,
            "common must be an always-selected boolean.",
        )
        for field in ("paths", "domains", "surfaces"):
            require(isinstance(rule.get(field), list), f"Missing {field}.")
        for path in rule["paths"]:
            relative(path)
        require(all(nonempty(d) for d in rule["domains"]), "Invalid domain.")
        refs(rule.get("sources"))
        require(isinstance(rule.get("notes"), str), "Missing notes.")
        for surface in rule["surfaces"]:
            require(isinstance(surface, dict), "Invalid surface.")
            relative(surface.get("path"))
            require(
                nonempty(surface.get("contains")),
                "Surface needs an exact reference marker.",
            )
            require(
                surface.get("role")
                in {"guidance", "documentation", "implementation", "verification"},
                "Invalid surface role.",
            )
            require(
                surface.get("gap") is None or nonempty(surface.get("gap")),
                "Invalid gap note.",
            )
        decision = rule.get("decision")
        if decision is not None:
            require(
                isinstance(decision, dict) and nonempty(decision.get("reason")),
                "Decision needs a reason.",
            )
            refs(decision.get("sources"))
            require(
                isinstance(decision.get("replacement"), list),
                "Decision needs replacement IDs (empty for an amendment).",
            )
        if rule["classification"] == "retired":
            require(
                decision is not None and bool(decision.get("replacement")),
                "Retirement needs reason, sources and replacement.",
            )
    require(
        categories == declared_categories, "Audit category has no classified rules."
    )
    for rule in rules:
        if rule.get("decision"):
            require(
                all(
                    r in ids and r != rule["id"]
                    for r in rule["decision"]["replacement"]
                ),
                "Broken replacement rule.",
            )


def known_routes(reader: Reader) -> set[str]:
    files = [".agents/routing.md"]
    folder = reader.root / ".agents/routes"
    Reader._guard(folder)
    files.extend(
        p.relative_to(reader.root).as_posix() for p in sorted(folder.glob("*.md"))
    )
    names = set()
    for path in files:
        for line in reader.text(path).splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if (
                line.startswith("|")
                and len(cells) == 5
                and cells[2] in {"R0", "R1", "R2", "R3"}
            ):
                names.add(cells[0])
    return names


def relevant(rule: dict, paths: list[str], domains: list[str]) -> bool:
    return (
        rule["common"]
        or bool(set(domains) & set(rule["domains"]))
        or any(
            overlaps(path, bound)
            for path in paths
            for bound in [*rule["paths"], *(s["path"] for s in rule["surfaces"])]
        )
    )


def compare_rules(current: dict, old: dict | None) -> list[dict]:
    if old is None:
        return []
    validate_registry(old)
    findings = []
    if current["audit"]["local_repository"] != old["audit"]["local_repository"]:
        findings.append({"level": "error", "code": "local_repository_changed"})
    if not set(old["audit"]["categories"]).issubset(current["audit"]["categories"]):
        findings.append({"level": "error", "code": "audit_category_removed"})
    current_rules = {r["id"]: r for r in current["rules"]}
    for prior in old["rules"]:
        rid = prior["id"]
        new = current_rules.get(rid)
        if new is None:
            findings.append({"level": "error", "code": "rule_deleted", "rule": rid})
            continue
        fields = (
            "category",
            "summary",
            "classification",
            "common",
            "domains",
            "paths",
            "sources",
            "surfaces",
        )
        old_observations = {
            ref["observation"]: old["observations"][ref["observation"]]
            for ref in prior["sources"]
        }
        changed = any(prior.get(f) != new.get(f) for f in fields) or any(
            current["observations"].get(k) != value
            for k, value in old_observations.items()
        )
        if changed:
            decision = new.get("decision")
            explained = decision is not None and decision != prior.get("decision")
            findings.append(
                {
                    "level": "review" if explained else "error",
                    "code": "rule_amended" if explained else "unexplained_rule_change",
                    "rule": rid,
                }
            )
    return findings


def check_references(reader: Reader, registry: dict, paths: list[str]) -> list[dict]:
    findings = []
    for rule in registry["rules"]:
        rid = rule["id"]
        refs = rule["sources"] + (rule.get("decision") or {}).get("sources", [])
        for ref in refs:
            obs = registry["observations"][ref["observation"]]
            if obs["repository"] != registry["audit"]["local_repository"]:
                continue  # Provenance only. Never resolve or execute provider content.
            try:
                if ref["locator"] not in reader.text(obs["path"]):
                    raise RequirementError("Source locator no longer resolves.")
            except (OSError, UnicodeError, RequirementError):
                findings.append(
                    {
                        "level": "error",
                        "code": "source_missing",
                        "rule": rid,
                        "path": obs["path"],
                    }
                )
        for surface in rule["surfaces"]:
            try:
                present = surface["contains"] in reader.text(surface["path"])
            except (OSError, UnicodeError, RequirementError):
                present = False
            if not present:
                affected = any(overlaps(surface["path"], path) for path in paths)
                findings.append(
                    {
                        "level": "warning"
                        if surface["gap"] and not affected
                        else "error",
                        "code": "known_gap" if surface["gap"] else "surface_missing",
                        "rule": rid,
                        "path": surface["path"],
                        "detail": surface["gap"]
                        or "Required reference marker is missing.",
                    }
                )
    return findings


def evaluate(
    root: Path,
    command: str,
    *,
    route: str = "change",
    paths: list[str] | None = None,
    domains: list[str] | None = None,
    base: str = "HEAD",
    baseline: str | None = None,
) -> dict:
    reader = Reader(root)
    if not (reader.root / REGISTRY).exists():
        raise RequirementError(
            "Requirements are not configured. Review .agents/harness/requirements.md "
            "and create a project-owned registry; no file has been created."
        )
    registry = decode(reader.read(REGISTRY))
    validate_registry(registry)
    require(route in known_routes(reader), "Unknown route; select one existing route.")
    paths = sorted({relative(p) for p in paths or []})
    domains = domains or []
    require(
        set(domains).issubset({d for r in registry["rules"] for d in r["domains"]}),
        "Unknown domain; use a declared domain or select by path.",
    )
    findings: list[dict] = []
    old = None
    observed_old = None
    base_sha = None
    if command == "check":
        actual_root = Path(
            git(reader.root, "rev-parse", "--show-toplevel").decode().strip()
        )
        require(
            actual_root.resolve() == reader.root.resolve(),
            "Use the Git top-level directory.",
        )
        base_sha = revision(reader.root, base)
        old = base_registry(reader.root, base_sha)
        actual, observed_old = changes(reader, base_sha, baseline)
        paths = sorted(
            set(paths) | set(actual)
        )  # Explicit paths add obligations, never hide actual changes.
        findings += compare_rules(registry, old)
        if observed_old is not None and observed_old != old:
            findings += compare_rules(registry, observed_old)
        findings += check_references(reader, registry, paths)
        require(
            revision(reader.root, base) == base_sha, "Base changed during check; retry."
        )
    old_rules = [
        r for previous in (old, observed_old) for r in (previous or {}).get("rules", [])
    ]
    selected = [
        r
        for r in registry["rules"]
        if relevant(r, paths, domains)
        or any(
            prior["id"] == r["id"] and relevant(prior, paths, domains)
            for prior in old_rules
        )
    ]
    unmatched = [
        p
        for p in paths
        if not any(
            overlaps(p, bound)
            for r in registry["rules"]
            for bound in [*r["paths"], *(s["path"] for s in r["surfaces"])]
        )
    ]
    for path in unmatched:
        findings.append({"level": "warning", "code": "unclassified_path", "path": path})
    selected_obs = {ref["observation"] for r in selected for ref in r["sources"]}
    all_gaps = [
        {"rule": r["id"], **s}
        for r in registry["rules"]
        for s in r["surfaces"]
        if s["gap"] and (command == "check" or r in selected)
    ]
    data = {
        "route": route,
        "paths": paths,
        "base": base_sha,
        "baseline": baseline,
        "bootstrap": command == "check" and old is None,
        "rules": selected if command == "select" else registry["rules"],
        "selected_ids": [r["id"] for r in selected],
        "observations": {
            key: registry["observations"][key] for key in sorted(selected_obs)
        }
        if command == "select"
        else registry["observations"],
        "known_gaps": all_gaps,
        "findings": findings,
        "counts": {
            key: sum(r["classification"] == key for r in registry["rules"])
            for key in sorted(CLASSIFICATIONS)
        },
        "measurement": reader.metrics(),
        "semantic_review": "Reference checks do not prove behavior. Review selected requirements against source changes and actual test evidence.",
    }
    return {
        "schema_version": 1,
        "command": command,
        "ok": not any(f["level"] == "error" for f in findings),
        "data": data,
        "error": None,
    }


def render(result: dict) -> str:
    if result.get("error"):
        return "FAIL: " + result["error"]
    data = result["data"]
    lines = [
        f"Requirements {result['command']}: {'PASS' if result['ok'] else 'NEEDS_REVISION'} (structural checks only)",
        f"Route: {data['route']}; selected: {len(data['selected_ids'])}; bootstrap: {data['bootstrap']}",
    ]
    for rule in data["rules"]:
        lines.append(
            f"{rule['id']} [{LABELS[rule['classification']]}] {rule['summary']}"
        )
        for ref in rule["sources"]:
            obs = data["observations"].get(ref["observation"])
            if obs:
                lines.append(f"  {obs['repository']}:{obs['path']} — {ref['locator']}")
        if rule["notes"]:
            lines.append("  " + rule["notes"])
    for finding in data["findings"]:
        lines.append(
            f"{finding['level'].upper()} {finding['code']}: {finding.get('rule', '')} {finding.get('path', '')}"
        )
    for gap in data["known_gaps"]:
        lines.append(f"GAP {gap['rule']}: {gap['path']} — {gap['gap']}")
    lines.extend([str(data["measurement"]), data["semantic_review"]])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["select", "check"])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--route", default="change")
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--domain", action="append", default=[])
    parser.add_argument("--base", default="HEAD")
    parser.add_argument(
        "--baseline",
        help="Reviewed pre-work snapshot path inside this repository; hashes and optional exact registry_text.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = evaluate(
            args.root,
            args.command,
            route=args.route,
            paths=args.path,
            domains=args.domain,
            base=args.base,
            baseline=args.baseline,
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        result = {
            "schema_version": 1,
            "command": args.command,
            "ok": False,
            "data": None,
            "error": str(exc),
        }
    print(
        json.dumps(result, ensure_ascii=False, sort_keys=True)
        if args.json
        else render(result)
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
