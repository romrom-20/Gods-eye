# Install the local Breakout browser app

God's Eye currently edits one bundled **20,486-parameter MinAtar Breakout
policy**. The local example runs real CPU evaluations without a provider key,
Docker, GPU, or model download. It demonstrates a known circuit; it does not
establish AI-discovered improvement or support editing arbitrary language models.

Use **macOS or Linux**, Python **3.9–3.12** (3.12 recommended), pip, a modern
browser, and a writable local directory. The commands below use POSIX shell
syntax. The package smoke check has been run on macOS with Python 3.9.6; the
workflow checks Linux when run in CI. Native Windows is currently unsupported:
the CLI loads operator code that uses POSIX file locking. WSL is unverified.
The advanced Docker workflow additionally
requires a source checkout, Docker Engine/Compose v2 and a non-root OS user.

Installation needs internet access for dependencies unless you already have a
complete local wheelhouse. CPU speed affects evaluation time. There is no
editable Qwen backend, hosted service, or guaranteed improvement.

## Install from a built wheel

There is **no assumed PyPI release**. Obtain `godseye-packages` from a successful
GitHub Actions **Build and verify installable packages** run for the revision you
intend to use, and unzip it. Alternatively, build the same files from a checkout
as described below. An Actions artifact is a build output, not a published release.

Create a virtual environment in your own working directory, outside the checkout:

```sh
mkdir godseye-local
cd godseye-local
python3.12 -m venv .venv
.venv/bin/python -m pip install '/absolute/path/to/godseye_wsp-0.3.0-py3-none-any.whl[server]'
.venv/bin/godseye serve
```

Replace the absolute path with the downloaded wheel location; keep the quotes and
`[server]`. Open **http://127.0.0.1:8787/lab** manually. The browser does not open
automatically. If that port is in use, choose another with `godseye serve --port
8789` and open that port; do not stop an unrelated service. Stop your server with
Ctrl+C. The writable server stays on loopback.

After installation, this local example works offline. Use the **no-key guided
example** in the lab: ablate the four known left-action connections, evaluate the
changed policy against `paper`, then restore and compare. Browser evaluation
performs CPU work and writes local evidence; it makes no provider requests. AI
goal execution is a separate advanced setup, described below.

For a small reproducible terminal example using the same installed backend:

```sh
.venv/bin/godseye inspect paper
.venv/bin/godseye compare --base zero --candidate paper --episodes 1 --max-steps 80 --seed 1000
```

This is a bounded baseline comparison, not a demonstration of learned repair.
By default, checkpoints, evaluation jobs and results live in `.godseye` in the
directory where you start the command. Reopen from the same directory to keep
using that workspace. To choose another location, set `GODSEYE_DATA_DIR` to an
absolute writable path before launching. Preserve that directory to keep results.
The package's bundled original weights remain available as `paper`.

For recorded evidence without writable evaluation, use `godseye serve --demo`.
To export the bundled recordings as static files, use `godseye export-demo
--output recorded-demo` with an empty/new destination. These recordings are
distinct from your local experiment results.

## Install or build from a Git checkout

```sh
git clone https://github.com/romrom-20/Gods-eye.git
cd Gods-eye
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[server]'
.venv/bin/godseye serve
```

For reproducibility, check out your chosen commit before installing. This is the
source-install route; `pip install godseye-wsp` is not an installation promise.
To produce wheel and source-distribution files locally:

```sh
.venv/bin/python -m pip install 'build>=1.2,<2'
.venv/bin/python -m build
GODSEYE_TEST_WHEEL="$PWD/dist/godseye_wsp-0.3.0-py3-none-any.whl" \
  .venv/bin/python -m unittest discover -s tests -p test_package_install.py -v
```

The build produces `dist/godseye_wsp-0.3.0-py3-none-any.whl` and
`dist/godseye_wsp-0.3.0.tar.gz`. The wheel is built from the source distribution.
The opt-in smoke test installs the wheel with server dependencies in a fresh venv
outside the checkout, checks bundled UI/policy/preset/recorded data, starts its own
loopback server on a temporary port, and submits a real bounded CPU evaluation.
Dependency installation can use the package index; the example itself uses no
provider, operator credentials, or Docker. Ordinary unit-test runs skip this test
unless `GODSEYE_TEST_WHEEL` is set. No publishing occurs.

## Advanced: isolated AI-guided experiments

Follow [local operator setup](local-operator-setup.md) **from a source checkout**.
The wheel supports the ordinary local CPU lab, CLI, and recorded demo. It does
**not** contain the repository's `isolation/` Compose files, Docker build contexts,
or operator documentation, which the isolated worker requires. Running
`bootstrap`, `launch`, or `readiness` from a wheel alone does not provide that
source isolation contract. A source archive also should not be assumed to carry
the complete operator checkout; use Git for this path.

Prepare Docker images explicitly using the linked instructions. Installation,
ordinary `serve`, and bootstrap do not silently fetch/build those images.
Isolated execution additionally requires fresh private evaluation state, a saved
provider profile, an explicitly selected compatible programmer model and review
of all request/token/time limits before starting. A saved key is not permission
to spend. Selecting a programmer model such as Qwen does not make its weights an
editable target: supported experiments still target Breakout. Real-provider
compatibility and useful repair quality remain unproven.

## Common first-run problems

- **Unsupported Python:** recreate the venv using Python 3.9–3.12; Python 3.13+
  is outside the declared dependency support.
- **Missing server dependencies:** reinstall the local wheel with `[server]`,
  or run `python -m pip install -e '.[server]'` from the checkout, using the
  virtual environment's Python. A base-only install still supports the CPU CLI.
- **Wrong environment:** use `.venv/bin/godseye` or `.venv/bin/python -m godseye`.
- **Port in use:** choose a free port with `--port`; existing servers are not
  stopped or reused by these instructions.
- **No isolated service configured:** use the local no-key example, or complete
  the separate operator setup. Installing a wheel does not authorize AI runs.
