# Diagnostic.18: USB reconnects after repeated sleep

4 October 2026, Pacific/Auckland. NEO-95.

Four physical USB removal/reconnection cycles passed on the same diagnostic.18
boot that completed [four consecutive RTC-wake cycles](148-diagnostic18-repeat-rtc-wake.md).
Each removal was followed by a configured UDC and independently verified USB
SSH before the next removal was accepted. The owner confirmed all four cycles
were complete and left USB connected. Final USB and Wi-Fi checks passed.

This qualifies ordinary awake reattachment after the sleep sequence. It does
not test cable removal during sleep, sleep with the cable absent, Mac sleep,
or reattachment latency. No new sleep, driver, image or policy change occurred.

## Protocol and identity

The owner gave readiness before recorder startup. After its explicit `ready`
event, the requested sequence was four repetitions of: unplug at the GameShell,
wait three seconds, reconnect, then wait thirty seconds. The final state was
connected. Physical timing was requested but not instrumented.

| Item | Value |
| --- | --- |
| Image / kernel | `0.1.0-diagnostic.18` / `6.18.54-gameshellneo18` |
| Boot | `e419f334-0a16-4b04-96d2-d97a2e4d5d0b` |
| Source revision | `47fea96` |
| Saved command | `task device:usb-reconnects CYCLES=4` |
| Recorder sampling | Nominal 250 ms, state changes saved |
| Completed cycles | 4 of 4 |
| PM successes / failures | 19/0 before and after |
| SDIO runtime references | 2 before and after |

The board recorder retained nine ordered observations: the initial configured
state, then four pairs of `not attached` and `configured`. All belonged to the
same boot. The host recorded a separate successful USB SSH verification for
each cycle, reaching the expected USB address. Connection errors while the
cable was absent remain in the host evidence. No network repair, gadget
restart, reboot or PM resubmission was used.

The recorded intervals from the first unattached sample to the configured
sample include the owner's unplugged wait, enumeration and sampling delay.
They are not plug-to-ready latency measurements. Intermediate USB states
may fall between samples; `physical_timing_qualified` remains false.

## Final checks

The recorder completed successfully, stopped its transient service and removed
its temporary board capture after retrieval. The final PM inspection passed
the existing health validator, as did the pre-test inspection. Independent
Wi-Fi SSH also succeeded.

Boot/image/kernel, PM statistics and controls, display settings, input identity,
charger settings, CPU policy, Wi-Fi profile/power policy, service state and
ordinary sleep masks matched the baseline. SDIO ownership was unchanged.
There were no new kernel journal entries. The battery reported 100%; this
does not measure capacity or energy consumed during the unplugged intervals.

The final Mac inspection saw GameShellNeo in its USB tree. All six read-only
host capture groups succeeded, and the saved Mac sleep/wake history matched
the pre-test capture. No host network or power settings were changed.

## Saved evidence

Paths below are relative to `.local/diagnostics/`:

| Evidence | Capture |
| --- | --- |
| Pre-test PM inspection | `20261004T023331.741744Z/inspection.json` |
| Cable recorder and host verification | `20261004T023403.563974Z/` |
| Post-test PM inspection | `20261004T023739.447914Z/inspection.json` |
| Pre-test Mac inspection | `20261004T022652.183031Z/` |
| Post-test Mac inspection | `20261004T023739.432176Z/` |

The recorder directory contains `summary.json`, `usb-reconnects.jsonl` and
`device-states.jsonl`. The host log is `.local/neo95-post-sleep-cable.log`;
the independent Wi-Fi status log is `.local/neo95-cable-after-wifi.log`.
The combined offline review is `.local/neo95-cable-review.json`.

| Artifact | SHA-256 |
| --- | --- |
| `summary.json` | `52c20d2012e9704a7df92b362c844d111da05560ec8ab344fb660776792f27ee` |
| `usb-reconnects.jsonl` | `21289dfb6277ad430bc6b240ad67440227ce08f918b99716d6e30789ca17c763` |
| `device-states.jsonl` | `b04d935efb961d1324d055b0df61cb9861523e7a6034938623421b4f80845030` |
| Combined review | `41334101bddb201708a7d3f46d71e5514905325d83884aef6dd27f2fc797d917` |

The current tasks were used unchanged, so this slice adds hardware evidence
and documentation only. NEO-95 remains open for other cable/host conditions.
NEO-109 tracks an explicit battery-only sleep profile: the existing sleep
recorder intentionally requires USB power, configuration and recovery, and
must not have those guarantees silently relaxed. Battery-only sleep and Mac
sleep need separately prepared workflows and fresh physical readiness.
