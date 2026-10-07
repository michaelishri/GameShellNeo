# AXP ADC width correction

7 October 2026. NEO-130. The shared ADC helper has a reproducible low-byte
decoding defect. Patch 0036 corrects it and passes actual-source native/ARM32
regressions and complete ARM driver compilation. Diagnostic.21 remains
installed and unchanged; this candidate is not hardware-qualified.

## Source audit and correction

The hash-verified Linux 6.18.54 archive contains the helper definition in
`include/linux/mfd/axp20x.h` and seven calls in two source files. The checker
scans every archived C/header file and rejects a changed reference inventory.

| Caller | Width contract |
| --- | --- |
| `axp192_adc_raw` | 13 bits for battery charge/discharge current; 12 otherwise |
| `axp20x_adc_raw` | 13 bits for battery discharge current; 12 otherwise |
| `axp22x_adc_raw` | 12 bits, including this board's AXP223 battery readings |
| `axp813_adc_raw` | 12 bits |
| AXP20x USB voltage/current fallbacks | Two 12-bit calls when IIO is unavailable |
| AXP717 USB voltage fallback | One 16-bit call before its separate conversion |

The AXP717 IIO ADC uses a different bulk-read/14-bit masking path and does not
call this helper. The AXP717 USB fallback's downstream modulo conversion is
recorded separately in FOLLOW-UP; it is not changed by patch 0036.

The helper promises 9–16-bit reads from an 8-bit regmap. It shifts the high
register by `width - 8` and then ORs in the low register. Previously, the
entire low byte was accepted. Unused upper bits can therefore contaminate bits
already assigned to the high byte. Applying a mask to the final combined
result does not fix this overlap.

For example, a 12-bit read with high byte `02` and low byte `f3` previously
returned `f3` (243), rather than `23` (35). This is an injected software
counterexample, not an observed GameShell register pair.

The one-line correction is:

```c
result |= reg_val & (BIT(width - 8) - 1);
```

For width 16, the mask is `ff` and all low-byte bits survive. Valid low-byte
values are unchanged for every supported width. The high-then-low reads,
short-circuit error returns, width precondition, scales, charger configuration
and all callers are unchanged. There is no extra bus transaction, retry or
delay. This is a correctness fix, without a measured performance/energy claim.
It does not provide a hardware latch or establish coherent ADC snapshots.
The documentation/analog limits in [report 184](184-axp223-measurement-source-audit.md)
continue to apply.

## Repeatable validation

```sh
task test:axp-adc-width
task check:axp-adc-drivers
task check
```

The first task is included in `task build`. The second also compiles the full
ADC and USB power driver under the board configuration, followed by the full
USB driver with `CONFIG_AXP20X_ADC=n`. Both ARM configurations pass; the latter
is a compilation-only configuration, not a changed board image.

The C harness compiles the complete extracted helper and four IIO callbacks,
including their original channel enums. Only the register bus and framework
types are modeled. An arithmetic oracle checks digit contributions separately
from the driver's shift/OR implementation.

- All 524,288 byte pairs across widths 9–16 pass natively and under ARM32 QEMU.
- All 130,560 valid byte pairs match the original helper, including every
  possible 16-bit pair.
- All 64 helper read-error cases pass, preserving error codes and stopping
  after a failed first read; register order/count are asserted throughout.
- All 57 actual IIO callback cases pass, including variant current widths,
  returned values and unchanged output on either read failure.
- Native undefined-behavior sanitizer execution passes.
- Eight negative controls fail their assertions as intended: the original
  unmasked helper, a fixed 12-bit mask, masking after OR, wrong high shift,
  wrong low-register address, ignored first/second errors, and wrong 13-bit
  caller selection. These failures establish that the checks detect the
  corresponding defects; they are not failed hardware experiments.

The full host suite passes 13 runtime and 626 tooling tests (one existing
optional user-systemd skip), compiled helper checks, Bash syntax and ShellCheck.
Logs are `.local/neo130-host-check.log` and `.local/build/axp-adc-drivers.log`.
No device sleep, charger/gauge write or source regression on hardware was used.

## Read-only hardware comparison

On the unchanged diagnostic.21/kernel `6.18.54-gameshellneo20`, boot
`50dc8224-95e2-4f92-b35e-e35ca5566340`, `task device:charge-inspect` passed with
USB connected. Capture `20261007T034242.541079Z/inventory.json` records
voltage bytes `ec/04`: unused low-byte bits are zero and both formulas yield
4.158 V, matching the separate sysfs observation. B8 is fresh `c0`; reported
controls and 100%/Charging/2 mA telemetry are unchanged from report 191.

This sample would not change with the candidate. It does not explain the
earlier 4.2559 V discrepancy or establish voltage/current accuracy, byte
coherence, calibrated capacity or charge gained during sleep. No guessed
offset or calibration setting was applied.

Final read-only PM inspection `20261007T034920.661973Z/inspection.json` passes
the existing health validator on the same boot at PM12/0, with normal dim
console settings. No new sleep was submitted and no physical action was needed.

## Evidence and next qualification

| Evidence | SHA-256 |
| --- | --- |
| Patch 0036 | `cb84828849caa61875bcdca3732dc6953b1b4ffbd75b6fbedae33b7c4e85452c` |
| `.local/build/axp-adc-width-tests/compile-evidence.json` | `2e18c96dea8fff3addbf4bca2b033ad9fafef95f6306938ba4629985f465817c` |
| Live inventory | `46483a54f98de6438977ba32d9010b9f8c58bac14c077cfc5253ae24ae00fc16` |
| Final PM inspection | `393f6b86d938e7cc67579fa47d947f0323f98020153c89b7500e9a8b109c721d` |

Compiler evidence binds the locked archive, full source-reference inventory,
original/generated/patched sources, script/harness/configuration identities,
native results, sanitizer/ARM32 runs, builder digest and isolated ARM objects.
The ADC/USB project objects and no-IIO USB object have SHA-256 values:

```text
3e56fbe762d8c475d34454bd0433ea013f036044795c41bb1eb29fb265ac698c
a8b17f0aa3ddb63152802361b8e8e56bac5627d630013a23e15499d13447be0e
e6ed9c39be04bbeff9bdf4f3c98ed4dcc272ad489d740c876006f095c6797add
```

Image integration must advance the image/kernel identity and the read-only
inventory contract so its formula labels match the installed helper. Preserve
diagnostic.21 recovery, then qualify startup/readings and relevant PM behavior
after the next card swap. Hardware behavior of other AXP variants is outside
the owner's CPI v3.1 scope. Independent electrical evidence remains necessary
to resolve absolute voltage accuracy; the source correction alone is not that
evidence.
