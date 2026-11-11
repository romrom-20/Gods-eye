"""Trusted, offline operator bootstrap. Never loads credentials or starts inference."""

import argparse
import json
import os
from pathlib import Path
import secrets
import shlex
import sys
import socket
import stat
import sqlite3
import subprocess

from .orchestration import DockerWorker, Orchestrator
from .provider_setup import ProviderSettings


class SetupError(ValueError):
    pass


def private_path(path, *, directory=True):
    """Check, never repair, ownership/mode; refuse symlinks in every component."""
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise SetupError("Private paths must not contain symbolic links.")
    info = path.stat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise SetupError("Private directories must be owned by you with mode 700; files mode 600.")
    return path


def run_local(command, *, env=None, timeout=10):
    # Suppress raw Docker errors: they can contain local paths/configuration.
    try:
        result = subprocess.run(
            command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired):
        raise SetupError(
            "Local Docker command unavailable or timed out; no provider request was made."
        ) from None
    if result.returncode:
        raise SetupError(
            "Local Docker check failed; check the daemon, Compose v2 and prebuilt isolation images."
        )


def readiness(checkout, settings=None):
    """Only local metadata/stat and Docker checks. No key opens, API calls or writes."""
    if os.getuid() == 0:
        raise SetupError("Run as a non-root OS user; do not override evaluator isolation.")
    checkout = Path(checkout).resolve()
    DockerWorker(checkout)  # Require the existing isolation contract/source checkout.
    run_local(["docker", "version", "--format", "{{.Server.Version}}"])
    run_local(["docker", "compose", "version"])
    run_local(
        [
            "docker",
            "image",
            "inspect",
            "isolation-evaluator",
            "isolation-agent",
            "isolation-gateway",
        ]
    )
    settings = settings or ProviderSettings()
    # Presence/permissions only: do not open provider.json, provider.env or any key.
    profiles = []
    if settings.directory.exists() or settings.directory.is_symlink():
        private_path(settings.directory)
        config = settings.directory / "provider.json"
        if config.exists() or config.is_symlink():
            private_path(config, directory=False)
            for provider in ("openai", "openrouter", "huggingface"):
                key = settings.directory / (provider + "-api-key")
                if key.exists() or key.is_symlink():
                    private_path(key, directory=False)
                    if key.stat().st_size:
                        profiles.append(provider)
    return dict(
        local_ready=True,
        provider_profiles_present=profiles,
        provider_verified=False,
        inference_authorized=False,
    )


def external_root(root, checkout):
    root = Path(root).expanduser().absolute()
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise SetupError("Private paths must not contain symbolic links.")
    root = root.resolve()
    checkout = Path(checkout).resolve()
    if root == checkout or checkout in root.parents:
        raise SetupError("Choose a private directory outside the source checkout and web root.")
    return root


