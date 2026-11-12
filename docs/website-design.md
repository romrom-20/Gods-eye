# Public website design

The landing is an editorial field note about inspecting, editing, and evaluating
open weights. Its first screen states the current Breakout-only compatibility,
provides an explicitly labeled **Recorded example**, and shows real before/after
evidence. The secondary path installs the runnable local CPU lab from source.
There is no signup, cloud execution, provider integration, or simulated success
on the landing.

## Reference principles

Inspected in Ego Lite on 2026-11-12:

- [Tinker](https://thinkingmachines.ai/tinker/): generous negative space,
  expressive type, and a short developer entry path. Our serif headline and
  restrained navigation establish a research tone without adopting its artwork.
- [Linear](https://linear.app/): clear hierarchy and an actual product surface
  close to the introduction. Real saved Breakout gameplay replaces decorative
  network imagery and generic feature cards.
- [Beaker](https://www.withbeaker.ai/): explain the experiment loop and make
  installation concrete. Here the loop is inspect → branch → evaluate; the
  known ablation is explicitly harmful, with no autonomous repair claim.

The original visual system combines warm paper, blue-black instrument panels,
lime highlights, and coral for the harmful result. System sans, Georgia, and
system monospace have distinct roles; there are no downloaded fonts. Ruled rows
explain the workbench. An abbreviated checkpoint lineage explains importing;
it is a workflow illustration, not an experiment result.

## Evidence provenance

The hero uses `godseye/data/demo/run-3ed8cc40701c4335.json`: `paper` versus
`bba6b79c8ba04971`, patch `W3[0:8:2, 1] = 0`. Mean scores are 186.375 and 0;
paired mean difference is −186.375, with SE 26.226 (rounded to three decimals).
The eight paired seeds are 1000–1007, the episode cap is 3,000 steps, and seven
original episodes hit that cap. These are recorded measurements, not a new run,
a benchmark claim, or evidence of general repair.

The SVGs render actual observation cells from seed 1000. Fourteen selected source
frames (steps 0–5, 10, 20, 40, 80, 120, 200, 300, 399) are embedded in `landing.js`.
The failed candidate's last saved frame stays visible after step 5. The input
reports the actual saved step rather than claiming uniform time intervals.
There is no autoplay or synthetic interpolation. Initial step 5 is also inline
in HTML, so the boards remain visible without JavaScript. Tests compare every
embedded frame and fallback SVG coordinate directly against the source JSON.

## Delivery and accessibility

Only existing allowlisted `landing.html`, `landing.css`, and `landing.js` are
needed. No exporter/server allowlist changes, new assets, dependencies, CDNs,
trackers, remote fonts, keys, or provider calls were added. The export still
contains exactly 13 public files. Embedded data is a subset of public evidence.
Relative lab/API links work beneath `/Gods-eye/` and at a local server root.
Installation, checkpoint format, recording, license, and roadmap links point to
actual repository files. All seven external destinations returned HTTP 200.

The page has a skip link, visible focus rings, semantic sections/headings,
accessible SVG descriptions, a native keyboard range, a polite copy status,
and a manual-copy fallback. Reduced motion disables smooth scrolling; there
is no animated decoration. Mobile stacks the explanatory panel below paired
boards and contains long installation commands in a scrolling pre. Installation
uses Python 3.9–3.12 and a source checkout, not a presumed PyPI release. Import
is limited to compatible Breakout `.npz` files, with architecture/size stated.

## Verification

From the repository root, with Python 3.9–3.12 and `.[dev]` installed:

```sh
python -m unittest discover -s tests -p test_landing.py -v
PYTHONPATH=tests python -m unittest test_platform.QueueTests.test_export_contains_only_bundled_public_data -v
node --test tests/ui/static_demo.test.cjs
node --check godseye/static/landing.js
python -m godseye export-demo --output /tmp/godseye-website-redesign/Gods-eye
python -m http.server 8894 --bind 127.0.0.1 --directory /tmp/godseye-website-redesign
# Separate terminal, requires Ego Lite:
ego-browser nodejs < tests/browser/landing_journey.cjs
```

Two landing tests passed; unchanged export contract passed; static live/mock
transport guard passed; JavaScript syntax passed. The actual browser journey
passed six widths (320, 390, 680, 768, 1024, 1440) with no horizontal document
overflow, keyboard Home/End scrubbing, the frozen ended episode, clipboard
feedback (`Commands copied.`), reduced motion, every local CTA path, and
navigation into recorded overview/workbench. Resource inspection found no
external landing dependencies or `/api/` calls. The recorded lab made no API
requests. With scripts disabled, 66 real observation cells, installation text,
and ordinary links remained present while the scrub control stayed hidden.

A separate local `godseye serve --port 8895` check loaded the landing at `/`;
`/lab.html`, `/api.html`, `/landing.css`, and `/landing.js` all returned 200.
The server used a temporary data path, not the operator's workspace. Both owned
servers were stopped after verification; nothing was deployed.

Screenshots captured and visually inspected:

- `/tmp/godseye-website-evidence/desktop.png` — 1440px full page.
- `/tmp/godseye-website-evidence/mobile.png` — 390px full page.
- `/tmp/godseye-website-evidence/mobile-no-js.png` — mobile without scripts.

Screenshots are local review evidence, not shipped assets. Ego Lite reported an
available update; the installed version was used without upgrading it.
