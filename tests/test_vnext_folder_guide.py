from __future__ import annotations

import hashlib
import importlib.util
import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPOSITORY = Path(__file__).resolve().parents[1]
GUIDE = ".agents/harness/repository-layout.md"
PRIOR_CONTRACT = "# Shared harness contract\n\n## Authority\n\nSource and deterministic tests outrank prose. Direction owns strategy; Work owns bounded execution;\nFailure records preserve prevention. Missing or remote activity is unknown.\n\n## Risk\n\n- R0: read-only; no rubric is required.\n- R1: bounded internal change; common rubric and self-check are required.\n- R2: public or multi-consumer impact; common plus profile rubric and independent review are required.\n- R3: release, external, destructive, or irreversible impact; fresh approval and independent review are required.\n\n## Verdicts\n\nUse only `PASS`, `NEEDS_REVISION`, or `INCONCLUSIVE`. A blocking criterion cannot be waived by a score.\nUse N/A only when its rubric condition is satisfied and record why.\n\n## Change safety\n\nPreserve unrelated dirty files. Never push, release, deploy, delete, or contact an external system\nwithout explicit authority. Validate exact changed paths and retain evidence. Read-only operations must\nnot change tracked files or the Git index.\n\n## Repository layout\n\nHarness/Eidos own declared control-plane paths only; they never create or rename product directories.\nUse `config/` for versioned configuration, profiles, scenarios, schemas and fixtures consumed by code,\ntests, packaging or deployment. Reserve `_meta/` for repository-only metadata, never runtime input.\n\nOptional `_docs/`, `_note/`, `_reference/`, `_evidence/` stay project-owned. Record deviations in a route.\nRenaming roots used by code, tests, docs, artifacts or deployment is R2: inventory consumers, preserve\nhistorical evidence, provide recovery and independent review. Kit installation never does it implicitly.\n\n## Identity\n\nNew Work uses an active canonical human `member:*` from project-owned identity. Historical Work keeps\nits IDs, resolved through explicit aliases. Claims separate member responsibility from `agent:*`\nexecution. Machine names, agents, aliases and unknown members cannot own new Work.\n\n## Failure knowledge\n\nSearch only failure entries selected by route tags. Promote reusable lessons with an enforcement link\nto a route, test, validator, or code boundary. Never store credentials, personal data, raw chat, raw\nlogs, or machine-specific absolute paths.\n"


class FolderGuideTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "project"
        self.root.mkdir()
        spec = importlib.util.spec_from_file_location(
            "folder_guide_manager", REPOSITORY / "kits/harness/v1/harness_kit.py"
        )
        self.module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.module
        spec.loader.exec_module(self.module)
        self.module.subprocess.run(
            ["git", "init", str(self.root)], check=True, capture_output=True
        )

    def install(self, enabled=True, layout="none"):
        self.module._command_install(
            self.module.argparse.Namespace(
                root=self.root,
                project_id="project:test",
                project_name="Test",
                without_eidos=not enabled,
                layout=layout,
            )
        )

    def prior_install(self, version="1.5.0"):
        self.install()
        manifest_path = self.root / self.module.MANIFEST_PATH
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        descriptor = self.module._release_descriptor(version)
        prior = json.loads(
            (
                REPOSITORY
                / "kits/harness/v1/evaluation/prior-requirements-surfaces.json"
            ).read_text(encoding="utf-8")
        )["files"]
        # These files changed with member-qualified Work IDs. Restore the exact
        # historical bytes rather than assuming today's reader/template are old.
        prior.update(
            json.loads(
                (
                    REPOSITORY
                    / "kits/harness/v1/evaluation/prior-work-id-surfaces.json"
                ).read_text(encoding="utf-8")
            )["files"]
        )
        if version == "1.5.0":
            prior[".agents/harness/contract.md"] = PRIOR_CONTRACT
        for relative, content in prior.items():
            if relative in descriptor["files"]:
                data = content.replace("\r\n", "\n").encode("utf-8")
                self.assertEqual(
                    hashlib.sha256(data).hexdigest(), descriptor["files"][relative]
                )
                (self.root / relative).write_bytes(data)
                manifest["files"][relative]["sha256"] = hashlib.sha256(data).hexdigest()
        removed = set(self.module.REQUIREMENTS_RELEASE_PATHS) | {
            ".agents/tools/layout.py"
        }
        if version == "1.5.0":
            removed.add(GUIDE)
        for relative in removed:
            (self.root / relative).unlink()
            del manifest["files"][relative]
        manifest["kit_version"] = version
        manifest_path.write_bytes(self.module._json_bytes(manifest))
        for relative, digest in descriptor["files"].items():
            self.assertEqual(
                hashlib.sha256((self.root / relative).read_bytes()).hexdigest(), digest
            )

    def test_upgrade_1_6_preserves_project_registry_and_adds_read_only_tool(self):
        self.prior_install("1.6.0")
        registry = self.root / "_meta/requirements/registry.json"
        registry.parent.mkdir(parents=True)
        registry.write_bytes(b'{"project_owned": true}\n')
        protected = {
            p: p.read_bytes()
            for p in (
                registry,
                self.root / "AGENTS.md",
                self.root / ".agents/context.json",
                self.root / ".agents/routing.md",
            )
        }
        self.upgrade()
        for path, data in protected.items():
            self.assertEqual(path.read_bytes(), data)
        for relative in self.module.REQUIREMENTS_RELEASE_PATHS:
            self.assertTrue((self.root / relative).is_file())
        self.assertIn(".cache/", (self.root / GUIDE).read_text())
        self.assertIn(".gitkeep", (self.root / GUIDE).read_text())

    def test_upgrade_1_6_refuses_unmanaged_requirements_tool_collision(self):
        self.prior_install("1.6.0")
        tool = self.root / ".agents/tools/requirements.py"
        tool.write_bytes(b"# existing project tool\n")
        before = self.snapshot()
        with self.assertRaises(self.module.HarnessKitError):
            self.upgrade()
        self.assertEqual(self.snapshot(), before)

    def snapshot(self):
        return {
            p.relative_to(self.root).as_posix(): (
                p.read_bytes(),
                stat.S_IMODE(p.stat().st_mode),
            )
            for p in self.root.rglob("*")
            if p.is_file() and ".git" not in p.parts
        }

    def upgrade(self):
        self.module._command_upgrade(self.module.argparse.Namespace(root=self.root))

    def test_fresh_install_with_and_without_eidos_scaffolds_support_files(self):
        for enabled in (True, False):
            with self.subTest(eidos=enabled):
                self.root = Path(self.temporary.name) / str(enabled)
                self.root.mkdir()
                self.module.subprocess.run(
                    ["git", "init", str(self.root)], check=True, capture_output=True
                )
                self.install(enabled, layout="auto")
                self.assertTrue((self.root / GUIDE).is_file())
                for folder in (
                    ".cache",
                    "_docs",
                    "_blueprint",
                    "_note",
                    "_reference",
                    "_evidence",
                    "_meta",
                ):
                    self.assertTrue((self.root / folder).is_dir(), folder)
                for folder in ("src", "web", "config", "_development_plan"):
                    self.assertFalse((self.root / folder).exists(), folder)

    def test_upgrade_1_5_preserves_project_conventions_and_material(self):
        self.prior_install()
        bootstrap = self.root / "AGENTS.md"
        bootstrap.write_bytes(
            bootstrap.read_bytes() + b"\nProject-specific folder convention.\n"
        )
        note = self.root / "_note/existing.md"
        note.parent.mkdir()
        note.write_bytes(b"Keep existing project material.\n")
        protected = {p: p.read_bytes() for p in (bootstrap, note)}
        self.upgrade()
        self.assertTrue((self.root / GUIDE).is_file())
        self.assertEqual(
            json.loads((self.root / self.module.MANIFEST_PATH).read_text())[
                "kit_version"
            ],
            self.module.KIT_VERSION,
        )
        for p, content in protected.items():
            self.assertEqual(p.read_bytes(), content)
        snapshot = self.snapshot()
        self.upgrade()
        self.assertEqual(self.snapshot(), snapshot)

    def test_unmanaged_guide_collision_preserves_whole_tree(self):
        self.prior_install()
        (self.root / GUIDE).write_bytes(b"Project-owned guide.\n")
        before = self.snapshot()
        with self.assertRaises(self.module.HarnessKitError) as raised:
            self.upgrade()
        self.assertEqual(raised.exception.code, "target_exists")
        self.assertEqual(self.snapshot(), before)

    def test_concurrent_guide_collision_before_snapshot_is_preserved(self):
        self.prior_install()
        before = self.snapshot()
        original = self.module._atomic_write_set

        def collide(root, writes, **kwargs):
            (root / GUIDE).write_bytes(b"Concurrent guide.\n")
            return original(root, writes, **kwargs)

        with mock.patch.object(self.module, "_atomic_write_set", side_effect=collide):
            with self.assertRaises(self.module.HarnessKitError):
                self.upgrade()
        after = self.snapshot()
        self.assertEqual(after.pop(GUIDE)[0], b"Concurrent guide.\n")
        self.assertEqual(after, before)

    def test_concurrent_guide_collision_during_publication_rolls_back(self):
        self.prior_install()
        before = self.snapshot()
        original = self.module._write_exclusive

        def collide(path, data, on_created=None):
            if path == self.root / GUIDE:
                path.write_bytes(b"Concurrent guide.\n")
            return original(path, data, on_created)

        with mock.patch.object(self.module, "_write_exclusive", side_effect=collide):
            with self.assertRaises(self.module.HarnessKitError):
                self.upgrade()
        after = self.snapshot()
        self.assertEqual(after.pop(GUIDE)[0], b"Concurrent guide.\n")
        self.assertEqual(after, before)

    def test_collision_between_absence_check_and_snapshot_stays_exclusive(self):
        self.prior_install()
        before = self.snapshot()
        original_atomic = self.module._atomic_write_set
        original_exists = Path.exists
        probes = 0

        def exists(path):
            nonlocal probes
            if path == self.root / GUIDE:
                probes += 1
                if probes == 2:
                    path.write_bytes(b"Concurrent guide.\n")
                    return False
            return original_exists(path)

        def collide(root, writes, **kwargs):
            with mock.patch.object(Path, "exists", exists):
                return original_atomic(root, writes, **kwargs)

        with mock.patch.object(self.module, "_atomic_write_set", side_effect=collide):
            with self.assertRaises(self.module.HarnessKitError):
                self.upgrade()
        after = self.snapshot()
        self.assertEqual(after.pop(GUIDE)[0], b"Concurrent guide.\n")
        self.assertEqual(after, before)
