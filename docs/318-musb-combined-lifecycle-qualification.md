# Joined MUSB startup, wake and Sunxi lifetime qualification

NEO-232 binds new, explicit qualification Tasks to the already-qualified
`musb-terminal-wake` queue. Its 45 patches already carry the startup-runtime-PM
and wake policy functions together with terminal IRQ/wakeup-source cleanup,
Sunxi child retirement and Allwinner PHY detector lifetime. This work adds no
profile alias, production patch, driver fix or semantics bridge.

The purpose is a bounded joined proof for CPI v3.1's peripheral/A33 PIO shape.
It does not promote a kernel/image or clear NEO-98/102/103/106, the clock fault,
physical USB readiness or the separately recorded provider/backend/SMP gates.
DMA work and unrelated held investigations are outside this qualification.

## Exact source and execution boundaries

The unchanged production queue has 33 entries. The selected existing terminal
queue has 45: production33, the ten retirement candidates, unchanged startup0029
and terminal0062 carrying the exact earlier0026 wake-policy function bodies.
The independent wake/startup35 and MPFS-retirement43 profiles remain unchanged.
Report [303](303-musb-terminal-wake-composition.md) records the terminal bridge;
reports [298](298-usb-removal-producer-lifetime.md) and [300](300-mpfs-removal-ownership.md)
record the detector and MPFS slices. This report adds joined qualification rather
than replacing their original evidence or broadening their claims.

The admitted non-test source specification SHA-256 is
`1ce7fd6a292db3d116efda91014bf5cf85ab8999d87b910ae363887b1c99bfca`;
its complete 97,301-entry tree inventory SHA-256 is
`cefbf14db681303831ff3edfd710e98c5d90eb2104567b0ca0c5d48b08345047`.
The explicit retained source is read-only. No full tree is copied, repaired or
relabelled as a new source.

Native tests project complete, pinned actual functions into a bounded host
model. Register, PM, IRQ, work and callback effects are explicitly modeled
there; native success does not establish actual Linux synchronization.

The Linux fixture starts at the complete real `musb_init_controller()` body
after synthetic register mapping and platform-data construction. It uses actual
registered devices, UDC/gadget binding and `musb_gadget_start()`, runtime-PM
accounting, device DPM phases/global IRQ traversal, shared IRQ actions and wake
references, wakeup-source teardown, extcon SRCU dispatch, work draining and
generic-PHY mutex/lifetime APIs. Counting threaded IRQ delivery replaces the
physical ISR. Register banks, clocks/reset effects and electrical pin levels
are test seams. The outer OF/controller resource probe, physical provider graph,
DMA, full-controller interrupt behavior, SMP and real board remain unqualified.

The CPI peripheral configuration uses the actual A33 six-index endpoint shape,
reset/no-configdata flags and Allwinner A33 PHY configuration. Existing work and
detector frames are admitted at their real source entry points. The notifier
hold is inside the actual Sunxi notifier under real extcon SRCU; the worker hold
is inside the actual generic-PHY mode callback; the detector hold is after real
notification, outside the PHY mutex. Each is released and joined before fixture
memory is freed, including assertion/error exits. No retirement wait holds the
MUSB spinlock.

The held detector records the actual source-captured generation and task. Its
access observer also rejects that old task touching a different, live generation;
a final correct cable level cannot hide such an access. The marker clears at
both actual tail exits so reuse of the same worker for a fresh scan remains valid.

## Finite case and control map

| Case | Joined observation |
| --- | --- |
| P01 | Real UDC bind/start, wake disabled, full DPM traversal and normal removal |
| P02 | Real UDC bind/start, wake enabled, full DPM traversal and normal removal |
| P03 | Shared peer wake reference preserved through remove and fresh child rebind |
| P04 | Initial checked runtime-PM failure enters actual probe unwind |
| P05 | Actual PHY-init failure unwinds notifier/work/clock ownership |
| P06 | Foreign wakeup source is rejected and preserved by actual probe unwind |
| P07 | Wake-arm failure balances PM and leaves clean removal |
| P08 | Late DPM failure rolls back and leaves clean removal |
| P09 | Resume disarm failure retains explicit one-attempt terminal wake debt |
| P10 | Initial admitted Sunxi notifier frame blocks synchronous retirement |
| P11 | Admitted actual Sunxi worker blocks backend resource release |
| P12 | Admitted real threaded IRQ action blocks action/backend retirement |
| P13 | Admitted old detector frame cannot access a retired/rebound PHY generation |
| P14 | Late closed producer causes no access; fresh child receives current state |

C01 uses named copies of the complete actual remove/free chain and omits only
terminal wake cleanup. Its quiescent P02 control requires exactly the three
source/capability/core-owner failures, then explicit fixture recovery. C02 copies
the actual Sunxi exit and omits only `disable_work_sync()`. Its quiescent P01
control requires exactly one accepted-late-queue failure, then flushes/disables
that fixture work after the observation. Neither control admits a live unsafe
actor or treats a different failure as success.

