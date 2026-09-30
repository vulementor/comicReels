"""Light kit/app entry smoke; no providers, browsers, models or workflow work."""
import builtins
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch


DEPLOYMENTS = (("service", "comicreels"), ("app", "thoremix"))


class EntrySmoke(unittest.TestCase):
    def invoke(self, root, kind, name, operation, *, enabled=False, settings=None):
        home = root / "consumer-home"
        launch = root / "launch"
        launch.mkdir(exist_ok=True)
        value = {"kind": kind, "name": name, "instance_id": "preview-a",
                 "release_id": "a" * 64, "channel": "candidate", "enabled": enabled}
        deployment = types.SimpleNamespace(
            as_dict=lambda: value, settings=settings or {}, profiles={},
            instance_id="preview-a", home=home, data_path=lambda path: home / path,
        )
        context = types.SimpleNamespace(entrypoint=operation, instance_dir=launch,
                                        deployment=lambda: deployment)
        def write(path, result):
            path.write_text(json.dumps(result), encoding="utf-8")
        module = types.ModuleType("stable_toolkit_runtime.context")
        module.atomic_json = write
        original_import = builtins.__import__
        def guarded_import(name, *args, **kwargs):
            if name.split(".")[0] in {"agent", "github_review_reel", "kabin_drama_toolkit"}:
                raise AssertionError("Business package import during administrative entry: " + name)
            return original_import(name, *args, **kwargs)
        spec = importlib.util.spec_from_file_location("private_consumer_entry", Path(__file__).with_name("entry.py"))
        entry = importlib.util.module_from_spec(spec)
        with patch.dict("sys.modules", {"stable_toolkit_runtime.context": module}), \
             patch("builtins.__import__", guarded_import), contextlib.redirect_stdout(io.StringIO()) as out:
            spec.loader.exec_module(entry)
            code = entry.main(context)
        payload = json.loads((launch / "app-result.json").read_text(encoding="utf-8"))
        self.assertEqual(payload, json.loads(out.getvalue()))
        return code, payload, home

    def test_disabled_help_and_status_distinguish_kit_from_app_without_business_imports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for kind, name in DEPLOYMENTS:
                for operation in ("help", "status"):
                    with self.subTest(kind=kind, name=name, operation=operation):
                        code, result, home = self.invoke(root, kind, name, operation)
                        self.assertEqual(code, 0)
                        self.assertFalse(result["enabled"])
                        self.assertEqual(result["schema"], f"stable.{kind}.entry.v1")
                        self.assertEqual(result[kind], name)
                        self.assertEqual((result["kind"], result["name"]), (kind, name))
                        self.assertNotIn("app" if kind == "service" else "service", result)
                        self.assertEqual(result["status"], "DISABLED")
                        self.assertEqual(result["execution_readiness"], "NOT_CHECKED")
                        self.assertEqual(result["domain_state"], "NOT_READ")
                        self.assertFalse(home.exists())
                        self.assertIn("help", result["supported_entries"])
                        self.assertIn("status", result["supported_entries"])
                        if kind == "service":
                            self.assertEqual(result["supported_entries"], ["help", "status", "server"])
                        else:
                            self.assertEqual(result["supported_entries"],
                                             ["help", "status", "campaign-status", "tick", "dispatch"])

    def test_enabled_declaration_with_missing_config_does_not_claim_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            for kind, name in DEPLOYMENTS:
                code, result, home = self.invoke(Path(directory), kind, name, "status", enabled=True)
                self.assertEqual(code, 0)
                self.assertEqual(result["status"], "CONFIGURATION_REQUIRED")
                self.assertTrue(result["missing_settings"])
                self.assertFalse(home.exists())

    def test_private_desktop_is_explicitly_unsupported_before_business_imports(self):
        with tempfile.TemporaryDirectory() as directory:
            for kind, name in DEPLOYMENTS:
                code, result, home = self.invoke(Path(directory), kind, name, "desktop")
                self.assertEqual(code, 2)
                self.assertEqual(result["error"], "BOUND_CHILD_LAUNCH_UNAVAILABLE")
                self.assertFalse(home.exists())

    def test_legacy_identity_wrong_kind_and_cross_workflow_entries_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for kind, name in (("app", "comic"), ("service", "comic"),
                               ("app", "comicreels"), ("service", "thoremix")):
                with self.subTest(kind=kind, name=name), self.assertRaisesRegex(ValueError, "UNSUPPORTED"):
                    self.invoke(root, kind, name, "status")
            for kind, name, operation in (("service", "comicreels", "tick"),
                                         ("service", "comicreels", "dispatch"),
                                         ("app", "thoremix", "server")):
                with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, "UNSUPPORTED"):
                    self.invoke(root, kind, name, operation)


if __name__ == "__main__":
    unittest.main()
