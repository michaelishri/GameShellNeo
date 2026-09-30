# Keypad supply-retention hardware validation (NEO-45)

30 September 2026. Owner's CPI v3.1, Samsung DEV card. This follows the
[diagnostic.9 preparation](62-keypad-supply-retention-preparation.md) and the
[diagnostic.8 persistence comparison](61-keypad-persistence-comparison.md).

## Candidate and recovery

The candidate is `0.1.0-diagnostic.9`, retaining the exact
`6.18.54-gameshellneo8` kernel/modules/configuration, package inventory and
runtime input hashes from diagnostic.8. The sole semantic DT change is
`/regulator-keypad/regulator-always-on`. Normal sleep remains disabled.

Diagnostic.8's verified raw/gzip images and matching metadata remain available
through `task mac:stage-recovery NAME=diagnostic8-before-keypad-retention`.
Its archive was independently reverified on the Mac before candidate transfer.

## Installation

The owner confirmed regular Wi-Fi for the transfer and then confirmed the
GameShell was shut down with its DEV card in the Mac reader. Fresh `mac:status`
and `mac:inspect DISK=disk16` identified the external physical USB card at
64,013,467,648 bytes, 512-byte sectors, with the expected FAT16/Linux layout.
`mac:preflight` reverified the archive and target without writing.

`task mac:flash DISK=disk16` then passed mount-veto verification, wrote
4,294,967,296 bytes, read back the full region and safely ejected the card.
The readback SHA-256 exactly matched the candidate:

`4c48c1bd110eabb310b5fa608ea1e99f7eef7560c295700763dc30da91d15567`.

Private flash evidence:
`.local/diagnostics/20260930T065155.880678Z/flash-result.json` and `flash.log`.
Fresh inspection/preflight logs are `.local/neo45-card-inspect.log` and
`.local/neo45-card-preflight.log`. The disk number is historical evidence,
not a reusable target selection.

## Boot and integration

The owner reported the normal login screen. USB inspection confirmed image
`0.1.0-diagnostic.9`, kernel `6.18.54-gameshellneo8` and boot ID
`3039b11f-a90b-4f55-bfdb-1f41e8cb604c`. The live keypad retention property is
present, the keypad supply reports enabled, and USB persistence remains `1`
with runtime policy `on` / forbidden and no keypad wake attribute. Initial
USB keypad device number is 2. All seven services are active without restarts;
taint and all PM counters are zero. Battery telemetry reports 100% and USB is
configured. Wi-Fi reports an association.

All six integration groups passed with configured/global regulatory country NZ
and radio domain 99. Evidence:

- `.local/diagnostics/20260930T065522.036210Z/inspection.json`
- `.local/diagnostics/20260930T065522.012546Z/keypad.json`
- `.local/diagnostics/20260930T065558.228303Z/integration.json`

The first freezer attempt stopped during the independent Wi-Fi SSH preflight:
the Mac, still on the transfer network, could not open the GameShell's Wi-Fi
route. No PM run was submitted and no suspend stage was entered. Its preflight
evidence is `.local/diagnostics/20260930T065623.688089Z/`, with the connection
failure in `.local/neo45-freezer.log`. The owner was asked to place the Mac on
the GameShell's configured network before continuing.

## First debug tests

After the owner placed the Mac on the same network, both independent SSH routes
worked. The freezer test passed with the original input handle healthy and
all controls restored: run `cb0cd155f15845b68ff3e388a45ae31e`, evidence
`.local/diagnostics/20260930T070006.771026Z/cycle-1/`. Its 5.306-second stage
includes the deliberate five-second debug pause.

The owner was ready to watch the first retention driver test, then confirmed
the normal dim console and brightness returned. Run
`a4bd89ff1137467aa76db12cdc88a8ab`, at
`.local/diagnostics/20260930T070110.143746Z/cycle-1/`, passed with:

- Both USB/Wi-Fi SSH routes and all PM/trace settings restored.
- The original input handle healthy, unchanged USB device number 2 and input
  sysfs identity, and no keypad disconnect.
- No keypad supply-disable event; 3,738 trace events with no overruns, commit
  overruns or dropped events on any CPU.
- A 7.596-second debug stage and a fresh healthy handle observed 0.176 seconds
  afterwards. This is approximately 7.772 seconds including the five-second
  pause and measurement overhead, not real sleep/wake or physical key latency.

The USB resume callback took 1.116684 seconds. The journal recorded
`Waited 0ms for CONNECT`, followed by reset-resume of the same low-speed USB
device. Supply retention avoids the disconnected persistence wait and preserves
the input handle, but it does not eliminate USB reset recovery.

## Interrupted repeated batch and recorder correction

The first four-cycle attempt is retained at
`.local/diagnostics/20260930T070308.916091Z/`. Its first cycle,
`f4641b415d2e49399c2c57e2b1fe0ba9`, passed with the same input continuity and
no supply-disable event. Its stage took 7.581 seconds, with a fresh healthy
handle observed 0.191 seconds later. Collection encountered one transient SSH
banner error; the saved retry collected the same run and verified both routes
without resubmitting a PM operation.

The second attempt, `cd9897ee95964bbf9748bfd710c7e91a`, was rejected by the
device-side health preflight before any PM stage. The host preflight had passed,
but the original recorder omitted the rejected device snapshot, so the exact
failing condition cannot be established retrospectively. The batch stopped;
it is not counted as a completed four-cycle qualification.