def bootstrap(root, checkout, settings=None):
    """Exclusively create fresh data, then register once. Preserve partial failures."""
    root = external_root(root, checkout)
    if root.exists():
        raise SetupError(
            "Setup directory already exists. Use launch for this setup, or choose a new directory for a new experiment; never reset or reuse suites."
        )
    if "," in str(root):
        raise SetupError("Choose a setup path without commas for the Docker bind mount.")
    report = readiness(checkout, settings)
    if not root.parent.is_dir():
        raise SetupError(
            "Create the parent directory first; setup creates only its fresh private child."
        )
    try:
        root.mkdir(mode=0o700)
    except FileExistsError:
        raise SetupError("Setup directory already exists; choose a fresh directory.") from None
    private_path(root)
    private = root / "evaluator"
    private.mkdir(mode=0o700)
    # Do not inherit provider/Compose overrides or mount any provider secret.
    env = {
        k: v
        for k, v in os.environ.items()
        if k
        in (
            "PATH",
            "HOME",
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "DOCKER_CONFIG",
            "DOCKER_TLS_VERIFY",
            "DOCKER_CERT_PATH",
            "TMPDIR",
        )
    }
    # Seed generation stays inside the container: no seed in argv, logs or receipt.
    code = (
        "import secrets; from godseye.evaluator import Evaluator; "
        'Evaluator.create("/private", seed=secrets.randbelow(2**31), '
        "instances=3, probes=2, forward_budget=800, episodes=2, max_steps=200)"
    )
    command = [
        "docker",
        "run",
        "--rm",
        "--pull=never",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--pids-limit=32",
        "--memory=512m",
        "--cpus=1",
        "--user",
        str(os.getuid()) + ":" + str(os.getgid()),
        "--mount",
        "type=bind,src=" + str(private) + ",dst=/private",
        "--tmpfs",
        "/tmp:size=16m,noexec,nosuid",
        "--entrypoint",
        "python",
        "isolation-evaluator",
        "-c",
        code,
    ]
    run_local(command, env=env, timeout=120)
    service = Orchestrator(root / "service")
    baseline_id = "local-" + secrets.token_hex(12)
    try:
        service.register(private, baseline_id=baseline_id, suite_id="breakout-local", revision="v1")
    finally:
        service.close()
    receipt = dict(
        schema_version=1,
        baseline_id=baseline_id,
        evaluation=dict(instances=3, episodes=2, max_steps=200, probes=2, forward_budget=800),
    )
    with open(root / "setup.json", "x", opener=lambda p, f: os.open(p, f, 0o600)) as stream:
        json.dump(receipt, stream, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(root, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return report


def open_service(root, checkout, settings=None):
    """Reopen identities only; never initialize/register or submit a run on reload."""
    root = external_root(root, checkout)
    private_path(root)
    for name in ("evaluator", "service"):
        private_path(root / name)
    private_path(root / "setup.json", directory=False)
    private_path(root / "service" / "orchestration.sqlite3", directory=False)
    receipt = json.loads((root / "setup.json").read_text())
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema_version") != 1
        or not isinstance(receipt.get("baseline_id"), str)
    ):
        raise SetupError("Setup receipt is invalid; preserve state and inspect it offline.")
    worker = DockerWorker(checkout)
    service = Orchestrator(root / "service", worker=worker, settings=settings)
    try:
        registered = service.registration(receipt["baseline_id"])
        if registered["directory"] != str((root / "evaluator").resolve()):
            raise SetupError("Setup registration does not match its private directory.")
    except BaseException:
        service.close()
        raise
    return service


def launch(root, checkout, *, port=8789):
    import uvicorn
    from .server import create_app
    from .core import Store

    if not 1 <= port <= 65535:
        raise SetupError("Choose a loopback port between 1 and 65535.")
    readiness(checkout)
    # Fail before opening the DB or recovering anything if another server owns it.
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            raise SetupError(
                "Requested loopback port is occupied. Choose another port; no existing server was changed."
            ) from None
    service = open_service(root, checkout)
    app = create_app(
        store=Store(Path(root).expanduser() / "lab"),
        orchestration=service,
        token=os.environ.get("GODSEYE_API_TOKEN"),
    )
    print("Local experiment workspace: http://127.0.0.1:" + str(port) + "/lab", flush=True)
    print(
        "Setup authorizes no inference. Review the supported Breakout goal, explicit provider/model/routing and all seven limits in the browser before confirming Start.",
        flush=True,
    )
    try:
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=port,
            workers=1,
            proxy_headers=False,
            limit_concurrency=32,
            timeout_keep_alive=5,
        )
    finally:
        service.close()


def port_number(value):
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Expected a port between 1 and 65535.") from None
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("Expected a port between 1 and 65535.")
    return port


def add_commands(sub):
    for name in ("bootstrap", "launch", "readiness"):
        parser = sub.add_parser(
            name,
            help={
                "bootstrap": "Create a fresh isolated local experiment without inference",
                "launch": "Serve an existing local setup without resuming experiments",
                "readiness": "Check local Docker/images/profile presence without reading keys",
            }[name],
        )
        if name != "readiness":
            parser.add_argument("--root", type=Path, required=True)
            parser.add_argument("--port", type=port_number, default=8789)
        if name == "bootstrap":
            parser.add_argument("--launch", action="store_true")


def execute(args):
    checkout = Path(__file__).resolve().parents[1]
    try:
        if args.command == "readiness":
            print(json.dumps(readiness(checkout)))
        elif args.command == "bootstrap":
            print(json.dumps(bootstrap(args.root, checkout)))
            print("Fresh suite registered; no provider request or experiment started.", flush=True)
            if args.launch:
                launch(args.root, checkout, port=args.port)
            else:
                print("Next: godseye launch --root " + shlex.quote(str(args.root)))
        else:
            launch(args.root, checkout, port=args.port)
    except (SetupError, OSError, ValueError, KeyError, sqlite3.Error) as error:
        # Only our fixed setup messages are public; never print raw filesystem,
        # database, provider, evaluator or Docker exception strings.
        message = (
            str(error)
            if isinstance(error, SetupError)
            else "Local setup failed. Preserve existing state; check private permissions, setup receipt and service ownership. No automatic retry or reset was attempted."
        )
        print(message, file=sys.stderr)
        return 2
    return 0
