# Power-key release semantics across input suspension

3 October 2026, Pacific/Auckland. Source research for the next diagnostic
slice after [the awake input qualification](114-awake-power-key-input.md).
This source-research report itself changes no driver or PMIC setting and
performs no board experiment. The subsequent bounded PM release and fresh
awake handoff passed in [report 116](116-bounded-power-key-pm-release.md), with
approximate physical release timing explicitly preserved. Other proposed
inhibit/tracing alternatives below remain hardware-unqualified.

The baseline is the [source lock](../build/sources.lock.json): Linux
`v6.18.54`, commit `1b357ecb321392158d507b04672ffee57bfa071d`, with the
project patches applied in `.local/sources/linux-6.18.54`. In particular,
[patch 0019](../kernel/patches/0019-wake-irq-error-ownership.patch) changes PEK
wake ownership, not its key-reporting semantics. Source links below point to
the inspected local tree; these private build files are not repository
deliverables. Upstream documentation supplies interface contracts, while the
locked source supplies the implementation facts.

## Recommendation

Preserve the input core's normal suspend clear and duplicate filtering.
Use a single bounded press/release during a `devices` PM diagnostic to
investigate delivery, retaining the established persistent ignore policy,
exclusive recorder and inhibitor. Instruct release by an independently
understood deadline of at most two seconds, preferably a one-second gesture,
even if the screen or PM call has not returned. Do not require a hold until
resume and do not change the PMIC forced-off setting to make this test fit.

Treat exact DBF/DBR counter deltas as **scoped dispatch evidence**, conditional
on the attended single gesture. They are not a current physical-key reading
and must not by themselves authorize policy restoration. After PM returns,
require a separate prompted awake press/release pair on the continuously owned
stream, with fresh baselines, no further PM transition, complete event
continuity and the existing quiet/ownership checks. Keep ignore installed until
that handoff proof passes. This is an engineering recommendation, not a claim
that the existing awake-only guard already accepts a post-PM session.

If the diagnostic needs exact software ordering beyond counters, first use
scoped tracing of the PEK handler and input-device PM callback. A permanent
input ABI extension is unnecessary for the initial qualification. Neither
tracing nor a driver-maintained last-edge variable resolves physical ordering
that the PMIC has already collapsed. The reasons and limits follow.

## What the pinned implementation does

The PEK handler reports `KEY_POWER=1` for DBF and `KEY_POWER=0` for DBR, then
calls `input_sync()`. It has no PWRON level read or cached physical-key state.
The input device supports `EV_KEY/KEY_POWER`; it supplies no `open` or `close`
callback. The AXP288-only resume status clear does not apply to AXP223.
[PEK driver: `axp20x_pek_irq`, probe and resume][pek].

`input_dev_suspend()` releases every logically pressed key through
`input_dev_release_keys()` and emits `SYN_REPORT=1` if any were cleared.
`input_dev_resume()` restores output state without rereading this key.
For ordinary key values, `input_get_disposition()` forwards an event only
when its Boolean value changes the logical bitmap. Therefore a subsequent
PEK DBR report of zero is ignored when suspend already cleared that bit.
`input_event_dispose()` also discards a lone SYN packet, so the later hardware
release need not create any evdev packet at all. This is an expected
interaction of the two implementations, not evidence that generic input
suspension is defective. [Input core: lines 208–279, 316–355, 674–689,
1791–1820][input].

The state returned by `EVIOCGKEY` is `input_dev->key`; it is not an extra PMIC
transaction. The upstream event contract describes input-maintained state
and permits drivers to report unchanged values. It also leaves EV_SYN values
undefined. Thus `SYN_REPORT=1` is a useful signature in this pinned
implementation, not a portable physical-release flag. Reset, inhibit, freeze
and disconnect paths can also produce software key releases. Attribute a PM
clear using the identified input-device suspend callback and event timeline,
not the SYN value alone. [evdev ioctl implementation][evdev],
[input core][input], [upstream input event documentation][event-doc].

Expected software sequence when the held logical state reaches the callback:

