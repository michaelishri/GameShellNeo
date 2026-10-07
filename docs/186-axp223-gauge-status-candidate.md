# AXP223 live gauge-status caching correction

7 October 2026. NEO-124. Source candidate on `work/axp223-gauge-status`, based
on `e43a061`. Native and emulated ARM32 regressions and a complete ARM MFD
object build pass. No image has been built, installed or exercised on hardware
with this change. The live board remains on diagnostic.20.

## Defect and correction

AXP223 B8 mixes gauge configuration with bit 4, which reports capacity
calibration in progress. Linux 6.18.54 omits B8 from the shared AXP22x volatile
range. A successful first read can populate regcache; a later read then returns
the old byte without reading the PMIC. That can hide a status transition or a
current bus error. [Report 184](184-axp223-measurement-source-audit.md) records
the manufacturer contract and the locked Linux paths.

Patch `0035-axp223-gauge-status-volatile.patch` gives AXP223 its own regmap
configuration and volatility callback. The callback adds B8 alone to the
existing ranges. All existing volatile registers, address limits, write access,
8-bit register/value widths and Maple cache choice remain unchanged. AXP221
and AXP809 still select the original configuration. AXP221 documentation also
supports dynamic bit 4, but AXP809 was not independently documented; this
candidate deliberately confines its behavioral change to the tested board's
PMIC rather than altering the shared table.

The callback uses the existing `AXP20X_CC_CTRL` address constant for B8; this
does not import the older AXP20x register's bit meanings. It adds no polling,
workqueue, gauge programming or charger policy. Reads of B8 now require a live
bus transaction, and cache-only mode returns an error instead of stale status.
Ordinary gauge percentage B9 and battery ADC registers were already volatile.
Thus this defect is **not an established cause** of the voltage discrepancy or
percentage movement, and this change makes no energy-saving claim.

## Repeatable source tests

```sh
task test:axp223-gauge-status
task check:axp223-gauge-driver
```

The runner verifies the locked Linux archive, extracts the actual MFD range/
configuration declarations, the three variant-selection cases, the new
callback, and existing regmap volatility/cache/read-decision functions. It
compiles them with a deterministic bus and cache-storage harness. The complete
`axp20x_match_device()` function is also compared with the original, allowing
only the AXP223 configuration selection to change; the shared declarations
must remain byte-identical.

The native and ARM32 runs cover:

- All 256 addresses on AXP221, AXP223 and AXP809, against independently frozen
  volatile/write-access expectations, including addresses beyond E6.
- All 256 B8 byte values, preserving configuration/reserved bits in returned
  data, plus explicit correction-start/end transitions `c0 → d0 → c0`.
- Ignoring a preexisting stale cached B8 byte, propagating a bus read error,
  rejecting a B8 read in cache-only mode, and reading correctly afterward.
- Preserved caching for ordinary REG33 configuration and B8 on the two
  unchanged variants; no cache population for volatile B8 on AXP223.

The original source fails the corrected behavior. Five additional negative
controls also fail: the wrong B8 address, dropped legacy volatile ranges,
wrong variant routing, changed maximum address and changed write-access table.
Each must compile and then fail an assertion; compilation errors are not
accepted as successful negative controls.

The actual `regmap_volatile()`, `regcache_read()`, `regcache_write()` and
`_regmap_read()` control flow is tested. Cache storage and bus I/O are modeled;
this is not execution of the Maple tree implementation, locking/concurrency,
RSB timing or real PMIC state changes. The readable-address shim represents
the audited map's default readable range. ARM32 runs use the locked builder
and QEMU user emulation, not a booted ARM kernel.

## Build and evidence

`task check:axp223-gauge-driver` also applies the full project patch queue to
verified isolated source, checks all 164 project configuration assertions and
compiles `drivers/mfd/axp20x.o` for ARM. It does not overwrite the installed
image's source, objects or artifacts. The full host check passes 13 runtime and
618 tooling tests; two existing optional checks are skipped in this isolated
worktree (user-systemd recovery and unavailable prepared Armbian source), with
C/shell checks passing. The earlier inventory branch ran the Armbian-dependent
check successfully in NEO-123.

Kernel checkpatch passes with `--no-signoff`. Its default mode reports only the
missing Signed-off-by line: this is a local candidate, not an upstream submission
with an asserted contributor sign-off.

Private evidence:

| Artifact | SHA-256 |
| --- | --- |
| `.local/build/axp223-gauge-status-tests/compile-evidence.json` | `c520797e24cc10f81fa1faa81f9f5f2238c5921b062bbb9e6d1a4336f5b1cce5` |
| Patch 0035 | `99ef36e6a0fa66fc5100e70abc68279ecf6154f10cdeb7d660f6d99d1a6edaa8` |
| Complete ARM `drivers/mfd/axp20x.o` | `be503c9098e1d12658fc4e9ba7e40ad3c5c7056fa96c068a231d515710eb5ebc` |
| ARM configuration | `d370205bf2e4eed5e35483f15372a6785e7d96252d40c343dfee0b2dde37a017` |

The JSON records archive, input, generated-function, builder, full patch queue
and verified source identities. Logs are `.local/build/axp223-gauge-driver.log`,
`.local/neo124-full-check.log` and `.local/neo124-checkpatch-no-signoff.log`.

## Integration boundary

Before installation, assign a new image/kernel identity and qualify the full
build. Update the strict inventory metadata checks to expect volatile B8 on
that specific image, and separate its status provenance from the still-cached
configuration registers. The existing schema-2 inventory correctly rejects this
changed map rather than silently claiming its old cache contract still applies.

An awake hardware check should verify fresh B8 metadata/read success and
unchanged controls, with normal startup and PM qualification. Do not enable
capacity correction simply to provoke a transition. A dynamic-bit transition
may remain unobserved when calibration is disabled. Independent voltage
measurement, ADC byte-coherence/width review, battery capacity characterization
and direct sleep-charge attribution remain separate work under NEO-10/NEO-117.
