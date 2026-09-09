from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "kits/harness/v1/template/.agents/tools/requirements.py"
spec = importlib.util.spec_from_file_location("portable_requirements", TOOL)
req = importlib.util.module_from_spec(spec)
spec.loader.exec_module(req)
CATEGORIES = {"build", "cache", "delivery", "history", "privacy", "quality", "source"}


class RequirementsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        self.git("init")
        self.git("config", "user.name", "Requirement Test")
        self.git("config", "user.email", "test@example.invalid")
        self.write(".gitignore", ".eido-runtime/\n")
        self.write(
            ".agents/routing.md",
            "| read-only | Read | R0 | none | all |\n| change | Change | R1 | common-change | all |\n| release-or-external | Publish | R3 | common-change, release-or-external | kit |\n",
        )
        self.write("evidence.md", "# Observed rule\n")
        self.write("guide.md", "# Missing cache explanation\n")
        self.write("tests/check.py", "def validates_cache(): pass\n")
        observation = {
            "repository": "SampleProject",
            "path": "evidence.md",
            "revision": "a" * 40,
            "observation": "working-tree",
            "sha256": hashlib.sha256(b"# Observed rule\n").hexdigest(),
        }
        self.registry = {
            "schema_version": 1,
            "audit": {
                "categories": sorted(CATEGORIES),
                "local_repository": "SampleProject",
                "repositories": ["SampleProject", "foreign"],
                "date": "2026-09-09",
                "limits": "fixture",
            },
            "observations": {"source": observation},
            "rules": [],
        }
        for i, category in enumerate(sorted(CATEGORIES)):
            rule = {
                "id": f"REQ-{i}",
                "category": category,
                "summary": category,
                "classification": "common",
                "common": i == 0,
                "domains": [],
                "paths": [f"component{i}"],
                "sources": [{"observation": "source", "locator": "# Observed rule"}],
                "surfaces": [],
                "notes": "",
                "decision": None,
            }
            self.registry["rules"].append(rule)
        cache = self.registry["rules"][2]
        cache.update(
            id="REQ-CACHE",
            classification="gap",
            paths=["kits", "guide.md"],
            domains=["kit"],
            surfaces=[
                {
                    "path": "guide.md",
                    "contains": ".cache/",
                    "role": "documentation",
                    "gap": "Known missing explanation",
                },
                {
                    "path": "tests/check.py",
                    "contains": "def validates_cache",
                    "role": "verification",
                    "gap": None,
                },
            ],
        )
        self.save()
        self.commit()

    def git(self, *args):
        result = subprocess.run(
            ["git", "-C", str(self.root), *args], capture_output=True, check=True
        )
        return result.stdout.decode().strip()

    def write(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")

    def save(self):
        self.write(req.REGISTRY, json.dumps(self.registry, indent=2) + "\n")

    def commit(self):
        self.git("add", "--all")
        self.git("commit", "-m", "fixture")

    def check(self, **kwargs):
        return req.evaluate(self.root, "check", **kwargs)

    def codes(self, result, level="error"):
        return {f["code"] for f in result["data"]["findings"] if f["level"] == level}

    def snapshot(self):
        return {
            p.relative_to(self.root).as_posix(): p.read_bytes()
            for p in self.root.rglob("*")
            if p.is_file()
        }

    def baseline(self):
        files = {
            p: hashlib.sha256((self.root / p).read_bytes()).hexdigest()
            for p in req.file_paths(self.root)
            if (self.root / p).is_file()
        }
        value = {
            "head": self.git("rev-parse", "HEAD"),
            "files": files,
            "registry_text": (self.root / req.REGISTRY).read_text(encoding="utf-8")
            if (self.root / req.REGISTRY).is_file()
            else None,
        }
        self.write(".eido-runtime/before.json", json.dumps(value))
        return ".eido-runtime/before.json"

    def test_omitted_cache_surface_blocks_only_affected_change(self):
        self.assertTrue(self.check()["ok"])
        self.write("application.py", "pass\n")
        self.assertTrue(self.check()["ok"])
        self.write("guide.md", "# Changed guide still omits cache\n")
        self.assertIn("known_gap", self.codes(self.check()))
        self.write("guide.md", "# Cache\n.cache/tool stores temporary output\n")
        self.assertTrue(self.check()["ok"])

    def test_release_route_keeps_kit_rules(self):
        result = req.evaluate(
            self.root, "select", route="release-or-external", paths=["kits/harness"]
        )
        self.assertIn("REQ-CACHE", result["data"]["selected_ids"])
        self.assertIn("REQ-0", result["data"]["selected_ids"])

    def test_unknown_paths_keep_common_and_warn(self):
        result = req.evaluate(self.root, "select", paths=["new-area/file.txt"])
        self.assertIn("REQ-0", result["data"]["selected_ids"])
        self.assertIn("unclassified_path", self.codes(result, "warning"))

    def test_removed_rule_and_detached_bindings_fail(self):
        original = copy.deepcopy(self.registry)
        self.registry["rules"].pop(2)
        self.save()
        # Category validation catches this minimal fixture's category loss too.
        with self.assertRaises(req.RequirementError):
            self.check()
        self.registry = original
        self.registry["rules"][2]["paths"] = []
        self.registry["rules"][2]["surfaces"] = []
        self.save()
        result = self.check(paths=["kits/harness"])
        self.assertIn("unexplained_rule_change", self.codes(result))
        self.assertIn("REQ-CACHE", result["data"]["selected_ids"])

    def test_rule_deletion_is_detected_when_category_still_represented(self):
        duplicate_category = copy.deepcopy(self.registry["rules"][2])
        duplicate_category["id"] = "REQ-EXTRA"
        self.registry["rules"].append(duplicate_category)
        self.save()
        self.commit()
        self.registry["rules"].pop(2)
        self.save()
        self.assertIn("rule_deleted", self.codes(self.check()))

    def test_retirement_retains_rule_and_requires_review(self):
        rule = self.registry["rules"][2]
        rule["classification"] = "retired"
        rule["decision"] = {
            "reason": "Replaced explicitly",
            "replacement": ["REQ-0"],
            "sources": rule["sources"],
        }
        self.save()
        result = self.check()
        self.assertTrue(result["ok"])
        self.assertIn("rule_amended", self.codes(result, "review"))
        self.commit()
        rule["paths"] = []
        self.save()
        self.assertIn("unexplained_rule_change", self.codes(self.check()))

    def test_broken_source_and_verification_fail_even_outside_changed_scope(self):
        (self.root / "evidence.md").unlink()
        self.assertIn("source_missing", self.codes(self.check()))
        self.write("evidence.md", "# Observed rule\n")
        self.write("tests/check.py", "# verifier removed\n")
        self.assertIn("surface_missing", self.codes(self.check()))

    def test_duplicate_id_and_observation_rebinding_fail(self):
        self.registry["rules"].append(copy.deepcopy(self.registry["rules"][0]))
        self.save()
        with self.assertRaises(req.RequirementError):
            self.check()
        self.registry["rules"].pop()
        self.registry["observations"]["source"]["sha256"] = "b" * 64
        self.save()
        self.assertIn("unexplained_rule_change", self.codes(self.check()))

    def test_read_only_including_git_index_and_external_no_execution(self):
        self.registry["observations"]["foreign"] = {
            "repository": "foreign",
            "path": "danger.py",
            "revision": None,
            "observation": "unborn",
            "sha256": "c" * 64,
        }
        self.registry["rules"][0]["sources"].append(
            {"observation": "foreign", "locator": "raise Exception"}
        )
        self.save()
        self.commit()
        sibling = self.root.parent / "foreign"
        sibling.mkdir()
        (sibling / "danger.py").write_text("raise Exception('must never execute')")
        before = self.snapshot()
        index = self.root / ".git/index"
        index_before = (index.stat().st_mtime_ns, index.stat().st_size)
        original_read = req.Reader.read

        def guard(reader, path):
            self.assertNotIn("danger.py", path)
            return original_read(reader, path)

        with mock.patch.object(req.Reader, "read", guard):
            selected = req.evaluate(self.root, "select", paths=["kits"])
            self.assertTrue(selected["ok"])
            self.assertTrue(self.check()["ok"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual((index.stat().st_mtime_ns, index.stat().st_size), index_before)

    def test_reviewed_dirty_baseline_keeps_old_selection_bindings(self):
        self.git("rm", "--", req.REGISTRY)
        self.git("commit", "-m", "before registry")
        self.save()
        baseline = self.baseline()
        rule = self.registry["rules"][2]
        rule.update(paths=[], surfaces=[], domains=[])
        rule["decision"] = {
            "reason": "Explicitly relocate this rule",
            "replacement": [],
            "sources": rule["sources"],
        }
        self.save()
        index = self.root / ".git/index"
        before = (index.read_bytes(), index.stat().st_mtime_ns, index.stat().st_size)
        result = self.check(baseline=baseline, paths=["kits/harness"])
        self.assertTrue(result["ok"])
        self.assertIn("REQ-CACHE", result["data"]["selected_ids"])
        self.assertIn("rule_amended", self.codes(result, "review"))
        self.assertEqual(
            (index.read_bytes(), index.stat().st_mtime_ns, index.stat().st_size), before
        )

    def test_unverified_snapshot_registry_field_is_not_used(self):
        self.git("rm", "--", req.REGISTRY)
        self.git("commit", "-m", "before registry")
        baseline = self.baseline()
        value = json.loads((self.root / baseline).read_text())
        value["registry"] = {"invalid": "not a verified registry snapshot"}
        self.write(baseline, json.dumps(value))
        self.save()
        result = self.check(baseline=baseline)
        self.assertTrue(result["ok"])

    def test_selection_omits_unrelated_gaps_and_rejects_unknown_domain(self):
        selected = req.evaluate(self.root, "select", paths=["component0"])
        self.assertEqual(selected["data"]["known_gaps"], [])
        with self.assertRaises(req.RequirementError):
            req.evaluate(self.root, "select", domains=["not-declared"])

    def test_select_does_not_read_reference_bodies(self):
        result = req.evaluate(self.root, "select", paths=["kits"])
        self.assertEqual(result["data"]["measurement"]["files_read"], 2)

    def test_preexisting_dirty_baseline_does_not_hide_later_change(self):
        self.write("guide.md", "# Prior unrelated draft\n")
        baseline = self.baseline()
        self.assertTrue(self.check(baseline=baseline)["ok"])
        self.write("guide.md", "# New edit\n")
        self.assertFalse(self.check(baseline=baseline)["ok"])

    def test_dirty_registry_cannot_override_committed_guard(self):
        self.registry["rules"][2]["surfaces"] = []
        self.save()
        baseline = self.baseline()
        self.assertIn(
            "unexplained_rule_change", self.codes(self.check(baseline=baseline))
        )

    def test_baseline_requires_exact_prior_registry_and_base(self):
        baseline = self.baseline()
        value = json.loads((self.root / baseline).read_text())
        value.pop("registry_text")
        self.write(baseline, json.dumps(value))
        with self.assertRaises(req.RequirementError):
            self.check(baseline=baseline)
        value["head"] = "f" * 40
        self.write(baseline, json.dumps(value))
        with self.assertRaises(req.RequirementError):
            self.check(baseline=baseline)

    def test_explicit_paths_cannot_filter_actual_changes(self):
        self.write("guide.md", "# Changed\n")
        self.assertFalse(self.check(paths=["application.py"])["ok"])

    def test_malformed_json_and_path_traversal_fail_with_json(self):
        self.write(req.REGISTRY, '{"schema_version": 1, "schema_version": 2}')
        env = dict(
            os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1"
        )
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(TOOL),
                "check",
                "--root",
                str(self.root),
                "--json",
            ],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)["ok"])
        for value in ("../foreign", "C:/foreign", ".git/index", "kit/*", "./src"):
            with self.subTest(value=value), self.assertRaises(req.RequirementError):
                req.relative(value)

    def test_reference_symlink_is_rejected(self):
        target = self.root.parent / "outside"
        target.write_text("# Observed rule\n")
        (self.root / "evidence.md").unlink()
        try:
            (self.root / "evidence.md").symlink_to(target)
        except OSError:
            self.skipTest("Symlink creation unavailable")
        self.assertIn("source_missing", self.codes(self.check()))

    def test_bootstrap_registry_reports_initial_adoption(self):
        base = self.git("rev-parse", "HEAD")
        self.git("rm", "--", req.REGISTRY)
        self.git("commit", "-m", "before registry")
        self.save()
        result = self.check()
        self.assertTrue(result["ok"])
        self.assertTrue(result["data"]["bootstrap"])
        self.assertNotEqual(result["data"]["base"], base)

    def test_example_and_arbitrary_project_categories(self):
        example = req.decode(
            (
                ROOT
                / "kits/harness/v1/template/.agents/harness/requirements.example.json"
            ).read_bytes()
        )
        req.validate_registry(example)
        self.assertEqual(example["audit"]["local_repository"], "local")
        self.assertNotIn("EidosWeb", json.dumps(example))
        self.assertTrue(self.check()["ok"])
        self.registry["audit"]["local_repository"] = "foreign"
        self.save()
        self.assertIn("local_repository_changed", self.codes(self.check()))

    def test_missing_registry_is_read_only_unconfigured(self):
        (self.root / req.REGISTRY).unlink()
        before = self.snapshot()
        with self.assertRaisesRegex(req.RequirementError, "not configured"):
            req.evaluate(self.root, "select")
        self.assertEqual(self.snapshot(), before)
