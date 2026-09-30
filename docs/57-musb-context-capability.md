# Sunxi MUSB context register capability (NEO-39)

30 September 2026. Implemented against locked Linux 6.18.54; not yet installed.
Diagnostic.7 remains the running image.

## Finding and correction

Each of the five successful devices-stage debug cycles in report 55 emitted
two Sunxi MUSB warnings: an unsupported read and write of the ULPI bus-control
register. The shared MUSB context save/restore functions accessed this register
unconditionally. Sunxi's register translation has no such register: its accessor
returns zero for the read and ignores the write after reporting the error.

Patch `0011-musb-sunxi-context.patch` adds `MUSB_NO_ULPI_BUSCONTROL`, selected by
Sunxi's platform operations. The shared context functions skip only that read
and write when the flag is present. Controllers without the flag retain their
previous behavior. Sunxi's accessors and their diagnostics are unchanged.

The correction applies wherever those context functions run, including runtime
and system PM. It does not change external VBUS handling, controller mode, USB
polling or the separate OHCI controller used by the internal keypad. The
existing external-VBUS setup branch is unchanged; the Sunxi platform does not
select it. The change avoids two unnecessary warning paths per observed driver
cycle, but no energy or elapsed-time saving has been measured.

## Verification

```sh
task test:musb-context
task check:musb-drivers
```

The first task verifies the locked archive, applies the patch and compiles the
actual original and patched context functions with register-access shims. It
uses the source's register definitions and context layouts. Across 256 cases,
all supported register accesses, resulting register values and saved context
matched, with the two unsupported accesses absent only for the Sunxi flag.
Cases cover dynamic FIFO enabled/disabled, missing/present endpoints, session
state and all combinations of the preserved SUSPENDM/RESUME bits. Native and
emulated ARM32 runs passed.

Negative controls reproduce failures for unpatched callbacks, either missing
guard and incorrectly skipping the register on every controller. The check
also verifies that the Sunxi source differs only in its capability declaration,
preserving its diagnostic accessors. `task build` includes this regression.

The second task additionally compiled the complete MUSB core and Sunxi driver
objects for ARM using the full patch queue and locked builder/configuration.
Evidence, source hashes and object hashes are in
`.local/build/musb-context-tests/compile-evidence.json`; logs are under
`.local/build/`. Existing image artifacts are preserved.

These checks use deterministic register shims, not physical MMIO or a running
USB controller. The next image must repeat the saved freezer/devices tests,
require disappearance of these specific warnings, and verify fresh USB and
Wi-Fi SSH plus normal display/input recovery. Keep unrelated invalid-access
warnings visible. Real sleep remains a separate qualification gate.

## Maintenance

The primary sources are `drivers/usb/musb/{musb_core.c,musb_core.h,sunxi.c}` in
the hash-locked archive identified by `build/sources.lock.json`. Remove this
patch once an equivalent capability distinction is verified in the selected
upstream source. Do not remove the checks merely because warnings disappear:
other controllers must continue saving their valid ULPI register.
