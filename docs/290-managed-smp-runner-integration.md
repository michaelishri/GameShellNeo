# Managed SMP runner integration (NEO-206)

22 October 2026, Pacific/Auckland. The bounded ARM guest and all ownership
checks passed. Source and documentation reviews found no actionable issues.

The prepared NEO-103 SMP runner supplied custom container names and inspected,
stopped and removed those names after execution. The QMP smoke test also used
Docker interactivity. NEO-194's managed foreground interface rejects these
options and collects terminal containers itself. The runners now use the same
durable stage manager instead of bypassing ownership.

## Exact run and result ownership

`docker-stage.py run --receipt PATH STAGE -- ...` publishes a private run
identity after reservation and before Docker creation. Receipt paths must be
inside the checkout's ignored `.local` directory and existing receipts are not
replaced. `resume --run ID` and `stop --run ID` check the expected run under the
ownership lock before inspecting or acting on a container; a successor rejects.

`tools/managed_container.py` invokes that manager, verifies the recorded
workspace/stage/run and retained log hash, and preserves the terminal result
and original container log in a fresh attempt directory. Completion requires
an observed normal exit, exit zero, no OOM/error and no deliberate stop.
There is no inspect-by-name after the manager removes the container.

If the host observer times out, the helper retains the available pre-stop
status and requests retirement of only its recorded run. Pending removal is
reconciled through the manager. Unknown creation/start ownership or a failed
retirement remains blocking evidence, with an explicit cleanup-pending record;
it is never relabeled a successful run. Accepted logs/results and available
failed guest artifacts remain independent of later Kbuild outputs.

The QMP client supplies its bounded request stream to an in-container pipe.
Docker remains a supported noninteractive foreground command. The guest has
its own timeout, distinct from the host observation limit. The SMP callback
runner uses the unchanged production callback source and the original test-only
hardware/register substitutions in report 274. The broader retirement profile
from report 289 is not included in this production-callback SMP test.

## Validation and original failures

The initial combined ownership attempt retained all twelve original passing
fixture groups but failed while the new runner fixture tried to decode an
unavailable startup status as JSON. The corrected fixture waits for ownership
publication, preserves unavailable status observations and targets its own
receipt during failure cleanup. The original failed attempt remains intact;
no driver fault is attributed to this fixture failure.

The frozen source is `057b50ee0d49c00bef859b322e713de0edb115f2` in
`remaining-smp-validation`. The original failed ownership attempt is
`.local/build/docker-ownership/attempts/ce50af1417b74510bd0403eb630d037c/`.
The corrected standalone new fixture passed before the complete thirteen-group
successor; neither replaced the original attempt.

| Check | Result | Receipt SHA-256 |
| --- | --- | --- |
| Full Docker ownership suite | All thirteen groups pass | `80269e27fdbb6d7636610a0809ddcce7717144c2b0a2cf7f7b80e47404c675c7` |
| QMP smoke | Exactly two ARM virtual CPUs; normal managed exit | `4a2e28685b6ccc78b766136fd970d246abc9991e42cfb7fced8f175462f9c6d5` |
| Real ARM SMP callback kernel | All eighteen cases pass on four guest CPUs under KASAN/lockdep | `0da5114f0a9efc7416eafcac814d17dbe0b23f3baa559c3c036e55bd9437d05c` |

The final Docker attempt is
`.local/build/docker-ownership/attempts/18102acf1da84e3681627ec628eaa76f/`.
Its seven recorded source hashes match, and no pending fixture record remains.
The QEMU receipt at `.local/build/kernel-qemu/receipt.json` retains ten hashed
artifacts and six source hashes, all reverified. Its immutable local image is
`sha256:356fc86704caed8b17cd3b86d4a4b2a3acb44e9d011583a358b4ef1baca6d667`.
The QMP smoke alone does not run a guest kernel or qualify MUSB.

The callback receipt is `.local/build/musb-callback-kunit/evidence.json`, with
ten retained artifacts in
`.local/build/musb-callback-kunit/kernel-5f37eae61b2e78ee/attempts/c3c5e4ded64e410086ee2c32d591e6bb/`.
Its kernel image hashes to
`984cbe61cc323d3f8292f2c8a174c0a886df20d360bb6d3b6a79240fa7b249e9`;
the immutable source-tree digest is
`9b07facbfe8e999c34613d41fa1e630221ff8583d286fbca9d426ee4002dcf97`.
The cases cover resume/suspend/disconnect/reset/setup callbacks in IRQ, timer
and process contexts, two concurrent IRQ callbacks, repeated rebind and an
unstarted unbinder. They exercise real kernel scheduling and callback lifetime
with the recorded hardware substitutions; they do not establish physical USB,
DMA or complete-controller retirement behavior.

Independent final audit re-admits all eighteen cases from both raw logs and
JSON results, verifies all sixteen declared inputs and ten retained artifacts,
and rehashes the complete immutable source tree. The managed result records
exit zero, no OOM, no stop request and no active ownership ledger. The private
audit aggregate `.local/build/smp-validation-result.json` hashes to
`e2ce9960f49847d03ac53e37bd8f5e0e094bffd347489ab9d0c55829409414f3`.

The final combined code at `58eeadd13faf6166c16893b8edfa337406bdeb05` passes
24 runtime and 1,053 tooling tests (two existing optional skips), C checks and
lint. Its receipt in `remaining-final-integration` at
`.local/build/final-host-check.json` hashes to
`61ce63af5fcae11934a34b97a94b0c8fde68c49c89c06e4f93b0f9a531748f18`.
The first run used the restricted sandbox, which blocked five synthetic local
socket fixtures; its complete log/receipt remain as
`final-host-check-sandbox.{log,json}`. The accepted successor used the local
fixture permissions required by the earlier host checks, with no code changes
or live SSH/network experiment.

At `057b50e`, Standards review reports zero hard violations or actionable
smells; Spec review reports no requirement gaps. The later NEO-207 code and its
small shared-fixture refactor also pass both axes. Final review of this report,
report 291, the handoff and follow-up/index updates finds no actionable
Standards or Spec issues. The completed kernel results in report 289 also pass
both final review axes.

This completes the runner compatibility preparation. NEO-103's matching-board
function-driver unbind/bind gate remains
open; electrical USB, DMA and complete controller-removal claims remain
outside the emulated fixture. No image or device change is made.
