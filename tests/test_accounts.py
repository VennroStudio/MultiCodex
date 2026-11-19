import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import runpy
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("accounts", ROOT / "scripts/accounts.py")
accounts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(accounts)
STATE = ".codex-global-state.json"


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="multicodex-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.primary = self.root / ".codex"
        self.primary.mkdir()
        self.secondary = self.root / ".codex-client-one"
        self.ui = self.root / "ui-client-one"
        self.source = {
            "local-projects": {"project-one": {"id": "project-one", "name": "First"}},
            "project-order": ["project-one"],
            "thread-project-assignments": {
                "thread-one": {"projectKind": "local", "projectId": "project-one"}
            },
        }
        (self.primary / STATE).write_text(json.dumps(self.source))
        (self.primary / "auth.json").write_text("primary test credentials")
        (self.primary / "config.toml").write_text("# primary settings\n")
        (self.primary / "sessions").mkdir()
        (self.primary / "sessions" / "test.jsonl").write_text("test history\n")
        self.database = self.primary / "state_5.sqlite"
        with sqlite3.connect(self.database) as database:
            database.execute("CREATE TABLE projects (id TEXT PRIMARY KEY)")
            database.execute("INSERT INTO projects VALUES ('server-one')")
        with sqlite3.connect(self.primary / "thread_history_1.sqlite") as database:
            database.execute("CREATE TABLE test_turns (text TEXT)")
            database.execute("INSERT INTO test_turns VALUES ('test turn')")
        self.app = self.root / "Fixture.app"
        executable = self.app / "Contents/MacOS/ChatGPT"
        executable.parent.mkdir(parents=True)
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o700)
        cli = self.app / "Contents/Resources/codex"
        cli.parent.mkdir(parents=True)
        cli.write_text("#!/bin/sh\nexit 0\n")
        cli.chmod(0o700)
        (self.app / "Contents/Info.plist").write_bytes(
            plistlib.dumps({"CFBundleExecutable": "ChatGPT"})
        )
        config = self.root / "accounts.json"
        config.write_text(json.dumps({
            "primary": "main",
            "accounts": {
                "main": {"codex_home": str(self.primary)},
                "client-one": {},
                "client-two": {},
            },
        }))
        self.environment = {
            "ACCOUNTS_FILE": str(config),
            "CODEX_PROFILES_DIR": str(self.root),
            "ELECTRON_PROFILES_DIR": str(self.root),
            "CHATGPT_APP": str(self.app),
            "STATE_DATABASE": str(self.database),
            "REGISTRY_DIR": str(self.root / "registry"),
        }
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, self.environment).start()

    def setup_account(self, name="client-one"):
        calls = []
        real_call = subprocess.call

        def call(command, **kwargs):
            calls.append(command)
            if "--no-launch" in command:
                return real_call(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **kwargs)
            # Inspect the launch boundary without starting a real desktop app.
            home = Path(command[command.index("--secondary-home") + 1])
            self.assertTrue((home / STATE).is_file())
            self.assertFalse((home / STATE).is_symlink())
            self.assertNotIn("--symlink-history", command)
            return 0

        with patch.object(accounts, "require_closed"), patch.object(
            accounts.subprocess, "call", side_effect=call
        ), patch.object(sys, "argv", ["accounts.py", "setup", "--account", name]):
            self.assertEqual(accounts.main(), 0)
        self.assertEqual(len(calls), 2)

    def sync(self, source, target):
        argv = ["sync_projects.py", "--source-home", str(source), "--target-home", str(target),
                "--database", str(self.database), "--apply"]
        # Fixture profiles have no running desktop process.
        with patch.object(sys, "argv", argv), patch.object(
            subprocess, "check_output", return_value=""
        ), contextlib.redirect_stdout(io.StringIO()):
            runpy.run_path(str(ROOT / "scripts/sync_projects.py"), run_name="__main__")

    def test_new_accounts_share_chats_but_keep_project_files_and_logins_separate(self):
        self.setup_account()
        self.setup_account("client-two")
        other = self.root / ".codex-client-two"
        for home in [self.secondary, other]:
            self.assertEqual(json.loads((home / STATE).read_bytes()), {})
            for relative in ["sessions", "archived_sessions", "attachments", "state_5.sqlite",
                             "state_5.sqlite-wal", "thread_history_1.sqlite"]:
                self.assertTrue((home / relative).is_symlink())
                self.assertEqual((home / relative).resolve(), (self.primary / relative).resolve())
            self.assertFalse((home / "auth.json").exists())
            self.assertFalse((home / "config.toml").exists())
        self.sync(self.primary, self.secondary)
        self.assertEqual(json.loads((self.secondary / STATE).read_bytes())["local-projects"],
                         self.source["local-projects"])
        self.assertEqual(json.loads((other / STATE).read_bytes()), {})
        (self.secondary / "sessions/test.jsonl").write_text("history from client-one\n")
        self.assertEqual((other / "sessions/test.jsonl").read_text(), "history from client-one\n")

    def test_repeated_setup_preserves_projects_auth_and_config(self):
        self.setup_account()
        self.sync(self.primary, self.secondary)
        (self.secondary / "auth.json").write_text("secondary test credentials")
        (self.secondary / "config.toml").write_text("# secondary settings\n")
        before = {str(path): path.read_bytes() for home in [self.primary, self.secondary]
                  for path in [home / STATE, home / "auth.json", home / "config.toml"]}
        self.setup_account()
        for path, content in before.items():
            self.assertEqual(Path(path).read_bytes(), content)

    def test_legacy_project_symlink_is_detached_and_sync_works_both_ways(self):
        self.secondary.mkdir()
        (self.secondary / STATE).symlink_to(self.primary / STATE)
        self.setup_account()
        self.assertEqual(json.loads((self.secondary / STATE).read_bytes()), self.source)
        target = json.loads((self.secondary / STATE).read_bytes())
        target["local-projects"]["project-two"] = {"id": "project-two", "name": "Second"}
        (self.secondary / STATE).write_text(json.dumps(target))
        self.assertNotIn("project-two", json.loads((self.primary / STATE).read_bytes())["local-projects"])
        self.sync(self.secondary, self.primary)
        self.sync(self.primary, self.secondary)
        for home in [self.primary, self.secondary]:
            self.assertIn("project-two", json.loads((home / STATE).read_bytes())["local-projects"])

    def test_failed_history_setup_does_not_launch(self):
        with patch.object(accounts, "require_closed"), patch.object(
            accounts.subprocess, "call", return_value=2
        ) as call, patch.object(sys, "argv", ["accounts.py", "setup", "--account", "client-one"]):
            self.assertEqual(accounts.main(), 2)
        self.assertEqual(call.call_count, 1)
        self.assertFalse((self.secondary / STATE).exists())

    def test_invalid_legacy_state_is_not_replaced(self):
        (self.primary / STATE).write_text("invalid json")
        self.secondary.mkdir()
        (self.secondary / STATE).symlink_to(self.primary / STATE)
        with self.assertRaises(ValueError):
            accounts.prepare_project_state(self.secondary)
        self.assertTrue((self.secondary / STATE).is_symlink())
        self.assertEqual((self.primary / STATE).read_text(), "invalid json")


if __name__ == "__main__":
    unittest.main()