| Point | Logical state / evdev | Additional evidence |
| --- | --- | --- |
| Initial physical press serviced | `KEY_POWER=1`, ordinary SYN | DBF dispatch increases |
| Input-device suspend callback | `KEY_POWER=0`, synthetic SYN | Matched input-device PM callback |
| Subsequent release serviced | Already zero; no new key packet required | DBR dispatch increases |
| New attended awake tap after return | New `1`, then `0`, ordinary packets | Fresh DBF and DBR increments |

This table is derived from source. Its event timestamps describe software
reporting, not physical contact times. An earlier physical release whose
interrupt is delayed can leave the logical bit set until suspend clears it;
the synthetic clear alone does not prove the switch was still held at that
instant. [Input core][input], [PEK handler][pek], [regmap dispatch][regmap].

## PMIC and interrupt limits

The supplied X-Powers AXP223 revision 1.1 datasheet describes PWRON connected
to ground through the key (§9.1.1, printed page 19). REG44 enables rising and
falling events, and REG4C bits 6 and 5 latch their IRQ status (§10.2.54 and
§10.2.59, printed pages 48–49). IRQ status is cleared by writing one (§9.8,
printed page 29). Those are event latches, not documented live PWRON levels.
No live PEK-level register was identified in this supplied register map; this
is a bounded finding about the documentation, not proof about undocumented
silicon functionality. [Supplied manufacturer datasheet][datasheet].

REG36 configures forced-off duration as 4, 6, 8 or 10 seconds and has a
separate enable bit. The [prior board readback](114-awake-power-key-input.md)
reports 6000 ms through the PEK shutdown attribute; that attribute reads the
duration bits, not the separate enable bit, and is not a measured hard-off
deadline. The pinned PM debug delay is five seconds, after device suspension,
with other callbacks and thawing outside that wait. Consequently a hold from
before entry through user-visible return has no defensible margin against
the configured duration. [REG36, §10.2.30][datasheet], [PEK attributes][pek],
[suspend test and `suspend_devices_and_enter`][suspend],
[upstream PM debugging documentation][pm-doc].

The AXP22x MFD uses the same status bank for acknowledgement and handles
five register banks. Regmap reads status, masks it, acknowledges sampled bits,
then dispatches each set bit in ascending software hwirq order. AXP22x's enum
deliberately puts falling before rising, yielding hwirq 22 for DBF and 23 for
DBR despite the reverse hardware bit positions. [MFD definitions][mfd],
[AXP22x IRQ enum][axp-header], [regmap IRQ thread][regmap].

**Inference:** when both latches are pending, Linux reports DBF then DBR
regardless of the actual ordering of the contacts. Repeated same-edge events
before acknowledgement cannot be counted individually from one status bit.
For example, release followed by re-press during delayed service can leave
the physical button held while software processes press then release and ends
logically up. A cached last-dispatched edge or an added event for each
dispatch inherits this ambiguity. The datasheet does not specify an edge
FIFO or precise behavior for a new same-bit event concurrent with its
write-one-to-clear acknowledgement; do not invent guarantees for that race.
[Datasheet IRQ mechanism][datasheet], [regmap dispatch][regmap],
[enum ordering][axp-header].

`handle_nested_irq()` increments the per-CPU IRQ counter after its admission
check and **before** calling `action->thread_fn()`. It does not emit the
ordinary `irq_handler_entry/exit` tracepoints. Thus a count proves an accepted
nested dispatch, not completion of the PEK callback. A shared parent IRQ count
cannot identify PEK because other PMIC sources share it. [Nested IRQ handler][irq],
[regmap dispatch][regmap].

The saved post-NEO-90 [interrupt capture][interrupt-capture] identifies Linux
IRQ 90/DBF and 91/DBR under `axp22x_irq_chip`, hwirqs 22 and 23, each with four
dispatches on CPU0 and zero on the other three displayed CPUs. This research
read that existing capture; it made no fresh board inspection. Linux IRQ numbers must be
rediscovered and checked against chip, hwirq and action name for each run.
`/proc/interrupts` prints per-online-CPU counters row by row; it is not an
atomic two-edge snapshot. Preserve the complete original rows, all CPU
columns, boot/kernel identity and sample times; reject changed CPU topology,
mapping, decreasing counts or ambiguous duplicates. [Interrupt rendering][irq-proc].

