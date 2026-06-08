"""Smoke tests for PROMPTPACK. No network, isolated temp registry per test."""
import json
import os
import tempfile
import unittest

from promptpack import Registry, ConflictError, NotFoundError, PromptPackError
from promptpack.cli import main


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "reg.json")
        self.reg = Registry(self.db)

    def test_commit_increments_versions(self):
        a = self.reg.commit("p", "hello {name}")
        b = self.reg.commit("p", "hello {name}!")
        self.assertEqual(a["version"], 1)
        self.assertEqual(b["version"], 2)
        self.assertEqual(a["vars"], ["name"])

    def test_duplicate_commit_rejected(self):
        self.reg.commit("p", "same")
        with self.assertRaises(ConflictError):
            self.reg.commit("p", "same")

    def test_tag_and_resolve(self):
        self.reg.commit("p", "v1")
        self.reg.commit("p", "v2")
        self.reg.tag("p", "prod", "1")
        self.assertEqual(self.reg.get("p", "prod")["body"], "v1")
        self.assertEqual(self.reg.get("p", "latest")["body"], "v2")
        self.assertEqual(self.reg.get("p")["body"], "v2")

    def test_rollback(self):
        self.reg.commit("p", "v1")
        self.reg.commit("p", "v2")
        self.reg.tag("p", "prod", "2")
        res = self.reg.rollback("p", "prod", "1")
        self.assertEqual(res["from"], 2)
        self.assertEqual(res["to"], 1)
        self.assertEqual(self.reg.get("p", "prod")["version"], 1)

    def test_render_substitution_and_missing(self):
        self.reg.commit("p", "hi {name} re {topic}")
        out = self.reg.render("p", {"name": "Acme", "topic": "billing"})
        self.assertEqual(out, "hi Acme re billing")
        with self.assertRaises(PromptPackError):
            self.reg.render("p", {"name": "Acme"})

    def test_ab_deterministic_choose(self):
        self.reg.commit("p", "v1")
        self.reg.commit("p", "v2")
        self.reg.set_ab("p", "prod", [{"version": 1, "weight": 1},
                                       {"version": 2, "weight": 4}])
        c1 = self.reg.choose("p", "prod", key="user-1")
        c2 = self.reg.choose("p", "prod", key="user-1")
        self.assertEqual(c1["version"], c2["version"])  # stable per key
        self.assertIn(c1["version"], (1, 2))

    def test_ab_weight_distribution(self):
        self.reg.commit("p", "v1")
        self.reg.commit("p", "v2")
        self.reg.set_ab("p", "prod", [{"version": 1, "weight": 1},
                                       {"version": 2, "weight": 9}])
        picks = [self.reg.choose("p", "prod", key=f"u{i}")["version"]
                 for i in range(400)]
        # v2 has 90% weight; expect a clear majority
        self.assertGreater(picks.count(2), picks.count(1))

    def test_diff(self):
        self.reg.commit("p", "line a\nline b")
        self.reg.commit("p", "line a\nline c")
        d = self.reg.diff("p", "1", "2")
        self.assertTrue(any(line.startswith("-line b") for line in d))
        self.assertTrue(any(line.startswith("+line c") for line in d))

    def test_not_found(self):
        with self.assertRaises(NotFoundError):
            self.reg.get("nope")

    def test_persistence_roundtrip(self):
        self.reg.commit("p", "persisted")
        self.reg.save()
        reg2 = Registry(self.db)
        self.assertEqual(reg2.get("p")["body"], "persisted")


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "reg.json")

    def _run(self, *args):
        return main(["--db", self.db, *args])

    def test_cli_lifecycle(self):
        self.assertEqual(self._run("commit", "p", "--body", "hi {x}"), 0)
        self.assertEqual(self._run("commit", "p", "--body", "hi {x}!"), 0)
        self.assertEqual(self._run("tag", "p", "prod", "--ref", "2"), 0)
        self.assertEqual(
            self._run("render", "p", "--ref", "prod", "--var", "x=world"), 0)
        self.assertEqual(self._run("ab", "p", "prod", "1:1", "2:3"), 0)
        self.assertEqual(
            self._run("choose", "p", "prod", "--key", "u1", "--format", "json"), 0)
        self.assertEqual(self._run("rollback", "p", "prod", "1"), 0)

    def test_cli_error_nonzero(self):
        rc = self._run("get", "missing", "--format", "json")
        self.assertEqual(rc, 1)

    def test_cli_json_output_parses(self):
        self._run("commit", "p", "--body", "x")
        # ensure registry file is valid JSON
        with open(self.db, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIn("prompts", data)


if __name__ == "__main__":
    unittest.main()
