# Diagnostic kernel patch ledger

Base: Linux **6.18.54**, source and upstream configuration hashes in
[the lock](../build/sources.lock.json). Only CPI v3.1 is targeted.

`tools/kernel-inputs.py --export DIRECTORY` creates the complete patch queue
and content manifest. Existing-source changes live in `patches/`; new source
files and bindings live in `overlay/` and become the third generated patch.
The same queue is applied by `--apply SOURCE` for local compilation. Input
changes require a fresh source extraction; do not silently reuse a patched tree.

| Patch | Purpose | Qualification and removal condition |
| --- | --- | --- |
| 0001 | Fix AXP finite input-current selection before any register side effect | Host test compiles the actual driver helper; replace with a verified equivalent upstream fix |
| 0002 | Wire project drivers, board DT and root compatible into Kbuild/schema | Remove corresponding hunks when support reaches the selected upstream release |
| 0003 (generated) | Fresh CPI3 DTS, panel/backlight implementations, bindings and current-limit helper | Compile/DT checks establish software integration only; hardware tests remain NEO-5 |
| 0004 | Describe GPIO hog children already supported by the sunxi GPIO driver | Remove when the upstream pinctrl schema accepts these standard GPIO nodes |
| 0005 | Stop NKMP factor search at its first exact match, preserving selected factors | Native/ARM32 equivalence and NEO-12 hardware checks passed; about 92% lower recorded governor CPU time at unchanged policy (report 33). Remove when an equivalent upstream optimization is verified |
| 0006 | Order AXP USB resource release as IRQs, polling work, then power supply | Actual-source host lifetime regressions and isolated ARM object build passed (report 38); installed in diagnostic.4, with hardware results in report 40. Normal integration does not exercise every teardown race. Remove when the selected upstream source has equivalent lifetime ordering |
| 0007 | Read effective rate constraints once per fixed-parent NM/NKM search | Native/ARM32 rates and factors match; isolated ARM clock-object builds passed (report 39). Installed in diagnostic.4, with hardware results in report 40; no attributed board timing or power measurement. Remove when equivalent upstream behavior is verified |
| 0008 | Opt-in CPI/AXP223 fixed-peripheral absent polling, with graph/configuration gates and IRQ-preserving rearm | Native/ARM32 policy, lifecycle and compiled-board regressions passed. Report 41 records diagnostic.5 build evidence and pending physical qualification. Keep disabled elsewhere; no charging writes or measured battery gain. Remove if an equivalent upstream policy is verified or the experiment fails qualification |
| 0009 | Opt-in USB callback counters and bounded poll-read error injection | Diagnostic.6 source/ARM/board and hardware checks are in reports 51–52. Defaults off; diagnostic.7 omits this opt-in along with experimental polling. These are diagnostic controls, not production energy measurements; remove when the investigation no longer needs them |
| 0010 | Disable/drain AXP USB polling across system suspend and balance wake IRQs on failures | Actual PM/IRQ source regressions, native/ARM32 and complete ARM driver compile passed (report 56). Installed in diagnostic.8 and ordinary-stage qualified in report 60; other notification work and parent wake-error propagation remain gates in report 68. Remove when equivalent upstream behavior is verified |
| 0011 | Skip absent ULPI bus-control register in Sunxi MUSB context save/restore | Native/ARM32 actual-source register equivalence and complete ARM core/glue compilation passed (report 57). Installed in diagnostic.8 with zero unsupported-register warnings across seven driver cycles (report 60). Accessor diagnostics and other controllers are preserved. Remove when equivalent upstream capability handling is verified |
| 0012 | Disable/drain Sun4i PHY cable detection across system suspend, rescan on resume and reject reads after PHY exit | 148 actual-source scenarios passed natively and on ARM32, six native negative controls rejected, and complete ARM driver compiled (report 69). Installed in diagnostic.11 (report 73); ordinary devices-stage results and the unresolved Wi-Fi failure are in reports 74/78. Actual sleep remains unqualified. Remove when equivalent upstream behavior is verified |
| 0013 | Freeze power-supply notification execution before device suspend and replay queued changes after device resume | 68 actual-source modeled scenarios passed natively and on ARM32, five native negative controls rejected and complete ARM core compiled (report 71). Requires the suspend freezer; preserves change/wake accounting. Installed in diagnostic.11, with board-specific ordinary-stage results in reports 74/78. Core-wide behaviour on other boards and actual sleep/wake policy remain unqualified. Remove when equivalent upstream behavior is verified |
| 0014 | Report brcmfmac KSO/clock/sleep errors, balance retune cleanup and revalidate uncertain state after partial transitions | 95 actual-source scenarios pass natively/ARM32, 12 native negative controls reject and the complete changed ARM SDIO object compiles (report 81). Built/offline-verified in diagnostic.12 (report 85); hardware qualification remains NEO-58. Remove when equivalent upstream failure, state and cleanup handling is verified |
| 0015 | Lock brcmfmac worker collection, bound its wait, thaw on collection timeout, protect completion reuse and centralize normal state/watchdog restoration | 44 lifecycle scenarios plus PM-disabled checks pass natively/ARM32, ten native negative controls reject, and complete ARM bcmsdh/SDIO objects compile (report 82). Built/offline-verified in diagnostic.12 (report 85); retained-power hardware qualification remains NEO-58. Remove when equivalent upstream collection, lifetime and ordering handling is verified |
| 0016 | Check retained-power transitions and wake ownership, roll back failed suspend, isolate firmware I/O after failed restore and complete pending control requests | 89 actual-source scenarios pass natively/ARM32, 25 negative controls reject, and the complete ARM driver compiles in normal/debug configurations (report 83). Includes a debug-error host-release fix. Built/offline-verified in diagnostic.12 (report 85). Failed restore requires a cold restart; patch 0017 handles reset/PM ownership, while hardware IRQ behaviour and automatic recovery remain open. Remove when equivalent upstream transaction, I/O and cleanup handling is verified |
| 0017 | Serialize shared SDIO PM/reset/removal state with F2's device lock, retire parked workers before removal, track power-off ownership and defer sleeping IRQ status reads | 102 native/ARM32 scenarios and 13 negative controls pass (report 84). Complete normal/debug ARM compilation is recorded there. Reset conflicts return busy; no automatic retry/recovery is added. Built/offline-verified in diagnostic.12 (report 85); hardware IRQ rates and sleep/resume qualification remain open. Remove when equivalent upstream lifecycle and IRQ ordering is verified |
| 0018 | Stop packet work after wake/clock/status failures, complete control waiters, quiesce IRQs from process context and protect OOB rearm against teardown | Native/ARM32 fault and lifecycle regressions in report 89; built/offline-verified in diagnostic.13 (report 91) and installed with passing baseline checks (report 93). A fatal error requires cold restart; automatic recovery and hardware qualification remain open. Remove when equivalent upstream propagation, isolation and ownership behavior is verified |
| 0019 | Propagate parent wake errors for atomic parent chips without wake registers; track PEK/RTC/AC arm and cleanup ownership | Actual IRQ-core/callback native and ARM32 failure tests, five negative controls and all four full ARM objects pass (report 100). Slow-bus/wake-bank fallback remains unchanged; hardware wake and lockdep qualification remain open. Remove when equivalent upstream error and reference handling is verified |
| 0020 | Defer country firmware commands between wiphy suspend/resume under RTNL; apply the latest valid request on resume and report replay errors | Sixteen actual-callback scenarios pass natively/ARM32, nine negative controls reject and the complete ARM cfg80211 object compiles (report 106). Deferred errors fail wiphy resume and close interfaces; hardware qualification is NEO-84. Not installed in diagnostic.14. Remove when equivalent upstream exclusion, request preservation and error handling are verified |
| 0021 | Drain network transmitters at wiphy suspend and retain an independent queue stop through bus/configuration restoration | 109 actual-function scenarios pass natively/ARM32, twelve negative controls reject and complete ARM core/cfg80211 objects compile (report 109). Includes concurrent modeled transmit/flow lock ordering and failed-resume carrier policy. Diagnostic.15 remains unchanged; hardware qualification is pending. Generic DOWN/error lifetime is unchanged. Remove when equivalent upstream queue ownership and restoration is verified |
| 0022 | Return failed required capability reads and transport errors, preserve optional legacy rejection defaults, and finish scalar queries before channel mutation | 85 actual-function scenarios pass natively/ARM32, ten negative controls reject and full ARM cfg80211 compiles (report 110). Bounds RX-chain count to the HT/VHT representation. Internal channel transaction, raw firmware rejection attribution and hardware qualification remain open. Not installed in diagnostic.15. Remove when equivalent upstream failure and bounds handling is verified |

