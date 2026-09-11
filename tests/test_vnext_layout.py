from __future__ import annotations

import contextlib
import io
import json
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MANAGER = runpy.run_path(str(ROOT / "kits/harness/v1/harness_kit.py"))
LAYOUT = MANAGER["_layout_module"]()


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def policy(self, mutate=lambda value: None):
        value = LAYOUT.default_policy()
        mutate(value)
        path = self.root / "_meta/layout.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_preview_is_read_only_and_unconfigured_warns(self):
        result = LAYOUT.inspect(self.root)
        self.assertTrue(result["ok"])
        self.assertEqual(result["findings"][0]["code"], "layout_unconfigured")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_scaffold_is_idempotent_and_preserves_project_files(self):
        writes = MANAGER["_layout_scaffold"](self.root)
        self.assertIn("_blueprint/README.md", writes)
        self.assertNotIn("config/README.md", writes)
        MANAGER["_atomic_write_set"](self.root, writes, require_absent=True)
        docs = self.root / "_docs/README.md"
        docs.write_text("custom project overview", encoding="utf-8")
        self.assertEqual(MANAGER["_layout_scaffold"](self.root), {})
        self.assertEqual(docs.read_text(), "custom project overview")
        self.assertEqual(LAYOUT.inspect(self.root)["findings"], [])

    def test_declared_entrypoint_missing_is_error(self):
        self.policy()
        self.assertFalse(LAYOUT.inspect(self.root)["ok"])

    def test_malformed_and_escaping_policy_fail_closed(self):
        for value in ("../outside", "/tmp", ".GIT/data", "a\\b", "a/../b", "a:stream"):
            with self.subTest(value=value):
                self.policy(lambda p: p["roles"].update(docs=value))
                self.assertFalse(LAYOUT.inspect(self.root)["ok"])
        (self.root / "_meta/layout.json").write_text("[]", encoding="utf-8")
        self.assertFalse(LAYOUT.inspect(self.root)["ok"])

    def test_case_insensitive_overlapping_roles_rejected(self):
        self.policy(lambda p: p["roles"].update(blueprint="_DOCS/details"))
        self.assertFalse(LAYOUT.inspect(self.root)["ok"])

    def test_windows_invalid_role_names_fail_even_when_docs_are_valid(self):
        docs = self.root / "_docs"
        docs.mkdir()
        (docs / "README.md").write_text("Overview", encoding="utf-8")
        for value in (
            'bad"name',
            "bad\nname",
            "CON",
            "aux.txt",
            "COM1",
            "LPT².txt",
            "a/NUL.log",
        ):
            with self.subTest(value=value):
                self.policy(lambda p: p["roles"].update(blueprint=value))
                self.assertFalse(LAYOUT.inspect(self.root)["ok"])

    def test_custom_roles_scaffold_respects_existing_policy(self):
        def customize(p):
            p["roles"]["docs"] = "handbook"
            p["roles"]["blueprint"] = "specifications"
            p["docs_entrypoints"] = ["handbook/README.md"]

        self.policy(customize)
        writes = MANAGER["_layout_scaffold"](self.root)
        self.assertIn("handbook/README.md", writes)
        self.assertIn("specifications/README.md", writes)
        self.assertNotIn("_meta/layout.json", writes)

    def test_detail_and_count_warnings_do_not_move_files(self):
        self.policy(lambda p: p.update(docs_max_files=1))
        docs = self.root / "_docs"
        docs.mkdir()
        for name in ("README.md", "ADR-001.md", "feature-design.md"):
            (docs / name).write_text("not classified by content", encoding="utf-8")
        before = {p.name: p.read_bytes() for p in docs.iterdir()}
        result = LAYOUT.inspect(self.root)
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["proposals"]), 2)
        self.assertIn("docs_too_large", {f["code"] for f in result["findings"]})
        self.assertEqual(before, {p.name: p.read_bytes() for p in docs.iterdir()})

    def test_exceptions_require_reasons(self):
        self.policy(
            lambda p: p.update(exceptions=[{"path": "_docs/legacy", "reason": ""}])
        )
        self.assertFalse(LAYOUT.inspect(self.root)["ok"])

    def test_link_path_is_refused(self):
        with mock.patch.object(Path, "is_symlink", return_value=True):
            self.assertFalse(LAYOUT.inspect(self.root)["ok"])

    def test_init_preview_does_not_write_and_apply_does(self):
        MANAGER["subprocess"].run(
            ["git", "init", str(self.root)], check=True, capture_output=True
        )
        args = MANAGER["argparse"].Namespace(root=self.root, action="init", apply=False)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(MANAGER["_command_layout"](args), 0)
        self.assertEqual([p.name for p in self.root.iterdir()], [".git"])
        args.apply = True
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(MANAGER["_command_layout"](args), 0)
        self.assertTrue((self.root / "_meta/layout.json").is_file())


if __name__ == "__main__":
    unittest.main()
