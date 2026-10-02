# Wi-Fi transmit admission across suspend (NEO-85)

3 October 2026, Pacific/Auckland. Patch 0021 drains network transmitters before
wiphy suspend continues and holds a dedicated queue-stop reason until wiphy
resume restores configuration. Native/ARM32 source tests and complete ARM
driver compilation pass. Diagnostic.15 remains installed; this source change
has not been tested on hardware.

## Evidence and scope

[Report 108](108-diagnostic15-hardware-qualification.md) records the first
late/noirq cycle's `brcmf_netdev_start_xmit: xmit rejected state=0` at raw
kernel time 906.317645 seconds, inside the five-second debug hold and before
transport restoration. Both SSH routes recovered. Four further cycles did not
repeat it. The packet and its origin are unknown; no relationship to NEO-55's
intermittent authentication failure is established.

The locked driver has two gaps relevant to that observation:

- `brcmf_cfg80211_suspend()` has no explicit network-queue quiescence. Link
  disassociation is not a substitute for owning transmit admission throughout
  the PM interval, including WoWL and not-ready interface paths.
- `brcmf_bus_change_state(UP)` directly wakes stopped queues without checking
  `netif_stop`. It can bypass firmware flow control, disconnected state or a
  new suspend owner.

`brcmf_netdev_start_xmit()` checks the bus state, stops the queue, frees the
packet and increments `tx_dropped` if the bus is unavailable. Patch 0021 does
not suppress or change that error path. It prevents admission during planned
suspend before the parent transport becomes unavailable.

## Change and locking

The common queue-stop bitmap gains `SUSPEND` and a zero-valued `NONE` reason.
The latter means recheck the existing owners without releasing any of them.
It uses the existing `brcmf_txflowblock_if()` lock and wake decision; no new
mutex or steady-state packet-path branch is introduced.

At wiphy suspend entry, each vif with a network device acquires the suspend
stop reason, then calls `netif_tx_disable()` to synchronize with an in-flight
`ndo_start_xmit` and leave its queue stopped. This also runs when the primary
interface is not ready, before the existing early exit. Both the no-WoWL and
WoWL branches are covered. The parent SDIO workers are still available during
this drain.

The flow-control lock is released **before** acquiring the network transmit
lock. The transmit path can acquire the flow-control lock through firmware
queue handling, so reversing that order would deadlock. Once installed, the
suspend bit prevents ordinary flow completions from reopening the queue while
the drain runs. RTNL and the wiphy lock stabilize the vif list in these PM
callbacks; the locked cfg80211 core acquires both.

Transport UP publishes its state as before, then asks the existing flow-control
helper to recheck admission with `NONE`. It cannot clear a suspend or other
owner. The wiphy resume callback releases suspend ownership only after WoWL
restoration and any deferred country update. A country error still propagates.
If configuration failed or the transport remains down, the helper first marks
the vif disconnected and turns carrier off, then clears its own suspend bit.
Traffic stays blocked while cfg80211 closes a failed interface, but a subsequent
explicit successful open/connect is not permanently blocked by stale suspend
ownership. Existing independent flow-control reasons remain intact.

The generic DOWN transition is intentionally unchanged. Moving queue draining
there would reach atomic/error contexts and would extend interface-lifetime
requirements beyond the verified wiphy boundary. Unexpected transport failures,
all hotplug/reset races, internal firmware-signalling queues and general bus
teardown are not qualified by this patch. It does not promise delivery of
already queued packets, add retransmission or change disassociation policy.

## Reproducible validation

```sh
task test:brcmfmac-tx-suspend
task check:brcmfmac-tx-suspend-driver
task check
```

`task build` includes the new regression. The checker verifies the locked
Linux archive and applies patches 0020/0021 without fuzz to isolated files.
It extracts the actual queue reasons, flow-control/carrier/bus-state functions,
new queue helpers and complete wiphy suspend/resume callbacks. Firmware
operations are modeled; the existing regulatory suite separately exercises
patch 0020's country helper.

