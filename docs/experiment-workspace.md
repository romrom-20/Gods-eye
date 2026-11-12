# Connected experiment workspace

The lab keeps the paper, blue-black, lime and coral visual language of the public
site. Its persistent header and activity/navigation rail frame a connected board
and contextual detail inspector. The board is an alternative way to use the
existing controllers, not an additional execution service.

## Objects and evidence

Only loaded checkpoint records and saved comparison records become board objects.
A root has `parent: null`; imported roots remain independent originals with
unverified provenance. A child is linked only to its saved parent ID. Missing
parents are labeled unavailable and receive no invented edge. Checkpoints without
saved comparisons say so. A comparison connects only its actual baseline and
candidate IDs; it displays paired difference, sample count and standard error.
Failed or cancelled jobs appear as status observations in the rail, not successful
evaluation nodes. Job details remain in Compare; agent activity remains in the
existing observed-activity inspector.

Selecting a root or edit opens the existing tensor inspector, selected checkpoint,
patch base, and saved numeric patch. Selecting a comparison opens its paired replay,
score uncertainty and episode observations. Selection does not submit a patch, job,
goal, or import. Node and list buttons work with Tab and Enter; selection moves
focus to the inspector summary. Fit and zoom support the bounded, scrollable board.
Narrow layouts stack the inspector beneath the board and offer the same List view.
The board changes between two-column and wider ancestry layouts to keep objects
readable; it is not an infinite canvas and requires no dragging.

The prominent request action opens the existing supported goal form. Exact review,
consent, admission identity, uncertain-start reconciliation, reload recovery and
cancellation still belong to that controller. The target remains fixed-schema
MinAtar Breakout. Arbitrary model-weight goals are unsupported; the Qwen pilot is
an experimental CLI workflow, not a board-supported model. Goal-service case roots
and evidence are not silently relabeled as local lab checkpoint records. Only
records actually loaded by the local checkpoint/run APIs enter the board.
Interpretability here means tensor values, saved patches and evaluation observations;
the UI adds no inferred causal explanations or invented model internals.

The external-agent affordance links to the API guide and copies a non-secret task
brief. It neither connects a provider nor discovers subscriptions or models.

## Compatibility and safety

All original IDs and `data-view` section boundaries are preserved, including the
source title and goal/overview markers consumed by `export_demo`. The original
import, patch preview/save, CPU comparison, replay, history, export and in-memory
auth controls remain in the inspector. The existing import and goal transport
controllers retain their reconciliation logic.

Static exports initialize the actual four-checkpoint/two-comparison graph from
`demo.json`. Both goal controllers exit before initialization even with
`?goalMode=mock`; no API request or mutation is needed for board selection or
playback. Existing static asset allowlisting and export file sets are unchanged.

## Verification

Run the UI suite with `node --test tests/ui/*.test.cjs` (75 passing), the bundled
contract check with `python -m unittest discover -s tests/browser -p
test_ui_contract.py` (1 passing), and static platform/allowlist checks with
`python -m unittest discover -s tests -p test_platform.py` (10 passing).

Actual Ego browser evidence used temporary loopback fixtures, with outbound
provider transports denied. The existing import journey passed real NPZ import,
root preservation, child numeric edit, a persisted two-game/100-step CPU comparison
(200 baseline and 12 candidate forward calls), disk/browser reload, inert hostile
provenance, and lost acknowledgment reconciliation without duplicate import.
The unconfigured first-use fixture passed the no-key four-game/1,000-step example.
The existing live scripted journey passed review/invalidation, duplicate Start,
negative measured result, terminal reload, expired-plan recovery, lost-start exact
tuple reconciliation, running/cancelling reload and cancellation acknowledgment,
5/10/20-second bounded retries, actual adapter budget stop, unavailable service,
mock separation and the CPU example. These tests make no paid provider calls and
do not claim GPU, cloud, Docker isolation or general model repair results.

`tests/browser/workspace_journey.cjs` adds real graph checks against the import
fixture's exported `/recorded` mount. Run the import journey first to seed a real
imported-root/child/result path. It checks static graph counts with the mock query,
no API traffic, actual tensor and saved-patch selection, paired playback, keyboard
list selection, imported lineage/evidence selection, and desktop/mobile overflow.
It keeps the shared browser task space open for inspection.

Local screenshots are `/tmp/godseye-board-tensor-desktop.png`,
`/tmp/godseye-board-evidence-desktop.png`, `/tmp/godseye-board-mobile.png`,
`/tmp/godseye-board-tensor-mobile.png`, `/tmp/godseye-board-evidence-mobile.png`,
`/tmp/godseye-board-import-lineage.png`,
and `/tmp/godseye-board-no-key-cpu-result.png`. Browser logs are
`/tmp/board-workspace-browser.log`, `/tmp/board-import-browser.log`,
`/tmp/board-goal-browser.log` and `/tmp/board-no-key-browser.log`.
