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
| 0010 | Disable/drain AXP USB polling across system suspend and balance wake IRQs on failures | Actual PM/IRQ source regressions, native/ARM32 and complete ARM driver compile passed (report 56). Not installed yet; physical qualification and other PMIC notification work remain separate gates. Remove when equivalent upstream behavior is verified |
| 0011 | Skip absent ULPI bus-control register in Sunxi MUSB context save/restore | Native/ARM32 actual-source register equivalence and complete ARM core/glue compilation passed (report 57). Accessor diagnostics and other controllers are preserved. Not installed yet; repeat USB recovery tests on the next image. Remove when equivalent upstream capability handling is verified |

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
