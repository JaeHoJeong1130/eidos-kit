from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPOSITORY = Path(__file__).resolve().parents[1]
KIT = REPOSITORY / "kits" / "eidos" / "v3" / "eidos_kit.py"


class EidosV3Test(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "project"
        self.root.mkdir()
        self.git("init")
        self.git("config", "user.name", "Eidos Test")
        self.git("config", "user.email", "eidos@example.invalid")
        self.git("commit", "--allow-empty", "-m", "initial")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_process(
        self, *arguments: object, check: bool = False
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [str(argument) for argument in arguments],
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if check and result.returncode != 0:
            self.fail(
                f"command failed: {arguments}\nstdout={result.stdout}\nstderr={result.stderr}"
            )
        return result

    def git(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return self.run_process("git", *arguments, check=True)

    def git_at(
        self, root: Path, *arguments: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        return self.run_process("git", "-C", root, *arguments, check=check)

    def kit(
        self, *arguments: str, check: bool = False
    ) -> subprocess.CompletedProcess[str]:
        return self.run_process(
            sys.executable, KIT, *arguments, "--root", self.root, check=check
        )

    def eidos(
        self, *arguments: str, check: bool = False
    ) -> subprocess.CompletedProcess[str]:
        return self.eidos_at(self.root, *arguments, check=check)

    def eidos_at(
        self, root: Path, *arguments: str, check: bool = False
    ) -> subprocess.CompletedProcess[str]:
        tool = root / ".agents/tools/eidos.py"
        return self.run_process(
            sys.executable, tool, *arguments, "--root", root, check=check
        )

    def index_identity(self, root: Path) -> tuple[bool, str | None, int | None]:
        raw = self.git_at(root, "rev-parse", "--git-path", "index").stdout.strip()
        path = Path(raw)
        if not path.is_absolute():
            path = root / path
        if not path.is_file():
            return False, None, None
        stat_result = path.stat()
        return (
            True,
            hashlib.sha256(path.read_bytes()).hexdigest(),
            stat_result.st_mtime_ns,
        )

    def install(self) -> None:
        self.kit(
            "install",
            "--project-id",
            "project:test-project",
            "--project-name",
            "Test Project",
            check=True,
        )
        (self.root / ".agents/eidos/identity.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "configured",
                    "members": [
                        {"id": "member:a", "display_name": "A", "status": "active"}
                    ],
                    "aliases": [],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )

    def install_identity_h_and_aliases(self, path: Path | None = None) -> None:
        target = path or self.root / ".agents/eidos/identity.json"
        target.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "configured",
                    "members": [
                        {"id": "member:h", "display_name": "H", "status": "active"}
                    ],
                    "aliases": [{"from": "member:a", "to": "member:h"}],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )

    def load_kit_module(self):
        name = f"_eidos_kit_test_{id(self)}"
        spec = importlib.util.spec_from_file_location(name, KIT)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        self.addCleanup(sys.modules.pop, name, None)
        spec.loader.exec_module(module)
        return module

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

    def create_work(
        self,
        *,
        slug: str = "first-work",
        owner: str = "member:a",
        workstream: str = "workstream:platform",
        scope: str = "src/platform",
        start: bool = False,
    ) -> Path:
        arguments = [
            "new-work",
            "--slug",
            slug,
            "--stage",
            "S01",
            "--title",
            slug.replace("-", " ").title(),
            "--owner",
            owner,
            "--workstream",
            workstream,
            "--write-scope",
            scope,
        ]
        if start:
            arguments.append("--start")
        result = self.eidos(*arguments, check=True)
        return self.root / result.stdout.strip()

    def close_work(self, path: Path) -> None:
        text = path.read_text(encoding="utf-8")
        created = re.search(r"(?m)^created_at:\s*(\S+)$", text)
        self.assertIsNotNone(created)
        timestamp = created.group(1)
        text = text.replace("status: planned", "status: done")
        text = text.replace("started_at: none", f"started_at: {timestamp}")
        text = text.replace("closed_at: none", f"closed_at: {timestamp}")
        text = text.replace("## Result\n\npending", "## Result\n\ncompleted")
        text = text.replace("## Evidence\n\npending", "## Evidence\n\n- test: passed")
        path.write_text(text, encoding="utf-8", newline="\n")

    def json_stdout(
        self, result: subprocess.CompletedProcess[str]
    ) -> dict[str, object]:
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            self.fail(
                f"invalid JSON output: {result.stdout}\nstderr={result.stderr}\n{exc}"
            )
        self.assertIsInstance(value, dict)
        return value

    def test_install_has_stable_v3_direction_without_manual_focus(self) -> None:
        self.install()
        direction = (self.root / ".agents/eidos/direction.md").read_text(
            encoding="utf-8"
        )
        headings = re.findall(r"^## (.+)$", direction, flags=re.MULTILINE)
        self.assertEqual(
            headings,
            ["Purpose", "Boundaries", "Baseline", "Stages", "Gates", "Dependencies"],
        )
        self.assertNotIn("Current Focus", direction)
        self.assertIn("project_id: project:test-project", direction)
        self.assertIn("# Test Project Direction", direction)
        validation = self.eidos("validate", "--json")
        self.assertEqual(
            validation.returncode, 0, validation.stdout + validation.stderr
        )
        self.assertTrue(self.json_stdout(validation)["ok"])

    def test_identity_registry_blocks_unconfigured_and_nonhuman_new_owners(
        self,
    ) -> None:
        self.install()
        identity_path = self.root / ".agents/eidos/identity.json"
        identity_path.write_text(
            '{\n  "schema_version": 1,\n  "status": "unconfigured",\n  "members": [],\n  "aliases": []\n}\n',
            encoding="utf-8",
            newline="\n",
        )
        blocked = self.eidos(
            "new-work",
            "--slug",
            "blocked-owner",
            "--stage",
            "S01",
            "--title",
            "Blocked Owner",
            "--owner",
            "member:a",
            "--write-scope",
            "src/blocked",
        )
        self.assertEqual(2, blocked.returncode)
        self.assertIn("identity_unconfigured", blocked.stderr)

        self.install_identity_h_and_aliases(identity_path)
        for owner in ("agent:root", "member:a", "member:unknown"):
            rejected = self.eidos(
                "new-work",
                "--slug",
                f"rejected-{owner.split(':')[1]}",
                "--stage",
                "S01",
                "--title",
                "Rejected Owner",
                "--owner",
                owner,
                "--write-scope",
                "src/rejected",
            )
            self.assertEqual(2, rejected.returncode)
            self.assertIn("active canonical member", rejected.stderr)

    def test_catalog_exposes_canonical_owner_without_rewriting_history(self) -> None:
        self.install()
        work = self.create_work()
        self.install_identity_h_and_aliases()
        result = self.eidos("catalog", "--owner", "member:h", "--json", check=True)
        item = self.json_stdout(result)["data"]["items"][work.stem]
        self.assertEqual("member:a", item["owner_id"])
        self.assertEqual("member:h", item["canonical_owner_id"])

        identity_path = self.root / ".agents/eidos/identity.json"
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
        identity["aliases"] = [{"from": "agent:root", "to": "member:h"}]
        identity_path.write_text(
            json.dumps(identity, indent=2) + "\n", encoding="utf-8"
        )
        rejected = self.json_stdout(self.eidos("validate", "--json"))
        self.assertIn(
            "identity_alias",
            {finding["code"] for finding in rejected["error"]["findings"]},
        )

    def test_install_rejects_agents_symlink_outside_repository(self) -> None:
        outside = self.root.parent / "outside-agents"
        outside.mkdir()
        agents = self.root / ".agents"
        try:
            agents.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("directory symlink creation is unavailable")
        result = self.kit(
            "install",
            "--project-id",
            "project:test-project",
            "--project-name",
            "Test Project",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("path_reparse", result.stderr)
        self.assertEqual(list(outside.iterdir()), [])

    def test_upgrade_rejects_agents_symlink_and_invalid_context_paths(self) -> None:
        self.install()
        context_path = self.root / ".agents/context.json"
        context = json.loads(context_path.read_text(encoding="utf-8"))
        context["eidos"]["work_root"] = "../outside-work"
        context_path.write_text(json.dumps(context, indent=2) + "\n", encoding="utf-8")
        validation = self.json_stdout(self.eidos("validate", "--json"))
        self.assertIn(
            "context_path",
            {item["code"] for item in validation["error"]["findings"]},
        )
        before = self.tree_state()
        invalid = self.kit("upgrade")
        self.assertEqual(invalid.returncode, 2)
        self.assertIn("context_path", invalid.stderr)
        self.assertEqual(before, self.tree_state())

        context["eidos"]["work_root"] = ".agents/eidos/work"
        context_path.write_text(json.dumps(context, indent=2) + "\n", encoding="utf-8")
        outside = self.root.parent / "installed-agents"
        shutil.move(str(self.root / ".agents"), outside)
        try:
            (self.root / ".agents").symlink_to(outside, target_is_directory=True)
        except OSError:
            shutil.move(str(outside), self.root / ".agents")
            self.skipTest("directory symlink creation is unavailable")
        outside_before = {
            path.relative_to(outside).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in outside.rglob("*")
            if path.is_file()
        }
        linked = self.kit("upgrade")
        self.assertEqual(linked.returncode, 2)
        self.assertIn("path_reparse", linked.stderr)
        self.assertEqual(
            outside_before,
            {
                path.relative_to(outside).as_posix(): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in outside.rglob("*")
                if path.is_file()
            },
        )

    def test_install_fault_rolls_back_every_file_and_created_directory(self) -> None:
        module = self.load_kit_module()
        arguments = module.argparse.Namespace(
            root=self.root,
            project_id="project:test-project",
            project_name="Test Project",
        )
        before = self.tree_state()
        original = module._write_exclusive
        calls = 0

        def fail_after_write(path, data):
            nonlocal calls
            original(path, data)
            calls += 1
            if calls == 3:
                raise OSError("fault after third install write")

        with mock.patch.object(
            module, "_write_exclusive", side_effect=fail_after_write
        ):
            with self.assertRaises(OSError):
                module._command_install(arguments)
        self.assertEqual(before, self.tree_state())
        self.assertFalse((self.root / ".agents").exists())

    def write_unmanaged_context(self) -> Path:
        path = self.root / ".agents/context.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "project": {
                        "id": "ald_sensor_timeseries",
                        "name": "Old Name",
                        "repository_contract": {"domain_routes": True},
                    },
                    "routing": {"catalog": ".agents/routes.json"},
                    "knowledge": {"memory": ".agents/memory"},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return path

    def migrate(self, *, check: bool = True) -> subprocess.CompletedProcess[str]:
        return self.kit(
            "migrate",
            "--project-id",
            "project:ald-sensor-timeseries",
            "--project-name",
            "ALD Sensor Timeseries",
            check=check,
        )

    def test_migrate_preserves_extended_context_and_installs_valid_eidos(self) -> None:
        context_path = self.write_unmanaged_context()
        context_path.chmod(0o600)
        context_mode = context_path.stat().st_mode
        before_index = self.index_identity(self.root)
        result = self.migrate()
        self.assertIn("Migrated existing context", result.stdout)
        self.assertEqual(before_index, self.index_identity(self.root))
        context = json.loads(
            (self.root / ".agents/context.json").read_text(encoding="utf-8")
        )
        self.assertEqual(context["project"]["id"], "project:ald-sensor-timeseries")
        self.assertEqual(context["project"]["name"], "ALD Sensor Timeseries")
        self.assertEqual(
            context["project"]["repository_contract"], {"domain_routes": True}
        )
        self.assertEqual(context["routing"], {"catalog": ".agents/routes.json"})
        self.assertEqual(context["knowledge"], {"memory": ".agents/memory"})
        self.assertEqual(context["eidos"]["version"], 3)
        manifest = json.loads(
            (self.root / ".agents/eidos/kit-manifest.json").read_text(encoding="utf-8")
        )
        context_entry = manifest["files"][".agents/context.json"]
        self.assertEqual(context_entry["ownership"], "project")
        self.assertEqual(
            context_entry["sha256"],
            hashlib.sha256(
                (self.root / ".agents/context.json").read_bytes()
            ).hexdigest(),
        )
        self.assertEqual(self.eidos("validate", "--json").returncode, 0)
        self.assertEqual(self.eidos("focus", "--json").returncode, 0)
        self.assertEqual(self.kit("doctor", "--json").returncode, 0)
        self.assertEqual(context_path.stat().st_mode, context_mode)

    def test_migrate_rejects_existing_contract_and_path_collision_without_mutation(
        self,
    ) -> None:
        context_path = self.write_unmanaged_context()
        context = json.loads(context_path.read_text(encoding="utf-8"))
        context["eidos"] = {"version": 3}
        context_path.write_text(json.dumps(context, indent=2) + "\n", encoding="utf-8")
        before = self.tree_state()
        managed = self.migrate(check=False)
        self.assertEqual(managed.returncode, 2)
        self.assertIn("already_managed", managed.stderr)
        self.assertEqual(before, self.tree_state())

        context.pop("eidos")
        context_path.write_text(json.dumps(context, indent=2) + "\n", encoding="utf-8")
        collision = self.root / ".agents/tools/eidos.py"
        collision.parent.mkdir(parents=True, exist_ok=True)
        collision.write_text("existing\n", encoding="utf-8")
        before = self.tree_state()
        collided = self.migrate(check=False)
        self.assertEqual(collided.returncode, 2)
        self.assertIn("target_exists", collided.stderr)
        self.assertEqual(before, self.tree_state())

    def test_migrate_fault_restores_context_tree_and_index(self) -> None:
        self.write_unmanaged_context()
        module = self.load_kit_module()
        arguments = module.argparse.Namespace(
            root=self.root,
            project_id="project:ald-sensor-timeseries",
            project_name="ALD Sensor Timeseries",
        )
        before_tree = self.tree_state()
        before_index = self.index_identity(self.root)
        original = module._write_exclusive
        calls = 0

        def fail_after_write(path, data, on_created=None):
            nonlocal calls
            original(path, data, on_created)
            calls += 1
            if calls == 3:
                raise OSError("migration fault")

        with mock.patch.object(
            module, "_write_exclusive", side_effect=fail_after_write
        ):
            with self.assertRaises(OSError):
                module._command_migrate(arguments)
        self.assertEqual(before_tree, self.tree_state())
        self.assertEqual(before_index, self.index_identity(self.root))

    def test_migrate_partial_exclusive_write_is_fully_rolled_back(self) -> None:
        self.write_unmanaged_context()
        module = self.load_kit_module()
        arguments = module.argparse.Namespace(
            root=self.root,
            project_id="project:ald-sensor-timeseries",
            project_name="ALD Sensor Timeseries",
        )
        before_tree = self.tree_state()
        before_index = self.index_identity(self.root)
        calls = 0

        def partial_write(path, data, on_created=None):
            nonlocal calls
            calls += 1
            if calls != 1:
                return module._write_exclusive(path, data, on_created)
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            created_stat = os.fstat(descriptor)
            if on_created is not None:
                on_created((created_stat.st_dev, created_stat.st_ino))
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data[:7])
            raise OSError("partial migration write")

        with mock.patch.object(module, "_write_exclusive", side_effect=partial_write):
            with self.assertRaises(OSError):
                module._command_migrate(arguments)
        self.assertEqual(before_tree, self.tree_state())
        self.assertEqual(before_index, self.index_identity(self.root))

    def test_guarded_context_replace_preserves_zero_mode_when_supported(self) -> None:
        context = self.write_unmanaged_context()
        context.chmod(0o000)
        mode = stat.S_IMODE(context.stat().st_mode)
        if mode != 0:
            context.chmod(0o644)
            self.skipTest("zero file mode is not represented on this platform")
        module = self.load_kit_module()
        original = context.read_bytes()
        snapshot = module._FileSnapshot(True, original, mode)
        module._replace_guarded(context, b"replacement\n", snapshot)
        self.assertEqual(stat.S_IMODE(context.stat().st_mode), mode)
        context.chmod(0o644)
        self.assertEqual(context.read_bytes(), b"replacement\n")

    def test_migrate_detects_concurrent_context_edit_without_clobbering_it(
        self,
    ) -> None:
        context_path = self.write_unmanaged_context()
        module = self.load_kit_module()
        arguments = module.argparse.Namespace(
            root=self.root,
            project_id="project:ald-sensor-timeseries",
            project_name="ALD Sensor Timeseries",
        )
        original = module._replace_guarded
        concurrent = b'{"schema_version": 2, "project": {"id": "concurrent"}}\n'

        def edit_then_replace(path, data, expected):
            context_path.write_bytes(concurrent)
            return original(path, data, expected)

        with mock.patch.object(
            module, "_replace_guarded", side_effect=edit_then_replace
        ):
            with self.assertRaises(module.KitError) as raised:
                module._command_migrate(arguments)
        self.assertEqual(raised.exception.code, "concurrent_modification")
        self.assertEqual(context_path.read_bytes(), concurrent)
        self.assertFalse((self.root / ".agents/eidos").exists())
        self.assertFalse((self.root / ".agents/tools/eidos.py").exists())

    def test_migrate_rejects_invalid_context_before_writing(self) -> None:
        context = self.write_unmanaged_context()
        value = json.loads(context.read_text(encoding="utf-8"))
        value["schema_version"] = 1
        context.write_text(json.dumps(value) + "\n", encoding="utf-8")
        before = self.tree_state()
        result = self.migrate(check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("context_invalid", result.stderr)
        self.assertEqual(before, self.tree_state())

    def test_v3_upgrade_manifest_fault_restores_all_files_and_modes(self) -> None:
        self.install()
        module = self.load_kit_module()
        arguments = module.argparse.Namespace(root=self.root)
        before = self.tree_state()
        original_render = module._rendered_files
        original_replace = module._replace

        def changed_render(project_id, project_name):
            rendered = original_render(project_id, project_name)
            for relative in rendered:
                if relative not in module.USER_OWNED:
                    rendered[relative] += b"\nupgrade candidate\n"
            return rendered

        def fail_after_manifest(path, data):
            original_replace(path, data)
            if path == self.root / module.MANIFEST_PATH:
                raise OSError("fault after manifest replacement")

        with mock.patch.object(module, "_rendered_files", side_effect=changed_render):
            with mock.patch.object(module, "_replace", side_effect=fail_after_manifest):
                with self.assertRaises(OSError):
                    module._command_upgrade(arguments)
        self.assertEqual(before, self.tree_state())

    def test_new_work_uses_v3_execution_axes_and_no_planner_link(self) -> None:
        self.install()
        work = self.create_work(start=True)
        text = work.read_text(encoding="utf-8")
        self.assertIn("eidos_version: 3", text)
        self.assertIn("owner_id: member:a", text)
        self.assertIn("workstream_id: workstream:platform", text)
        self.assertIn("parent_work_id: none", text)
        self.assertIn("depends_on: none", text)
        self.assertIn("write_scope: src/platform", text)
        self.assertIn("risk: R1", text)
        self.assertNotIn("planner_work_id", text)
        metadata = dict(
            line.split(":", 1)
            for line in text.split("---", 2)[1].splitlines()
            if ":" in line
        )
        for field in ("created_at", "started_at", "updated_at", "closed_at"):
            self.assertIn(field, metadata)
        self.assertEqual(
            metadata[" status"].strip()
            if " status" in metadata
            else metadata["status"].strip(),
            "in_progress",
        )

    def test_every_real_work_requires_an_explicit_assigned_owner(self) -> None:
        self.install()
        before = self.tree_state()
        omitted = self.eidos(
            "new-work",
            "--slug",
            "owner-omitted",
            "--stage",
            "S01",
            "--title",
            "Owner Omitted",
            "--write-scope",
            "src",
        )
        self.assertEqual(omitted.returncode, 2)
        self.assertIn("--owner", omitted.stderr)
        self.assertEqual(before, self.tree_state())

        for start in (False, True):
            arguments = [
                "new-work",
                "--slug",
                "owner-unassigned",
                "--stage",
                "S01",
                "--title",
                "Owner Unassigned",
                "--owner",
                "unassigned",
                "--write-scope",
                "src",
            ]
            if start:
                arguments.append("--start")
            unassigned = self.eidos(*arguments)
            self.assertEqual(unassigned.returncode, 2)
            self.assertIn("owner_required", unassigned.stderr)
            self.assertEqual(before, self.tree_state())

        work = self.create_work(slug="manual-owner-edit")
        work.write_text(
            work.read_text(encoding="utf-8").replace(
                "owner_id: member:a", "owner_id: unassigned"
            ),
            encoding="utf-8",
            newline="\n",
        )
        validation = self.eidos("validate", "--json")
        self.assertEqual(validation.returncode, 2)
        payload = self.json_stdout(validation)
        self.assertFalse(payload["ok"])
        self.assertIn(
            "owner_required",
            {item["code"] for item in payload["error"]["findings"]},
        )

    def test_direction_rejects_duplicate_and_reordered_sections(self) -> None:
        self.install()
        direction = self.root / ".agents/eidos/direction.md"
        original = direction.read_text(encoding="utf-8")
        direction.write_text(
            original + "\n## Purpose\n\nduplicate\n",
            encoding="utf-8",
            newline="\n",
        )
        duplicate = self.json_stdout(self.eidos("validate", "--json"))
        duplicate_codes = {item["code"] for item in duplicate["error"]["findings"]}
        self.assertIn("direction_section_duplicate", duplicate_codes)
        self.assertIn("direction_section_order", duplicate_codes)

        reordered = original.replace("## Purpose", "## __TEMP__", 1)
        reordered = reordered.replace("## Boundaries", "## Purpose", 1)
        reordered = reordered.replace("## __TEMP__", "## Boundaries", 1)
        direction.write_text(reordered, encoding="utf-8", newline="\n")
        result = self.json_stdout(self.eidos("validate", "--json"))
        codes = {item["code"] for item in result["error"]["findings"]}
        self.assertIn("direction_section_order", codes)
        self.assertNotIn("direction_section_duplicate", codes)

    def test_focus_and_catalog_are_derived_and_read_only(self) -> None:
        self.install()
        active = self.create_work(slug="active-work", start=True)
        planned = self.create_work(slug="planned-work")
        before = self.tree_hash()
        focus = self.json_stdout(self.eidos("focus", "--json", check=True))["data"]
        catalog = self.json_stdout(self.eidos("catalog", "--json", check=True))["data"]
        after = self.tree_hash()
        self.assertEqual(before, after)
        self.assertEqual(
            [item["work_id"] for item in focus["active_work"]], [active.stem]
        )
        self.assertEqual(
            [item["work_id"] for item in focus["planned_work"]], [planned.stem]
        )
        self.assertEqual(focus["remote_activity"], "unknown")
        self.assertEqual(set(catalog["items"]), {active.stem, planned.stem})
        self.assertNotIn("planner_work_id", catalog["items"][active.stem])

    def tree_hash(self) -> str:
        digest = hashlib.sha256()
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or ".git" in path.parts:
                continue
            digest.update(path.relative_to(self.root).as_posix().encode())
            digest.update(path.read_bytes())
        return digest.hexdigest()

    def legacy_direction(self, revision: str = "D0001") -> str:
        return f"""---
eidos_version: 2
document_type: direction
project_id: project:test-project
revision: {revision}
updated_at: 2026-08-19
---

# Legacy Direction

## Purpose

Keep the verified purpose.

## Boundaries

- Included scope: test

## Baseline

Legacy baseline.

## Stages

### S01 — Legacy stage

- Status: active
- Outcome: Legacy outcome.
- Gate: Legacy gate is satisfied.
- Depends on: none

## Current Focus

This prose must not enter v3.

## Dependencies

none

## Decisions Needed

none
"""

    def legacy_work(self, *, status: str = "done") -> str:
        day = "2026-08-19"
        started = f"{day}T10:01:00+09:00" if status != "planned" else "none"
        closed = (
            f"{day}T10:02:00+09:00"
            if status in {"done", "failed", "cancelled"}
            else "none"
        )
        return f"""---
eidos_version: 2
document_type: work
project_id: project:test-project
work_id: W-20260819-01-legacy-work
planner_work_id: work:0045
direction_revision: D0001
stage_id: S01
owner_id: member:a
status: {status}
risk: R2
created_at: {day}T10:00:00+09:00
started_at: {started}
updated_at: {day}T10:02:00+09:00
closed_at: {closed}
---

# Legacy Work

## Intent

Legacy intent.

## Plan

- Completion criteria: legacy

## Progress

- {day}T10:00:00+09:00 — Created.
- {day}T10:02:00+09:00 — Recorded the result.

## Result

Legacy result.

## Evidence

- legacy: passed

## Deviation and Next

- Plan deviation: none
"""

    def test_reader_accepts_unchanged_v2_archive_and_closed_work(self) -> None:
        self.install()
        archive = self.root / ".agents/eidos/archive/D0001.md"
        legacy = self.legacy_direction()
        archive.write_text(legacy, encoding="utf-8", newline="\n")
        direction = self.root / ".agents/eidos/direction.md"
        current = direction.read_text(encoding="utf-8").replace(
            "revision: D0001", "revision: D0002"
        )
        direction.write_text(current, encoding="utf-8", newline="\n")
        work = self.root / ".agents/eidos/work/W-20260819-01-legacy-work.md"
        work.write_text(self.legacy_work(), encoding="utf-8", newline="\n")
        before = (
            hashlib.sha256(archive.read_bytes()).hexdigest(),
            hashlib.sha256(work.read_bytes()).hexdigest(),
        )
        result = self.eidos("validate", "--json")
        after = (
            hashlib.sha256(archive.read_bytes()).hexdigest(),
            hashlib.sha256(work.read_bytes()).hexdigest(),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(before, after)
        item = self.json_stdout(self.eidos("catalog", "--json", check=True))["data"][
            "items"
        ][work.stem]
        self.assertEqual(item["eidos_version"], 2)
        self.assertIsNone(item["workstream_id"])

    def test_legacy_open_work_and_v3_current_focus_are_rejected(self) -> None:
        self.install()
        archive = self.root / ".agents/eidos/archive/D0001.md"
        archive.write_text(self.legacy_direction(), encoding="utf-8", newline="\n")
        direction = self.root / ".agents/eidos/direction.md"
        direction.write_text(
            direction.read_text(encoding="utf-8").replace(
                "revision: D0001", "revision: D0002"
            )
            + "\n## Current Focus\n\nForbidden.\n",
            encoding="utf-8",
            newline="\n",
        )
        work = self.root / ".agents/eidos/work/W-20260819-01-legacy-work.md"
        work.write_text(
            self.legacy_work(status="in_progress"), encoding="utf-8", newline="\n"
        )
        result = self.json_stdout(self.eidos("validate", "--json"))
        codes = {item["code"] for item in result["error"]["findings"]}
        self.assertIn("legacy_open_work", codes)
        self.assertIn("current_focus_forbidden", codes)

    def test_work_documents_must_remain_flat(self) -> None:
        self.install()
        work = self.create_work()
        nested = work.parent / "nested" / work.name
        nested.parent.mkdir()
        shutil.move(work, nested)
        result = self.json_stdout(self.eidos("validate", "--json"))
        codes = {item["code"] for item in result["error"]["findings"]}
        self.assertIn("work_not_flat", codes)

    def test_claim_lifecycle_conflict_release_and_no_cleanup(self) -> None:
        self.install()
        first = self.create_work(slug="claim-one", scope="src")
        second = self.create_work(slug="claim-two", scope="src/platform")
        acquired = self.json_stdout(
            self.eidos(
                "claim",
                "acquire",
                "--work-id",
                first.stem,
                "--actor",
                "agent:first",
                "--json",
                check=True,
            )
        )
        self.assertEqual(3, acquired["schema_version"])
        self.assertEqual("member:a", acquired["member_id"])
        self.assertEqual("member:a", acquired["origin"]["member_id"])
        claim_id = acquired["claim_id"]
        conflict = self.eidos(
            "claim",
            "acquire",
            "--work-id",
            second.stem,
            "--actor",
            "agent:second",
            "--json",
        )
        self.assertEqual(conflict.returncode, 2)
        self.assertIn("claim_conflict", conflict.stderr)
        renewed = self.eidos(
            "claim",
            "renew",
            "--claim-id",
            claim_id,
            "--actor",
            "agent:first",
            "--json",
        )
        self.assertEqual(renewed.returncode, 0, renewed.stderr)
        released = self.eidos(
            "claim",
            "release",
            "--claim-id",
            claim_id,
            "--actor",
            "agent:first",
            "--json",
        )
        self.assertEqual(released.returncode, 0, released.stderr)
        focus_after_release = self.json_stdout(
            self.eidos("focus", "--json", check=True)
        )["data"]
        self.assertEqual(focus_after_release["claims"], [])
        listing_after_release = self.json_stdout(
            self.eidos("claim", "list", "--json", check=True)
        )
        self.assertEqual(len(listing_after_release["claims"]), 1)
        common_raw = self.git("rev-parse", "--git-common-dir").stdout.strip()
        common = (
            Path(common_raw)
            if Path(common_raw).is_absolute()
            else self.root / common_raw
        )
        claim_path = common.resolve() / "eidos" / "claims" / f"{claim_id}.json"
        self.assertTrue(claim_path.is_file())
        adopted = self.eidos(
            "claim",
            "adopt",
            "--claim-id",
            claim_id,
            "--actor",
            "agent:second",
            "--json",
        )
        self.assertEqual(adopted.returncode, 0, adopted.stderr)
        payload = self.json_stdout(adopted)
        self.assertEqual(payload["actor_id"], "agent:second")
        self.assertEqual(payload["history"][0]["actor_id"], "agent:first")
        self.assertTrue(claim_path.is_file())

    def test_cross_worktree_adopt_retains_origin_dirty_and_unknown_state(self) -> None:
        self.install()
        work = self.create_work(slug="adopt-provenance", scope="scope-adopt")
        self.git("add", ".agents")
        self.git("commit", "-m", "install adopt provenance fixture")
        origin_root = self.root.parent / "origin-worktree"
        self.git("worktree", "add", "-b", "origin-adopt", str(origin_root))
        try:
            acquired = self.json_stdout(
                self.eidos_at(
                    origin_root,
                    "claim",
                    "acquire",
                    "--work-id",
                    work.stem,
                    "--actor",
                    "agent:origin",
                    "--json",
                    check=True,
                )
            )
            self.eidos_at(
                origin_root,
                "claim",
                "release",
                "--claim-id",
                acquired["claim_id"],
                "--actor",
                "agent:origin",
                check=True,
            )
            origin_dirty = origin_root / "scope-adopt/origin.py"
            origin_dirty.parent.mkdir()
            origin_dirty.write_text(
                "value = 'origin'\n", encoding="utf-8", newline="\n"
            )
            adopted = self.json_stdout(
                self.eidos(
                    "claim",
                    "adopt",
                    "--claim-id",
                    acquired["claim_id"],
                    "--actor",
                    "agent:current",
                    "--json",
                    check=True,
                )
            )
            self.assertEqual(adopted["schema_version"], 3)
            self.assertEqual(adopted["member_id"], "member:a")
            self.assertEqual(adopted["history"][0]["member_id"], "member:a")
            self.assertEqual(adopted["origin"]["worktree_id"], acquired["worktree_id"])
            self.assertEqual(
                adopted["history"][0]["worktree_id"], acquired["worktree_id"]
            )
            self.assertNotEqual(adopted["worktree_id"], acquired["worktree_id"])

            listing = self.json_stdout(
                self.eidos("claim", "list", "--json", check=True)
            )
            claim = listing["claims"][0]
            states = {item["worktree_id"]: item for item in claim["worktree_states"]}
            origin = states[acquired["worktree_id"]]
            current = states[adopted["worktree_id"]]
            self.assertIs(origin["origin"], True)
            self.assertIs(origin["custody_retired"], True)
            self.assertEqual(origin["dirty_state"], "dirty")
            self.assertIs(origin["orphaned_dirty"], True)
            self.assertIs(current["current"], True)
            self.assertEqual(current["dirty_state"], "clean")
            self.assertIs(current["orphaned_dirty"], False)
            self.assertEqual(claim["dirty_state"], "dirty")
            self.assertIs(claim["orphaned_dirty"], True)
            serialized = json.dumps(listing, ensure_ascii=False)
            self.assertNotIn(str(self.root), serialized)
            self.assertNotIn(str(origin_root), serialized)

            removed = self.git_at(
                self.root,
                "worktree",
                "remove",
                "--force",
                str(origin_root),
                check=False,
            )
            self.assertEqual(removed.returncode, 0, removed.stderr)
            unavailable = self.json_stdout(
                self.eidos("claim", "list", "--json", check=True)
            )["claims"][0]
            unavailable_states = {
                item["worktree_id"]: item for item in unavailable["worktree_states"]
            }
            self.assertEqual(
                unavailable_states[acquired["worktree_id"]]["availability"],
                "unknown",
            )
            self.assertEqual(unavailable["dirty_state"], "unknown")
            self.assertEqual(unavailable["orphaned_dirty"], "unknown")

            common_raw = self.git("rev-parse", "--git-common-dir").stdout.strip()
            common = Path(common_raw)
            if not common.is_absolute():
                common = self.root / common
            claim_path = (
                common.resolve() / "eidos" / "claims" / f"{acquired['claim_id']}.json"
            )
            malformed = json.loads(claim_path.read_text(encoding="utf-8"))
            malformed["origin"]["worktree_id"] = f"worktree-{'0' * 32}"
            malformed["origin"]["worktree_root_ref"] = f"git-common:worktree-{'0' * 32}"
            claim_path.write_text(
                json.dumps(malformed, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            invalid = self.eidos("claim", "list", "--json")
            self.assertEqual(invalid.returncode, 2)
            invalid_payload = self.json_stdout(invalid)
            self.assertIn(
                "claim_schema",
                {item["code"] for item in invalid_payload["findings"]},
            )
        finally:
            if origin_root.exists():
                self.git_at(
                    self.root,
                    "worktree",
                    "remove",
                    "--force",
                    str(origin_root),
                    check=False,
                )

    def test_unexpired_claim_cannot_be_adopted(self) -> None:
        self.install()
        work = self.create_work()
        claim = self.json_stdout(
            self.eidos(
                "claim",
                "acquire",
                "--work-id",
                work.stem,
                "--actor",
                "agent:first",
                "--json",
                check=True,
            )
        )
        result = self.eidos(
            "claim",
            "adopt",
            "--claim-id",
            claim["claim_id"],
            "--actor",
            "agent:second",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("claim_not_adoptable", result.stderr)

    def test_claim_cannot_expand_the_durable_work_scope(self) -> None:
        self.install()
        work = self.create_work(scope="src/platform")
        result = self.eidos(
            "claim",
            "acquire",
            "--work-id",
            work.stem,
            "--actor",
            "agent:first",
            "--path",
            "src",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("claim_scope_expansion", result.stderr)

    def test_claim_scopes_normalize_aliases_with_repository_case_semantics(
        self,
    ) -> None:
        self.git("config", "core.ignorecase", "true")
        self.install()
        first = self.create_work(slug="scope-lower", scope="src/platform")
        second = self.create_work(slug="scope-upper", scope=r"SRC\.\platform//child")
        self.assertIn(
            "write_scope: SRC/platform/child",
            second.read_text(encoding="utf-8"),
        )
        acquired = self.json_stdout(
            self.eidos(
                "claim",
                "acquire",
                "--work-id",
                first.stem,
                "--actor",
                "agent:lower",
                "--path",
                r"src\.\platform",
                "--json",
                check=True,
            )
        )
        self.assertEqual(acquired["paths"], ["src/platform"])
        conflict = self.eidos(
            "claim",
            "acquire",
            "--work-id",
            second.stem,
            "--actor",
            "agent:upper",
            "--path",
            r"SRC\.\platform\child",
        )
        self.assertEqual(conflict.returncode, 2)
        self.assertIn("claim_conflict", conflict.stderr)
        traversal = self.eidos(
            "claim",
            "acquire",
            "--work-id",
            second.stem,
            "--actor",
            "agent:upper",
            "--path",
            "SRC/../platform",
        )
        self.assertEqual(traversal.returncode, 2)
        self.assertIn("claim_path", traversal.stderr)

    def test_unsafe_windows_and_git_pathspec_scopes_fail_without_index_writes(
        self,
    ) -> None:
        self.install()
        work = self.create_work(slug="literal-scope", scope="src")
        self.git("add", ".agents")
        self.git("commit", "-m", "install literal scope fixture")
        claim = self.json_stdout(
            self.eidos(
                "claim",
                "acquire",
                "--work-id",
                work.stem,
                "--actor",
                "agent:literal",
                "--json",
                check=True,
            )
        )
        unsafe = ("src.", "src ", ":(top)src", "src/[ab]")
        before_rejections = self.index_identity(self.root)
        for index, scope in enumerate(unsafe):
            rejected = self.eidos(
                "claim",
                "acquire",
                "--work-id",
                work.stem,
                "--actor",
                f"agent:unsafe-{index}",
                "--path",
                scope,
            )
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("claim_path", rejected.stderr)
        self.assertEqual(before_rejections, self.index_identity(self.root))

        common_raw = self.git("rev-parse", "--git-common-dir").stdout.strip()
        common = Path(common_raw)
        if not common.is_absolute():
            common = self.root / common
        claim_path = common.resolve() / "eidos" / "claims" / f"{claim['claim_id']}.json"
        original = json.loads(claim_path.read_text(encoding="utf-8"))
        for scope in unsafe:
            malformed = dict(original)
            malformed["paths"] = [scope]
            claim_path.write_text(
                json.dumps(malformed, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            before = self.index_identity(self.root)
            listing = self.eidos("claim", "list", "--json")
            self.assertEqual(listing.returncode, 2)
            listing_payload = self.json_stdout(listing)
            self.assertIn(
                "claim_schema",
                {item["code"] for item in listing_payload["findings"]},
            )
            focus = self.eidos("focus", "--json")
            self.assertEqual(focus.returncode, 2)
            focus_payload = self.json_stdout(focus)
            self.assertFalse(focus_payload["ok"])
            self.assertEqual(focus_payload["error"]["code"], "claim_validation_failed")
            self.assertEqual(before, self.index_identity(self.root))
        claim_path.write_text(
            json.dumps(original, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )

        tool = self.root / ".agents/tools/eidos.py"
        name = f"_eidos_literal_pathspec_test_{id(self)}"
        spec = importlib.util.spec_from_file_location(name, tool)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        self.addCleanup(sys.modules.pop, name, None)
        spec.loader.exec_module(module)
        completed = subprocess.CompletedProcess(["git"], 0, "", "")
        with mock.patch.object(module.subprocess, "run", return_value=completed) as run:
            module._run_git_result(self.root, "diff", "--quiet", "--", "src")
        environment = run.call_args.kwargs["env"]
        self.assertEqual(environment["GIT_LITERAL_PATHSPECS"], "1")
        self.assertEqual(environment["GIT_OPTIONAL_LOCKS"], "0")
        self.assertNotIn("GIT_GLOB_PATHSPECS", environment)

    def test_malformed_claim_is_a_list_and_doctor_finding_without_crash(self) -> None:
        self.install()
        work = self.create_work(scope="src")
        claim = self.json_stdout(
            self.eidos(
                "claim",
                "acquire",
                "--work-id",
                work.stem,
                "--actor",
                "agent:first",
                "--json",
                check=True,
            )
        )
        common_raw = self.git("rev-parse", "--git-common-dir").stdout.strip()
        common = (
            Path(common_raw)
            if Path(common_raw).is_absolute()
            else self.root / common_raw
        )
        claim_path = common.resolve() / "eidos" / "claims" / f"{claim['claim_id']}.json"
        malformed = json.loads(claim_path.read_text(encoding="utf-8"))
        malformed["paths"] = "src"
        claim_path.write_text(json.dumps(malformed) + "\n", encoding="utf-8")

        listing = self.eidos("claim", "list", "--json")
        self.assertEqual(listing.returncode, 2)
        payload = self.json_stdout(listing)
        self.assertEqual(payload["claims"], [])
        self.assertIn("claim_schema", {item["code"] for item in payload["findings"]})

        focus = self.eidos("focus", "--json")
        self.assertEqual(focus.returncode, 2)
        focus_payload = self.json_stdout(focus)
        self.assertFalse(focus_payload["ok"])
        self.assertEqual(focus_payload["error"]["code"], "claim_validation_failed")
        self.assertIn(
            "claim_schema",
            {item["code"] for item in focus_payload["error"]["findings"]},
        )

        doctor = self.kit("doctor", "--json")
        self.assertEqual(doctor.returncode, 2)
        doctor_payload = self.json_stdout(doctor)
        self.assertIn(
            "claim_schema",
            {item["code"] for item in doctor_payload["findings"]},
        )

    def test_released_claim_with_dirty_scope_is_reported_as_orphaned_dirty(
        self,
    ) -> None:
        self.install()
        work = self.create_work(scope="src")
        claim = self.json_stdout(
            self.eidos(
                "claim",
                "acquire",
                "--work-id",
                work.stem,
                "--actor",
                "agent:first",
                "--json",
                check=True,
            )
        )
        self.eidos(
            "claim",
            "release",
            "--claim-id",
            claim["claim_id"],
            "--actor",
            "agent:first",
            check=True,
        )
        dirty = self.root / "src" / "uncommitted.py"
        dirty.parent.mkdir()
        dirty.write_text("value = 1\n", encoding="utf-8")

        listing = self.json_stdout(self.eidos("claim", "list", "--json", check=True))
        self.assertEqual(len(listing["claims"]), 1)
        self.assertTrue(listing["claims"][0]["orphaned_dirty"])
        self.assertEqual(listing["claims"][0]["dirty_paths"], ["src"])
        doctor = self.json_stdout(self.kit("doctor", "--json", check=True))
        self.assertIn(
            "claim_orphaned_dirty",
            {item["code"] for item in doctor["findings"]},
        )

    def test_linked_worktree_claims_do_not_reattach_after_exact_name_reuse(
        self,
    ) -> None:
        self.install()
        main_work = self.create_work(slug="main-claim", scope="scope-a")
        linked_work = self.create_work(slug="linked-claim", scope="scope-b")
        self.git("add", ".agents")
        self.git("commit", "-m", "install eidos and works")
        linked = self.root.parent / "linked"
        self.git("worktree", "add", "-b", "linked-eidos", str(linked))
        original_git_dir = Path(
            self.git_at(linked, "rev-parse", "--absolute-git-dir").stdout.strip()
        )
        try:
            main_claim = self.json_stdout(
                self.eidos(
                    "claim",
                    "acquire",
                    "--work-id",
                    main_work.stem,
                    "--actor",
                    "agent:main",
                    "--json",
                    check=True,
                )
            )
            linked_claim = self.json_stdout(
                self.eidos_at(
                    linked,
                    "claim",
                    "acquire",
                    "--work-id",
                    linked_work.stem,
                    "--actor",
                    "agent:linked",
                    "--json",
                    check=True,
                )
            )
            self.assertNotEqual(main_claim["worktree_id"], linked_claim["worktree_id"])
            for claim in (main_claim, linked_claim):
                self.assertRegex(claim["worktree_id"], r"^worktree-[a-f0-9]{32}$")
                self.assertEqual(
                    claim["worktree_root_ref"],
                    f"git-common:{claim['worktree_id']}",
                )

            common_raw = self.git("rev-parse", "--git-common-dir").stdout.strip()
            common = Path(common_raw)
            if not common.is_absolute():
                common = self.root / common
            for claim in (main_claim, linked_claim):
                claim_bytes = (
                    common.resolve() / "eidos" / "claims" / f"{claim['claim_id']}.json"
                ).read_text(encoding="utf-8")
                self.assertNotIn(str(self.root), claim_bytes)
                self.assertNotIn(str(linked), claim_bytes)

            self.eidos(
                "claim",
                "release",
                "--claim-id",
                main_claim["claim_id"],
                "--actor",
                "agent:main",
                check=True,
            )
            self.eidos_at(
                linked,
                "claim",
                "release",
                "--claim-id",
                linked_claim["claim_id"],
                "--actor",
                "agent:linked",
                check=True,
            )

            staged = self.root / "scope-a/staged.py"
            staged.parent.mkdir()
            staged.write_text("value = 'staged'\n", encoding="utf-8", newline="\n")
            self.git("add", "scope-a/staged.py")
            untracked = linked / "scope-b/untracked.py"
            untracked.parent.mkdir()
            untracked.write_text(
                "value = 'untracked'\n", encoding="utf-8", newline="\n"
            )

            before = (self.index_identity(self.root), self.index_identity(linked))
            listing = self.json_stdout(
                self.eidos("claim", "list", "--json", check=True)
            )
            after_listing = (
                self.index_identity(self.root),
                self.index_identity(linked),
            )
            self.assertEqual(before, after_listing)
            focus = self.json_stdout(self.eidos("focus", "--json", check=True))
            after_focus = (
                self.index_identity(self.root),
                self.index_identity(linked),
            )
            self.assertEqual(before, after_focus)

            listed = {item["work_id"]: item for item in listing["claims"]}
            self.assertEqual(listed[main_work.stem]["dirty_state"], "dirty")
            self.assertEqual(
                listed[main_work.stem]["scope_states"], {"scope-a": "dirty"}
            )
            self.assertIs(listed[main_work.stem]["orphaned_dirty"], True)
            self.assertEqual(listed[linked_work.stem]["dirty_state"], "dirty")
            self.assertEqual(
                listed[linked_work.stem]["scope_states"], {"scope-b": "dirty"}
            )
            self.assertIs(listed[linked_work.stem]["orphaned_dirty"], True)
            serialized = json.dumps(
                {"listing": listing, "focus": focus}, ensure_ascii=False
            )
            self.assertNotIn(str(self.root), serialized)
            self.assertNotIn(str(linked), serialized)

            removed = self.git_at(
                self.root,
                "worktree",
                "remove",
                "--force",
                str(linked),
                check=False,
            )
            self.assertEqual(removed.returncode, 0, removed.stderr)
            unavailable = self.json_stdout(
                self.eidos("claim", "list", "--json", check=True)
            )
            unavailable_by_work = {
                item["work_id"]: item for item in unavailable["claims"]
            }
            linked_item = unavailable_by_work[linked_work.stem]
            self.assertEqual(linked_item["worktree_availability"], "unknown")
            self.assertEqual(linked_item["dirty_state"], "unknown")
            self.assertEqual(linked_item["orphaned"], "unknown")
            self.assertEqual(linked_item["orphaned_dirty"], "unknown")

            recreated_result = self.git("worktree", "add", str(linked), "linked-eidos")
            self.assertEqual(recreated_result.returncode, 0, recreated_result.stderr)
            recreated_git_dir = Path(
                self.git_at(linked, "rev-parse", "--absolute-git-dir").stdout.strip()
            )
            self.assertEqual(original_git_dir.name, recreated_git_dir.name)
            recreated_claim = self.json_stdout(
                self.eidos_at(
                    linked,
                    "claim",
                    "acquire",
                    "--work-id",
                    linked_work.stem,
                    "--actor",
                    "agent:recreated",
                    "--json",
                    check=True,
                )
            )
            self.assertNotEqual(
                recreated_claim["worktree_id"], linked_claim["worktree_id"]
            )
            marker = recreated_git_dir / "eidos/worktree-instance"
            self.assertEqual(
                marker.read_text(encoding="utf-8").strip(),
                recreated_claim["worktree_id"],
            )
            recreated_dirty = linked / "scope-b/recreated.py"
            recreated_dirty.parent.mkdir()
            recreated_dirty.write_text(
                "value = 'recreated'\n", encoding="utf-8", newline="\n"
            )
            recreated_listing = self.json_stdout(
                self.eidos("claim", "list", "--json", check=True)
            )
            by_claim = {item["claim_id"]: item for item in recreated_listing["claims"]}
            historical = by_claim[linked_claim["claim_id"]]
            current = by_claim[recreated_claim["claim_id"]]
            self.assertEqual(historical["worktree_availability"], "unknown")
            self.assertEqual(historical["dirty_state"], "unknown")
            self.assertEqual(historical["orphaned"], "unknown")
            self.assertEqual(historical["orphaned_dirty"], "unknown")
            self.assertEqual(current["worktree_availability"], "available")
            self.assertEqual(current["dirty_state"], "dirty")
            self.assertEqual(current["scope_states"], {"scope-b": "dirty"})
            self.assertIs(current["orphaned"], False)
            self.assertIs(current["orphaned_dirty"], False)
        finally:
            if linked.exists():
                self.git_at(
                    self.root,
                    "worktree",
                    "remove",
                    "--force",
                    str(linked),
                    check=False,
                )

    def test_unborn_head_dirty_probe_is_unknown_and_does_not_create_an_index(
        self,
    ) -> None:
        unborn = self.root.parent / "unborn"
        unborn.mkdir()
        self.git_at(unborn, "init")
        installed = self.run_process(
            sys.executable,
            KIT,
            "install",
            "--root",
            unborn,
            "--project-id",
            "project:unborn",
            "--project-name",
            "Unborn",
        )
        self.assertEqual(installed.returncode, 0, installed.stderr)
        tool = unborn / ".agents/tools/eidos.py"
        name = f"_eidos_unborn_test_{id(self)}"
        spec = importlib.util.spec_from_file_location(name, tool)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        self.addCleanup(sys.modules.pop, name, None)
        spec.loader.exec_module(module)

        before = self.index_identity(unborn)
        self.assertEqual(module._scope_dirty(unborn, "src"), "unknown")
        source = unborn / "src/untracked.py"
        source.parent.mkdir()
        source.write_text("value = 1\n", encoding="utf-8", newline="\n")
        self.assertEqual(module._scope_dirty(unborn, "src"), "unknown")
        self.assertEqual(before, self.index_identity(unborn))

    def test_closed_work_rejects_new_claim_and_renewal(self) -> None:
        self.install()
        closed = self.create_work(slug="closed-before-claim", scope="src/closed")
        self.close_work(closed)
        acquire = self.eidos(
            "claim",
            "acquire",
            "--work-id",
            closed.stem,
            "--actor",
            "agent:first",
        )
        self.assertEqual(acquire.returncode, 2)
        self.assertIn("claim_closed_work", acquire.stderr)

        active = self.create_work(slug="closed-after-claim", scope="src/active")
        claim = self.json_stdout(
            self.eidos(
                "claim",
                "acquire",
                "--work-id",
                active.stem,
                "--actor",
                "agent:first",
                "--json",
                check=True,
            )
        )
        self.close_work(active)
        renewal = self.eidos(
            "claim",
            "renew",
            "--claim-id",
            claim["claim_id"],
            "--actor",
            "agent:first",
        )
        self.assertEqual(renewal.returncode, 2)
        self.assertIn("claim_closed_work", renewal.stderr)

    def test_parent_and_dependency_cycles_are_rejected(self) -> None:
        self.install()
        first = self.create_work(slug="cycle-first", scope="src/first")
        result = self.eidos(
            "new-work",
            "--slug",
            "cycle-second",
            "--stage",
            "S01",
            "--title",
            "Cycle Second",
            "--owner",
            "member:a",
            "--workstream",
            "workstream:platform",
            "--parent",
            first.stem,
            "--depends-on",
            first.stem,
            "--write-scope",
            "src/second",
            check=True,
        )
        second = self.root / result.stdout.strip()
        first_text = first.read_text(encoding="utf-8")
        first_text = first_text.replace(
            "parent_work_id: none", f"parent_work_id: {second.stem}"
        )
        first_text = first_text.replace(
            "depends_on: none", f"depends_on: {second.stem}"
        )
        first.write_text(first_text, encoding="utf-8", newline="\n")
        result = self.json_stdout(self.eidos("validate", "--json"))
        codes = {item["code"] for item in result["error"]["findings"]}
        self.assertIn("parent_cycle", codes)
        self.assertIn("dependency_cycle", codes)

    def prepare_legacy_install(self, *, status: str = "done") -> tuple[bytes, Path]:
        agents = self.root / ".agents"
        (agents / "eidos/archive").mkdir(parents=True)
        (agents / "eidos/work").mkdir(parents=True)
        (agents / "tools").mkdir(parents=True)
        context = {
            "schema_version": 1,
            "project": {"id": "project:test-project", "name": "Test Project"},
            "eidos": {
                "version": 2,
                "direction_path": ".agents/eidos/direction.md",
                "work_root": ".agents/eidos/work",
                "archive_root": ".agents/eidos/archive",
            },
        }
        (agents / "context.json").write_text(
            json.dumps(context, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        direction = agents / "eidos/direction.md"
        legacy_bytes = self.legacy_direction().replace("\n", "\r\n").encode()
        direction.write_bytes(legacy_bytes)
        work = agents / "eidos/work/W-20260819-01-legacy-work.md"
        work.write_text(self.legacy_work(status=status), encoding="utf-8", newline="\n")
        return legacy_bytes, direction

    def test_upgrade_archives_legacy_direction_byte_identically(self) -> None:
        original, direction = self.prepare_legacy_install()
        result = self.kit("upgrade")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            (self.root / ".agents/eidos/archive/D0001.md").read_bytes(), original
        )
        current = direction.read_text(encoding="utf-8")
        self.assertIn("eidos_version: 3", current)
        self.assertIn("revision: D0002", current)
        self.assertNotIn("Current Focus", current)
        self.assertIn("## Gates", current)
        self.assertIn("Legacy gate is satisfied.", current)
        self.assertEqual(self.eidos("validate").returncode, 0)

    def test_v2_upgrade_manifest_fault_restores_legacy_tree_exactly(self) -> None:
        self.prepare_legacy_install()
        module = self.load_kit_module()
        arguments = module.argparse.Namespace(root=self.root)
        before = self.tree_state()
        original = module._write_exclusive

        def fail_after_manifest(path, data):
            original(path, data)
            if path == self.root / module.MANIFEST_PATH:
                raise OSError("fault after legacy manifest write")

        with mock.patch.object(
            module, "_write_exclusive", side_effect=fail_after_manifest
        ):
            with self.assertRaises(OSError):
                module._command_upgrade(arguments)
        self.assertEqual(before, self.tree_state())
        self.assertFalse((self.root / module.MANIFEST_PATH).exists())
        self.assertFalse((self.root / ".agents/eidos/archive/D0001.md").exists())

    def test_upgrade_refuses_legacy_open_work_without_mutation(self) -> None:
        original, direction = self.prepare_legacy_install(status="in_progress")
        before = self.tree_hash()
        result = self.kit("upgrade")
        after = self.tree_hash()
        self.assertEqual(result.returncode, 2)
        self.assertIn("legacy_open_work", result.stderr)
        self.assertEqual(before, after)
        self.assertEqual(direction.read_bytes(), original)
        self.assertFalse((self.root / ".agents/eidos/archive/D0001.md").exists())

    def test_diff_upgrade_and_doctor_track_kit_owned_drift(self) -> None:
        self.install()
        self.assertEqual(self.kit("diff").returncode, 0)
        self.assertEqual(self.kit("doctor", "--json").returncode, 0)
        direction = self.root / ".agents/eidos/direction.md"
        direction.write_text(
            direction.read_text(encoding="utf-8").replace(
                "State the stable problem this project solves and the expected outcome.",
                "Maintain the project's stable purpose.",
            ),
            encoding="utf-8",
            newline="\n",
        )
        self.assertEqual(self.kit("diff").returncode, 0)
        self.assertEqual(self.kit("doctor", "--json").returncode, 0)
        workflow = self.root / ".agents/workflows/eidos-v3.md"
        workflow.write_text(
            workflow.read_text(encoding="utf-8") + "local edit\n",
            encoding="utf-8",
            newline="\n",
        )
        self.assertEqual(self.kit("diff").returncode, 1)
        upgrade = self.kit("upgrade")
        self.assertEqual(upgrade.returncode, 2)
        self.assertIn("local_modification", upgrade.stderr)

    def test_doctor_uses_source_trust_even_if_target_manifest_is_forged(self) -> None:
        self.install()
        marker = self.root.parent / "modified-tool-executed"
        tool = self.root / ".agents/tools/eidos.py"
        tool.write_text(
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n",
            encoding="utf-8",
            newline="\n",
        )
        result = self.kit("doctor", "--json")
        self.assertEqual(result.returncode, 2)
        payload = self.json_stdout(result)
        self.assertIn("kit_modified", {item["code"] for item in payload["findings"]})
        self.assertFalse(marker.exists())

        manifest_path = self.root / ".agents/eidos/kit-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"][".agents/tools/eidos.py"]["sha256"] = hashlib.sha256(
            tool.read_bytes()
        ).hexdigest()
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        forged = self.kit("doctor", "--json")
        self.assertEqual(forged.returncode, 2)
        forged_payload = self.json_stdout(forged)
        self.assertIn(
            "manifest_untrusted",
            {item["code"] for item in forged_payload["findings"]},
        )
        self.assertFalse(marker.exists())

    def test_upgrade_rejects_jointly_forged_kit_file_and_manifest(self) -> None:
        self.install()
        tool = self.root / ".agents/tools/eidos.py"
        tool.write_text("# forged tool\n", encoding="utf-8", newline="\n")
        manifest_path = self.root / ".agents/eidos/kit-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"][".agents/tools/eidos.py"]["sha256"] = hashlib.sha256(
            tool.read_bytes()
        ).hexdigest()
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        result = self.kit("upgrade")
        self.assertEqual(2, result.returncode)
        self.assertIn("manifest_untrusted", result.stderr)
        self.assertEqual("# forged tool\n", tool.read_text(encoding="utf-8"))

    def test_upgrade_rejects_removed_manifest_entry_and_modified_file(self) -> None:
        self.install()
        tool = self.root / ".agents/tools/eidos.py"
        tool.write_text("# omitted forged tool\n", encoding="utf-8", newline="\n")
        manifest_path = self.root / ".agents/eidos/kit-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        del manifest["files"][".agents/tools/eidos.py"]
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        result = self.kit("upgrade")
        self.assertEqual(2, result.returncode)
        self.assertIn("manifest_untrusted", result.stderr)
        self.assertEqual("# omitted forged tool\n", tool.read_text(encoding="utf-8"))

    def test_claim_adoption_rejects_work_owner_transfer(self) -> None:
        self.install()
        identity_path = self.root / ".agents/eidos/identity.json"
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
        identity["members"].append(
            {"id": "member:b", "display_name": "B", "status": "active"}
        )
        identity_path.write_text(
            json.dumps(identity, indent=2) + "\n", encoding="utf-8"
        )
        work = self.create_work(scope="src/transfer")
        acquired = self.json_stdout(
            self.eidos(
                "claim",
                "acquire",
                "--work-id",
                work.stem,
                "--actor",
                "agent:first",
                "--json",
                check=True,
            )
        )
        self.eidos(
            "claim",
            "release",
            "--claim-id",
            acquired["claim_id"],
            "--actor",
            "agent:first",
            check=True,
        )
        work.write_text(
            work.read_text(encoding="utf-8").replace(
                "owner_id: member:a", "owner_id: member:b"
            ),
            encoding="utf-8",
            newline="\n",
        )
        rejected = self.eidos(
            "claim",
            "adopt",
            "--claim-id",
            acquired["claim_id"],
            "--actor",
            "agent:second",
        )
        self.assertEqual(2, rejected.returncode)
        self.assertIn("claim_member_transfer", rejected.stderr)

    def test_doctor_never_executes_a_reparse_installed_tool(self) -> None:
        self.install()
        marker = self.root.parent / "reparse-tool-executed"
        external = self.root.parent / "external-eidos.py"
        external.write_text(
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n",
            encoding="utf-8",
            newline="\n",
        )
        tool = self.root / ".agents/tools/eidos.py"
        tool.unlink()
        try:
            tool.symlink_to(external)
        except OSError:
            self.skipTest("file symlink creation is unavailable")
        result = self.kit("doctor", "--json")
        self.assertEqual(result.returncode, 2)
        payload = self.json_stdout(result)
        self.assertIn("path_reparse", {item["code"] for item in payload["findings"]})
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