Each Linux case has an ordered begin/ownership/cleanup stream. Admission checks
the complete permitted KTAP stream, exact case outcomes and assertion blocks,
source-backed failure diagnostics and successful actor cleanup. Additional
messages, cleanup timeouts, slow-test warnings, stale results or ordinary return
from a control stay inconclusive. Original guest exit and parser exit are
retained independently from the managed container outcome and owner release.

## Disposable read-only test view and resource limits

One generated test-only append modifies three existing translation units and
MUSB Kconfig; its stamp is exactly terminal45 plus that append. Only these five
existing files receive private read-only replacements:

- `drivers/usb/musb/musb_core.c`
- `drivers/usb/musb/sunxi.c`
- `drivers/phy/allwinner/phy-sun4i-usb.c`
- `drivers/usb/musb/Kconfig`
- `.gameshellneo-patches.json`

The private header and three fixture fragments are inlined into the generated
translation units. No new mountpoint or absent source-tree file is needed. A
strict no-fuzz patch replay independently checks the four changed source files.
Before compilation and each execution, complete inventories verify both the
original mounted45 entry and actual mounted46 view. A stamp alone is insufficient.

The generated Kconfig changes only USB_MUSB_SUNXI's exact `ARCH_SUNXI` dependency
to `ARCH_SUNXI || (COMPILE_TEST && KUNIT)` and appends the new test symbol. This
explicit test-only configuration seam allows UML to select the real Sunxi
object with its SRAM/PHY dependencies. It grants no production Kconfig change,
board admission or image selection. The effective configuration must prove
that selection and `MUSB_PIO_ONLY=y`.

The declared incremental disk cap is 384 MiB, with at least 3 GiB free and
128 MiB independent headroom plus the remaining reservation before a new heavy
stage. One output/kernel is built serially. The initial two controls and positive
attempt, plus the separately authorized fresh positive, retain distinct output
directories and use the same frozen kernel/config. Docker is network-disabled,
limited to one CPU/2560 MiB and a private 768 MiB UML temporary filesystem.

The pinned `kunit.py exec` launcher appends `mem=1G`. The dedicated runner instead
launches that same frozen UML kernel with explicit `mem=512M`, a single exact
suite filter and halt policy, then invokes the unchanged pinned parser with UML
metadata. Guest argv, raw exit, parser exit, raw log and JSON hashes are retained.
There is no outer observation deadline, cached-result fallback or automatic
retry. A lost observation requires inspecting the original managed operation.

## Qualification and retained originals

The original native/sanitizer run at `c39f8b2` passed all fourteen families in
both builds. Both controls returned exactly1 with the prescribed three/one
observations in both builds and empty stderr. Its 33 complete function pins and
12 original maintained-input pins are retained. This evidence remains tied to
its original base. The first extractor newline failure, corrected seven-test
host result and subsequent native operation are separate originals.

ARM qualification may explicitly readmit that original native closure only
against exact originalc39 Git blobs and the successful receipt/full outputs.
Default whole-input admission remains strict. Context differences are allowed
only in the owned checker and whole Taskfile, with exact original native
execution/flags/validators and two original Task blocks still unchanged. Every
changed whole-file pin and original-versus-current provenance is recorded.

The genuine ARM run at `af72bb2` passed the same fourteen cases and both exact
controls, matching the native output byte-for-byte. Read-only context operation
`21127` verifies the six existing terminal45 object/configuration receipts:
project, host, dual-role, module, PM without sleep and no PM. Those are historical
builds with exact source/config/ELF pins, not six new executions of this fixture.

The real Linux build at `38fbb2f` completed successfully and selected
`USB_MUSB_SUNXI=y`, `SUNXI_SRAM=y`, `REGMAP_MMIO=y`, `PHY_SUN4I_USB=y`,
`MUSB_PIO_ONLY=y` and the dedicated test symbol. The actual mounted base and
view each have 97,301 entries. The generated46 source specification is
`ec7a8cb01fb3b979523842d2e6af49288ea3ecc6b52aa3badf43453dd0c62258`;
the complete view inventory is
`b90768ef2ccf83cf7104c7516efd826efa1ecd19b5577a5ada97bef8a63e2598`.
Its test append is
`5c61a11f8edb301f241509b84a454a7f62bd968a4044d38f7ea6b5efe5e8b52b`.

The original Linux Task `27877` returned 201 (underlying checker exit1). Its
two controls are valid: each raw guest returned0, parser/managed returned1,
with exactly the prescribed three/one failures and complete actor cleanup.
The initial positive guest reported fourteen passing cases, but the frozen
95-line contract correctly refused an additional real PHY-framework message.
That attempt remains failed admission. Linux `drivers/phy/phy-core.c:244–249`
emits `phy init failed --> -5` when the actual init operation returns the P05
injected `-EIO`. The corrected grammar requires that exact PHY identity/message
once in P05, before the controller/probe errors. Missing, duplicated, misplaced,
wrong-error, wrong-device and other-case messages are rejected. All 27 focused
host checks pass; arbitrary extra diagnostics remain inconclusive.