Patch 0023 balances the Sunxi SDIO interrupt's runtime reference only on
enabled-state transitions under the existing IRQ lock, preserving every IMASK
write and independent users' references. The actual host/core source passes
2,058 native/ARM32 cases and rejects eight negative controls; complete ARM
host/core objects compile. `task test:sunxi-sdio-refs` and
`task check:sunxi-sdio-driver` reproduce these checks. Diagnostic.17 will
qualify the candidate against the recorded per-cycle count growth; hardware
and energy claims remain pending. Remove the patch when equivalent upstream
ownership is verified. See [report 117](../docs/117-sdio-runtime-reference-ownership.md).

Patch 0024 prints the saved endpoint result in `udc_log_ep`, correcting a
shadowed local variable in the generated trace printer. It changes no USB
operation or event layout. The actual formatting expression passes 252 cases
natively/ARM32 and rejects three negative controls; the complete ARM UDC core
compiles. Use `task test:udc-trace` or `task check:udc-driver`.
[Report 127](../docs/127-usb-endpoint-trace-format.md) records the evidence and
pending image/live qualification. Remove when equivalent upstream formatting
is verified.

Patch 0025 owns a temporary system-sleep pull-up gate for fixed peripherals
with USB system wake disabled and without `MUSB_PRESERVE_SESSION`. It preserves
connection intent, drains pending work outside the spinlock, masks saved
SOFTCONN during restoration and reconnects after successful resume work.
Worker PM failures skip MMIO; unregister-generated work is drained; the first
pending callback error remains observable. `task test:musb-sleep` executes
actual functions natively/ARM32; `task check:musb-sleep-drivers` also compiles
the complete controller/gadget/Sunxi objects. Hardware reconnection remains
unqualified. Remove when equivalent upstream lifecycle ownership is verified.
See [design](../docs/126-musb-system-sleep-design.md) and
[candidate](../docs/128-musb-system-sleep-candidate.md).

