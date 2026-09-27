# Driver optimization and lifecycle audit

Date: **2026-09-28 NZDT**. Ticket: **NEO-16**.

This is a source audit for the owner's CPI v3.1. It identifies work that can
be developed and checked on the Intel host without using the GameShell or Mac.
It does not report new power measurements, hardware tests or deployed changes.

## Findings and order of work

The best next algorithmic candidate is reducing repeated clock-rate constraint
lookups inside fixed-parent factor searches. The best small project-driver
candidate is avoiding repeated backlight commands when the commanded state is
already valid. Separately, display shutdown ownership deserves a correctness
cleanup. USB work cancellation is already tracked as NEO-17; the experimental
polling policy remains the distinct work described in [report 36](36-usb-polling-policy.md).

| Finding | Concrete opportunity | Host-only work | Hardware still required |
| --- | --- | --- | --- |
| 1. Fixed-parent clock searches | Query stable rate limits once per search; consider narrowly proven exact-match exits | Actual-function equivalence, lookup counts, ARM32 arithmetic and object compilation | Display/startup regression and actual latency, if a patch is selected |
| 2. OCP8178 repeated requests | Skip duplicate brightness transactions and a repeated, already completed off delay | GPIO/delay event tests, retry and invalidation tests, compilation | Brightness/off-on checks and eventual suspend/resume |
| 3. RSB runtime power management | Match controller autosuspend policy to measured gaps between transactions | Source analysis and a bounded experiment specification | Runtime suspend residency, resume cost, errors and battery comparison |
| 4. Panel shutdown ownership | Let the display controller own the normal DRM shutdown sequence | Shutdown call graph, error-path tests, compilation | Reboot/power-off/blanking and removal behavior |
| 5. USB delayed-work lifetime | Cancel the worker before its power-supply object is released | Managed-resource ordering and injected probe-failure checks | Later integration regression; no intentional live unbind tonight |

The scope is deliberately bounded. None of the first four findings implies
the current image wastes a measured amount of battery power. Setup, modeset
and shutdown work must not be described as continuously recurring idle work.

## Source baseline

The inspected kernel is the locked **Linux 6.18.54**, commit
`1b357ecb321392158d507b04672ffee57bfa071d`, with project sources under
`kernel/overlay/`. The local kernel tree already includes the shipped NKMP
exact-match optimization, patch 0005. Its measured result belongs to NEO-12
and is not a new finding here. Source identity and the existing patch ledger:
[source lock](../build/sources.lock.json), [kernel ledger](../kernel/README.md),
[NKMP results](33-nkmp-clock-search-optimization.md).

Code references below name functions and link to the corresponding stable
source or the checked-in project implementation. The local copies in
`.local/sources/linux-6.18.54` were read directly; upstream links make the
findings independently reviewable.

## 1. Avoid repeated clock constraint walks inside fixed-parent searches

