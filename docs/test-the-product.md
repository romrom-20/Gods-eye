# Try the product and report what happened

The public recorded demo needs no account, key or installation. Select an original
checkpoint, inspect a tensor, then select a saved comparison and play both versions.
Try History and the keyboard-friendly List view. Report the URL, browser, viewport,
expected behavior, actual behavior, and a screenshot in a GitHub issue. Never
include credentials or private model data. A recording is not a live experiment.

For real edits, follow [installation](install.md), run `godseye serve`, and open the
local `/lab#overview` URL. Try the no-key four-number change, or import a compatible
Breakout NPZ and edit a child. The browser's board should gain the new checkpoint
and then its measured comparison. The original must remain unchanged.

To use your own coding agent, open **Use your coding agent** in that local lab and
copy the brief into your existing coding tool. The brief names the actual local
server address and bounds one proposed edit and CPU comparison. Review its proposal
before authorizing writes. The browser observes saved changes every four seconds
while visible. A coding agent running in a remote sandbox cannot reach your Mac's
loopback address; install and run the lab inside that sandbox instead. Do not
expose the local writable server to the internet to bridge this gap.

The public page cannot attach a coding subscription, hold credentials, run Python,
or update weights. The local API is the bridge to an agent you already run. API
provider-driven repair is a separate Docker/operator setup and is not needed for
this CPU test. Qwen and arbitrary model architectures are not supported by the lab.

For each test, report the repository commit, Python/browser versions, checkpoint
and run IDs, whether the result appeared without reloading, whether you could
understand it without coaching, and the first point where you got stuck. Keep a
negative result: a score decrease is useful evidence, not a failed product test.