**109 scenarios** pass natively and under ARM32 emulation, including every
combination of the three prior stop reasons, two interfaces plus a vif without
a netdev and an empty bus slot, ready/not-ready and WoWL/no-WoWL paths,
pending/no-pending/failed country updates, parent abort before suspension,
failed transport resume, independent-owner completion, clean recovery and
missing driver/interface cases.

A pthread-backed transmit-lock scenario holds an actual concurrent modeled
transmitter while suspend closes admission. That thread acquires the modeled
flow lock before releasing its transmit lock; suspend must drain it without
lock inversion or reopening the queue. This exercises the modeled lock order,
not kernel lockdep or every netdev scheduling path. The standard kernel
`netif_tx_disable()` contract is verified from the locked source; its internal
implementation is not copied into the harness.

Twelve deliberately broken variants fail by assertion: lost bus wake, missing
UP publication, lost suspend reason/drain/admission, missing/early release,
swallowed replay failure, missing failure carrier/transport gate and bypassed
independent stop ownership. The complete `core.o` and `cfg80211.o` build as
ARM ELF32 with the full project patch queue and unchanged resolved Kconfig.
Host checks pass 13 runtime and 346 tooling tests (one existing optional skip),
compiled current-selector/mount-guard checks, Bash syntax and ShellCheck.

| Evidence | Value |
| --- | --- |
| Patch 0021 SHA-256 | `a4c38e5c9d2b3ddb5f9747db67155849f2f1f3420bebd7603f847da3f85ca644` |
| Harness SHA-256 | `f5c6fc1272987a3275ae834ca56a1e796d33a6c61dcee863219b8b53b3d4f3ef` |
| Complete ARM core object | `d8c4c110c6774331dc033cd5b6f035f0557c71585ef810ece0bd88339c3fcb2b` |
| Complete ARM cfg80211 object | `c7e1a74f4733199c5dcc6d73528d443c5e05f1d2bc9d690d889e792b825fc5dd` |
| Resolved Kconfig | `d370205bf2e4eed5e35483f15372a6785e7d96252d40c343dfee0b2dde37a017` |

Evidence is under `.local/build/brcmfmac-tx-suspend-tests/compile-evidence.json`,
with compiler/ELF output and isolated objects in
`kernel-8811886efb900cff/`. Host logs are `.local/neo85-*.log` and the saved
task transcripts under `.local/build/`.

## Hardware follow-up

Preserve diagnostic.15 recovery before a separately identified image build.
After offline verification, use the established physical card and full-readback
workflow. Requalify startup and awake gates, then owner-ready devices/late-noirq
cycles with original keypad and both-route proofs. Compare raw kernel errors,
flow recovery and policy restoration; a warning-free run alone does not prove
every network producer was exercised. Preserve failures without resubmitting
ambiguous PM commands. Physical input and cable checks remain attended tasks.

This slice accessed no device after the final NEO-84 snapshots, changed no
running module and performed no new PM cycle. Normal real sleep remains
disabled. No battery-power, latency, firmware-country or all-transport
reliability claim follows from these source tests.

## Source anchors

All are from the verified Linux 6.18.54 archive in the source lock, with the
project's prerequisite patch 0020 where noted:

- `net/wireless/sysfs.c`: `wiphy_suspend()`/`wiphy_resume()` RTNL/wiphy ownership
  and failed-resume interface shutdown.
- `include/linux/netdevice.h`: `netif_tx_disable()` takes the transmit queue
  locks while stopping queues.
- `net/core/dev.c`: `HARD_TX_LOCK` and stopped-queue checks around normal/direct
  transmit, and the device attach/detach behavior considered during the audit.
- `brcmfmac/core.c`: transmit/drop path, locked stop-reason handling, carrier
  ownership, bus-state publication and interface lifetime.
- `brcmfmac/cfg80211.c`: vif PM callbacks and deferred country replay.
- `brcmfmac/fwsignal.c`, `flowring.c`: independent flow-control owners invoked
  from packet/firmware processing.
