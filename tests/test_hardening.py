"""Hardening tests: bad input, missing files, corrupt registry, edge cases."""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from promptpack.core import (
    NotFoundError,
    PromptPackError,
    Registry,
)
from promptpack.cli import main


class RegistryBadInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "reg.json")
        self.reg = Registry(self.db)

    # --- corrupt / missing registry file ---------------------------------

    def test_load_corrupt_json_raises(self):
        bad = os.path.join(self.tmp, "bad.json")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("{not valid json")
        with self.assertRaises(PromptPackError) as ctx:
            Registry(bad)
        self.assertIn("not valid JSON", str(ctx.exception))

    def test_load_wrong_root_type_raises(self):
        bad = os.path.join(self.tmp, "bad2.json")
        with open(bad, "w", encoding="utf-8") as fh:
            json.dump([1, 2, 3], fh)
        with self.assertRaises(PromptPackError) as ctx:
            Registry(bad)
        self.assertIn("JSON object", str(ctx.exception))

    def test_load_prompts_not_dict_raises(self):
        bad = os.path.join(self.tmp, "bad3.json")
        with open(bad, "w", encoding="utf-8") as fh:
            json.dump({"prompts": "not_a_dict"}, fh)
        with self.assertRaises(PromptPackError) as ctx:
            Registry(bad)
        self.assertIn("prompts", str(ctx.exception))

    # --- invalid prompt names --------------------------------------------

    def test_commit_empty_name_raises(self):
        with self.assertRaises(PromptPackError) as ctx:
            self.reg.commit("", "body")
        self.assertIn("empty", str(ctx.exception))

    def test_commit_invalid_name_raises(self):
        with self.assertRaises(PromptPackError) as ctx:
            self.reg.commit("bad name!", "body")
        self.assertIn("invalid prompt name", str(ctx.exception))

    def test_commit_valid_name_chars(self):
        # hyphens, underscores, dots should all be accepted
        obj = self.reg.commit("my-prompt_v1.0", "hello")
        self.assertEqual(obj["version"], 1)

    # --- A/B edge cases --------------------------------------------------

    def test_ab_zero_weight_rejected(self):
        self.reg.commit("p", "v1")
        with self.assertRaises(PromptPackError):
            self.reg.set_ab("p", "prod", [{"version": 1, "weight": 0}])

    def test_ab_negative_weight_rejected(self):
        self.reg.commit("p", "v1")
        with self.assertRaises(PromptPackError):
            self.reg.set_ab("p", "prod", [{"version": 1, "weight": -5}])

    def test_ab_empty_variants_rejected(self):
        self.reg.commit("p", "v1")
        with self.assertRaises(PromptPackError):
            self.reg.set_ab("p", "prod", [])

    # --- empty registry list ----------------------------------------------

    def test_list_empty_registry(self):
        result = self.reg.list_prompts()
        self.assertEqual(result, [])

    # --- rollback on missing tag -----------------------------------------

    def test_rollback_missing_tag_raises(self):
        self.reg.commit("p", "v1")
        with self.assertRaises(NotFoundError):
            self.reg.rollback("p", "nosuch", "1")


class CliBadInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "reg.json")

    def _run(self, *args):
        return main(["--db", self.db, *args])

    def test_commit_missing_file_returns_1(self):
        rc = self._run("commit", "p", "--file", "no_such_file_xyz.txt")
        self.assertEqual(rc, 1)

    def test_ab_bad_version_type_returns_1(self):
        self._run("commit", "p", "--body", "v1")
        self._run("commit", "p", "--body", "v2")
        rc = self._run("ab", "p", "prod", "notanumber:1")
        self.assertEqual(rc, 1)

    def test_ab_bad_weight_type_returns_1(self):
        self._run("commit", "p", "--body", "v1")
        rc = self._run("ab", "p", "prod", "1:notaweight")
        self.assertEqual(rc, 1)

    def test_get_missing_prompt_returns_1(self):
        rc = self._run("get", "nonexistent")
        self.assertEqual(rc, 1)

    def test_get_missing_prompt_json_returns_1(self):
        rc = self._run("get", "nonexistent", "--format", "json")
        self.assertEqual(rc, 1)

    def test_corrupt_db_returns_1(self):
        corrupt = os.path.join(self.tmp, "corrupt.json")
        with open(corrupt, "w", encoding="utf-8") as fh:
            fh.write("{{BAD")
        rc = main(["--db", corrupt, "list"])
        self.assertEqual(rc, 1)

    def test_var_missing_equals_returns_1(self):
        self._run("commit", "p", "--body", "hi {x}")
        rc = self._run("render", "p", "--var", "noequalssign")
        self.assertEqual(rc, 1)


class McpServerImportTests(unittest.TestCase):
    def test_mcp_server_imports_cleanly(self):
        """mcp_server must import without error (no broken top-level imports)."""
        import importlib
        mod = importlib.import_module("promptpack.mcp_server")
        self.assertTrue(callable(getattr(mod, "serve", None)))


if __name__ == "__main__":
    unittest.main()
