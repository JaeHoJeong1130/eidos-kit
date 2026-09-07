from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPOSITORY = Path(__file__).resolve().parents[1]
MANAGER = REPOSITORY / "kits/harness/v1/harness_kit.py"

# Immutable historical fixture: old release digests must not be derived from new prose.
HISTORICAL_CONTRACT = """# Shared harness contract

## Authority

Current source and deterministic tests outrank prose. Eidos Direction owns stable strategy; Work owns
bounded execution; failure records preserve reusable prevention. Missing or remote activity is unknown.

## Risk

- R0: read-only; no rubric is required.
- R1: bounded internal change; common rubric and self-check are required.
- R2: public or multi-consumer impact; common plus profile rubric and independent review are required.
- R3: release, external, destructive, or irreversible impact; fresh approval and independent review are required.

## Verdicts

Use only `PASS`, `NEEDS_REVISION`, or `INCONCLUSIVE`. A blocking criterion cannot be waived by a score.
Use N/A only when its rubric condition is satisfied and record why.

## Change safety

Preserve unrelated dirty files. Never push, release, deploy, delete, or contact an external system
without explicit authority. Validate exact changed paths and retain evidence. Read-only operations must
not change tracked files or the Git index.

## Repository layout

Harness and Eidos own only their declared bootstrap and control-plane paths; they do not create or
rename product directories. Use `config/` for versioned configuration, profiles, scenarios, schemas,
and fixtures consumed by application code, tests, packaging, or deployment. Reserve `_meta/`, when
a project needs it, for repository-management metadata that no product runtime consumes; never mix
runtime inputs and repository-only state under that name.

Human and support roots such as `_docs/`, `_note/`, `_reference/`, and `_evidence/` remain
project-owned and optional. Record deviations in a project route. Renaming an established root with
code, test, documentation, artifact, or deployment consumers is an R2 contract migration: inventory
every consumer, preserve immutable historical evidence, provide a recoverable transition, and obtain
independent review. Kit install and upgrade never perform that migration implicitly.

## Identity

Git-tracked Work ownership uses an active canonical human `member:*` ID from the project-owned
Eidos identity registry. Historical IDs remain in immutable Work and are resolved through explicit
aliases. Local claims separately identify the responsible member and the acting `agent:*`; a machine
name is not a person identity. Never assign new Work to `agent:*`, a historical alias, or an unknown
member.

## Failure knowledge

Search only failure entries selected by route tags. Promote reusable lessons with an enforcement link
to a route, test, validator, or code boundary. Never store credentials, personal data, raw chat, raw
logs, or machine-specific absolute paths.
"""


class HarnessKitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "project"
        self.root.mkdir()
        self.git("init")
        self.git("config", "user.name", "Harness Test")
        self.git("config", "user.email", "harness@example.invalid")
        self.git("commit", "--allow-empty", "-m", "initial")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_process(
        self, *arguments: object, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(argument) for argument in arguments],
            cwd=cwd or self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    def git(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        result = self.run_process("git", *arguments)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def manager(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return self.run_process(
            sys.executable, "-B", MANAGER, *arguments, "--root", self.root
        )

    def tool(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return self.run_process(
            sys.executable,
            "-B",
            self.root / ".agents/tools/harness.py",
            *arguments,
            "--root",
            self.root,
        )

    def eidos(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return self.run_process(
            sys.executable,
            "-B",
            self.root / ".agents/tools/eidos.py",
            *arguments,
            "--root",
            self.root,
        )

    def install(self, *, without_eidos: bool = False) -> None:
        arguments = [
            "install",
            "--project-id",
            "project:test-project",
            "--project-name",
            "Test Project",
        ]
        if without_eidos:
            arguments.append("--without-eidos")
        result = self.manager(*arguments)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        if not without_eidos:
            (self.root / ".agents/eidos/identity.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "status": "configured",
                        "members": [
                            {
                                "id": "member:a",
                                "display_name": "A",
                                "status": "active",
                            }
                        ],
                        "aliases": [],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
                newline="\n",
            )
            synchronized = self.manager("upgrade")
            self.assertEqual(
                synchronized.returncode,
                0,
                synchronized.stdout + synchronized.stderr,
            )

    def emulate_harness_1_0_0(self) -> None:
        module = self.load_manager()
        contract_path = self.root / ".agents/harness/contract.md"
        current = HISTORICAL_CONTRACT
        layout_start = current.index("\n## Repository layout\n")
        failure_start = current.index("\n## Failure knowledge\n")
        prior = current[:layout_start] + current[failure_start:]
        descriptor = module._release_descriptor("1.0.0")
        prior_digest = hashlib.sha256(prior.encode("utf-8")).hexdigest()
        self.assertEqual(
            prior_digest, descriptor["files"][".agents/harness/contract.md"]
        )
        contract_path.write_text(prior, encoding="utf-8", newline="\n")

        manifest_path = self.root / module.MANIFEST_PATH
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["kit_version"] = "1.0.0"
        manifest["files"][".agents/harness/contract.md"]["sha256"] = prior_digest
        manifest_path.write_bytes(module._json_bytes(manifest))

    def emulate_harness_1_1_0(self) -> None:
        module = self.load_manager()
        contract_path = self.root / ".agents/harness/contract.md"
        current = HISTORICAL_CONTRACT
        identity_start = current.index("\n## Identity\n")
        failure_start = current.index("\n## Failure knowledge\n")
        without_identity = current[:identity_start] + current[failure_start:]
        prior = without_identity.replace("Reserve `_meta/`", "Reserve `_config/`")
        descriptor = module._release_descriptor("1.1.0")
        prior_digest = hashlib.sha256(prior.encode("utf-8")).hexdigest()
        self.assertEqual(
            prior_digest, descriptor["files"][".agents/harness/contract.md"]
        )
        contract_path.write_text(prior, encoding="utf-8", newline="\n")

        manifest_path = self.root / module.MANIFEST_PATH
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["kit_version"] = "1.1.0"
        manifest["files"][".agents/harness/contract.md"]["sha256"] = prior_digest
        manifest_path.write_bytes(module._json_bytes(manifest))

    def prepare_migration_inputs(
        self, *, invalid_routing: bool = False, drifted_adapter: bool = False
    ) -> dict[str, bytes]:
        module = self.load_manager()
        rendered = module._combined_render("project:test-project", "Test Project", True)
        selected = (
            "AGENTS.md",
            "FAILURE_LOG.md",
            ".agents/context.json",
            ".agents/routing.md",
            "CLAUDE.md",
        )
        expected: dict[str, bytes] = {}
        for relative in selected:
            data = rendered[relative]
            if relative == "AGENTS.md":
                data += b"\nProject-owned migration rule.\n"
            elif relative == "FAILURE_LOG.md":
                data += b"\nProject-owned failure guide.\n"
            elif relative == ".agents/context.json":
                context = json.loads(data)
                context["project_application"] = "src/example"
                data = module._json_bytes(context)
            elif relative == ".agents/routing.md" and invalid_routing:
                data = b"invalid routing\n"
            elif relative == "CLAUDE.md" and drifted_adapter:
                data += b"drift\n"
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            expected[relative] = data
        return expected

    def index_identity(self) -> tuple[bool, str | None, int | None]:
        raw = self.git("rev-parse", "--git-path", "index").stdout.strip()
        path = Path(raw)
        if not path.is_absolute():
            path = self.root / path
        if not path.is_file():
            return False, None, None
        return (
            True,
            hashlib.sha256(path.read_bytes()).hexdigest(),
            path.stat().st_mtime_ns,
        )

    def tree_state(self) -> dict[str, tuple[str, int, str | None]]:
        result: dict[str, tuple[str, int, str | None]] = {}
        for path in sorted(self.root.rglob("*")):
            relative = path.relative_to(self.root)
            if ".git" in relative.parts:
                continue
            if path.is_file():
                result[relative.as_posix()] = (
                    "file",
                    path.stat().st_mode,
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
            elif path.is_dir():
                result[relative.as_posix()] = ("directory", path.stat().st_mode, None)
        return result

    def load_manager(self):
        name = f"_harness_manager_test_{id(self)}"
        spec = importlib.util.spec_from_file_location(name, MANAGER)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        self.addCleanup(sys.modules.pop, name, None)
        spec.loader.exec_module(module)
        return module

    def create_work(self) -> str:
        result = self.eidos(
            "new-work",
            "--slug",
            "failure-source",
            "--stage",
            "S01",
            "--title",
            "Failure Source",
            "--owner",
            "member:a",
            "--workstream",
            "workstream:harness",
            "--write-scope",
            "src",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return Path(result.stdout.strip()).stem

    @staticmethod
    def failure_input(work_id: str) -> dict[str, object]:
        return {
            "observed_on": "2026-08-21",
            "area": "harness",
            "tags": ["harness", "atomicity"],
            "status": "mitigated",
            "source_work_id": work_id,
            "enforced_by": [".agents/tools/harness.py"],
            "title": "Partial write was possible",
            "failed_assumption": "A partial write was assumed to be harmless.",
            "root_cause": "The write set was not committed atomically.",
            "prevention": "Snapshot every target and restore the complete set.",
            "evidence": "Focused rollback regression passed.",
            "slug": "partial-write",
        }

    def test_default_install_composes_eidos_and_validates(self) -> None:
        self.install()
        context = json.loads(
            (self.root / ".agents/context.json").read_text(encoding="utf-8")
        )
        self.assertEqual(context["eidos"]["version"], 3)
        self.assertTrue(context["harness"]["eidos_enabled"])
        manifest = json.loads(
            (self.root / ".agents/harness/kit-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(manifest["eidos"]["enabled"])
        self.assertRegex(manifest["eidos"]["manifest_sha256"], r"^[a-f0-9]{64}$")
        self.assertEqual(self.tool("validate", "--json").returncode, 0)
        self.assertEqual(self.eidos("validate", "--json").returncode, 0)
        self.assertEqual(self.eidos("focus", "--json").returncode, 0)
        doctor = self.manager("doctor", "--json")
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)

        direction = self.root / ".agents/eidos/direction.md"
        direction.write_text(
            direction.read_text(encoding="utf-8").replace(
                "State the stable problem this project solves and the expected outcome.",
                "Keep the project's durable outcome explicit.",
            ),
            encoding="utf-8",
        )
        self.assertEqual(self.manager("doctor", "--json").returncode, 0)

    def test_install_documents_but_does_not_create_product_layout_roots(self) -> None:
        self.install()
        contract = (self.root / ".agents/harness/contract.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Use `config/` for versioned configuration", contract)
        self.assertIn("Reserve `_meta/`", contract)
        optional_roots = (
            "config",
            "_meta",
            "_docs",
            "_note",
            "_reference",
            "_evidence",
        )
        for relative in optional_roots:
            self.assertFalse((self.root / relative).exists(), relative)

    def test_without_eidos_has_no_eidos_files_and_allows_none_work(self) -> None:
        self.install(without_eidos=True)
        self.assertFalse((self.root / ".agents/eidos").exists())
        context = json.loads(
            (self.root / ".agents/context.json").read_text(encoding="utf-8")
        )
        self.assertFalse(context["harness"]["eidos_enabled"])
        payload = self.failure_input("none")
        result = self.tool("failure", "new", "--input-json", json.dumps(payload))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.tool("failure", "validate", "--json").returncode, 0)

    def test_assess_is_read_only_and_install_refuses_collision(self) -> None:
        (self.root / "AGENTS.md").write_text("existing\n", encoding="utf-8")
        before_tree = self.tree_state()
        before_index = self.index_identity()
        result = self.manager("assess")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["installable"])
        self.assertIn("AGENTS.md", payload["collisions"])
        self.assertEqual(before_tree, self.tree_state())
        self.assertEqual(before_index, self.index_identity())
        refused = self.manager(
            "install",
            "--project-id",
            "project:test-project",
            "--project-name",
            "Test Project",
        )
        self.assertEqual(refused.returncode, 2)
        self.assertEqual(
            (self.root / "AGENTS.md").read_text(encoding="utf-8"), "existing\n"
        )

    def test_assess_includes_default_eidos_collisions(self) -> None:
        direction = self.root / ".agents/eidos/direction.md"
        direction.parent.mkdir(parents=True)
        direction.write_text("existing\n", encoding="utf-8")
        before = (self.tree_state(), self.index_identity())
        result = self.manager("assess")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["installable"])
        self.assertIn(".agents/eidos/direction.md", payload["collisions"])
        self.assertEqual(before, (self.tree_state(), self.index_identity()))

    def test_migrate_preserves_project_owned_and_adopts_only_exact_kit_bytes(
        self,
    ) -> None:
        expected = self.prepare_migration_inputs()
        migrated = self.manager(
            "migrate",
            "--project-id",
            "project:test-project",
            "--project-name",
            "Test Project",
        )
        self.assertEqual(migrated.returncode, 0, migrated.stdout + migrated.stderr)
        for relative, data in expected.items():
            self.assertEqual((self.root / relative).read_bytes(), data)
        manifest = json.loads(
            (self.root / ".agents/harness/kit-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["files"]["AGENTS.md"]["ownership"], "project")
        self.assertEqual(manifest["files"]["CLAUDE.md"]["ownership"], "kit")
        self.assertEqual(self.tool("validate", "--json").returncode, 0)
        self.assertEqual(self.eidos("validate", "--json").returncode, 0)
        doctor = self.manager("doctor", "--json")
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)

    def test_migrate_adopts_authenticated_standalone_eidos_v3(self) -> None:
        module = self.load_manager()
        eidos_module = module._load_eidos_module()
        eidos = eidos_module.render_installation("project:test-project", "Test Project")
        for relative, data in eidos.items():
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

        context_path = self.root / ".agents/context.json"
        context = json.loads(context_path.read_text(encoding="utf-8"))
        context["project_application"] = "src/example"
        context["harness"] = {
            "version": 1,
            "eidos_enabled": True,
            "routing_path": ".agents/routing.md",
            "failure_root": ".agents/failures",
        }
        context_path.write_bytes(module._json_bytes(context))
        direction_path = self.root / ".agents/eidos/direction.md"
        direction_path.write_bytes(
            direction_path.read_bytes().replace(
                b"State the verified baseline.", b"Verified project baseline."
            )
        )
        preserved = {
            ".agents/context.json": context_path.read_bytes(),
            ".agents/eidos/direction.md": direction_path.read_bytes(),
        }

        combined = module._combined_render("project:test-project", "Test Project", True)
        for relative in (
            "AGENTS.md",
            "FAILURE_LOG.md",
            ".agents/routing.md",
            "CLAUDE.md",
            ".agents/workflows/change.md",
        ):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(combined[relative])

        migrated = self.manager(
            "migrate",
            "--project-id",
            "project:test-project",
            "--project-name",
            "Test Project",
        )
        self.assertEqual(migrated.returncode, 0, migrated.stdout + migrated.stderr)
        for relative, data in preserved.items():
            self.assertEqual((self.root / relative).read_bytes(), data)
        self.assertEqual(self.manager("doctor", "--json").returncode, 0)
        self.assertEqual(self.eidos("validate", "--json").returncode, 0)

    def test_migrate_rejects_forged_standalone_eidos_manifest(self) -> None:
        module = self.load_manager()
        eidos = module._load_eidos_module().render_installation(
            "project:test-project", "Test Project"
        )
        for relative, data in eidos.items():
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        manifest_path = self.root / ".agents/eidos/kit-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"][".agents/tools/eidos.py"]["ownership"] = "project"
        manifest_path.write_bytes(module._json_bytes(manifest))
        before = self.tree_state()

        refused = self.manager(
            "migrate",
            "--project-id",
            "project:test-project",
            "--project-name",
            "Test Project",
        )
        self.assertEqual(refused.returncode, 2)
        self.assertIn("eidos_migration_manifest", refused.stderr)
        self.assertEqual(before, self.tree_state())

    def test_migrate_rejects_kit_drift_and_invalid_project_contract_before_write(
        self,
    ) -> None:
        self.prepare_migration_inputs(drifted_adapter=True)
        before = self.tree_state()
        refused = self.manager(
            "migrate",
            "--project-id",
            "project:test-project",
            "--project-name",
            "Test Project",
        )
        self.assertEqual(refused.returncode, 2)
        self.assertIn("migration_collision", refused.stderr)
        self.assertEqual(before, self.tree_state())

        (self.root / "CLAUDE.md").unlink()
        shutil_expected = self.prepare_migration_inputs(invalid_routing=True)
        del shutil_expected
        before = self.tree_state()
        refused = self.manager(
            "migrate",
            "--project-id",
            "project:test-project",
            "--project-name",
            "Test Project",
        )
        self.assertEqual(refused.returncode, 2)
        self.assertIn("candidate_invalid", refused.stderr)
        self.assertEqual(before, self.tree_state())

    def test_migrate_validates_existing_unmanaged_control_extensions(self) -> None:
        self.prepare_migration_inputs()
        route = self.root / ".agents/routes/bad.md"
        route.parent.mkdir(parents=True, exist_ok=True)
        route.write_text(
            "| route | risk |\n| --- | --- |\n| bad | R1 |\n",
            encoding="utf-8",
        )
        before = self.tree_state()

        refused = self.manager(
            "migrate",
            "--project-id",
            "project:test-project",
            "--project-name",
            "Test Project",
        )

        self.assertEqual(refused.returncode, 2)
        self.assertIn("candidate_invalid", refused.stderr)
        self.assertEqual(before, self.tree_state())

    def test_migrate_extension_cas_rolls_back_on_concurrent_change(self) -> None:
        self.prepare_migration_inputs()
        route = self.root / ".agents/routes/custom.md"
        route.parent.mkdir(parents=True, exist_ok=True)
        route.write_text(
            "# Project route\n\n"
            "| Route | Use when | Risk | Rubrics | Failure tags |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| custom | Internal change | R1 | common-change | custom |\n\n"
            "## Scope\n\nInternal only.\n",
            encoding="utf-8",
        )
        module = self.load_manager()
        arguments = module.argparse.Namespace(
            root=self.root,
            project_id="project:test-project",
            project_name="Test Project",
            without_eidos=False,
        )
        original = module._replace
        changed = False

        def mutate_after_first_replace(path, data, expected=None):
            nonlocal changed
            original(path, data, expected)
            if not changed:
                route.write_text(
                    "| route | risk |\n| --- | --- |\n| custom | R1 |\n",
                    encoding="utf-8",
                )
                changed = True

        with mock.patch.object(
            module, "_replace", side_effect=mutate_after_first_replace
        ):
            with self.assertRaisesRegex(
                module.HarnessKitError, "control extensions changed"
            ):
                module._command_migrate(arguments)

        self.assertTrue(changed)
        self.assertFalse((self.root / ".agents/harness/kit-manifest.json").exists())
        self.assertIn("| route | risk |\n", route.read_text(encoding="utf-8"))
        self.assertEqual(self.tool("validate", "--json").returncode, 2)

    def test_migrate_fault_restores_existing_and_new_paths(self) -> None:
        self.prepare_migration_inputs()
        module = self.load_manager()
        arguments = module.argparse.Namespace(
            root=self.root,
            project_id="project:test-project",
            project_name="Test Project",
            without_eidos=False,
        )
        before = self.tree_state()
        original = module._write_exclusive
        calls = 0

        def fail_after_third(path, data, on_created=None):
            nonlocal calls
            original(path, data, on_created)
            calls += 1
            if calls == 3:
                raise OSError("fault during migration")

        with mock.patch.object(
            module, "_write_exclusive", side_effect=fail_after_third
        ):
            with self.assertRaises(OSError):
                module._command_migrate(arguments)
        self.assertEqual(before, self.tree_state())

    def test_root_reparse_is_rejected_before_resolution(self) -> None:
        alias = self.root.parent / "project-alias"
        try:
            alias.symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest("directory symlink creation is unavailable")
        result = self.run_process(
            sys.executable, "-B", MANAGER, "assess", "--root", alias
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("root_reparse", result.stderr)

    def test_project_name_is_json_safe_and_control_characters_are_rejected(
        self,
    ) -> None:
        quoted = self.manager(
            "install",
            "--project-id",
            "project:quoted",
            "--project-name",
            'Quoted "Project"',
        )
        self.assertEqual(quoted.returncode, 0, quoted.stdout + quoted.stderr)
        context = json.loads(
            (self.root / ".agents/context.json").read_text(encoding="utf-8")
        )
        self.assertEqual(context["project"]["name"], 'Quoted "Project"')

    def test_install_fault_rolls_back_combined_harness_and_eidos_set(self) -> None:
        module = self.load_manager()
        arguments = module.argparse.Namespace(
            root=self.root,
            project_id="project:test-project",
            project_name="Test Project",
            without_eidos=False,
        )
        before = self.tree_state()
        original = module._write_exclusive
        calls = 0

        def fail_after_fifth(path, data, on_created=None):
            nonlocal calls
            original(path, data, on_created)
            calls += 1
            if calls == 5:
                raise OSError("fault after combined write")

        with mock.patch.object(
            module, "_write_exclusive", side_effect=fail_after_fifth
        ):
            with self.assertRaises(OSError):
                module._command_install(arguments)
        self.assertEqual(before, self.tree_state())
        self.assertFalse((self.root / ".agents").exists())

    def test_install_collision_never_deletes_concurrent_file(self) -> None:
        module = self.load_manager()
        arguments = module.argparse.Namespace(
            root=self.root,
            project_id="project:test-project",
            project_name="Test Project",
            without_eidos=False,
        )
        original = module._write_exclusive
        injected = False

        def collide(path, data, on_created=None):
            nonlocal injected
            if not injected:
                injected = True
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"concurrent-owner\n")
            return original(path, data, on_created)

        with mock.patch.object(module, "_write_exclusive", side_effect=collide):
            with self.assertRaises(module.HarnessKitError):
                module._command_install(arguments)
        concurrent = next(
            path
            for path in self.root.rglob("*")
            if path.is_file() and ".git" not in path.parts
        )
        self.assertEqual(concurrent.read_bytes(), b"concurrent-owner\n")

    def test_install_semantically_validates_combined_candidate_before_write(
        self,
    ) -> None:
        module = self.load_manager()
        arguments = module.argparse.Namespace(
            root=self.root,
            project_id="project:test-project",
            project_name="Test Project",
            without_eidos=False,
        )
        original = module._combined_render

        def invalid_candidate(project_id, project_name, eidos):
            writes = original(project_id, project_name, eidos)
            routing = ".agents/routing.md"
            writes[routing] = b"broken\n"
            manifest = json.loads(writes[module.MANIFEST_PATH.as_posix()].decode())
            manifest["files"][routing]["sha256"] = module._sha(writes[routing])
            writes[module.MANIFEST_PATH.as_posix()] = module._json_bytes(manifest)
            return writes

        before = self.tree_state()
        with mock.patch.object(
            module, "_combined_render", side_effect=invalid_candidate
        ):
            with self.assertRaisesRegex(module.HarnessKitError, "Candidate validation"):
                module._command_install(arguments)
        self.assertEqual(before, self.tree_state())

    def test_supported_version_upgrade_updates_manifest(self) -> None:
        self.install()
        self.emulate_harness_1_1_0()
        module = self.load_manager()
        arguments = module.argparse.Namespace(root=self.root)
        self.assertEqual(module._command_upgrade(arguments), 0)
        manifest = json.loads(
            (self.root / ".agents/harness/kit-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["kit_version"], module.KIT_VERSION)

    def test_upgrade_skips_unchanged_managed_files(self) -> None:
        self.install()
        self.emulate_harness_1_0_0()
        module = self.load_manager()
        unchanged = (
            self.root / ".agents/tools/harness.py",
            self.root / ".agents/tools/eidos.py",
            self.root / ".agents/eidos/kit-manifest.json",
        )
        before = {path: path.stat().st_mtime_ns for path in unchanged}
        original = module._replace
        replaced: list[Path] = []

        def record_replace(path, data, expected=None):
            replaced.append(path)
            return original(path, data, expected)

        with mock.patch.object(module, "_replace", side_effect=record_replace):
            self.assertEqual(
                module._command_upgrade(module.argparse.Namespace(root=self.root)), 0
            )

        self.assertEqual(before, {path: path.stat().st_mtime_ns for path in unchanged})
        self.assertTrue(all(path not in replaced for path in unchanged))
        self.assertIn(self.root / ".agents/harness/contract.md", replaced)

    def test_prior_upgrade_is_independent_of_project_name_prose(self) -> None:
        installed = self.manager(
            "install",
            "--project-id",
            "project:eidos-name",
            "--project-name",
            "Eidos",
        )
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.emulate_harness_1_0_0()
        module = self.load_manager()
        self.assertEqual(
            module._command_upgrade(module.argparse.Namespace(root=self.root)), 0
        )

    def test_release_descriptor_matches_exact_v1_template_bytes(self) -> None:
        module = self.load_manager()
        rendered = module._combined_render(
            "project:descriptor", "Descriptor Project", True
        )
        descriptor = json.loads(
            (
                REPOSITORY
                / f"kits/harness/v1/release-manifests/{module.KIT_VERSION}.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(set(descriptor["files"]), module.HARNESS_RELEASE_PATHS)
        self.assertEqual(
            descriptor["files"],
            {
                relative: hashlib.sha256(rendered[relative]).hexdigest()
                for relative in module.HARNESS_RELEASE_PATHS
            },
        )
        eidos_module = module._load_eidos_module()
        eidos = eidos_module.render_installation("project:example", "Example Project")
        eidos_manifest = json.loads(eidos[".agents/eidos/kit-manifest.json"])
        self.assertEqual(
            descriptor["eidos"],
            {
                "kit_version": eidos_manifest["kit_version"],
                "files": {
                    relative: record["sha256"]
                    for relative, record in eidos_manifest["files"].items()
                    if record["ownership"] == "kit"
                },
            },
        )

    def test_upgrade_rejects_unsigned_composed_eidos_release(self) -> None:
        self.install()
        self.emulate_harness_1_0_0()
        module = self.load_manager()
        real_eidos = module._load_eidos_module()
        original_render = real_eidos.render_installation
        before = {
            path.relative_to(self.root).as_posix(): path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file() and ".git" not in path.parts
        }

        def changed_render(project_id, project_name):
            writes = original_render(project_id, project_name)
            tool = ".agents/tools/eidos.py"
            writes[tool] += b"\n# compatible next release\n"
            manifest_path = ".agents/eidos/kit-manifest.json"
            manifest = json.loads(writes[manifest_path])
            manifest["kit_version"] = "3.1.0"
            manifest["files"][tool]["sha256"] = hashlib.sha256(writes[tool]).hexdigest()
            writes[manifest_path] = module._json_bytes(manifest)
            return writes

        real_eidos.render_installation = changed_render
        arguments = module.argparse.Namespace(root=self.root)
        with mock.patch.object(module, "_load_eidos_module", return_value=real_eidos):
            with self.assertRaisesRegex(
                module.HarnessKitError, "Installed Eidos release is not trusted"
            ):
                module._command_upgrade(arguments)
        after = {
            path.relative_to(self.root).as_posix(): path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file() and ".git" not in path.parts
        }
        self.assertEqual(after, before)

    def test_upgrade_preserves_project_owned_and_blocks_kit_drift(self) -> None:
        self.install()
        agents = self.root / "AGENTS.md"
        agents.write_text(
            agents.read_text(encoding="utf-8") + "\nProject rule.\n", encoding="utf-8"
        )
        upgraded = self.manager("upgrade")
        self.assertEqual(upgraded.returncode, 0, upgraded.stdout + upgraded.stderr)
        self.assertIn("Project rule.", agents.read_text(encoding="utf-8"))
        contract = self.root / ".agents/harness/contract.md"
        contract.write_text(
            contract.read_text(encoding="utf-8") + "drift\n", encoding="utf-8"
        )
        self.assertEqual(self.manager("diff", "--json").returncode, 1)
        refused = self.manager("upgrade")
        self.assertEqual(refused.returncode, 2)
        self.assertIn("local_modification", refused.stderr)

    def test_upgrade_rejects_forged_kit_hash_in_manifest(self) -> None:
        self.install()
        contract = self.root / ".agents/harness/contract.md"
        contract.write_text("forged\n", encoding="utf-8")
        manifest_path = self.root / ".agents/harness/kit-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"][".agents/harness/contract.md"]["sha256"] = hashlib.sha256(
            contract.read_bytes()
        ).hexdigest()
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        refused = self.manager("upgrade")
        self.assertEqual(refused.returncode, 2)
        self.assertIn("manifest_untrusted", refused.stderr)
        self.assertEqual(contract.read_text(encoding="utf-8"), "forged\n")

    def test_mode_drift_is_reported_and_blocks_upgrade(self) -> None:
        self.install()
        contract = self.root / ".agents/harness/contract.md"
        contract.chmod(0o444)
        try:
            diff = self.manager("diff", "--json")
            self.assertEqual(diff.returncode, 1)
            row = next(
                item
                for item in json.loads(diff.stdout)["files"]
                if item["path"] == ".agents/harness/contract.md"
            )
            self.assertEqual(row["status"], "modified")
            self.assertEqual(self.manager("upgrade").returncode, 2)
        finally:
            contract.chmod(0o644)

    def test_upgrade_fault_restores_manifest_files_and_modes(self) -> None:
        self.install()
        self.emulate_harness_1_0_0()
        module = self.load_manager()
        arguments = module.argparse.Namespace(root=self.root)
        before = self.tree_state()
        original = module._replace

        def fail_at_manifest(path, data, expected=None):
            original(path, data, expected)
            if path == self.root / module.MANIFEST_PATH:
                raise OSError("fault after manifest")

        with mock.patch.object(module, "_replace", side_effect=fail_at_manifest):
            with self.assertRaises(OSError):
                module._command_upgrade(arguments)
        self.assertEqual(before, self.tree_state())

    def test_upgrade_refuses_concurrent_edit_without_clobber(self) -> None:
        self.install()
        self.emulate_harness_1_1_0()
        module = self.load_manager()
        arguments = module.argparse.Namespace(root=self.root)
        target = self.root / ".agents/harness/contract.md"
        original_replace = module._replace
        injected = False

        def concurrent_replace(path, data, expected=None):
            nonlocal injected
            if path == target and not injected:
                injected = True
                path.write_text("concurrent owner bytes\n", encoding="utf-8")
            return original_replace(path, data, expected)

        with mock.patch.object(module, "_replace", side_effect=concurrent_replace):
            with self.assertRaisesRegex(
                module.HarnessKitError, "Target changed during upgrade"
            ):
                module._command_upgrade(arguments)
        self.assertEqual(target.read_text(encoding="utf-8"), "concurrent owner bytes\n")

    def test_upgrade_rolls_back_when_unchanged_managed_file_changes(self) -> None:
        self.install()
        self.emulate_harness_1_1_0()
        module = self.load_manager()
        contract = self.root / ".agents/harness/contract.md"
        manifest = self.root / module.MANIFEST_PATH
        unchanged = self.root / ".agents/tools/harness.py"
        contract_before = contract.read_bytes()
        manifest_before = manifest.read_bytes()
        original_replace = module._replace
        injected = False

        def mutate_unchanged_after_publish(path, data, expected=None):
            nonlocal injected
            original_replace(path, data, expected)
            if path == manifest and not injected:
                injected = True
                unchanged.write_bytes(b"concurrent owner bytes\n")

        with mock.patch.object(
            module, "_replace", side_effect=mutate_unchanged_after_publish
        ):
            with self.assertRaisesRegex(
                module.HarnessKitError, "Managed file changed during upgrade"
            ):
                module._command_upgrade(module.argparse.Namespace(root=self.root))

        self.assertEqual(unchanged.read_bytes(), b"concurrent owner bytes\n")
        self.assertEqual(contract.read_bytes(), contract_before)
        self.assertEqual(manifest.read_bytes(), manifest_before)

    def test_upgrade_rename_cas_detects_last_moment_concurrent_edit(self) -> None:
        self.install()
        self.emulate_harness_1_1_0()
        module = self.load_manager()
        target = self.root / ".agents/harness/contract.md"
        original_rename = module.os.rename
        injected = False

        def race_at_rename(source, destination):
            nonlocal injected
            if Path(source) == target and not injected:
                injected = True
                target.write_text("last moment owner bytes\n", encoding="utf-8")
            return original_rename(source, destination)

        with mock.patch.object(module.os, "rename", side_effect=race_at_rename):
            with self.assertRaisesRegex(
                module.HarnessKitError, "Target changed during upgrade"
            ):
                module._command_upgrade(module.argparse.Namespace(root=self.root))
        self.assertEqual(
            target.read_text(encoding="utf-8"), "last moment owner bytes\n"
        )

    def test_doctor_rejects_forged_tool_and_reparse_without_execution(self) -> None:
        self.install()
        marker = self.root.parent / "executed"
        tool = self.root / ".agents/tools/harness.py"
        original_tool = tool.read_bytes()
        tool.write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).write_text('yes')\n",
            encoding="utf-8",
        )
        manifest_path = self.root / ".agents/harness/kit-manifest.json"
        original_manifest = manifest_path.read_bytes()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"][".agents/tools/harness.py"]["sha256"] = hashlib.sha256(
            tool.read_bytes()
        ).hexdigest()
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        forged = self.manager("doctor", "--json")
        self.assertEqual(forged.returncode, 2)
        self.assertFalse(marker.exists())

        external = self.root.parent / "external.py"
        external.write_text("raise SystemExit('executed')\n", encoding="utf-8")
        manifest_path.write_bytes(original_manifest)
        tool.write_bytes(original_tool)
        tool.unlink()
        try:
            tool.symlink_to(external)
        except OSError:
            self.skipTest("file symlink creation is unavailable")
        reparse = self.manager("doctor", "--json")
        self.assertEqual(reparse.returncode, 2)
        self.assertIn("path_reparse", reparse.stdout)

    def test_doctor_warns_about_root_tool_caches_without_mutation(self) -> None:
        self.install()
        observed_files = [self.root / "AGENTS.md"]
        for relative in (".pytest_cache", ".ruff_cache", ".mypy_cache"):
            cache = self.root / relative
            cache.mkdir()
            state = cache / "state"
            state.write_text("cache\n", encoding="utf-8")
            observed_files.append(state)
        before = (self.tree_state(), self.index_identity())
        before_files = {
            path: (
                hashlib.sha256(path.read_bytes()).hexdigest(),
                path.stat().st_mtime_ns,
            )
            for path in observed_files
        }

        doctor = self.manager("doctor", "--json")

        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
        payload = json.loads(doctor.stdout)
        warnings = [
            item
            for item in payload["findings"]
            if item["code"] == "misplaced_root_cache"
        ]
        self.assertTrue(payload["ok"])
        self.assertEqual(
            {item["message"] for item in warnings},
            {
                ".mypy_cache should be generated under .cache/mypy",
                ".pytest_cache should be generated under .cache/pytest",
                ".ruff_cache should be generated under .cache/ruff",
            },
        )
        self.assertEqual(before, (self.tree_state(), self.index_identity()))
        self.assertEqual(
            before_files,
            {
                path: (
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                    path.stat().st_mtime_ns,
                )
                for path in observed_files
            },
        )

    def test_doctor_rejects_root_cache_reparse_without_traversal(self) -> None:
        self.install()
        external = self.root.parent / "external-cache"
        external.mkdir()
        state = external / "state"
        state.write_text("external\n", encoding="utf-8")
        cache = self.root / ".pytest_cache"
        try:
            cache.symlink_to(external, target_is_directory=True)
        except OSError:
            self.skipTest("directory symlink creation is unavailable")
        before = (state.read_bytes(), state.stat().st_mtime_ns, self.index_identity())

        doctor = self.manager("doctor", "--json")

        self.assertEqual(doctor.returncode, 2)
        payload = json.loads(doctor.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("path_reparse", {item["code"] for item in payload["findings"]})
        self.assertEqual(
            before,
            (state.read_bytes(), state.stat().st_mtime_ns, self.index_identity()),
        )

    def test_failure_records_are_work_bound_searchable_private_and_no_clobber(
        self,
    ) -> None:
        self.install()
        work_id = self.create_work()
        value = self.failure_input(work_id)
        created = self.tool("failure", "new", "--input-json", json.dumps(value))
        self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        path = self.root / created.stdout.strip()
        original = path.read_bytes()
        listing = json.loads(self.tool("failure", "list").stdout)
        self.assertEqual(len(listing["failures"]), 1)
        found = json.loads(self.tool("failure", "search", "--tag", "atomicity").stdout)
        self.assertEqual(found["failures"][0]["failure_id"], path.stem)

        invalid = dict(value)
        invalid["evidence"] = "password=supersecret"
        rejected = self.tool("failure", "new", "--input-json", json.dumps(invalid))
        self.assertEqual(rejected.returncode, 2)
        self.assertEqual(path.read_bytes(), original)
        missing_work = dict(value)
        missing_work["source_work_id"] = "W-20260821-99-missing"
        refused = self.tool("failure", "new", "--input-json", json.dumps(missing_work))
        self.assertEqual(refused.returncode, 2)
        self.assertEqual(self.tool("failure", "validate", "--json").returncode, 0)

    def test_failure_supersession_cycle_is_rejected(self) -> None:
        self.install()
        work_id = self.create_work()
        first_input = self.failure_input(work_id)
        first = self.tool("failure", "new", "--input-json", json.dumps(first_input))
        self.assertEqual(first.returncode, 0, first.stderr)
        first_path = self.root / first.stdout.strip()
        second_input = dict(first_input)
        second_input["slug"] = "partial-write-correction"
        second_input["supersedes_id"] = first_path.stem
        second = self.tool("failure", "new", "--input-json", json.dumps(second_input))
        self.assertEqual(second.returncode, 0, second.stderr)
        second_id = Path(second.stdout.strip()).stem
        first_path.write_text(
            first_path.read_text(encoding="utf-8").replace(
                "supersedes_id: none", f"supersedes_id: {second_id}"
            ),
            encoding="utf-8",
        )
        validation = self.tool("failure", "validate", "--json")
        self.assertEqual(validation.returncode, 2)
        self.assertIn("failure_supersession", validation.stdout)

    def test_failure_requires_canonical_work_enforcement_and_private_text_rejection(
        self,
    ) -> None:
        self.install()
        work_id = self.create_work()
        fake_id = "W-20260821-99-fake"
        fake = self.root / ".agents/eidos/work" / f"{fake_id}.md"
        fake.write_text(
            "---\n"
            "eidos_version: 3\n"
            "document_type: work\n"
            "project_id: project:test-project\n"
            f"work_id: {fake_id}\n"
            "status: in_progress\n"
            "---\n",
            encoding="utf-8",
        )
        fake_input = self.failure_input(fake_id)
        self.assertEqual(
            self.tool(
                "failure", "new", "--input-json", json.dumps(fake_input)
            ).returncode,
            2,
        )
        fake.unlink()

        for private_text in (
            "Authorization: Bearer sk-r2-secret-value",
            r"\\server\share\raw.log",
            "raw-log payload follows",
            "ghp_abcdefghijklmnopqrstuvwxyz123456",
            "AKIAABCDEFGHIJKLMNOP",
            "-----BEGIN PRIVATE KEY-----",
            "/etc/passwd",
            "xoxb-1234567890-secretvalue",
            "AIzaSyDUMMY012345678901234567890",
            "sk_live_abcdefghijklmnopqrstuvwxyz",
            "token=abcdefghijklmnopqrstuvwxyz123456",
            "npm_abcdefghijklmnopqrstuvwxyz123456",
            "eyJheader123456.payload123456.signature123456",
        ):
            value = self.failure_input(work_id)
            value["evidence"] = private_text
            result = self.tool("failure", "new", "--input-json", json.dumps(value))
            self.assertEqual(result.returncode, 2)
            self.assertIn("failure_privacy", result.stderr)
        unenforced = self.failure_input(work_id)
        unenforced["enforced_by"] = ["none"]
        result = self.tool("failure", "new", "--input-json", json.dumps(unenforced))
        self.assertEqual(result.returncode, 2)
        self.assertIn("failure_enforcement", result.stderr)
        routing_enforced = self.failure_input(work_id)
        routing_enforced["slug"] = "routing-enforced"
        routing_enforced["enforced_by"] = [".agents/routing.md"]
        result = self.tool(
            "failure", "new", "--input-json", json.dumps(routing_enforced)
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        git_config = self.failure_input(work_id)
        git_config["enforced_by"] = [".git/config"]
        result = self.tool("failure", "new", "--input-json", json.dumps(git_config))
        self.assertEqual(result.returncode, 2)
        self.assertIn("failure_enforcement", result.stderr)

        work = self.root / ".agents/eidos/work" / f"{work_id}.md"
        work.write_text(
            work.read_text(encoding="utf-8").replace("risk: R1", "risk: RX"),
            encoding="utf-8",
        )
        invalid_work = self.failure_input(work_id)
        invalid_work["slug"] = "invalid-work-risk"
        result = self.tool("failure", "new", "--input-json", json.dumps(invalid_work))
        self.assertEqual(result.returncode, 2)
        self.assertIn("failure_work", result.stderr)

    def test_failure_work_binding_uses_full_eidos_semantics(self) -> None:
        self.install()
        work_id = self.create_work()
        work = self.root / ".agents/eidos/work" / f"{work_id}.md"
        original = work.read_text(encoding="utf-8")
        mutations = (
            ("depends_on: none", "depends_on: W-20260821-99-missing"),
            ("write_scope: src", "write_scope: ../outside"),
            ("direction_revision: D0001", "direction_revision: D9999"),
        )
        for index, (before, after) in enumerate(mutations, start=1):
            with self.subTest(after=after):
                self.assertIn(before, original)
                work.write_text(original.replace(before, after), encoding="utf-8")
                self.assertEqual(self.eidos("validate", "--json").returncode, 2)
                value = self.failure_input(work_id)
                value["slug"] = f"invalid-eidos-work-{index}"
                result = self.tool("failure", "new", "--input-json", json.dumps(value))
                self.assertEqual(result.returncode, 2)
                self.assertIn("failure_work", result.stderr)
                work.write_text(original, encoding="utf-8")

    def test_failure_work_validation_uses_source_pinned_eidos_tool(self) -> None:
        self.install()
        work_id = self.create_work()
        marker = self.root / "unexpected-eidos-execution.marker"
        eidos_tool = self.root / ".agents/tools/eidos.py"
        eidos_tool.write_text(
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n",
            encoding="utf-8",
        )

        eidos_manifest_path = self.root / ".agents/eidos/kit-manifest.json"
        eidos_manifest = json.loads(eidos_manifest_path.read_text(encoding="utf-8"))
        eidos_manifest["files"][".agents/tools/eidos.py"]["sha256"] = hashlib.sha256(
            eidos_tool.read_bytes()
        ).hexdigest()
        eidos_manifest_path.write_text(
            json.dumps(eidos_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        harness_manifest_path = self.root / ".agents/harness/kit-manifest.json"
        harness_manifest = json.loads(harness_manifest_path.read_text(encoding="utf-8"))
        eidos_manifest_digest = hashlib.sha256(
            eidos_manifest_path.read_bytes()
        ).hexdigest()
        harness_manifest["eidos"]["manifest_sha256"] = eidos_manifest_digest
        harness_manifest["files"][".agents/eidos/kit-manifest.json"]["sha256"] = (
            eidos_manifest_digest
        )
        harness_manifest_path.write_text(
            json.dumps(harness_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        value = self.failure_input(work_id)
        value["slug"] = "source-pinned-validator"
        result = self.tool("failure", "new", "--input-json", json.dumps(value))
        self.assertEqual(result.returncode, 2)
        self.assertIn("failure_work", result.stderr)
        self.assertFalse(marker.exists())

    def test_failure_search_reads_only_selected_bodies(self) -> None:
        self.install()
        work_id = self.create_work()
        first = self.failure_input(work_id)
        self.assertEqual(
            self.tool("failure", "new", "--input-json", json.dumps(first)).returncode,
            0,
        )
        second = self.failure_input(work_id)
        second["slug"] = "unrelated-entry"
        second["tags"] = ["unrelated"]
        created = self.tool("failure", "new", "--input-json", json.dumps(second))
        self.assertEqual(created.returncode, 0, created.stderr)
        path = self.root / created.stdout.strip()
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "Focused rollback regression passed.", "password=hidden-value"
            ),
            encoding="utf-8",
        )
        selected = self.tool("failure", "search", "--tag", "atomicity")
        self.assertEqual(selected.returncode, 0, selected.stderr)
        self.assertEqual(len(json.loads(selected.stdout)["failures"]), 1)
        self.assertEqual(self.tool("failure", "validate", "--json").returncode, 2)

    def test_failure_search_validates_global_supersession_graph(self) -> None:
        self.install()
        work_id = self.create_work()
        value = self.failure_input(work_id)
        created = self.tool("failure", "new", "--input-json", json.dumps(value))
        self.assertEqual(created.returncode, 0, created.stderr)
        path = self.root / created.stdout.strip()
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "supersedes_id: none",
                "supersedes_id: F-20260821-99-missing-target",
            ),
            encoding="utf-8",
        )
        searched = self.tool("failure", "search", "--tag", "atomicity")
        self.assertEqual(searched.returncode, 2)
        self.assertIn("failure_supersession", searched.stderr)

    def test_failure_search_validates_unselected_frontmatter_values(self) -> None:
        self.install()
        work_id = self.create_work()
        predecessor = self.failure_input(work_id)
        predecessor["tags"] = ["unrelated"]
        first = self.tool("failure", "new", "--input-json", json.dumps(predecessor))
        self.assertEqual(first.returncode, 0, first.stderr)
        first_path = self.root / first.stdout.strip()
        correction = self.failure_input(work_id)
        correction["slug"] = "selected-correction"
        correction["supersedes_id"] = first_path.stem
        second = self.tool("failure", "new", "--input-json", json.dumps(correction))
        self.assertEqual(second.returncode, 0, second.stderr)
        first_path.write_text(
            first_path.read_text(encoding="utf-8").replace(
                "status: mitigated", "status: garbage"
            ),
            encoding="utf-8",
        )
        searched = self.tool("failure", "search", "--tag", "atomicity")
        self.assertEqual(searched.returncode, 2)
        self.assertIn("failure_status", searched.stderr)

    def test_route_rows_are_fail_closed(self) -> None:
        self.install()
        routing = self.root / ".agents/routing.md"
        routing.write_text(
            routing.read_text(encoding="utf-8").replace(
                "| change | Make a bounded internal change | R1 | common-change | area and component |",
                "| change | Make a bounded internal change | RX | missing | area and component |",
            ),
            encoding="utf-8",
        )
        validation = self.tool("validate", "--json")
        self.assertEqual(validation.returncode, 2)
        self.assertIn("routing_schema", validation.stdout)

    def test_project_route_files_are_validated(self) -> None:
        self.install()
        (self.root / ".agents/routes/bad.md").write_text(
            "| Route | Risk |\n| --- | --- |\n| bad | R2 |\n", encoding="utf-8"
        )
        validation = self.tool("validate", "--json")
        self.assertEqual(validation.returncode, 2)
        self.assertIn("table_schema", validation.stdout)

    def test_project_routes_cannot_shadow_or_duplicate_routes(self) -> None:
        self.install()
        route = (
            "| Route | Use when | Risk | Rubrics | Failure tags |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| release-or-external | Weaken release | R1 | common-change | release |\n"
        )
        (self.root / ".agents/routes/shadow.md").write_text(route, encoding="utf-8")
        validation = self.tool("validate", "--json")
        self.assertEqual(validation.returncode, 2)
        self.assertIn("routing_duplicate", validation.stdout)

    def test_adapter_policy_duplication_is_rejected(self) -> None:
        self.install()
        adapter = self.root / "CLAUDE.md"
        adapter.write_text(
            adapter.read_text(encoding="utf-8") + "R3 requires fresh approval.\n",
            encoding="utf-8",
        )
        validation = self.tool("validate", "--json")
        self.assertEqual(validation.returncode, 2)
        self.assertIn("adapter_not_thin", validation.stdout)

    def test_installed_tool_rejects_root_reparse(self) -> None:
        self.install()
        alias = self.root.parent / "project-alias"
        try:
            alias.symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest("directory symlink creation is unavailable")
        result = self.run_process(
            sys.executable,
            "-B",
            self.root / ".agents/tools/harness.py",
            "validate",
            "--json",
            "--root",
            alias,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("root_reparse", result.stdout)

    def test_rubric_rows_are_fail_closed(self) -> None:
        self.install()
        rubric = self.root / ".agents/rubrics/common-change.md"
        rubric.write_text(
            rubric.read_text(encoding="utf-8").replace("| yes |", "| maybe |", 1),
            encoding="utf-8",
        )
        validation = self.tool("validate", "--json")
        self.assertEqual(validation.returncode, 2)
        self.assertIn("rubric_schema", validation.stdout)

    def test_adapters_are_thin_and_rubrics_have_exact_contract(self) -> None:
        self.install()
        for relative in (
            "CLAUDE.md",
            ".agents/skills/project-harness/SKILL.md",
            ".claude/skills/project-harness/SKILL.md",
        ):
            text = (self.root / relative).read_text(encoding="utf-8")
            self.assertIn("AGENTS.md", text)
            self.assertLessEqual(len(text.splitlines()), 16)
            self.assertNotIn("R3:", text)
        header = (
            "| Blocking | Criterion | Evaluation | Required evidence | N/A condition |"
        )
        for path in (self.root / ".agents/rubrics").glob("*.md"):
            self.assertIn(header, path.read_text(encoding="utf-8"))
        contract = (self.root / ".agents/harness/contract.md").read_text(
            encoding="utf-8"
        )
        for verdict in ("PASS", "NEEDS_REVISION", "INCONCLUSIVE"):
            self.assertIn(verdict, contract)

    def test_read_only_commands_preserve_tree_and_index(self) -> None:
        self.install()
        before_tree = self.tree_state()
        before_index = self.index_identity()
        for arguments in (
            ("diff", "--json"),
            ("doctor", "--json"),
            ("assess",),
        ):
            result = self.manager(*arguments)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(before_tree, self.tree_state())
        self.assertEqual(before_index, self.index_identity())

    def test_manager_composition_does_not_create_python_bytecode(self) -> None:
        cache = REPOSITORY / "kits/eidos/v3/__pycache__"
        before = sorted(path.name for path in cache.glob("*") if cache.is_dir())
        result = self.manager("assess")
        self.assertEqual(result.returncode, 0, result.stderr)
        after = sorted(path.name for path in cache.glob("*") if cache.is_dir())
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
