# Charging-voltage evidence gap and a fresh-register diagnostic

10 October 2026. NEO-10 source investigation, with no device connection,
charger write, calibration change or new hardware result.

The next useful software step is a narrowly scoped, driver-owned diagnostic
that reads charger controls directly through the existing regmap. Linux
6.18.54 already provides the required single-register primitive:
`regmap_read_bypassed()`. It can distinguish an ordinary possibly cached value
from a fresh bus value without rewriting the cache. It does **not** establish
physical battery voltage, and its deliberate override of cache-only mode means
that PM and device lifetime must be addressed before exposing it.
[Regmap implementation][regmap].

This advances the source/API question left by
[report 184](184-axp223-measurement-source-audit.md). It does not identify the
cause of the recorded target/readout discrepancy or close NEO-10.

## What the existing evidence does and does not exclude

| Evidence | Supported conclusion | Remaining uncertainty |
| --- | --- | --- |
| Documented voltage conversion, checked against the IIO and battery drivers | The implemented 1.1 mV-per-code scale agrees with the manufacturer table | Resolution is not absolute accuracy; a guessed offset has no evidential basis |
| Patch 0036 masks unused low-byte bits; the recorded `ec/03` sample has none set | The represented software defect is fixed, and both old/new formulas agree for that captured sample | That later sample cannot explain or invalidate the earlier 4.2559 V observation; ADC byte coherence is still unspecified |
| Patch 0035 makes B8 calibration status volatile on AXP223 | B8 status reads no longer reuse a cached byte | This does not make REG33/34 fresh or establish why voltage/percentage changes occurred |
| Inventory REG33/34=`c6/45`; reported target 4.2 V | Recorded ordinary reads have the documented target encoding and raw REG34 bit 2 set | The inventory and target getter may share the same cached control byte; their agreement is not an independent live-register check |
| Later 100%/Charging, small instantaneous current and a lower reported voltage | Those are the observations at those later instants | They do not independently calibrate the ADC, validate termination or establish the unidentified pack's limits |

The conversion and register descriptions are in the supplied
[AXP223 Chinese manual, pp. 28 and 40][cn28]. The installed corrections and raw
sample are recorded in [report 194](194-diagnostic22-installation-and-adc-validation.md).
The target getter calls ordinary `regmap_read()` for REG33; the existing
inventory reaches the same API through regmap debugfs.
[Battery driver][battery], [regmap debugfs][debugfs],
[inventory source](../tools/charge_inventory.py).

The REG34[2] polarity conflict between the Chinese and English manufacturer
manuals remains unresolved. A fresh value of 1 would establish the bit value,
not an authoritative compensation-enabled state or a voltage adjustment amount.
[Chinese p. 40][cn40], [English p. 43][en43]. The prior audit's ADC-accuracy,
read-latch and pack-identification gaps also remain; this investigation found
no source-backed reason to apply a correction or change charging policy.
[Report 184](184-axp223-measurement-source-audit.md),
[pack identification](30-bl5c-battery-identification.md).

## The existing kernel primitive and its limits

The pinned implementation performs the following under the map's normal lock:

1. Save `cache_bypass` and `cache_only`.
2. Set bypass true and cache-only false.
3. Call `_regmap_read()` for one register.
4. Restore both flags and release the lock, including on a read error.

With bypass set, `_regmap_read()` skips both cache lookup and cache population.
It still checks register readability, calls the configured bus reader and
returns that reader's error. Thus a failed bus read does not fall back to a
cached success. For this direct, unpaged AXP223 register map, the proposed
REG33/34 reads do not require a register-window selector write.
[Regmap implementation][regmap], [AXP223 configuration patch](../kernel/patches/0035-axp223-gauge-status-volatile.patch).

This is materially different from toggling `cache_bypass` through debugfs or
calling `regcache_cache_bypass(true)`, reading, then toggling it back. The setter
locks only its own flag update. Separate calls leave an interval in which other
regmap clients can observe the changed mode. The scoped read keeps the change
inside its own locked transaction. It should be called normally by the owning
driver, not while that caller manually holds the same non-recursive map lock.
[Regcache setter][regcache], [regmap implementation][regmap].

The kernel's existing `read_bypassed` KUnit case already constructs different
cached and backing-register values and checks that bypass returns the backing
value while restoring cache-only mode. This is useful test infrastructure to
extend, not a test run or board qualification performed by this report.
[Pinned KUnit source][kunit].

Two boundaries matter for a follow-up implementation:

- **Cache-only is deliberately overridden.** A prior userspace observation of
  `cache_only=N` is not admission synchronized with a later read. The diagnostic
  needs a reviewed awake/system-sleep and device-removal contract at its owning
  driver; this API alone supplies neither. The RSB reader already obtains and
  releases a runtime-PM reference around each transaction, but the RSB driver's
  separate noirq system-suspend path resets the controller. Runtime-PM handling
  is not evidence that arbitrary access during system sleep is supported.
  [RSB read and PM callbacks][rsb], [MFD lifetime][mfd-rsb].
