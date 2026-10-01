# Saved unattended awake qualification (NEO-75)

2 October 2026 New Zealand time (1 October UTC).

The individual checks in [report 94](94-unattended-diagnostic13-validation.md)
are now composed into one repeatable command. This reduces manual handoffs
while preserving the distinction between awake software checks and the
observed PM, physical-input, cable and visual/audio qualification still due
for diagnostic.13.

## Routine

```sh
task device:qualify-awake-plan
task device:qualify-awake ACTIVE_COUNTRY=AU
task report:awake CAPTURE='.local/diagnostics/awake-<timestamp>'
```

Keep USB connected, the Mac awake on the same available Wi-Fi network, and
controls untouched. Do not run another diagnostic or configuration command
concurrently. The AU override is the owner's accepted AP announcement;
configured NZ is unchanged. Credentials stay in `.env`, read by existing
controllers. These tasks require the current locked diagnostic image with
retained keypad supply and speaker support. No image rebuild is needed for
this host-side addition.

The sequence is fixed:

1. Refuse active diagnostics or unresolved recovery ownership.
2. Verify current image/boot, kernel/radio health and both SSH routes.
3. Inspect PM state, keypad identity and idle audio as the baseline.
4. Exercise installed firmware through four software reconnections, a
   120-second synthetic unavailable-network window and a 120-second connected
   window. Require all seven independent Wi-Fi SSH checkpoints and restoration.
5. Inspect the device again before starting load, including unchanged boot,
   configuration, PM counters and charging/CPU/display policies.
6. Verify a new temporary 128 MiB file by direct read, then run the existing
   five-minute CPU/memory workload with its temperature/taint/USB guards.
7. Run the isolated installed battery-policy simulations and six integration
   check groups.
8. Repeat boot/routes, PM, keypad and idle-audio checks, then verify diagnostic
   services and recovery records are absent.

Ordinary duration is approximately 12–15 minutes. `--cycles 0`, explicit USB
routing and 120-second windows override inherited task defaults. There are no
PM entries, physical prompts, tones, firmware replacements or reboots.

## Evidence and failure handling

`tools/qualify-awake.py` invokes existing controllers with exact argument lists.
`remote.evidence_directory()` accepts an optional existing subdirectory within
`.local/diagnostics`, allowing each new step to own a fresh capture. Escapes,
symlink escapes and ambiguous multiple captures are rejected. The wrapper
never searches global captures for a previous success.

One private `awake-<timestamp>/` directory holds a source-lock copy, helper
source hashes, atomically replaced/fsynced `progress.json`, a readable
`report.md`, and per-step logs and raw evidence. A step is marked running before
submission. A pass requires both exit zero and complete semantic evidence:
for example, Wi-Fi restoration and all checkpoints, verified storage/load and
cleanup, unchanged PM counters/policies, original keypad identity and idle
unchanged audio controls. Source changes during the run stop qualification.

Each host child has a wall-clock deadline. On interruption or deadline expiry,
the wrapper sends SIGINT to allow existing Python cleanup hooks, waits a
bounded grace period, then kills a stuck controller. The Wi-Fi phase allows
450 seconds for its existing stop/restore hooks; other phases allow 30 seconds.
These conservative bounds are failure limits, not intended test durations.
The firmware-trial service's runtime cap and `ExecStopPost` recovery run on the
device independently of the host. The stability service retains its own
seven-minute runtime bound. Recovery still requires functioning kernel/systemd
and, for Wi-Fi association, an available original AP.

Any failure or interruption stops subsequent tests and reports restoration as
**unverified**, even if a controller says it attempted cleanup. No automatic
retry, resume, firmware reload, deletion of recovery records or power cycle is
performed. Read the logs and verify the relevant retained device state before
another run. The README documents the existing Wi-Fi helper recovery procedure.
The offline report command never contacts the hardware. A saved running record
is incomplete and can also mean that the host process died; it is not a pass.

A local flock excludes a second copy of this workflow. Read-only guards reject
other active GameShellNeo diagnostic services and leftover ownership records
at the beginning/end. This is not a global lock shared by all older tools, so
operators must still avoid concurrent diagnostic commands.

## Validation

The new host suite covers success ordering and durable progress, failed exits,
missing/ambiguous/stale evidence, interruption, timeout, source changes, offline
reporting, evidence-root escapes, incorrect Wi-Fi restoration/checkpoints,
changed boot/policies/PM counters, keypad re-enumeration and non-idle/changed
audio. Real local subprocess tests verify graceful timeout cleanup and forced
termination of an unresponsive controller. These tests do not simulate a
kernel hang or physical power loss.

The shared host checks passed: 13 runtime tests; 313 tool tests with one
optional systemd test skipped; compiled current-selector and Mac mount-guard
checks; Bash syntax and ShellCheck. The 18 new orchestration tests also passed
separately after the report formatting update.

The live command passed all fifteen stages in 661.256 seconds (about eleven
minutes), from 11:17:14 to 11:28:15 UTC on 1 October. Private evidence is in
`.local/diagnostics/awake-20261001T111714.703944Z/`; the controller transcript is
`.local/neo75-live.log`. The saved offline report task was also exercised
while the run was active and after completion.

The device retained boot `b5e3abbd-775f-4004-9100-0c7a20dfb59b`, image
`0.1.0-diagnostic.13` and kernel `6.18.54-gameshellneo13` throughout.

| Check | Result |
| --- | --- |
| Wi-Fi | Seven independent SSH checkpoints; all four reconnects passed. Unavailable and connected windows lasted 120.184 and 120.158 seconds; configuration restored. |
| Radio health | One expected firmware identity; zero tracked crash, SDIO-removal or PM-underflow markers. |
| Storage/load | 134,217,728 bytes verified by direct read; CPU/memory workload passed; temporary files removed. |
| Temperature | Maximum sampled 65.448 C, below the existing 80 C stop limit; this is not a controlled comparison with the prior run. |
| Battery policy | Nine isolated simulated tests passed; no real shutdown/discharge test. |
| Integration | All six groups passed. |
| Final state | Both SSH routes verified; PM counters stayed zero; firmware/configuration, charging/CPU/display policy and keypad devnum 2 retained. |
| Audio | PCMs closed, amplifiers Off, mixer controls unchanged; no tones played. |
| Cleanup | No active diagnostic services or retained ownership records; original awake state verified. |
| Power | Valid software estimate 100%; USB supply remained present/online. This does not qualify the battery's physical capacity or charge limits. |

The storage SHA-256 was
`b7d3920eb4c12e7cc7d38e7e0fb6f55fb1e1b9a51a7c767c7385dee8d6b4bd57`.
Each step's exact commands, duration, source hashes, results and evidence path
remain in `progress.json`. No permanent device-policy change was required.

## Remaining hardware work

This tool does not qualify real sleep/wake, buttons/cables, visual/audio
quality, battery capacity, charge calibration, energy savings or long-term
reliability. It does not resolve NEO-10's battery-reading discrepancy,
NEO-55's original radio outage or the fatal transport-error recovery policy.
Initial observations of new PM stages and the attended diagnostic.13 sequence
remain separate. The known speaker-confirmation delay remains deferred.
