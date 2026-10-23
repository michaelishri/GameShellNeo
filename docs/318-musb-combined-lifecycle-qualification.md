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
stage. One output/kernel is built serially. Three fresh suite execution
directories use the same frozen kernel/config. Docker is network-disabled,
limited to one CPU/2560 MiB and a private 768 MiB UML temporary filesystem.

The pinned `kunit.py exec` launcher appends `mem=1G`. The dedicated runner instead
launches that same frozen UML kernel with explicit `mem=512M`, a single exact
suite filter and halt policy, then invokes the unchanged pinned parser with UML
metadata. Guest argv, raw exit, parser exit, raw log and JSON hashes are retained.
There is no outer observation deadline, cached-result fallback or automatic
retry. A lost observation requires inspecting the original managed operation.

## Current evidence and next gates

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

Linux/ARM execution and final current-base host qualification are pending.
The pre-compilation fixture work corrected the saved-flags signature of
`unlock_system_sleep()` and replaced an ambiguous generator opening anchor;
neither was an executed kernel result. The full source/view/stream contract
must be frozen before the separately granted heavy operation. Final integration
requires accepted dependencies, independent fresh Standards and Spec reviews
and the root's serialized publication grant. Parents remain open.

Primary-source authority is the fully pinned Linux6.18.54 source described
above, including MUSB, Sunxi, Allwinner PHY, UDC, PM, IRQ, extcon and KUnit bodies.
The upstream [device-PM documentation](https://docs.kernel.org/driver-api/pm/devices.html)
explains the phase ordering and runtime/system-PM distinction; it does not
establish this fixture's results or the board's physical behavior.
