# Legacy MUSB source reconciliation (NEO-207)

22 October 2026, Pacific/Auckland. The owner requested completion of all
unattended work needed to finish the remaining branch integrations, preserving
open work requiring human interaction. This bounded source reconciliation
starts at `057b50ee0d49c00bef859b322e713de0edb115f2`, after NEO-205's isolated
retirement profiles and NEO-206's managed SMP callback runner adaptations.
The five earlier source histories below can be retired after this result is
reviewed, merged and published; their worktrees and original evidence remain.
This does not close their wider parent tickets or qualify a combined image.

## Pinned histories and retained implementations

| Earlier branch | Reviewed tip |
| --- | --- |
| `work/musb-wake-irq-policy` | `2b6e295cb16947fb12e892d525135883f2f73925` |
| `work/musb-startup-pm` | `2c1bf7d6333c0a6e31607275f98c09e8fb0d191f` |
| `work/musb-callback-lifetime` | `9f5e68c97621fa585dcc5293907e8f361a602e6c` |
| `work/musb-teardown-audit` | `666965f2b18a4dd42c7296c70c5be9d739abff2c` |
| `work/musb-removal-lifetime` | `48af268846453062e205b1023ce39f782f2a7451` |

The source changes in all eleven unique non-merge commits through the final
removal-lifetime tip are mapped as follows. Current implementations and test
scope are retained instead of replaying the older whole-tree snapshots.

| Earlier input | Current disposition |
| --- | --- |
| 0026 checked wake ownership and 0029 startup runtime PM | Original patch bytes retained in `kernel/candidates/musb-wake-startup/`, outside automatic image export; selected explicitly by the offline `musb-wake-startup` profile |
| Wake/IRQ portions of the old sleep fixture | Ported as optional `MUSB_WAKE_STARTUP` sections into the current sleep fixture, retaining current 0033 logical session disconnect and 0037 deferred callback ownership |
| Probe/remove and UDC-start tests | Exact `musb_wake_probe_test.c` and `musb_startup_test.c` retained, with optional orchestration in `tools/musb_wake_checks.py` |
| PM result and RTC wake-error classification | Narrow shared `kernel_fault()` guard and regressions ported to current PM/RTC evidence handling; benign wake metadata remains accepted |
| Callback patch 0030 | Byte-identical to the production patch; current callback fixture/helper retain the original coverage and newer request-completion boundary checks |
| Extcon drain 0031 and provider link 0034 | Byte-identical to isolated retirement candidates 0043 and 0045 |
| Sunxi child-owner 0033 | Superseded by isolated 0044 plus its PHY mode persistence/rebind correction and expanded assertions; the old coverage is retained |
| KUnit integration patches 0032 and 0035 | Byte-identical to `kernel/tests/extcon-notifier-kunit.patch` and `extcon-provider-kunit.patch`; they remain test-only |
| Old overlay notifier/provider C fixtures | Byte-identical to `kernel/tests/extcon-notifier-kunit.c` and `extcon-provider-kunit.c`; no test overlay enters production |
| Native extcon fixture/parser and resolved-configuration tests | `extcon_notifier_test.c`, `extcon_kunit_results.py` and `test_driver_config.py` are byte-identical; current runners/configuration composition and retention/parser tests supersede older versions |
| Historical teardown audit | Exact C fixture retained; checker adapted only for isolated patch lookup, explicit historical scope and a separate work directory; a passing run reproduces old defects and is never current safe-removal qualification |
| Reports and operational instructions | Missing report 132 restored with historical scope/current navigation. Reports 136/137/139/141/144–147 already retained; current Tasks, README and evidence/ownership workflows supersede their old branch commands |

The original untracked `musb_request_resume_audit.c` remains unchanged in the
original removal worktree. It is an earlier baseline reproducer with stale
request/free and stranded-head expectations, rather than a missing correction.
Current endpoint-owned restart regression and retirement suites retain their
separate 48/52-case contracts; this work does not replace them.

## Explicit source profiles and current tests

`tools/kernel_candidates.py` gives wake/startup a named profile containing only
the exact 0026/0029 inputs. `compile_objects(candidate_profile=...)` replays the
complete production queue plus this explicit profile into a separately identified,
read-only source cache. The ordinary exporter, board configuration, lock and
overlay are unchanged. All 33 production patch names and hashes match the
starting point exactly.

The optional checker builds on the current sleep source extraction and adds the
actual IRQ core wake-depth, per-IRQ suspend/flow/resume, MUSB probe/remove,
runtime-get helpers and UDC start wrapper. Current session-disconnect negative
controls, callback admission/drain and deferred resume-work lock boundaries
remain. Probe/startup helpers and the shared callback checker derive their ARM
include/output locations from the selected work directory, so an isolated run
cannot silently compile stale default-suite headers. Production and candidate
outputs use different directories.

Saved unattended commands are:

```sh
task test:musb-wake-startup
task check:musb-wake-startup-configs
task test:musb-sleep
task audit:musb-teardown-baseline
task check
```

The historical audit deliberately extracts only its original MUSB baseline
through patch 0030; it omits later 0033/0037 and retirement candidates. Its
ordering transformations are diagnostic controls, not production proposals.
The default image workflow does not invoke either new candidate/audit task.

Original patch identities:

- `0026-musb-wake-irq-policy.patch`: `fc8c8d43c63d9f31b1d1e821d3492736841ca80be14b0e3d1a3282117b804e84`.
- `0029-musb-startup-runtime-pm.patch`: `6c2193b516144840cc0d367161dd1a454eeb92c0472fee7ef26d576ddcb7a54b`.

## Qualification and retained evidence

Final evidence is recorded after the saved Tasks finish. Early rejected fixture
compilation is retained separately and is not accepted evidence. No maintained
patch was changed to accommodate a test result.

## Remaining software and physical gates

Wake/startup and `musb-retirement` are independent profiles. Exact-context
review confirms 0026/0029 replay against current production MUSB inputs
0011/0025/0030/0033/0037. Combining them unchanged with retirement fails at
0039's `musb_free()` refactor: wake cleanup ownership must be reconciled with
`musb_free_irq()`/terminal IRQ shutdown. That is future software composition
and qualification, not a human-only blocker. Neither current profile claims
to provide the other profile's fixes or a complete removal solution.

NEO-98 remains open for whole-kernel PM/IRQ traversal, allocation/sysfs
concurrency and other-backend/runtime-wake coverage, plus its final disarm
failure limit. The source model explicitly retains unsuccessful final-disarm
debt and cannot prove recovery after object destruction. NEO-102 retains the
separate stop/failed-power teardown design; UDC ignores stop errors and a void
remove cannot safely abandon owned resources. NEO-106 retains caller/global
accessor lifetime, Allwinner PHY detector post-notification access, other
backend/DMA ownership, source masking and inaccessible-hardware software work.
Existing reports/FOLLOW-UP own those wider audits; source reconciliation does
not represent them as completed or merely awaiting a person.

Physical qualification requires deliberate image/kernel identity selection,
complete build/offline checks, card installation and fresh matching-board
startup/wake/reconnect or function-driver unbind/rebind observations. NEO-103's
kernel callback checks retain substituted physical hardware boundaries.
NEO-192 clock admission still blocks fresh PM claims. Existing diagnostic.26
installation/awake prerequisites, physical cable/SD actions and warning/observer
requirements stay in force. No hardware/SSH/Mac/network/PM experiment, image
build or flash is performed by this reconciliation. NEO-154 remains abandoned.
