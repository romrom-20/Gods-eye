# Recorded public demo (0.3.0)

The public recorded demo is [romrom-20.github.io/Gods-eye](https://romrom-20.github.io/Gods-eye/).
First deployed on 2026-11-12 from verified main `8b1a544`, following the user's
request for a shared testing site. Main-only environment restrictions and a
required reviewer remain enabled. No live API or compute service is published.

Public browser checks verified four checkpoint tensor selections, both recordings
advancing, the developer guide, disabled mutations, and zero API traffic even with
`?goalMode=mock#goal`. HTML uses content-versioned CSS and JavaScript URLs.
Use [the tester handoff](test-the-product.md) for independent feedback.

## Reproduce the preview

```sh
python -m godseye export-demo --output /tmp/godseye-preview/Gods-eye
python -m http.server 8080 --directory /tmp/godseye-preview
```

Open `http://localhost:8080/Gods-eye/`, then `lab.html` (no hash),
`lab.html#overview`, and `lab.html#workbench`. Both comparisons must replay;
each of the four checkpoint selectors must load real tensor values. Check that
edit preview, save and evaluation are disabled, connection settings are absent,
and the default goal page shows recorded evidence rather than a live API form.
Even `?goalMode=mock#goal` must stay recorded-only in the exported site.

The exporter reads only `godseye/data` and an explicit static asset allowlist.
It never exports the operator's `.godseye`, provider settings, keys, private
suite or local run history. It refuses a nonempty output directory. The JSON
contains public checkpoint tensors, run summaries, full saved gameplay traces,
and the bundled patch preset. Network provenance and licenses travel with it.
Do not upload the repository, a local workspace, or an experiment evidence folder
as the site. The export does intentionally expose all its bundled tensor values.

## Deployment gate and approval

`.github/workflows/ci.yml` tests and builds the downloadable artifact.
`pages.yml` consumes that **exact artifact** only after successful push CI on
this repository's `main`, and only if repository Actions variable
`PUBLIC_DEMO_PAGES_ENABLED` equals the string `true`. Missing/false means off.
PR CI and forks cannot trigger deployment. No custom server is deployed.

After the coordinator receives explicit user deployment approval:

1. Review the public artifact and main commit; confirm no private content.
2. In repository Settings → Environments, configure `github-pages` with a required
   reviewer and main-only deployment branch policy where available.
3. In Settings → Pages, select GitHub Actions as the source; do not use a branch.
4. Set Actions repository variable `PUBLIC_DEMO_PAGES_ENABLED=true`.
5. Re-run the successful **push-to-main** CI run for the approved revision (a new
   push to main also works). Its completion triggers the Pages workflow; approve
   the environment deployment if configured. A manual CI dispatch does not deploy.
6. Verify landing, default lab, both replays and four checkpoints at `/Gods-eye/`.
   Only then add the actual working URL to README and repository homepage.

No Pages setting, enable variable, environment, external homepage/profile, remote
branch or release is changed by preparing these files. Keep the variable off
until approval. To stop future publication, set it false; removing an already
published site requires a separate Pages action. A failed later deployment may
leave the previous site visible. GitHub Pages provides public static files only:
no Python, API, writable jobs, provider calls, GPU, accounts or private storage.
Any genuine goal execution remains a separately installed trusted local service.
Do not enter credentials into a static site or expose the local writable API.

## Proposed profile and repository framing (read-only audit, 2026-11-11)

GitHub API inspection found no `romrom-20/romrom-20` profile README repository
(404), and the account has no bio or blog URL. Vernier's current description is
“A local-first Mac app for reflecting on how AI shapes your choices and judgment.
Open-source prototype, starting with Codex in Conductor.” Its README positions it
as local, inspectable decision history, with explicit prototype and model limits.
God's Eye's current description accurately describes a weight-space workbench,
bounded AI-guided Breakout experiments, a CPU example, browser UI and API; its
homepage is unset. Neither project establishes general AI repair or human
judgment measurement.

Suggested profile pitch for user review: “Building open-source tools to inspect
AI behavior and keep evidence close: God's Eye for reversible weight edits;
Vernier for local reflection on AI-assisted choices.” Link those names to
https://github.com/romrom-20/Gods-eye and https://github.com/romrom-20/Vernier.
Propose pinning both; consider Corrigibility and counterfactual-traces only after
reviewing their intended audience and evidence. Current pins were not verified.
Do not create a profile repo, change pins, or update homepage until separately
authorized. Add the Pages link only after the approved deployment is verified.

## Preparation evidence

Verified locally on 2026-11-11 from origin/main `5a06494`: Python suite completed 166 tests
(15 container/opt-in skips), browser contract 1 passed, Node UI 39 passed,
Ruff and JavaScript syntax passed, and wheel/sdist build succeeded at 0.3.0.
Ego Lite browser preview at `http://localhost:8087/Gods-eye/` loaded landing and
no-hash lab, advanced both recordings (`ef25348adab6497b` and
`3ed8cc40701c4335`) from frame 12 to frame 16, and inspected `paper`, `zero`,
`bba6b79c8ba04971`, and `86bbfe9d4157446f`. Zero's tensor was all zero;
restored and original checkpoint hashes matched. The default and mock-override
URLs exposed no goal form and loaded only CSS, app JS and `demo.json`, with no
API requests. Mutation controls were disabled and the editor hidden.

The audited export is about 916 KiB and contains exactly 13 allowlisted files,
including `.nojekyll` and network provenance/licenses. Automated export assertions
check the file list, both runs, four checkpoints and absence of the goal form;
controller tests prove neither live nor mock goal recovery can initialize in a
static export. This records the original preparation; the verified first public
deployment is recorded at the top of this document.