Independent inspection at
`.local/diagnostics/20260930T070603.044574Z/inspection.json` confirmed the same
boot, restored `pm_test=none` / `pm_async=1`, PM success count 3, all failure
counters zero, all services active without restarts, USB/Wi-Fi connected and
fresh valid charging telemetry at 100%. The saved service journal showed no
service restart or failure; its Wi-Fi disconnect/reconnect preceded the
rejected preflight and does not establish the cause.

NEO-46 fixes the evidence gap: device-owned results now preserve a rejected
preflight snapshot and identify failed health gates without exposing credentials
in errors. All gate thresholds and entry/restoration rules are unchanged.
The added regression proves rejected preflights cannot enter PM. Host checks
passed 234 tool tests (one optional skip), 13 runtime tests and compiled/lint
checks. Commit `6be4f60` was pushed before restarting the full four-cycle batch;
no image or live power policy changed.

## Completed four-cycle batch

The unchanged candidate passed a fresh `task device:keypad-retention CYCLES=4`
batch after the recorder correction. Evidence is under
`.local/diagnostics/20260930T070923.063896Z/`, in each cycle's `result.json`,
`retention.json` and bounded trace. The complete host log is
`.local/neo45-retention-four-rerun.log`.

| Cycle | Debug stage (s) | Fresh healthy handle after stage (s) | Combined observation (s) | Keypad USB resume callback (s) |
| --- | ---: | ---: | ---: | ---: |
| 1 | 7.644 | 0.238 | 7.882 | 1.091 |
| 2 | 7.638 | 0.214 | 7.852 | 1.096 |
| 3 | 7.698 | 0.245 | 7.942 | 1.088 |
| 4 | 7.665 | 0.240 | 7.905 | 1.111 |

Run IDs, in order:

- `41cdeafdc97d4830aee7cd282394905d`
- `3474c039391f41198b3e8f760d485cd4`
- `f1ea595fcefc4d8d8dd1e8be2f7bb0d8`
- `f6ac237185b8487c82c87eec39698d77`

Every cycle preserved the original open input handle, USB device number 2 and
input sysfs identity. There were no keypad disconnects or supply-disable events.
Persistence remained enabled, runtime control remained `on` and no keypad wake
attribute appeared. Each trace captured 3,738/3,738 events with no overruns,
commit overruns or dropped events, and all tracing/PM controls were restored.
Fresh USB and Wi-Fi SSH connections passed after every cycle. No unsupported
ULPI warnings, PM failures or extra firmware loads occurred.

Cycles 1 and 2 each encountered one transient SSH collection error (`No existing
session`). The saved retry retrieved the same completed run and verified both
routes; no PM operation was resubmitted. Cycles 3 and 4 collected directly.
There was no health-preflight rejection in this complete batch. The owner
confirmed the normal dim login console and brightness after the batch.

## Comparison and remaining cost

The mean combined observation is 7.895 seconds, versus 9.372 seconds for
diagnostic.8's accepted persistence-off/power-off candidate, and 11.187 seconds
for the mean of its surrounding persistence-on/power-off observations. Supply
retention therefore produced a healthy handle about **1.48 seconds earlier than
the previous fastest candidate**, or 3.29 seconds earlier than the surrounding
default-policy baseline. More significantly, the original handle survived;
the power-off variants required consumers to reopen the input device.

The prior comparison is preserved at
`.local/diagnostics/20260930T061124.693722Z/` and described in
[report 61](61-keypad-persistence-comparison.md). These are small samples from
different boots using the same kernel binary and tracing method. The combined
observation includes the intentional five-second debug pause, suspend/setup
work, synchronization and handle polling. It is not real wake latency or the
time to the first physical key event; subtracting five seconds does not make
it either measurement.

Reset-resume remains: every cycle recorded `Waited 0ms for CONNECT` and a reset
of the same low-speed USB device. The keypad's USB resume callback still took
1.088–1.111 seconds, while the traced `dpm_resume` interval was 1.521–1.542
seconds. Retaining the supply removes disconnection and the exhausted connect
wait, but further USB recovery work remains before a sub-second target can be
assessed.

## Final state and limits

Independent final inspections are saved at:

- `.local/diagnostics/20260930T071505.380898Z/inspection.json`
- `.local/diagnostics/20260930T071505.339387Z/keypad.json`

The original boot ID is unchanged. PM success is 7, accounting for one freezer
and six executed devices stages: the first watched stage, the completed stage
from the interrupted batch, and the four-cycle rerun. All failure counters are
zero. `pm_test=none`, `pm_async=1`, all seven services are active without
restarts, no units have failed, taint is zero and there has been one firmware
load for the entire boot. USB is configured, Wi-Fi is connected and battery
telemetry reports 100% with USB attached. Keypad device number remains 2 and
its supply reports enabled. Software supply state does not measure rail voltage.

NEO-45's installation and driver-debug continuity qualification is complete.
The test is repeatable with the saved task; diagnostic.8 recovery remains
available. Physical input delivery, held/released-key behavior, real sleep,
power-button wake, wake latency and retention energy cost remain unqualified.
Normal sleep stays disabled and the power button retains its shutdown behavior.
The next qualification should exercise actual key presses/releases through the
retained handle before assessing scoped USB recovery options and the power cost
of retaining the keypad supply.
