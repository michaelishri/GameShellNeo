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

## Hardware status

Freezer and retention debug tests are pending. Boot and integration do not
qualify keypad continuity, input delivery, actual sleep, wake latency or energy
cost.