`ccu_nm_find_best()` evaluates every N/M combination through
`ccu_is_better_rate()`. That comparator obtains the effective clock rate range
on every call. `clk_hw_get_rate_range()` reaches `clk_core_get_boundaries()`,
which walks the clock's consumer list twice to combine minimum and maximum
constraints. The range is therefore reconstructed for every candidate even
though the fixed-parent NM search contains no intervening callback or range
update. The fixed-parent `ccu_nkm_find_best()` has the same pattern.
[NM search, lines 31–57](https://github.com/gregkh/linux/blob/v6.18.54/drivers/clk/sunxi-ng/ccu_nm.c#L31),
[NKM search, lines 75–107](https://github.com/gregkh/linux/blob/v6.18.54/drivers/clk/sunxi-ng/ccu_nkm.c#L75),
[rate comparator, lines 42–62](https://github.com/gregkh/linux/blob/v6.18.54/drivers/clk/sunxi-ng/ccu_common.c#L42),
[constraint walks, lines 781–813](https://github.com/gregkh/linux/blob/v6.18.54/drivers/clk/clk.c#L781).

**Candidate:** snapshot the effective minimum and maximum once on entry to
each fixed-parent search and use the same comparison semantics for every
candidate. Preserve overflow behavior, rejection boundaries, iteration order
and factor tie choices. Avoid a persistent cache: limits must be fetched again
for the next search. `clk_core_get_boundaries()` asserts the clock prepare lock;
normal rate-setting and consumer range-setting use that same lock. This supports
a snapshot within these callback-free searches, not arbitrary caching across
parent callbacks or independent API calls.
[clock locking and range setting](https://github.com/gregkh/linux/blob/v6.18.54/drivers/clk/clk.c#L2584),
[range update](https://github.com/gregkh/linux/blob/v6.18.54/drivers/clk/clk.c#L2734).

The A33 video PLL has 128 possible N values and 16 M values: the unshortened NM
search can make **2,048 comparator calls**. This is a source-derived work
count, not a timing result. A real display call path exists:
`sun4i_tcon0_mode_set_rgb()` requests the dot clock, and
`sun4i_dclk_round_rate()` tries parent rates for candidate output divisors.
The normal audio SDM rates and the PLL's special fractional rates can bypass
the NM integer search. The diagnostic configuration disables Lima and A33 MBUS
devfreq, so GPU/DRAM frequency loops are not established hot paths here.
[A33 clock definitions](https://github.com/gregkh/linux/blob/v6.18.54/drivers/clk/sunxi-ng/ccu-sun8i-a33.c#L62),
[RGB mode setting](https://github.com/gregkh/linux/blob/v6.18.54/drivers/gpu/drm/sun4i/sun4i_tcon.c#L500),
[dot-clock parent search](https://github.com/gregkh/linux/blob/v6.18.54/drivers/gpu/drm/sun4i/sun4i_tcon_dclk.c#L70),
[project configuration](../kernel/gameshellneo.config).

A smaller alternative is to stop `ccu_nk_find_best()` at its first exact match,
as already done for NKMP. Its floor-selection comparator only replaces a
candidate with a strictly better result. NM/NKM floor-mode searches offer the
same opportunity after acceptance of an exact match. Do not blindly extend
that change to `ccu_nkm_find_best_with_parent_adj()`: it deliberately permits a
later equal-rate choice when that choice retains the current parent. Also test
the actual signed/unsigned arithmetic of closest-rate comparisons before making
claims about their extreme inputs.
[NK selection](https://github.com/gregkh/linux/blob/v6.18.54/drivers/clk/sunxi-ng/ccu_nk.c#L18),
[parent-adjusting tie rule](https://github.com/gregkh/linux/blob/v6.18.54/drivers/clk/sunxi-ng/ccu_nkm.c#L33).

**Host validation:** compile the actual old/new functions, compare returned
rate and every selected factor across attainable boundaries and neighboring
requests, min/max constraints, both comparison modes, zero and extreme inputs,
and 32-bit ARM versus native arithmetic. Instrument the range getter to check
the intended call-count reduction and prove that changed constraints between
successive searches take effect. Reuse the actual-source extraction approach
of `task test:nkmp`. A kernel object build verifies integration; an isolated
search benchmark can report computation time, not device energy savings.

This would be a behavior-preserving algorithmic optimization once equivalence
is demonstrated. No kernel change or equivalence result is claimed by this audit.

## 2. Skip redundant OCP8178 commands with an explicitly valid state

`ocp8178_update()` always writes the address byte and brightness byte for a
nonzero request, even when that brightness is already commanded. For zero it
always drives CTRL low and sleeps for 3 ms. Each byte has 60 microseconds of
explicit delays inside local interrupt masking, excluding GPIO and loop
overhead. Two unchanged-brightness bytes therefore repeat 120 microseconds of
programmed busy waits across two separate interrupt-masked sections.
[project driver: `ocp8178_off()`, `ocp8178_write_byte()`, `ocp8178_update()`](../kernel/overlay/drivers/video/backlight/ocp8178_bl.c).

Equal sysfs brightness writes really reach this code:
`backlight_device_set_brightness()` sets the property and calls the update
operation without an equality test. By contrast, equal `bl_power` writes are
already suppressed by the core. There is no periodic brightness writer in the
current project runtime, so this is a per-request saving, potentially useful
to a future launcher or overlapping blanking paths, rather than an observed
idle drain.
[backlight core, lines 146–220](https://github.com/gregkh/linux/blob/v6.18.54/drivers/video/backlight/backlight.c#L146),
[runtime sources](../runtime), [existing visual test](../tools/check-backlight.sh).

**Candidate:** under the existing mutex, cache the last commanded brightness
and whether that state is valid. Skip duplicate successful nonzero requests;
skip repeated off requests only after a complete shutdown interval has already
been established. A zero-initialized `enabled == false` at probe does **not**
establish that the hardware has been held low for 3 ms: the first off sequence
must remain. Every actual off, enable timeout, reinitialization and future
power-loss/resume path must update or invalidate the state correctly. Shutdown
must retain an unconditional safe-off route when state is uncertain.

This intentionally changes wire behavior and is therefore not in the same
category as pure clock arithmetic equivalence. The driver requests no ACK;
the cache represents a completed software command, not a verified brightness
register. Repeating a value currently retransmits it and could recover an
unobserved lost command. A proposed cache must account for that tradeoff and
must never survive a hardware reset merely because the requested brightness
property is unchanged. Existing lifecycle and protocol limits remain in the
[kernel ledger](../kernel/README.md).

**Host validation:** exercise the actual update path with fake GPIO, timing
and enable results: first off, repeated off, first on, equal on, changed level,
off/on restoring the same level, blank/unblank, enable failure/retry, and
release after a failed enable. Assert ordered wire/delay events and final cache
validity. Hardware validation later needs the existing visual brightness and
dark/bright sequence, followed by suspend/resume once that feature exists.
Do not shorten the documented off delay or replace the wire protocol as part
of this change.

## 3. RSB autosuspend is a separate optimization from fewer USB polls

The RSB controller sets its autosuspend delay to **1,000 ms**. Every successful
entry into its read/write transfer path takes a runtime-PM reference; after
the transfer it marks the controller busy and drops the reference with
autosuspend. Runtime suspend gates the RSB clock and runtime resume enables it.
The transport itself is interrupt/completion driven in the normal IRQ-enabled
case, rather than continuously busy-waiting for the PMIC.
[`sunxi_rsb_read()`, `sunxi_rsb_write()`, runtime callbacks and probe](https://github.com/gregkh/linux/blob/v6.18.54/drivers/bus/sunxi-rsb.c#L333).

**Inference:** recurring 50 ms AXP status reads prevent a one-second quiet gap;
changing those reads to 250 ms still does not, by itself, allow the current RSB
autosuspend timer to expire. Fewer polls can reduce CPU and transaction work
without demonstrating that the bus clock spends more time off. Other PMIC
consumers, including regulator changes and the battery guard's measurements,
also affect the gaps. This has not been checked against live runtime-PM
residency counters in this audit.
[current USB polling worker](https://github.com/gregkh/linux/blob/v6.18.54/drivers/power/supply/axp20x_usb_power.c#L127),
[proposed USB policy](36-usb-polling-policy.md),
[battery property reads](https://github.com/gregkh/linux/blob/v6.18.54/drivers/power/supply/axp20x_battery.c#L276).

**Candidate experiment, not a default change:** after qualifying the USB
policy, compare the unchanged one-second RSB delay with a bounded shorter
delay, restore the original value afterward, and measure runtime-active time,
resume count, RSB errors, governor work and battery telemetry under identical
conditions. Too short a delay can exchange a constantly enabled clock for
frequent resume/suspend work. This needs hardware and cannot be selected from
source code alone. The host can prepare the sampler and rollback checks first.

An attractive-looking shortcut was rejected: replacing the two
`regmap_read()` calls in `axp20x_read_variable_width()` with a bulk read does
not automatically turn two AXP223 RSB reads into one transfer. This RSB regmap
backend supplies scalar `reg_read`/`reg_write`; the generic bulk fallback still
loops over individual registers. RD16 in the backend selects a 16-bit register
value width, not proof that two adjacent 8-bit AXP registers can be combined.
Any real transport batching needs the bus/device protocol checked first.
[AXP helper](https://github.com/gregkh/linux/blob/v6.18.54/include/linux/mfd/axp20x.h#L973),
[RSB regmap backend](https://github.com/gregkh/linux/blob/v6.18.54/drivers/bus/sunxi-rsb.c#L426),
[regmap bulk fallback](https://github.com/gregkh/linux/blob/v6.18.54/drivers/base/regmap/regmap.c#L3145).

## 4. Give normal panel shutdown one lifecycle owner

The project `gameshell_shutdown()` directly calls `drm_panel_disable()` and
`drm_panel_unprepare()`. The sun4i display controller also invokes
`drm_atomic_helper_shutdown()` during shutdown and unbind, which leads through
the display's panel lifecycle. The DRM panel helpers explicitly warn about
redundant panel-driver shutdown calls; they skip already disabled/unprepared
states rather than calling the operations twice.
[project panel shutdown/remove](../kernel/overlay/drivers/gpu/drm/panel/panel-clockworkpi-gameshell.c),
[sun4i controller shutdown](https://github.com/gregkh/linux/blob/v6.18.54/drivers/gpu/drm/sun4i/sun4i_drv.c#L417),
[sun4i unbind](https://github.com/gregkh/linux/blob/v6.18.54/drivers/gpu/drm/sun4i/sun4i_drv.c#L133),
[DRM lifecycle checks](https://github.com/gregkh/linux/blob/v6.18.54/drivers/gpu/drm/drm_panel.c#L160).

**Finding:** duplicate ownership exists in the source. A particular shutdown
warning or incorrect hardware shutdown order is not established by this
audit. The helpers' state checks already prevent a second ordinary regulator
disable after successful unprepare. This is a reliability/diagnostic cleanup,
not a claimed continuous power saving.

**Candidate:** make the controller's atomic shutdown the normal owner, review
device-link and removal ordering, and keep removal/error cleanup distinct from
ordinary shutdown. Do not simply delete every cleanup call without accounting
for a panel removed while the display is still bound or a partially completed
prepare. Host work can test both callback orders and injected SPI/regulator
errors. Hardware qualification must still check power-off, reboot, repeated
blank/unblank and the eventual supported removal path.

Do not opportunistically remove the repeated `0x2b/0x01` panel command from
prepare/enable or combine its four initialization transactions. The panel
controller and full cold-start/reset timing remain unidentified; the current
sequence is limited reference evidence, not a documented idempotence or chip
select contract. These are occasional lifecycle writes, not an observed idle
hotspot. See the [panel provenance](../kernel/README.md).

## 5. USB delayed-work cancellation: tracked separately as NEO-17

In the inspected baseline, `axp20x_usb_power_probe()` registers managed delayed
work before registering the managed power-supply object, and requests IRQs
last. Reverse managed-resource release can therefore unregister the supply
before cancelling the worker, although the worker dereferences that supply
when announcing status changes. Failed probe after work becomes reachable and
driver teardown must preserve the required ordering: stop IRQ producers,
cancel work, then release the supply. Work must still be initialized before
an IRQ can schedule it.
[baseline probe ordering](https://github.com/gregkh/linux/blob/v6.18.54/drivers/power/supply/axp20x_usb_power.c#L973),
[worker's supply use](https://github.com/gregkh/linux/blob/v6.18.54/drivers/power/supply/axp20x_usb_power.c#L127).

This is the separate **NEO-17** implementation and validation task;
its completed patch and host/ARM-build evidence are recorded in
[report 38](38-usb-work-lifetime.md).
It is a correctness prerequisite for driver experimentation, not an expected
change to steady-state polling or charging. The separate NEO-15 polling
proposal also covers unknown/error-state behavior. In particular the PHY
currently falls back to VBUS high if its supply-property read fails; changing
that policy requires a justified retry/notification design rather than a
blanket cached read.
[PHY property-read fallback](https://github.com/gregkh/linux/blob/v6.18.54/drivers/phy/allwinner/phy-sun4i-usb.c#L418),
[USB policy and fault tests](36-usb-polling-policy.md).

## Validation boundary and follow-up

This audit completed source/caller inspection and identified bounded testable
changes. It did not execute new kernel tests, benchmark candidates, alter the
locked source tree, connect to either device, or change charger/OPP settings.
The next host-only implementation should choose one change per ticket, prove
its own intended behavior, and retain the existing kernel build/check tasks.
Hardware-sensitive policies remain experiments until later owner-supervised
tests. NEO-10's battery-voltage discrepancy is unaffected by this work.