## A defensible bounded diagnostic

This is a proposed acceptance contract, not a ready-to-run command:

1. Establish normal diagnostic ownership and persistent ignore, match the
   input and IRQ identities, and take a released/quiet baseline. Record the
   observed press before initiating PM; obtain a held baseline containing
   exactly that one DBF increment and no DBR increment. The physical release
   deadline is measured from the operator's press, independent of successful
   PM submission or a later UI prompt.
2. Run only the intended debug stage. Record the input-device suspend and
   resume callbacks, complete evdev packets, IRQ baselines/results, PM result
   and run identity. A `devices` test does not establish real sleep or wake
   capability. If release occurs before the target clear, the held-clear
   reproduction is inconclusive; do not lengthen the next hold to compensate.
3. After return, a held-baseline delta of DBF `+0`, DBR `+1` supports one
   release dispatch during the controlled interval. With the matched synthetic
   packet and otherwise complete evidence, it supports the filtering
   explanation. It cannot establish exactly when the physical release happened
   or serve as release authority after an unknown event history.
4. While ignore and continuous ownership remain, start a **new awake evidence
   interval** and prompt a distinct tap. Require its fresh press/release pair,
   matching counter increments, released logical bitmap and quiet interval.
   Recheck that neither PM nor inhibition/reset invalidated that interval,
   and keep the existing policy/configuration transaction checks around
   handback. Do not silently rewrite or discard the previous PM transcript.
5. Reject missing evidence, event/trace loss, extra edges, unclear stage
   attribution, ownership loss or an unresolved held key. Retain ignore and
   evidence for the established recovery path. Passing a fresh awake pair
   does not turn an inconclusive PM measurement into a qualified PM result.

These checks deliberately depend on an attended, controlled sequence. Even a
fresh awake pair cannot prove arbitrary physical state after hidden coalesced
transitions. Product recovery after whole-controller loss or unknown startup
state needs a separately specified contract; it must not adopt these counters
or an evdev bitmap as a level sensor. A `SYN_DROPPED` resynchronization can
recover the input core's logical state but cannot reconstruct missing physical
edges. [Event-loss contract][event-doc], [evdev state query][evdev],
[latched IRQ mechanism][datasheet].

## Awake reproduction and stronger instrumentation

An awake inhibit/uninhibit sequence can isolate the input behavior without
the five-second PM wait. While a known press is held under the same ownership,
write the identified input device's `inhibited` attribute, verify the synthetic
clear, promptly uninhibit, then ask for release within the independent short
deadline. The core clears keys before marking the device inhibited and drops
all input events while inhibited. Uninhibit does not restore held keys. PEK
has no input `open`/`close` hook to disable its IRQs for this operation, so
interrupt dispatch evidence remains conceptually available. [Input inhibit
implementation][input], [PEK probe][pek], [upstream inhibit contract][inhibit-doc].

Release **after uninhibit** if the intended observation is duplicate-zero
filtering. A release while still inhibited instead tests unconditional event
suppression. Both cases need their actual order recorded; a release racing
the control writes makes the intended case inconclusive. This is an awake
reproduction of shared core behavior, not a replacement for PM, wake or
resume qualification. Recovery must also preserve and restore the original
inhibition state without restoring shutdown after unknown input.

For stronger software attribution, prefer existing PM callback tracepoints
plus a temporary PEK-entry/return probe carrying the IRQ identity, if the
running kernel actually supports it. Generic PM trace records identify the
input child and parent; parent PEK-device callbacks alone are insufficient to
locate the child's core clear. Kprobe events are configurable and require
`CONFIG_KPROBE_EVENTS`; their availability and argument capture on this
kernel need preflight. Capture trace loss and clock identity, using a compatible
clock for evdev correlation. This report does not establish available board
probe symbols or tracing configuration. [PM callback instrumentation][pm-main],
[power trace definitions][power-trace], [upstream event tracing][trace-doc],
[upstream kprobe events][kprobe-doc].

