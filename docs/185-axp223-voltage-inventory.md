# AXP223 charger-control and voltage-byte inventory

7 October 2026. NEO-123. The saved read-only inventory now includes REG34 and
battery-voltage bytes 78/79. Host checks and one awake hardware capture pass.
This narrows the software decoding investigation from
[report 184](184-axp223-measurement-source-audit.md); it does not resolve the
electrical voltage discrepancy or qualify charging during sleep.

## Saved workflow and limits

```sh
task device:charge-inspect
```

Keep USB connected. Schema 2 reads exactly eleven documented addresses:
00, 01, 33, 34, 78, 79, B8, B9, E0, E1 and E6. Existing identity, layout,
cache-mode, continuity, strict read-length/address and private provenance gates
remain. Each register uses one read-only seven-byte `pread`; there is no
buffered read-ahead, raw-bus access or cache bypass. No charging, gauge, display,
alarm or sleep control is changed. E2/E3, IRQ status, vendor-only OCV/resistance
registers and addresses beyond E6 remain excluded.

REG34 is labeled possibly cached. Its raw bit 2 is recorded as a number, with
both contradictory manual interpretations, rather than an authoritative
`enabled` boolean. The supplied Chinese manual says 1 follows charging current;
the English manual says 1 disables that behavior. Neither gives a quantitative
voltage adjustment formula. Recording bit 2 cannot explain an offset by itself.

Registers 78 and 79 must have the expected volatile classification. The report
preserves their values and unused low-register bits, then evaluates both
`(high << 4) | (low & 0x0f)` and the existing Linux helper's
`(high << 4) | low`, multiplied by 1,100 microvolts. Nonzero unused bits do not
necessarily change the formula: they may already overlap set high-byte bits.
No manufacturer latch contract has been established, so these are sequential
byte observations and formula comparisons, not a guaranteed coherent sample.
Neither is a calibrated physical measurement.

The awake charging sampler embeds this same helper; its outer schema remains
unchanged and its inventory record now carries schema 2. Old captures remain
unaltered and retain their original helper hashes. A later volatility fix must
explicitly revise the strict metadata admission before using this helper on
the changed map; this version intentionally rejects such a change.

## Hardware observation

Diagnostic.20, kernel `6.18.54-gameshellneo19`, boot
`d49e0999-5edd-4fe1-9c6e-1c8e17cadfa9`, USB connected:

| Field | Observation |
| --- | --- |
| REG33/34 | `c6/45`, possibly cached; REG34[2]=1, polarity unresolved |
| Voltage bytes 78/79 | `eb/02`; unused low-register bits zero |
| Formula comparisons | Both 4.1382 V; no unused-bit difference in this sample |
| Separate sysfs voltage | 4.1382 V; agreement does not prove an atomic read |
| Battery report | 100%, Charging, instantaneous 3 mA, present, health Good |
| B8, E0/E1 | `c0`, `00/00`, possibly cached; capacity configuration unset |
| Programmed limits | 4.2 V, 1.2 A constant current, USB input limit 900 mA |
| External power | Both reported inputs present and online |
| Continuity | Same boot and PM0/0 before/after; no detected sleep |

This later near-full reading is distinct from the earlier 4.2559 V charging
trace. It establishes neither charger termination nor a correction to that
trace. The 100% gauge, tiny instantaneous current and health label do not
qualify physical battery capacity, voltage accuracy or the pack's limits.

The subsequent saved PM inspection passes the existing image/health validator:
same boot and PM0/0, brightness 1, backlight power 0, with no screen transition,
reboot or sleep requested. No further test is running.

Private evidence beneath `.local/diagnostics/`:

| Capture | SHA-256 |
| --- | --- |
| `20261007T012218.285838Z/inventory.json` | `c94f4168725e7300f91cf8e5971b7291d3ec83d47883f3400898ed5998436b11` |
| Its `provenance.json` | `ca3e70f72a139eecb059de1d3abb86ced8d95ce0f044f738e98a61c9d1ee9e0c` |
| `20261007T012243.316485Z/inspection.json` | `0585363a21b64be4beecf454376dda7c52d71bb5e78db33df077f42adc2d29dd` |

The executed inventory helper SHA-256 is
`cc5cf2d3327b9a15e9b3b6d1286540fa245935ab1e9bf34f4a238111da8495ac`.

## Validation and next work

The focused inventory/baseline suites pass 22 tests. Coverage includes exact
allowlisted read offsets, no register open after rejected metadata, correct
cache labels, read-error cleanup, disputed-bit raw preservation, low-byte
formulas with zero/nonzero unused bits and unchanged standalone composition.
`task check` passes 13 runtime and 618 tooling tests, with the existing optional
user-systemd test skipped, plus compiled checks, shell syntax and ShellCheck.
Logs are `.local/neo123-focused.log` and `.local/neo123-full-check.log`.

Next, correct the documented AXP223 B8 live-status caching at the owning MFD
driver and test the actual source before any new image. Keep the shared ADC
width-mask audit separate from physical accuracy and coherence. Independent
terminal-voltage evidence and battery characterization remain open under
NEO-10; direct sleep-charge attribution remains open under NEO-117.
