# Diagnostic.25 MUSB restart integration review

9 October 2026. NEO-177, completing NEO-108's deferred endpoint restart scope.
Branch: `work/musb-restart-integration`.

The final review found **no actionable Standards or Spec findings**. The
endpoint-owned restart fix, NEO-163 correction, image integration and planned
bounded hardware qualification are complete. Diagnostic.25 can retain this
patch as its reviewed baseline. This closes the defined restart-ownership
work; it does not close the separate controller-removal audit or establish
standby energy savings.

## Fixed scope and method

The review extends the owner's previously agreed pre-NEO-108 baseline through
the tested diagnostic.25 checkpoint:

```sh
git diff 8d8a2e42a147dd4c642e8b03a1ff79b254b192f3...6ac61a357dd0764ef7a4e48a4073508448bc6c06
```

Both revisions resolve and the diff is nonempty: 12 commits, 25 changed files.
The specification is the recorded NEO-108, NEO-163 and NEO-170 scope, with
[report 225](225-musb-resume-request-ownership.md) defining the corrected
ownership behavior and validation limits. Separate reviewers used the
`code-review` skill for Standards and Spec; a third pass checked the retained
artifact provenance. Standards include both applicable `AGENTS.md` files and
the skill's code-smell heuristics. Spec review also examined the patched full
driver context, beyond the changed lines.

This review made no Mac or device connection, changed no runtime settings and
performed no sleep, reboot, image build or physical test. It did not resume
the abandoned SSH-stall investigation. Original evidence remains unchanged.

## Standards

**No actionable findings.**

Patch 0037 fixes request lifetime and restart progress in the driver, consistent
with the project's preference for correcting the underlying layer. The
endpoint ownership flags and comments describe the restart obligation and
temporary runtime-PM reference. The pending-work drainer releases `list_lock`
before callbacks and preserves the first error. Removing its redundant null
callback check is supported by `musb_queue_resume_work()` rejecting null
callbacks.

Repository tasks provide native/ARM32 fixtures, negative controls and isolated
Linux KUnit validation. Test-only hooks stay outside the production patch
queue. Reports distinguish modeled interleavings, kernel integration and
bounded hardware coverage. No speculative fixture refactoring or ownership
abstraction is required for acceptance.

## Spec

**No actionable findings.** No missing requirements, unrequested behavior or
incorrect implementation was found within the agreed NEO-108/163/170 scope.

The production callback retains an endpoint rather than a possibly completed
request, selects the current queue head under the controller lock and coalesces
pending restarts. An overlapping busy giveback retains the restart obligation
with one extra PM reference, released on restart or cancellation. Synchronous
completion advances the owned restart to the current head. Resume-list
callbacks run outside `list_lock`; re-entry, error retention and allocation
failure are covered without silently dropping the remaining work.

The reviewed contexts include endpoint enable/disable, queue/dequeue, giveback
and runtime-resume work. The dedicated fixtures cover completion/free before
resume, current-head progress, same/other-endpoint requeue and allocation
failure. Linux KUnit exercises real locking, completion and reference accounting
with the hardware restart replaced by a test hook. Diagnostic.25 excludes the
unfinished NEO-106 controller-removal stack.

## Evidence provenance

The independently saved review is
`.local/neo177-provenance-review.json`, SHA-256
`5ba18d970bbf31ec61a8552373caf59269d0b1ad5204505599a3d243201cf165`.
All 23 checks pass:

- The exact image manifest, all 344 project-input hashes and source lock match
  this worktree. Kernel release is `6.18.54-gameshellneo24` and image identity
  is `0.1.0-diagnostic.25`.
- The repository's patch exporter reproduces all 32 production queue entries,
  including generated overlay patch 0003. Patch 0037 has SHA-256
  `1f43648b48c14bd29a6aff68bdeb26077bf8d4888f174afb2b24fbf3396e8137`.
  Retained patch files, completed kernel outputs and recovery metadata match.
- The three request/KUnit/ARM-matrix receipts cited in report 225 match their
  recorded hashes in `work/musb-request-resume`. Their recorded source inputs
  remain identical. The only integration source-lock differences are the
  image and kernel version labels; Linux and the patch contents are unchanged.
- All four retained KUnit artifacts, including the executable and result log,
  match their receipt. All seven cases pass. Its source queue contains the same
  32 production patches plus one test-only patch; that hook is absent from the
  image queue. The six ARM configurations' saved object and configuration
  hashes also match.
- The final saved device inspection contains the exact image manifest. The
  completed guided batch, final PM inspection and restored power-policy
  hashes match report 238 and its final validation record.

The initial local audit assumed flat ARM scratch paths and a static overlay
patch. Inspecting the saved compile helper and patch exporter corrected those
audit assumptions to `output/` paths and generated patch 0003. The initial
audit is retained separately as `.local/neo177-provenance-review-initial.json`;
these were audit-script errors, not product failures or missing artifacts.

The six focused evidence-validator unit tests also pass during this review:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/tests -p test_musb_restart_validation.py -v
```

The reviewer observed exit 0 and six passing tests; output is retained in the
review tool response, with no separate on-disk test log.
The expensive native/ARM32/KUnit runs and full image checks are prior,
source-bound results, not newly executed tests. Their reproducible tasks and
original receipts remain in reports 225 and
[232](232-musb-restart-image-integration.md). The already completed full-card
readback in [report 233](233-diagnostic25-installation.md) was not repeated.

## Hardware coverage and limits

Reports [234](234-diagnostic25-pm-qualification.md)–
[238](238-diagnostic25-guided-cable-sleep-qualification.md) establish the
following on the installed CPI v3.1 image and its recorded boot:

| Coverage | Accepted result |
| --- | --- |
| Staged debug prerequisites | Three seven-check sequences: 21 debug passes |
| Actual sleep with USB connected | One initial cycle and four repeats |
| Actual sleep on battery | One RTC-wake cycle, Wi-Fi recovery before separate reconnect |
| Cable changes during actual sleep | Two removals and two insertions; both insertions remain dark until RTC wake |
| Awake USB reconnects after sleep | Four cycles, independent USB access after each |
| Final PM accounting | 31 successes, zero failures: 21 debug checks plus 10 actual sleeps |

All four CPU s2idle counters finish at 10; actual sleep results include
independent timekeeping-freeze evidence. The owner confirmed warning tones,
normal display returns and the guided cable observations. Original keypad,
SDIO usage and temporary-policy restoration pass. Final saved USB and Wi-Fi
access pass. Collection errors remain in the original results and are not
discarded or counted as extra sleep attempts.

These tests do not prove the deferred-request race happened on the board.
The source fixtures and single-CPU UML interleavings do not establish arbitrary
SMP/DMA behavior or real runtime-power transitions. Hardware results do not
establish broader reliability, energy savings, charge acceptance during sleep,
deep retention or power-button wake. The historical image manifest's
`hardware_qualified=false` remains unchanged; later bounded results live in
the qualification reports.

## Disposition

NEO-177's integration review and NEO-108's defined restart-ownership work are
complete. No code change, new image or repeat physical test is required by
this review. The result is retained on `work/musb-restart-integration`; this
does not merge the main checkout or its unrelated user changes.

Separate follow-ups remain for failed-queue DMA mapping, general dequeue
progress outside an owned restart, NEO-106 controller removal, battery energy
and protection during sleep, and the eventual product power-button policy.
They retain their own acceptance criteria in [FOLLOW-UP.md](../FOLLOW-UP.md).
Diagnostic.24 remains the retained recovery image.
