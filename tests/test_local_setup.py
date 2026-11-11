"""Offline setup/service checks; opt-in Docker test uses existing images, no provider."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from godseye.core import Store
from godseye.evaluator import Evaluator
from godseye.experiment_spec import DEFAULT_CEILINGS
from godseye.local_setup import (
    SetupError,
    bootstrap,
    execute,
    open_service,
    private_path,
    readiness,
)
from godseye.provider_setup import ProviderSettings
from godseye.server import create_app

CHECKOUT = Path(__file__).resolve().parents[1]


class LocalSetupTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name).resolve()
        self.root = self.path / "fresh"
        self.settings = ProviderSettings(self.path / "settings")
        self.settings.save("sk-dummy-setup-only", "dummy-model")
        self.commands = []

    def local_command(self, command, **kwargs):
        self.commands.append((command, kwargs))
        if command[:2] == ["docker", "run"]:
            # The offline fixture replaces only container initialization.
            Evaluator.create(
                self.root / "evaluator",
                seed=523,
                instances=1,
                episodes=2,
                max_steps=1,
                forward_budget=4,
            )

    def prepare(self):
        with patch("godseye.local_setup.run_local", side_effect=self.local_command):
            return bootstrap(self.root, CHECKOUT, self.settings)

    def test_bootstrap_and_service_reload_are_inert(self):
        original_open = Path.open

        def guarded_open(path, *args, **kwargs):
            if path.name in ("openai-api-key", "provider.env", "provider.json"):
                raise AssertionError("Setup must not read provider settings or credentials")
            return original_open(path, *args, **kwargs)

        with (
            patch.object(Path, "open", guarded_open),
            patch.object(
                ProviderSettings, "credential", side_effect=AssertionError("No credential load")
            ),
        ):
            report = self.prepare()
            self.assertEqual(report["provider_profiles_present"], ["openai"])
            self.assertFalse(report["inference_authorized"])
            receipt = json.loads((self.root / "setup.json").read_text())
            baseline = receipt["baseline_id"]
            request = dict(
                schema_version=1,
                text="Improve Breakout score",
                provider=dict(name="openai", model="dummy-model", routing="price"),
                limits=dict(DEFAULT_CEILINGS),
            )
            first_draft = first_hash = None
            for iteration in range(2):
                service = open_service(self.root, CHECKOUT, self.settings)
                with TestClient(
                    create_app(store=Store(self.path / "lab"), orchestration=service)
                ) as client:
                    plan = client.post("/api/v1/experiments/plan", json=request)
                    self.assertEqual(plan.status_code, 200)
                    data = plan.json()
                    self.assertEqual(data["outcome"], "ready")
                    self.assertEqual(data["spec"]["baseline"]["id"], baseline)
                    self.assertEqual(service.rows("run"), [])
                    response = client.post(
                        "/api/v1/experiments/start",
                        json=dict(
                            schema_version=1,
                            draft_id=data["draft_id"],
                            spec_hash=data["spec_hash"],
                            idempotency_key="not-approved",
                            confirmed=False,
                        ),
                    )
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(service.rows("run"), [])
                    self.assertEqual(len(service.rows("registry")), 1)
                    if iteration:
                        self.assertEqual(service.load(first_draft, "draft")["hash"], first_hash)
                    first_draft, first_hash = data["draft_id"], data["spec_hash"]
            with self.assertRaisesRegex(SetupError, "already exists"):
                bootstrap(self.root, CHECKOUT, self.settings)
        command, options = self.commands[-1]
        self.assertEqual(command[:2], ["docker", "run"])
        self.assertIn("--network=none", command)
        self.assertIn("--pull=never", command)
        self.assertNotIn("REPAIR_AGENT_KEY_FILE", options["env"])
        self.assertNotIn("sk-dummy", json.dumps(self.commands))
        self.assertFalse((self.root / "evaluator" / ".orchestration.claim").exists())
        self.assertEqual((self.root / "setup.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)

    def test_partial_failure_preserved_not_registered_or_reused(self):
        def fail(command, **kwargs):
            if command[:2] == ["docker", "run"]:
                (self.root / "evaluator" / "partial").write_text("preserve")
                raise SetupError("Controlled initialization failure")

        with patch("godseye.local_setup.run_local", side_effect=fail):
            with self.assertRaisesRegex(SetupError, "Controlled"):
                bootstrap(self.root, CHECKOUT, self.settings)
        self.assertFalse((self.root / "setup.json").exists())
        self.assertFalse((self.root / "service").exists())
        with self.assertRaisesRegex(SetupError, "already exists"):
            bootstrap(self.root, CHECKOUT, self.settings)
        self.assertEqual((self.root / "evaluator" / "partial").read_text(), "preserve")

    def test_missing_profile_is_visible_without_creating_settings(self):
        settings = ProviderSettings(self.path / "absent")
        with patch("godseye.local_setup.run_local"):
            report = readiness(CHECKOUT, settings)
        self.assertEqual(report["provider_profiles_present"], [])
        self.assertFalse(settings.directory.exists())

    def test_root_permissions_symlinks_and_checkout_refused(self):
        with patch("godseye.local_setup.os.getuid", return_value=0):
            with self.assertRaisesRegex(SetupError, "non-root"):
                readiness(CHECKOUT, self.settings)
        self.settings.directory.chmod(0o755)
        with patch("godseye.local_setup.run_local"):
            with self.assertRaisesRegex(SetupError, "700"):
                readiness(CHECKOUT, self.settings)
        link = self.path / "linked"
        link.symlink_to(self.settings.directory, target_is_directory=True)
        with self.assertRaisesRegex(SetupError, "symbolic"):
            private_path(link)
        with self.assertRaisesRegex(SetupError, "outside"):
            bootstrap(CHECKOUT / "no-private-state", CHECKOUT, self.settings)

    def test_occupied_port_preserves_existing_service(self):
        import socket
        from godseye.local_setup import launch

        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            with (
                patch("godseye.local_setup.readiness"),
                patch("godseye.local_setup.open_service") as opened,
            ):
                with self.assertRaisesRegex(SetupError, "occupied"):
                    launch(self.root, CHECKOUT, port=listener.getsockname()[1])
                opened.assert_not_called()

    def test_raw_failure_is_not_echoed(self):
        import argparse
        import contextlib
        import io

        output = io.StringIO()
        with patch("godseye.local_setup.readiness", side_effect=ValueError("secret-body")):
            with contextlib.redirect_stderr(output):
                self.assertEqual(execute(argparse.Namespace(command="readiness")), 2)
        self.assertNotIn("secret-body", output.getvalue())


@unittest.skipUnless(
    os.environ.get("GODSEYE_SETUP_DOCKER_TEST") == "1",
    "Opt in to local Docker initialization; never builds or contacts providers",
)
class DockerSetupTest(unittest.TestCase):
    setUp = LocalSetupTest.setUp

    def prepare(self):
        return bootstrap(self.root, CHECKOUT, self.settings)

    # Run only the actual setup/reload scenario, not inherited mock assertions.
    def test_bootstrap_and_service_reload_are_inert(self):
        with patch.object(
            ProviderSettings, "credential", side_effect=AssertionError("No credential load")
        ):
            report = self.prepare()
            self.assertFalse(report["inference_authorized"])
            for _ in range(2):
                service = open_service(self.root, CHECKOUT, self.settings)
                with TestClient(
                    create_app(store=Store(self.path / "lab"), orchestration=service)
                ) as client:
                    response = client.post(
                        "/api/v1/experiments/plan",
                        json=dict(
                            schema_version=1,
                            text="Improve Breakout score",
                            provider=dict(name="openai", model="dummy-model", routing="price"),
                            limits=dict(DEFAULT_CEILINGS),
                        ),
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["outcome"], "ready")
                    self.assertEqual(service.rows("run"), [])
                    self.assertEqual(len(service.rows("registry")), 1)
            with self.assertRaisesRegex(SetupError, "already exists"):
                bootstrap(self.root, CHECKOUT, self.settings)

    def test_cli_bootstrap_launch_and_restart_over_tcp(self):
        import signal
        import socket
        import subprocess
        import sys
        import time
        import urllib.error
        import urllib.request

        home = self.path / "home"
        home.mkdir(mode=0o700)
        ProviderSettings(home / ".godseye-secrets").save("sk-dummy-setup-only", "dummy-model")
        env = {
            k: v
            for k, v in os.environ.items()
            if k
            in (
                "PATH",
                "DOCKER_HOST",
                "DOCKER_CONTEXT",
                "DOCKER_CONFIG",
                "DOCKER_TLS_VERIFY",
                "DOCKER_CERT_PATH",
                "TMPDIR",
            )
        }
        env["HOME"] = str(home)
        # Keep the local Docker context while isolating all provider profiles.
        env["DOCKER_CONFIG"] = os.environ.get("DOCKER_CONFIG", str(Path.home() / ".docker"))
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        base = "http://127.0.0.1:" + str(port)
        request = dict(
            schema_version=1,
            text="Improve Breakout score",
            provider=dict(name="openai", model="dummy-model", routing="price"),
            limits=dict(DEFAULT_CEILINGS),
        )
        first = None
        for command in ("bootstrap", "launch"):
            argv = [
                sys.executable,
                "-m",
                "godseye",
                command,
                "--root",
                str(self.root),
                "--port",
                str(port),
            ]
            if command == "bootstrap":
                argv.append("--launch")
            with tempfile.TemporaryFile() as log:
                process = subprocess.Popen(argv, cwd=CHECKOUT, env=env, stdout=log, stderr=log)
                try:
                    deadline = time.monotonic() + 45
                    while True:
                        try:
                            with urllib.request.urlopen(base + "/healthz", timeout=1) as response:
                                self.assertEqual(response.status, 200)
                            break
                        except (urllib.error.URLError, TimeoutError):
                            if process.poll() is not None or time.monotonic() > deadline:
                                log.seek(0)
                                detail = (
                                    log.read()
                                    .decode(errors="replace")
                                    .replace("sk-dummy-setup-only", "[redacted]")
                                )
                                self.fail("CLI did not expose its local service: " + detail)
                            time.sleep(0.1)
                    message = urllib.request.Request(
                        base + "/api/v1/experiments/plan",
                        data=json.dumps(request).encode(),
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(message, timeout=5) as response:
                        plan = json.load(response)
                    self.assertEqual(plan["outcome"], "ready")
                    identity = plan["spec"]["baseline"]["id"]
                    self.assertEqual(identity, first or identity)
                    first = identity
                    with urllib.request.urlopen(base + "/lab", timeout=5) as response:
                        self.assertEqual(response.status, 200)
                finally:
                    process.send_signal(signal.SIGINT)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    log.seek(0)
                    self.assertNotIn(b"sk-dummy-setup-only", log.read())
        service = open_service(self.root, CHECKOUT, ProviderSettings(home / ".godseye-secrets"))
        try:
            self.assertEqual(service.rows("run"), [])
            self.assertEqual(len(service.rows("registry")), 1)
            self.assertEqual(len(service.rows("draft")), 2)
        finally:
            service.close()


if __name__ == "__main__":
    unittest.main()