Patch 0026 is a separate NEO-98 source candidate, absent from diagnostic.18.
It balances the probe-time IRQ-wake reference, preserves the enabled default
for supported fresh controllers, and checks owned system-sleep arm/disarm and
cleanup before backend teardown. Failed disarm remains owned and reported;
foreign capability/source/wakeirq arrangements are rejected unchanged.
205 native/ARM32 source scenarios and 22 negative controls pass, including
actual probe/remove functions and per-IRQ PM/dispatch helpers. Six ARM driver
configuration builds pass for the unchanged patch. Whole-kernel PM/IRQ traversal,
other-backend runtime wake and hardware qualification remain open. Permanent
teardown disarm failure remains an explicit limitation. Use
`task check:musb-wake-configs`; [report 132](../docs/132-musb-wake-irq-candidate.md)
defines the tested scope. Remove when equivalent upstream ownership and error
handling are verified. Assign a new image/kernel identity before image assembly.

Patches 0014–0017 are integrated for image qualification in
[diagnostic.12 preparation](../docs/85-diagnostic12-preparation.md). The ledger's
source-test results do not establish hardware recovery or energy savings.
[Installation and baseline checks](../docs/86-diagnostic12-installation.md)
pass. [Ordinary PM-stage hardware checks](../docs/87-diagnostic12-pm-validation.md)
also pass across five driver cycles, with both network routes and original
keypad connection retained. Failure injection, precise sleep-gap IRQ behaviour
and actual sleep remain unqualified; transient Wi-Fi retries remain under
investigation.

[Deferred status/DPC tests](../docs/88-wifi-deferred-interrupt-service.md)
extend this with 23 native/ARM32 scenarios and 14 negative controls against
unchanged diagnostic.12 sources. Four scenarios characterize existing worker
error limitations; they do not qualify recovery or hardware IRQ timing.
[Worker error handling](../docs/89-wifi-worker-error-handling.md) converts those
limitations into checked failures in patch 0018, with a separate source-test
task. Diagnostic.13 integrates that candidate; reports 91 and 93 record its
preparation and running baseline.

## Provenance and limits

- Board wiring, regulator settings, LCD timings and four register/value pairs
  are derived from Clockwork's CPI3 schematic and the GPL/X11 DTS/GPL display
  sources in GameShell commit `523cf591e2f955d001d257d7c850406f9fd917eb`.
  Existing code is reference material; no historical patch queue is applied.
  The schematic maps the LCD connector VDD to DCDC1's VCC-3V0, I/O supplies
  to ALDO1, and joins DLDO1/2/4 on the radio rail. Those radio outputs remain on.