If a driver instrumentation patch is eventually necessary, a scoped trace
event can record device, edge IRQ, software sequence and whether both edge
bits were present in the same regmap sample. The last field requires evidence
at the regmap sample boundary; a PEK-only last-edge field cannot infer it.
Keep normal KEY_POWER reporting and synthetic clears intact. Trace time remains
dispatch time; even perfect trace retention does not recover collapsed
physical edges. [Regmap thread][regmap], [PEK handler][pek].

An `EV_MSC` extension could retain a driver-originated packet when the
KEY_POWER value is filtered: supported miscellaneous events pass the input
core without key-state comparison. However, it still disappears while the
device is inhibited, needs a defined hardware-data meaning and compatibility
review, and cannot make the PMIC into a level-reading device. `MSC_SCAN` names
a scan-code facility; merely reusing its name does not define a portable
press/release metadata ABI. Prefer a diagnostic trace until a product consumer
and a valid event contract justify a persistent interface. This is an
engineering assessment based on [EV_MSC handling][input],
[input event codes][event-doc] and [the UAPI identifiers][input-uapi].

## Remaining qualification boundary

Source evidence establishes the synthetic-clear and duplicate-filtering
mechanism and the limits of available IRQ evidence. It does not establish
physical hold duration, reliable status delivery across PM, actual sleep,
power-key wake, forced-off timing, autonomous recovery after controller loss,
or product gestures. Exact physical edge chronology requires a documented
level/timestamp facility or independent physical measurement; none is
established here. Keep those claims separate from a successful bounded
diagnostic and from [the product power-key contract](79-power-button-policy.md).

Inspected file SHA-256 values, for reproducing the source assessment:

| Source | SHA-256 |
| --- | --- |
| `drivers/input/input.c` | `556b513c542462bc8cef2c9a94c31bdf7ce5fa3654ebea06b133c9f3adcbf9bf` |
| `drivers/input/misc/axp20x-pek.c` | `cb7fd6fd616af38bc4d94619c899848c7edb6722813e1ccab35d5f193b705e93` |
| `drivers/base/regmap/regmap-irq.c` | `1cae271727fdeeee5894fa5bc2318831e3a270201bbd01da98b68bacc15df345` |
| `kernel/irq/chip.c` | `0a527fabc628c89be01ed60d75f674ac711c4f443716583fd0d124b4f4d4c3fd` |
| Supplied AXP223 PDF | `d4d2cc18904794abcabbd25f1b8727f020d0610217d11f3d77e7d013ba7217b6` |

[input]: ../.local/sources/linux-6.18.54/drivers/input/input.c
[pek]: ../.local/sources/linux-6.18.54/drivers/input/misc/axp20x-pek.c
[evdev]: ../.local/sources/linux-6.18.54/drivers/input/evdev.c
[regmap]: ../.local/sources/linux-6.18.54/drivers/base/regmap/regmap-irq.c
[mfd]: ../.local/sources/linux-6.18.54/drivers/mfd/axp20x.c
[axp-header]: ../.local/sources/linux-6.18.54/include/linux/mfd/axp20x.h
[irq]: ../.local/sources/linux-6.18.54/kernel/irq/chip.c
[irq-proc]: ../.local/sources/linux-6.18.54/kernel/irq/proc.c
[suspend]: ../.local/sources/linux-6.18.54/kernel/power/suspend.c
[pm-main]: ../.local/sources/linux-6.18.54/drivers/base/power/main.c
[power-trace]: ../.local/sources/linux-6.18.54/include/trace/events/power.h
[input-uapi]: ../.local/sources/linux-6.18.54/include/uapi/linux/input-event-codes.h
[datasheet]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf>
[event-doc]: https://docs.kernel.org/input/event-codes.html
[inhibit-doc]: https://docs.kernel.org/input/input-programming.html#inhibiting-input-devices
[pm-doc]: https://docs.kernel.org/power/basic-pm-debugging.html
[trace-doc]: https://docs.kernel.org/trace/events.html
[kprobe-doc]: https://docs.kernel.org/trace/kprobetrace.html
[interrupt-capture]: ../.local/diagnostics/20261002T200536.530622Z/inspection.json
