# Wi-Fi resume metadata recorder (NEO-55)

1 October 2026, Pacific/Auckland. Follow-up to the
[source audit](76-wifi-resume-authentication-source-audit.md) and
[unattended checks](77-unattended-diagnostic11-validation.md).

Diagnostic.11 previously failed one unchanged postflight check after ordinary
driver resume: association was reported, WPA completion timed out, and retries
backed off. Later successful runs did not establish the cause. This slice adds
repeatable evidence to distinguish host packet observations from supplicant
handshake state, without changing the firmware or authentication policy.

## Saved workflow

```sh
task device:wifi-trace-smoke
# Once the awake check passes and the owner explicitly confirms readiness:
task device:pm-test STAGE=devices CYCLES=1 WIFI_TRACE=1
```

The first task performs one awake software reassociation over the USB control
route. It requires EAPOL metadata in both directions, a supplicant security
completion, restored recorder settings, unchanged PM counters/configuration,
and independent Wi-Fi SSH to the same boot. The second adds the recorder to
the existing ordinary devices debug stage. The owner watches for the normal
dim console to return, leaving USB and controls untouched. No card flash,
physical USB change or actual low-power sleep is involved.

`WIFI_TRACE=1` is restricted to the ordinary devices task without physical
keypad prompts or keypad policy changes. The existing observational
`KEYPAD_TRACE=1` remains compatible. Existing image, power, radio, service,
keypad, process-memory and restoration gates remain in force. Postflight is
sampled at the existing point after the 30-second recovery wait, before the
new recorder's collection/cleanup; collection time cannot silently extend it.

## Capture and restoration

The saved `tools/wifi_trace.py` helper creates its own tracefs instance with
a 256 KiB buffer per CPU and the monotonic clock. Network events are filtered
to `wlan0` and EtherType `0x888e`; ordinary PM stage/callback events are also
enabled. The network trace contains metadata rather than packet payloads.
The helper requires the expected live formats and complete zero-loss trace
statistics from each reported CPU. Missing or nonzero overrun/drop counters
reject the capture.

Supplicant logging temporarily changes from its original INFO/WARNING/ERROR
level to DEBUG, preserving timestamp policy. Before changing it, the helper
requires the exact installed service arguments, without key-display or D-Bus
debug options, and records process PID/start time. `LOG_LEVEL` does not enable
key display. A separate ownership record stores the original level and boot;
unexpected process or logging changes prevent blind restoration.

The normal private device journal retains DEBUG messages, which can include
network identifiers. Exported supplicant evidence is an allowlist of numeric
timestamps, known state transitions, handshake step numbers, timer durations
and numeric failure/backoff fields. Free-form messages, network names,
addresses, packet dumps and keys are not copied into that timeline. More than
4,000 journal rows rejects the capture. This bounds collection, but does not
prove that journald delivered every userspace message; absence alone is not
proof of a lost radio frame.

Context cleanup and the device-owned unit's `ExecStopPost` both restore the
owned settings. Trace cleanup failure still attempts logging restoration;
Wi-Fi cleanup failure does not block the existing PM-control restoration.
Failed cleanup retains ownership for diagnosis/retry. The PM unit keeps its
120-second limit; the awake unit has a 90-second limit. These depend on a
functioning kernel/systemd and cannot recover a hard hardware hang.

Existing `device:pm-collect RUN=...` and `device:pm-restore` handle the PM
capture. For an interrupted awake run, first stop its
`gameshellneo-wifi-trace-smoke` unit over USB, then use `device:pm-restore` if
owned restoration still needs retrying. The failed helper/evidence are retained.
See the [routine instructions](../README.md) for the complete workflow.

## Validation before observed PM

The complete `task check` passed: 276 tool tests (one optional skip), 13 runtime
tests, compiled regression helpers, Bash syntax and ShellCheck. Eight new
recorder test methods exercise privacy filtering, trace loss, setup/body/
collection failures, restoration, conflicting ownership and changed processes.
Two PM regressions cover option restrictions/service bounds and independent
PM restoration despite Wi-Fi-cleanup failure. Log: `.local/neo55-check.log`.

Current-boot and PM inspections first passed on the original boot
`3bf2069f-24a7-4e0b-b7d3-18d4048e3c7f`, kernel
`6.18.54-gameshellneo11`, with both network routes healthy. Those captures are
`.local/diagnostics/20260930T184013.036816Z/` and
`20260930T184013.043744Z/` respectively.

The saved awake check then passed at
`.local/diagnostics/20260930T184925.795745Z/`:

- Two EAPOL receive events and two transmit submissions; no trace loss on
  any of the four CPUs.
- Supplicant message 1 received, message 2 sent, message 3 received, message 4
  sent, followed by key-negotiation completion and `COMPLETED` state.
- 374 journal rows reduced to 19 allowlisted events; a 1,798-byte metadata
  trace. Repeated userspace RX log entries are not a count of unique frames.
- INFO/timestamp-off logging and the private trace instance restored; the
  network configuration, firmware hashes, boot and PM counters unchanged.
- Both USB and independent Wi-Fi SSH verified afterward.

The trace context lasted about 4.04 seconds, including setup, polling and
collection; this is not a precise association latency or an overhead benchmark.
The observed driver capture is the next step after explicit owner readiness.

## Interpretation limits

Transmit metadata means submission to the host driver, not successful radio
delivery. Receive metadata locates packets entering the normal host network
path; it is not an independent RF capture. Supplicant and kernel timestamps
support ordering comparisons but include logging/scheduling delay.

The firmware remains proprietary. This recorder can narrow the failure and
guide later numeric host-driver instrumentation; it cannot establish firmware
internals. NEO-55 remains open until the intermittent PM failure is understood
and an appropriate change is qualified. Passing another cycle alone does not
establish reliable real sleep, wake latency, power savings or AP-loss recovery.