- The new DRM panel owns standard prepare/enable/disable/unprepare. Its GPIO
  SPI transport preserves the idle-high clock/rising-edge sample sequence.
  Upstream spi-gpio does not enforce its requested bit delay; the DT frequency
  is not a measured upper bound. Qualify the transport on this board.
  The first image does not establish independent cold initialization after a
  panel rail cut; the bootloader initializes the display and reset timing is
  not yet documented. No invented reset pulse is used.
- OCP8178 adapts [Wim de With's GPL-2.0-only v4 driver](https://lkml.iu.edu/2608.3/04616.html),
  preserving attribution and pulse timing. Lifecycle additions hold CTRL low
  for 3 ms, re-enter one-wire after off, serialize writes, and defer illumination
  until DRM enables the panel. The 16-page datasheet mirror is linked in report23.
  Initial brightness 1 preserves the old installation's controller code.
- The AXP correction retains the variant tables and rejects non-finite requests.
  It does not resolve the conflicting AXP223 selector-10 documentation, program
  a startup current limit, or prove whole-port current limiting.
- Only standard backlight, DRM, input, regulator and power-supply interfaces
  are exposed. There is no writable LCD/backlight bytecode or private `/proc` API.

The kernel fragment starts from upstream `sunxi_defconfig`, enables required
Debian/systemd features, and disables deferred functionality, hibernation and
PSCI deep idle. Diagnostic.7 enables system-suspend/debug infrastructure only
for explicit freezer/devices tests, while normal systemd sleep remains masked.
USB experiments remain off with their existing PM_SLEEP refusal guard intact.
The SDIO node advertises `keep-power-in-suspend`, matching brcmfmac's retained
power request when card power-off is not enabled; no radio wake or full card
power-off is qualified. See [report 54](../docs/54-staged-pm-diagnostic.md).
The next diagnostic fragment also enables dynamic debug and event tracing for
the opt-in keypad recorder, with function instrumentation disabled. Trace
capture and recovery are documented in [report 58](../docs/58-keypad-pm-investigation.md);
this does not change keypad power policy or enable normal sleep.
CPU DVFS uses upstream operating points with
the CPU supply correctly linked. Timings, voltage behavior and peripheral
compatibility still require physical qualification.

Diagnostic.10 brings forward the upstream A33 digital/analogue codec, DAI and
simple sound card for speaker confirmation cues. The standard simple amplifier
owns PL3 and follows the board's AC-coupled stereo route. Its PS supply voltage
is deliberately unspecified; no audio driver patch is added. The upstream
700 ms analogue startup delay is retained. Quiet playback, mixer/idle
restoration and one audio-assisted input/driver PM test passed on CPI v3.1.
Normal sleep remains disabled; actual sleep, headphones and idle power remain
unqualified. See [preparation report 65](../docs/65-speaker-confirmation-cues.md)
and [hardware report 66](../docs/66-speaker-hardware-validation.md).

A33 temperature sensing uses `SUN4I_GPADC`, despite the misleading older-family
name. `SUN8I_THERMAL` alone does not bind the A33 sensor. Both the A33 ADC and
the IIO hwmon bridge are explicitly enabled and asserted in the fragment.

`task test:nkmp` checks patch 0005 against the actual functions extracted from
the hash-verified Linux archive. It compares rates and all four selected factors
on native Linux and emulated ARM32, including every output boundary and its
neighbors for the tested constraints, plus the A33 CPU operating points.
The arithmetic shim models `do_div`'s quotient, not its kernel implementation
or timing. See [report 33](../docs/33-nkmp-clock-search-optimization.md).

`task test:usb-lifecycle` extracts the actual probe, IRQ and poll functions from
the hash-verified Linux archive and runs deterministic managed-resource/work
shims. Its negative control reproduces the old ordering failure; the patched
code covers immediate IRQs and partial-probe unwind. `task check:usb-driver`
also compiles the complete driver for ARM in isolated scratch, preserving the
installed-image build artifacts. These checks do not execute kernel concurrency
or physical PMIC transactions. See [report 38](../docs/38-usb-work-lifetime.md).

`task test:clock-ranges` compares actual NM/NKM searches, comparators and clock
boundary code from the verified archive, natively and on ARM32. It checks fresh
constraints, ties, arithmetic extremes and reduced getter calls. The exported
comparator and parent-adjusting search retain their previous behavior.
`task check:clock-drivers` additionally builds complete affected clock objects
in isolated scratch. These are computation and integration checks, not physical
PLL, power or timing measurements. See [report 39](../docs/39-clock-rate-constraint-optimization.md).