- **Two reads are two transactions.** REG33 and REG34, or ordinary and bypass
  reads of REG33, are not an atomic multi-register snapshot. Other legitimate
  register writers can run between them; the battery driver exposes charger
  setters using regmap updates. A differing pair is an observation requiring
  writer/order investigation, not automatic proof of a stale cache. Even an
  ordinary → bypass → ordinary pattern does not exclude an intervening
  change-and-restore. [Regmap implementation][regmap], [battery setters][battery].

## Bounded follow-up implementation and acceptance

The recommended candidate is a diagnostic attached to the existing owning
AXP223 driver/map, with a fixed REG33/34 allowlist, one bounded request, explicit
per-read errors and recorded ordering/time brackets. Preserve raw bytes and
label normal versus bypass provenance. Restrict the initial implementation to
the documented AXP223 variant; do not expose arbitrary PMIC addresses, IRQ
status, raw bus access, charger writes, cache sync or an automatic repair.
REG33/34 are documented RW controls with no specified read-clear behavior;
the purpose is to observe them. [Chinese p. 40][cn40], [English pp. 42–43][en42].

The driver proposal must resolve removal, system-sleep admission and lock order
before implementation is considered complete. Do not add a new userspace bypass
toggle to the current inventory as a substitute. Preserve that inventory's old
schema/provenance, then explicitly admit a new diagnostic/image contract only
after the corresponding implementation exists.
[Current inventory](../tools/charge_inventory.py).

Source tests should exercise the actual regmap primitive and the new diagnostic
wrapper with differing cached/hardware values, both bus-error positions,
unchanged cached contents and flags on every exit, the exact address/read-count
allowlist, zero charger writes, and concurrent ordinary map clients. Tests for
the proposed PM/removal admission must demonstrate that rejected operations
never reach the bus. Use the real kernel locking/lifetime paths for concurrency
claims; a mocked mutex cannot establish them. Compile the complete affected ARM
driver and retain failures as failures rather than substituting a cached value.

An eventual awake board capture could corroborate the control bytes on that
boot while leaving settings unchanged. Matching ordinary/bypass values would
close that contemporaneous provenance gap only. Different values would justify
tracing their writer/initialization history before proposing any correction.
Neither result resolves REG34's documentation conflict or supplies an independent
measurement of voltage at the battery terminals.

## What still needs evidence outside this software path

Separating physical terminal voltage from ADC gain/offset error requires an
independent, suitably characterized voltage reference or measurement. Repeated
sysfs, debugfs and IIO reads from this same ADC are not independent references.
A timed discharge and the pack's advertised capacity also cannot calibrate a
voltage channel. Appropriate terminal measurement and manufacturer-specific pack
limits remain distinct missing evidence, as recorded in
[reports 29](29-hardware-qualification.md#charging-voltage-discrepancy-neo-10)
and [30](30-bl5c-battery-identification.md). The available software evidence
therefore cannot certify the physical charging voltage or attribute a fixed
55.9 mV adjustment to REG34.

No extended charging experiment, ADC-offset patch or PMIC-control write is
justified by this source audit. NEO-10 remains open with a concrete, bounded
fresh-control diagnostic lead and explicit limits on what that lead can resolve.

## Source provenance

The audit used the locally prepared Linux 6.18.54 source selected by
[sources.lock.json](../build/sources.lock.json), with the existing project patch
queue. The relevant unmodified infrastructure files have these SHA-256 values:

| File beneath `drivers/` | SHA-256 |
| --- | --- |
| `base/regmap/regmap.c` | `5ad5df5cfbd6bccee21c47f3acebf41f59428da5a49a3a3d1b103eb29510ee28` |
| `base/regmap/regmap-kunit.c` | `06704659a84cd2c60472f98739b7b26a1e3144d3ef88eb1462f9dad334d22641` |
| `base/regmap/regmap-debugfs.c` | `7aa0eae06e643bc3e0f8c2489f40644d348292f41f3678eada92482efffb8566` |
| `bus/sunxi-rsb.c` | `25db5e4d8dda62defe42ade3ea7e96e8abebec7a4466cdb87ab9314a3bef175f` |

The kernel.org page could not be retrieved through the web reader during this
audit; implementation claims above were checked directly against those local
files, not inferred from the inaccessible page. The supplied Chinese PDF was
read locally, and the X-Powers-authored English PDF was available from its
linux-sunxi mirror. Report 184 records their full document identities.

[regmap]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/base/regmap/regmap.c?h=v6.18.54#n2823
[regcache]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/base/regmap/regcache.c?h=v6.18.54#n596
[kunit]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/base/regmap/regmap-kunit.c?h=v6.18.54#n390
[debugfs]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/base/regmap/regmap-debugfs.c?h=v6.18.54#n215
[battery]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/power/supply/axp20x_battery.c?h=v6.18.54
[rsb]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/bus/sunxi-rsb.c?h=v6.18.54#n333
[mfd-rsb]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/mfd/axp20x-rsb.c?h=v6.18.54
[cn28]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=28>
[cn40]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=40>
[en42]: https://linux-sunxi.org/images/e/e5/AXP223_Datasheet_V1.0_en.pdf#page=42
[en43]: https://linux-sunxi.org/images/e/e5/AXP223_Datasheet_V1.0_en.pdf#page=43
