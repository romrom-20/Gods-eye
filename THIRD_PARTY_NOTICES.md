# Third-party materials

The root MIT license applies to original God's Eye code and documentation.
It does not replace licenses attached to third-party material or dependencies.

- The Breakout network in `fixtures/breakout/` and `godseye/data/breakout/`
  is by Rikiya Takehi, Jayden Teoh, Alex Zhang, and Omar Khattab, from
  [Sparks of Weight-Space Programming](https://rikiyat.github.io/blog/weight-space-programming/).
  It is provided under **CC BY 4.0**. Attribution, source commit, and the
  original notice accompany both copies. The copy in `godseye/data/` makes
  installed wheels self-contained; the legacy path remains for existing scripts.
- `godseye/data/demo/` includes copies and modified copies of that network
  (the ablated and restored checkpoints), with the same attribution. The exact
  modifications and parent hashes are recorded in checkpoint JSON files.
  Demo replay previews are limited to 400 frames; full episode scores remain intact.
- MinAtar 1.0.15 by Kenny Young and Tian Tian is a **GPL-3.0** dependency.
  Its game source is not copied into this repository. Installing dependencies
  or building a container does not relicense MinAtar. Preserve upstream notices
  and consider the applicable dependency terms when redistributing a combined
  application or container.
- NumPy, FastAPI, Uvicorn, and other installed packages retain their own licenses.
- The UI optionally loads DM Sans and IBM Plex Mono through Google Fonts;
  system fonts remain available when those resources cannot be reached.

Source network: `RikiyaT/lm_understand-logs`, commit
`4d09ba6d6a7e891dd8063974dfe81b3d78e3494f`.
No affiliation with or endorsement by Thinking Machines Lab is implied.
