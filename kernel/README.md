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
Debian/systemd features, and disables deferred functionality, system suspend,
hibernation and PSCI deep idle. CPU DVFS uses upstream operating points with
the CPU supply correctly linked. Timings, voltage behavior and peripheral
compatibility still require physical qualification.

A33 temperature sensing uses `SUN4I_GPADC`, despite the misleading older-family
name. `SUN8I_THERMAL` alone does not bind the A33 sensor. Both the A33 ADC and
the IIO hwmon bridge are explicitly enabled and asserted in the fragment.
