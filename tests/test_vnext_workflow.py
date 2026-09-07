from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import re
import sys
import unittest
from datetime import timedelta
from unittest import mock

import test_vnext_eidos_v3 as fixtures


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.EidosV3Test()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.install()
        self.root = self.fixture.root
        name = "workflow_tool_" + str(id(self))
        spec = importlib.util.spec_from_file_location(
            name, self.root / ".agents/tools/eidos.py"
        )
        self.tool = importlib.util.module_from_spec(spec)
        sys.modules[name] = self.tool
        self.addCleanup(sys.modules.pop, name, None)
        spec.loader.exec_module(self.tool)

    def request(self, **changes):
        return {
            "slug": "small-change",
            "title": "Clarify parser contract",
            "owner": "member:a",
            "stage": "S01",
            "write_scope": ["src/parser"],
            "risk": "R1",
            "actor": "agent:test",
            "intent": "Make empty input deterministic.",
            "completion_criteria": "Empty input returns no rows.",
            "verification_plan": "Run parser boundary tests.",
            **changes,
        }

    def call(self, operation, payload):
        with (
            mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            code = self.tool._command_work(
                argparse.Namespace(root=self.root, operation=operation, input="-")
            )
        return code, json.loads(output.getvalue())

    def start(self):
        code, result = self.call("start", self.request())
        self.assertEqual(code, 0, result)
        return result["data"]

    def finish_request(self, started, **changes):
        return {
            "work_id": started["work_id"],
            "claim_id": started["claim_id"],
            "actor": "agent:test",
            "status": "done",
            "result": "Empty input now returns no rows.",
            "evidence": "Parser boundary tests passed.",
            **changes,
        }

    def test_lifecycle_retry_and_closed_bytes(self):
        index = self.fixture.index_identity(self.root)
        started = self.start()
        target = self.root / started["path"]
        initial = target.read_bytes()
        self.assertIn(started["path"], self.tool._load_claims(self.root)[0]["paths"])
        self.assertEqual(self.call("start", self.request())[1]["data"], started)
        self.assertEqual(initial, target.read_bytes())
        request = self.finish_request(started)
        code, result = self.call("finish", request)
        self.assertEqual(code, 0, result)
        finished = target.read_bytes()
        self.assertEqual(self.call("finish", request)[0], 0)
        self.assertEqual(finished, target.read_bytes())
        self.assertEqual(
            self.call("finish", {**request, "result": "Different result."})[0], 2
        )
        self.assertEqual(finished, target.read_bytes())
        self.assertEqual(self.tool._load_claims(self.root)[0]["status"], "released")
        self.assertEqual(index, self.fixture.index_identity(self.root))

    def test_bad_inputs_fail_before_work_write(self):
        for change in (
            {"intent": "pending"},
            {"completion_criteria": ""},
            {"verification_plan": "none"},
            {"owner": "agent:test"},
            {"write_scope": ["../escape"]},
            {"risk": "R0"},
            {"actor": "member:a"},
            {"title": "bad\nstatus: done"},
            {"intent": "## Result\nfake"},
            {"unexpected": True},
        ):
            with self.subTest(change=change):
                before = self.fixture.tree_state()
                self.assertEqual(self.call("start", self.request(**change))[0], 2)
                self.assertEqual(before, self.fixture.tree_state())

    def test_conflict_and_wrong_finish_claim(self):
        started = self.start()
        code, result = self.call("start", self.request(slug="overlap"))
        self.assertEqual((code, result["error"]["code"]), (2, "claim_conflict"))
        self.assertEqual(len(self.tool.inspect_project(self.root).work), 1)
        for change in (
            {"actor": "agent:another"},
            {"claim_id": "claim-" + "a" * 32},
            {"evidence": "pending"},
        ):
            self.assertEqual(
                self.call("finish", self.finish_request(started, **change))[0], 2
            )
        self.assertEqual(
            self.tool.inspect_project(self.root).work[0]["status"], "in_progress"
        )

    def test_start_and_finish_write_failures_restore_and_retry(self):
        original = self.tool._atomic_bytes

        def fail_claim(path, *args, **kwargs):
            if path.parent.name == "claims":
                raise OSError("injected claim write failure")
            return original(path, *args, **kwargs)

        with mock.patch.object(self.tool, "_atomic_bytes", side_effect=fail_claim):
            code, result = self.call("start", self.request())
        self.assertEqual((code, result["error"]["code"]), (2, "work_retry"))
        self.assertEqual(self.tool.inspect_project(self.root).work, [])
        started = self.start()
        target = self.root / started["path"]
        before = self.tool._file_snapshot(target)
        with mock.patch.object(self.tool, "_atomic_bytes", side_effect=fail_claim):
            self.assertEqual(self.call("finish", self.finish_request(started))[0], 2)
        self.assertEqual(before, self.tool._file_snapshot(target))
        self.assertEqual(self.call("finish", self.finish_request(started))[0], 0)

    def test_concurrent_work_edit_is_preserved(self):
        started = self.start()
        target = self.root / started["path"]
        original = self.tool._atomic_bytes
        external = None

        def concurrent(path, *args, **kwargs):
            nonlocal external
            if path.parent.name == "claims":
                external = target.read_bytes() + b"\nExternal note.\n"
                target.write_bytes(external)
                raise OSError("injected concurrent edit")
            return original(path, *args, **kwargs)

        with mock.patch.object(self.tool, "_atomic_bytes", side_effect=concurrent):
            code, result = self.call("finish", self.finish_request(started))
        self.assertEqual((code, result["error"]["code"]), (2, "work_recovery_required"))
        self.assertEqual(target.read_bytes(), external)
        self.assertEqual(self.call("finish", self.finish_request(started))[0], 2)
        self.assertEqual(target.read_bytes(), external)

    def test_archived_direction_remains_usable(self):
        started = self.start()
        target = self.root / started["path"]
        before = target.read_bytes()
        direction = self.root / ".agents/eidos/direction.md"
        original = direction.read_bytes()
        (self.root / ".agents/eidos/archive/D0001.md").write_bytes(original)
        direction.write_bytes(original.replace(b"revision: D0001", b"revision: D0002"))
        model = self.tool.inspect_project(self.root)
        self.assertFalse(model.errors)
        self.assertIn("work_revision_stale", {item.code for item in model.findings})
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(self.call("finish", self.finish_request(started))[0], 0)
        self.assertIn(b"direction_revision: D0001", target.read_bytes())
        code, result = self.call(
            "start", self.request(slug="next", write_scope=["src/next"])
        )
        self.assertEqual(code, 0, result)
        self.assertIn(
            b"direction_revision: D0002",
            (self.root / result["data"]["path"]).read_bytes(),
        )

    def test_edit_during_preparation_is_not_approved_as_baseline(self):
        started = self.start()
        target = self.root / started["path"]
        prepare = self.tool._finish_work_operation

        def concurrent(*args):
            result = prepare(*args)
            target.write_bytes(target.read_bytes() + b"\nConcurrent human note.\n")
            return result

        with mock.patch.object(
            self.tool, "_finish_work_operation", side_effect=concurrent
        ):
            code, result = self.call("finish", self.finish_request(started))
        self.assertEqual((code, result["error"]["code"]), (2, "work_changed"))
        self.assertIn(b"Concurrent human note.", target.read_bytes())
        self.assertIn(b"status: in_progress", target.read_bytes())

    def test_pending_start_cannot_cross_direction_change(self):
        atomic = self.tool._atomic_bytes

        def fail_claim(path, *args, **kwargs):
            if path.parent.name == "claims":
                raise OSError("injected")
            return atomic(path, *args, **kwargs)

        with mock.patch.object(self.tool, "_atomic_bytes", side_effect=fail_claim):
            self.assertEqual(self.call("start", self.request())[0], 2)
        direction = self.root / ".agents/eidos/direction.md"
        original = direction.read_bytes()
        (self.root / ".agents/eidos/archive/D0001.md").write_bytes(original)
        direction.write_bytes(original.replace(b"revision: D0001", b"revision: D0002"))
        self.assertEqual(self.call("start", self.request())[0], 2)
        self.assertEqual(self.tool.inspect_project(self.root).work, [])

    def test_late_edit_without_io_exception_prevents_success(self):
        started = self.start()
        target = self.root / started["path"]
        atomic = self.tool._atomic_bytes

        def concurrent(path, *args, **kwargs):
            result = atomic(path, *args, **kwargs)
            if path.parent.name == "claims":
                target.write_bytes(target.read_bytes() + b"\nLate external note.\n")
            return result

        with mock.patch.object(self.tool, "_atomic_bytes", side_effect=concurrent):
            code, result = self.call("finish", self.finish_request(started))
        self.assertEqual((code, result["error"]["code"]), (2, "work_recovery_required"))
        self.assertIn(b"Late external note.", target.read_bytes())

    def test_legacy_placeholder_warns_without_breaking_validation(self):
        self.fixture.create_work()
        model = self.tool.inspect_project(self.root)
        self.assertFalse(model.errors)
        self.assertIn("work_content_incomplete", {item.code for item in model.findings})

    def test_malformed_receipts_fail_with_json_without_writes(self):
        started = self.start()
        target = self.root / started["path"]
        before = target.read_bytes()
        receipt = next((self.root / ".git/eidos/operations").glob("*.json"))
        original = json.loads(receipt.read_text(encoding="utf-8"))
        for bad in (
            [],
            None,
            {**original, "claim": []},
            {**original, "guards": []},
            {**original, "before_work": {"bytes": "broken"}},
        ):
            receipt.write_text(json.dumps(bad), encoding="utf-8")
            code, result = self.call("start", self.request())
            self.assertEqual(code, 2)
            self.assertFalse(result["ok"])
            self.assertEqual(target.read_bytes(), before)

    def test_pending_finish_expiry_blocks_republish_but_all_after_can_ack(self):
        started = self.start()
        request = self.finish_request(started)
        atomic = self.tool._atomic_bytes

        def fail_claim(path, *args, **kwargs):
            if path.parent.name == "claims":
                raise OSError("injected")
            return atomic(path, *args, **kwargs)

        with mock.patch.object(self.tool, "_atomic_bytes", side_effect=fail_claim):
            self.assertEqual(self.call("finish", request)[0], 2)
        before = self.fixture.tree_state(), self.tool._load_claims(self.root)
        future = self.tool._utc_now() + timedelta(hours=2)
        with mock.patch.object(self.tool, "_utc_now", return_value=future):
            code, result = self.call("finish", request)
        self.assertEqual((code, result["error"]["code"]), (2, "claim_expired"))
        self.assertEqual(
            before, (self.fixture.tree_state(), self.tool._load_claims(self.root))
        )
        self.assertEqual(self.call("finish", request)[0], 0)
        for receipt in (self.root / ".git/eidos/operations").glob("*.json"):
            journal = json.loads(receipt.read_text(encoding="utf-8"))
            if journal["operation"] == "finish":
                journal["state"] = "pending"
                receipt.write_text(json.dumps(journal), encoding="utf-8")
        after = self.fixture.tree_state(), self.tool._load_claims(self.root)
        with mock.patch.object(self.tool, "_utc_now", return_value=future):
            self.assertEqual(self.call("finish", request)[0], 0)
        self.assertEqual(
            after, (self.fixture.tree_state(), self.tool._load_claims(self.root))
        )

    def test_partially_published_finish_cannot_resume_after_expiry(self):
        started = self.start()
        target = self.root / started["path"]
        original_work = target.read_bytes()
        atomic = self.tool._atomic_bytes

        def fail_claim_and_rollback(path, content, *args, **kwargs):
            if path.parent.name == "claims" or (
                path == target and content == original_work
            ):
                raise OSError("injected")
            return atomic(path, content, *args, **kwargs)

        request = self.finish_request(started)
        with mock.patch.object(
            self.tool, "_atomic_bytes", side_effect=fail_claim_and_rollback
        ):
            self.assertEqual(
                self.call("finish", request)[1]["error"]["code"],
                "work_recovery_required",
            )
        before = self.fixture.tree_state(), self.tool._load_claims(self.root)
        future = self.tool._utc_now() + timedelta(hours=2)
        with mock.patch.object(self.tool, "_utc_now", return_value=future):
            self.assertEqual(
                self.call("finish", request)[1]["error"]["code"], "claim_expired"
            )
        self.assertEqual(
            before, (self.fixture.tree_state(), self.tool._load_claims(self.root))
        )

    def test_summary_limits_diagnostics_and_read_only(self):
        self.start()
        before = self.fixture.tree_state(), self.fixture.index_identity(self.root)
        detailed = self.fixture.json_stdout(
            self.fixture.eidos("focus", "--json", check=True)
        )
        summary = self.fixture.json_stdout(
            self.fixture.eidos(
                "focus", "--summary", "--limit", "1", "--json", check=True
            )
        )
        self.assertIn("claims", detailed["data"])
        self.assertNotIn("claims", summary["data"])
        self.assertEqual(summary["data"]["counts"]["active_work"], 1)
        self.assertEqual(
            before, (self.fixture.tree_state(), self.fixture.index_identity(self.root))
        )
        for args in (("--summary", "--limit", "0"), ("--limit", "1")):
            self.assertEqual(self.fixture.eidos("focus", *args).returncode, 2)
        claim = self.tool._load_claims(self.root)[0]
        path = self.tool._claims_root(self.root) / (claim["claim_id"] + ".json")
        path.write_text("broken", encoding="utf-8")
        result = self.fixture.eidos("focus", "--summary", "--json")
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.fixture.json_stdout(result)["ok"])

    def test_summary_sort_omission_and_invalid_timestamp(self):
        first = self.fixture.create_work(slug="first")
        second = self.fixture.create_work(slug="second")
        stamp = re.search(
            r"(?m)^updated_at: (.+)$", second.read_text(encoding="utf-8")
        )[1]
        first.write_text(
            re.sub(
                r"(?m)^updated_at: .+$",
                "updated_at: " + stamp,
                first.read_text(encoding="utf-8"),
            ),
            encoding="utf-8",
            newline="\n",
        )
        result = self.fixture.json_stdout(
            self.fixture.eidos(
                "focus", "--summary", "--limit", "1", "--json", check=True
            )
        )["data"]
        self.assertEqual(result["planned_work"][0]["work_id"], first.stem)
        self.assertEqual(result["omitted"]["planned_work"], 1)
        second.write_text(
            re.sub(
                r"(?m)^updated_at: .+$",
                "updated_at: invalid",
                second.read_text(encoding="utf-8"),
            ),
            encoding="utf-8",
            newline="\n",
        )
        result = self.fixture.eidos("focus", "--summary", "--json")
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.fixture.json_stdout(result)["ok"])
        self.assertNotIn("Traceback", result.stderr)
