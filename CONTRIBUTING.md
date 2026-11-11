# Contributing

Start with [the roadmap](docs/roadmap.md) and discuss substantial changes in an
issue. Include the user outcome, scope, acceptance checks and evidence. Keep
scientific claims proportional to measured results and record failed attempts.

Use Python 3.9–3.12 and install `pip install -e '.[dev]'`. Before a PR, run:

```sh
python -m unittest discover -s tests -v
python -m unittest discover -s tests/browser -p test_ui_contract.py -v
node --check godseye/static/app.js
node --test tests/ui/*.test.cjs
ruff check godseye tests experiments/validate_client.py experiments/benchmark_demo.py
```

For UI changes, test the actual local server and the exported site under a
subdirectory; see [public demo checks](docs/public-demo.md). Include reproduction
steps and relevant test results in your PR. Keep changes small and preserve
other contributors' work. Do not include credentials, private suites, real user
sessions, provider responses or local evidence folders. Use invented or bundled
public fixtures. See [the security boundary](docs/security.md); report sensitive
issues privately through GitHub's security advisory channel where available,
not as a public issue with secrets.