After the corrected 96-line contract was frozen at `7930d4e`, one fresh positive
operation `23147` passed all fourteen cases and the entire stream. Raw guest,
parser and managed exits were0, with no OOM, error, stop or unresolved owner.
The two original controls were strictly revalidated without replay. The private
single-positive invocation reused the original read-only view/kernel through
the existing inside-guest and managed APIs, used one unique fresh destination,
and had no catch, retry, cached-pass fallback or rebuild. Before execution,
exact source and function comparisons proved that only host diagnostic
admission/tests changed; all generated C/Kconfig/patch/stamp bytes and compiled
kernel/configuration remained identical. Actual mounted inventories were
checked again before this fresh guest.

The shared kernel SHA-256 is
`d06c236d830587da417262d61e5de1c66e60e20c9a181353f3be306026fb726c`;
its effective configuration is
`edd7e94b96b219accff511790b5c7d36ad6173933b77e149f8da6509d9ba139b`.
Failed-final-disarm debt in P09 remains explicitly observed as one attempt;
fixture recovery happens after the observation using its saved valid identity.
No retry or guessed wake-reference decrement is part of the qualified source.

| Original operation | Retained receipt SHA-256 |
| --- | --- |
| Native/sanitizer `97154` | `6f79575e86d8b490d9b23ec7c41c09ceb4c14f228224ef0c2a5426fdc6604db2` |
| ARM `62180` | `e5e378982fffbbd667454a1d7a88b57dc4f0a403ef280966e79b520d192c6402` |
| Historical object context `21127` | `6dc65ad86cc7a4ac0660b5cfff1f464ae0440cade81df708e2032f2ab69ff711` |
| Original Linux `27877` failed admission audit | `424fb29a34c75d1f3d421f9b5444ab8d7ceacd892981216957a425c0beb9d2b3` |
| Fresh Linux `23147` | `0c2a5530a9d8f1a3af830acd2bb0b7be021b06d668d905f3bf5bfc729882f7a9` |

The original managed build run is `d99fdbea49b3485ab381e1ddcc2e3750`;
terminal/work controls are `d19f924913234816b48606da133b7f25` and
`d338d3ccfc524f1cac7d294dd4b72087`. The fresh positive run is
`40b2321c2da24d81a97b1af3c2f1bbbe`. Actual original terminal wrappers,
logs, ownership results, before/after identities and all failed observations
are retained in ignored evidence. There was one kernel build and no
ARM/native/context/control replay for a changed Git ancestry.

Pre-compilation fixture observations also remain separate: the first extractor
newline failure, ambiguous opening-anchor failure, saved-flags signature
correction for `unlock_system_sleep()`, and actual preprocessing that exposed
four corrupted Sunxi ops designators. Temporary function-like aliases now undef
existing I/O self-macros, preserve fields/bare function addresses and wrap only
calls. A real preprocessor guard covers all thirteen Sunxi/PHY aliases; active
source has no mapped member-call/address use requiring interception. These were
fixture/preprocessing observations, not failed production kernels. The initial
two disposable views remain preserved and unexecuted.

## Accepted context and remaining gates

Published dependency `916993715ddceb43b4e03845e4e96a1b3b69aeee` is adopted by
normal merge, preserving both histories and shared navigation/Task sections.
Original native, ARM, kernel and control execution provenance stays tied to
the revisions above. Exact current executable/function/Task/view comparisons
account for changed whole-file context pins without relabelling those old
runs. One final ordinary `task check` at a clean accepted-base checkpoint is
pending; it will be recorded separately from kernel qualification.

Future reproducible heavy qualification uses the saved Tasks with an explicit
verified terminal45 source path and fresh owned outputs. Default prepared-view
and native whole-input guards remain strict. The historical native exception
requires explicit exact originalc39 provenance. The private one-positive route
is a bounded grant-bound historical invocation, not a new general resume API.

Final integration requires independent fresh Standards and Spec reviews and
the root's serialized publication grant. No production queue/profile changed,
no image or device was accessed, and parents NEO-98/102/106 stay open. Other
platform/backend/provider lifetime, failed-power removal, full-controller/ISR,
DMA/SMP, image integration, board-clock admission and physical USB/PM gates
remain separate.

Primary-source authority is the fully pinned Linux6.18.54 source described
above, including MUSB, Sunxi, Allwinner PHY, UDC, PM, IRQ, extcon and KUnit bodies.
The upstream [device-PM documentation](https://docs.kernel.org/driver-api/pm/devices.html)
explains the phase ordering and runtime/system-PM distinction; it does not
establish this fixture's results or the board's physical behavior.
