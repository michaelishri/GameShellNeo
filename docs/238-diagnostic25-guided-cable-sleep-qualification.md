# Diagnostic.25 guided cable changes during sleep

9 October 2026; evidence timestamps are UTC. NEO-176 is complete under
NEO-108. All seven fresh debug prerequisites pass, with PM27/0 and independent
USB/Wi-Fi recovery throughout. The owner confirms normal warnings and display
returns. All four guided cable cycles pass, including separate owner
observations: two removals and two attachments during sleep. Both insertions
stay dark until the later RTC wake. Final health and both network routes pass
at PM31/0; USB is connected and no further sleep test is running.

## Scope and starting state

[Report 237](237-diagnostic25-battery-rtc-qualification.md) records the passing
battery-only RTC sleep and separate USB reattachment. This slice uses the
existing [guided four-cycle workflow](174-guided-cable-sleep-batch.md): removal,
attachment, removal, attachment. Each step runs its own awake RTC rehearsal
and one sleep, then stops for a separately recorded owner observation. The
fixed session carries one fresh debug baseline through the four steps without
an extra awake cable change between steps. It was previously qualified on
diagnostic.20 in [report 178](178-guided-cable-batch-hardware-validation.md).

Source checkpoint is `ed16433`, diagnostic.25/kernel
`6.18.54-gameshellneo24`, boot `2170b296-d964-4d16-bdb1-c135b0e7b812`.
The current USB-connected PM inspection passes full health, with PM20/0,
all four CPU s2idle counts 6 and valid battery monitoring reporting 99% and
charging. Independent Wi-Fi SSH verifies the same boot. Disabled MUSB and
external-supply wake policies match the declared `masked-cable-v2` criteria.
No image, helper source, charging or network configuration is changed.

Preflight capture is
`.local/diagnostics/20261009T065713.430931Z/inspection.json`, SHA-256
`170e732d5ee7f01e9e5d2164e265650b3e5f6106935badf457626cf3f690e575`.
Private evidence is `.local/neo176-before-{pm,wifi}.log` and
`.local/neo176-preflight-validation.json`.

The earlier battery history has already been consumed and cannot become a
cable profile. The owner explicitly readied the fresh debug preparation,
keeping USB connected, the headphone socket empty and controls untouched,
watching for the long warnings and normal dim-console returns. Each original
result is reviewed before the next submission; any failure stops the sequence.
The freezer, devices and five platform debug stages do not enter real sleep.

```sh
task device:pm-test STAGE=freezer CYCLES=1 SOCKET_STATE=0
task device:pm-power-key STAGE=devices CYCLES=1 KEYPAD_TRACE=1 WIFI_TRACE=1 SOCKET_STATE=0
task device:pm-platform WIFI_TRACE=1 SOCKET_STATE=0
```

The platform command ran five times, subject to review. The saved
`check:sdio-ref-history -- --require-stable` task binds all seven explicit
original results. Cable-cycle readiness is separate and describes keeping the
starting cable state through the awake rehearsal, waiting ten seconds after
darkness, then performing one requested action. The next action is not
authorized by a prior observation alone.

## Fresh seven-debug results

Each original result passes full offline revalidation before the next command.
PM advances 20 → 27 with all failure counters zero. All four CPU s2idle counts
remain 6 and their s2idle time is unchanged; these are debug stages rather than
actual sleep. SDIO usage stays 2 with unchanged policy. The six devices/platform
checks retain the original keypad handle, USB device number and input identity,
with no disconnect or supply-disable event. Wi-Fi/keypad traces, warning mixer
state and power-key ownership restore correctly. Both network routes are
independently verified after every result.

Capture paths are relative to `.local/diagnostics/`, with each original saved as
`cycle-1/result.json`.

| Stage | Capture | Run ID | PM afterward | Stage seconds |
| --- | --- | --- | --- | --- |
| Freezer | `20261009T065830.178271Z` | `4f13c4c22d2440baaac5a25efed3ad28` | 21/0 | 5.312 |
| Devices | `20261009T065947.058559Z` | `386d50690d5648a88aee5ba9329ceec8` | 22/0 | 7.821 |
| Late/noirq 1 | `20261009T070106.221270Z` | `c397ea41b7344465ae1fef40bb8c523a` | 23/0 | 7.810 |
| Late/noirq 2 | `20261009T070224.313978Z` | `1a32e4a9f74d4058a5d38fdab6fd8176` | 24/0 | 7.881 |
| Late/noirq 3 | `20261009T070342.364421Z` | `44d6c7b4804a41f393b955ccfd459d33` | 25/0 | 7.906 |
| Late/noirq 4 | `20261009T070459.970655Z` | `c602d4b8e66a4b9ba8a11fc1e287ab56` | 26/0 | 7.801 |
| Late/noirq 5 | `20261009T070619.569981Z` | `b643f3e816da4c5b8e486cc1de80fcfe` | 27/0 | 7.904 |

| Original result | SHA-256 |
| --- | --- |
| Freezer | `2a8337d355abf5d23aeb058476820aea516efe8ea28e73f349ee1dc396f0e4ec` |
| Devices | `23e59beb5083c22644e0cd6d13a2399aa12fc3706abadf088f89b073f3db8de9` |
| Late/noirq 1 | `497dc674ccb946ed8ff798526b9a0d2bc52050ab1dc109dd3549f8ba9d364741` |
| Late/noirq 2 | `4b7e69e616e382b15b9e08640f7001713e8f8ccf67e10b57d2461a63ace70e4d` |
| Late/noirq 3 | `f1e690c54a7134ae13278c1cf2298528f85787f4440421db4a3c0c82ed33283b` |
| Late/noirq 4 | `90b9bec128eb2a4e12cae77f2ca423980f92fb8d6f95fc4da6cf231d03dbd756` |
| Late/noirq 5 | `d001712778500b74671e258c11c263f50eeac4d88f9c9e4ae59dfacee3d585e2` |

The saved `check:sdio-ref-history -- --require-stable` task binds all seven
explicit originals in `.local/neo176-reference-history.json`, SHA-256
`6728c87a6846192f49b9b0c0569204553ee0c8147a95a3a82d084377109ac1d3`. Offline review is
`.local/neo176-debug-summary.json`; task logs are `.local/neo176-freezer.log`,
`.local/neo176-driver.log` and `.local/neo176-platform{1,2,3,4,5}.log`.

Platform checks 1 and 2 each retain one channel-opening timeout; platform
checks 3 and 5 each retain one channel-connect failure. The same original
results were subsequently collected, and independent route proofs passed.
The freezer, devices and platform4 captures have no collection errors. These
errors are preserved without a root-cause claim or renewed SSH investigation;
no PM submission was repeated.

The owner subsequently answered “All looks good” to the preparation's warning
and display confirmation. Separate cycle-1 instructions request keeping USB
connected through the awake alarm check, waiting ten seconds after screen
darkness, removing USB once and leaving it disconnected. No button action is
requested; an early screen return means leaving the cable untouched. Actual
submission waits for the owner's explicit readiness to follow that sequence.

## Qualification limits

Each original awake/sleep result must pass full source, boot, lineage, RTC,
PM, memory, keypad, trace, audio and control-restoration checks. Actual sleeps
also require all four WFI sleep callbacks and independent timekeeping-freeze
evidence. Removal ends on battery with Wi-Fi proof; attachment ends with USB
and Wi-Fi proof. An independent endpoint inspection precedes the owner report.
The owner must confirm the requested action occurred during darkness and the
normal display returned. Insertion should leave the screen dark until RTC wake.

Original failed or uncertain attempts are preserved, with collection by their
original run ID and no second PM submission. The abandoned SSH-stall work is
not resumed. Software cable/IRQ observations and the owner's display report
do not measure electrical edge timing, charging current during sleep, energy
savings, deeper CPU/DRAM retention or general reliability. Ordinary product
sleep and power-button wake remain separate.

## Guided session results

Batch ID: `a5a0d897f18c4a30bf2017b0c6ac1e99`. Private session: `.local/diagnostics/20261009T071557.123299Z`.
Accepted owner-observed cycles: 4/4. Saved state at this
checkpoint: `complete`. Each cycle has separate described readiness.

Saved commands (observation arguments reflect the owner's actual report):

```sh
task device:sleep-cable-batch-start QUALIFICATION=.local/neo176-reference-history.json ATTENDED=1 CABLE_ACTION=1 SOCKET_STATE=0
task report:sleep-cable-batch BATCH=.local/diagnostics/20261009T071557.123299Z OBSERVATION=during-dark DISPLAY=normal
task device:sleep-cable-batch-next BATCH=.local/diagnostics/20261009T071557.123299Z ATTENDED=1 CABLE_ACTION=1 SOCKET_STATE=0
```

The observer report performs no device action. Each next command runs only
one awake rehearsal and one actual sleep, then stops. Result, rehearsal,
endpoint and observer hashes are pinned in the batch record. The saved
`report:sleep-evidence` task independently assesses each actual result;
its `overall_requalified=false` preserves the original result.

### Accepted cycle 1: removal

Awake rehearsal `47c60b67648f45e1bdb60a7ac374bbdc` passes with RTC IRQ31
9 → 10 after 30.418 seconds, PM27/0 unchanged and
the starting cable state untouched. Actual sleep `70e5bb829bcb4e6298bce82fc1fbe226`
passes PM27 → 28, zero failures and RTC IRQ31
10 → 11. The original wake observation identifies an RTC event
and wake IRQ31.

Alarm-to-return is 32.067 seconds, with a
28.870-second BOOTTIME–MONOTONIC gap. All four CPU s2idle
counts advance once, to 7, and one timekeeping-freeze pair is observed.
Original memory, keypad, warning audio, console, traces, RTC and power-key
ownership restore, with SDIO usage unchanged at 2.

Final cable state is absent: UDC not attached, carrier0, PHY USB0/HOST0
and both external supplies absent/offline. Independent Wi-Fi proof and the
separate endpoint inspection pass before any later attachment. Absent USB is
explicitly not reported as USB recovery. The owner confirms the clear warning,
one removal during darkness and normal dim-console return.

Cable-handler deltas are `{'ACIN_PLUGIN': 0, 'ACIN_REMOVAL': 0, 'VBUS_PLUGIN': 0, 'VBUS_REMOVAL': 0}`,
accepted under the predeclared `masked-cable-v2` criteria. Handler counts do
not timestamp the physical edge.

Original collection errors are preserved:

- result: `SSHException: Timeout opening channel.`; `ChannelException: ChannelException(2, 'Connect failed')`; `ChannelException: ChannelException(2, 'Connect failed')`.

All refer to collection of the original run; no sleep was resubmitted.

| Evidence | SHA-256 |
| --- | --- |
| rehearsal | `8ab8ff3567270ebfbac7fb908ef43c34e8cdd6e99702273be4d084d64f7e348c` |
| result | `f390cec864158dd06d8059b1d460a7f0ded413f4e8c67320eeed9fc27f0a156c` |
| endpoint | `b6af1b587bc394f569dd39b35ef91242e77f306f3b996dc4df675ab928700c89` |
| observer | `3f33910d10f608cdab62d26edc96b5305de0eedfddc6dc022e6a6e326438fb2d` |

Private task log: `.local/neo176-cable-cycle1.log`. Offline review is
`.local/neo176-cycle1-review.json`; separate assessment and owner-report logs
are `.local/neo176-cycle1-evidence.log` and
`.local/neo176-cycle1-observation.log`.

### Accepted cycle 2: attachment

Awake rehearsal `c02d4c53aeba47f78f6a979b770871ff` passes with RTC IRQ31
11 → 12 after 30.722 seconds, PM28/0 unchanged and
the starting cable state untouched. Actual sleep `e795226416f04d0c85bc79adef4e6ed2`
passes PM28 → 29, zero failures and RTC IRQ31
12 → 13. The original wake observation identifies an RTC event
and wake IRQ31.

Alarm-to-return is 32.483 seconds, with a
29.254-second BOOTTIME–MONOTONIC gap. All four CPU s2idle
counts advance once, to 8, and one timekeeping-freeze pair is observed.
Original memory, keypad, warning audio, console, traces, RTC and power-key
ownership restore, with SDIO usage unchanged at 2.

Final cable state is attached: configured UDC, carrier1, PHY USB1/HOST0
and both external supplies present/online. Both USB and Wi-Fi proofs and the
separate endpoint inspection pass. The owner confirms the clear warning, one
insertion during darkness, the screen staying dark after insertion, and later
normal dim-console return on RTC wake. This is visible stay-asleep behavior,
not a measurement of charging current while asleep.

Cable-handler deltas are `{'ACIN_PLUGIN': 0, 'ACIN_REMOVAL': 0, 'VBUS_PLUGIN': 0, 'VBUS_REMOVAL': 0}`,
accepted under the predeclared `masked-cable-v2` criteria. Handler counts do
not timestamp the physical edge.

Original collection errors are preserved:

- result: `ChannelException: ChannelException(2, 'Connect failed')`; `SSHException: Timeout opening channel.`; `ChannelException: ChannelException(2, 'Connect failed')`.

All refer to collection of the original run; no sleep was resubmitted.

| Evidence | SHA-256 |
| --- | --- |
| rehearsal | `b857bff6cb8a556280b9d69539225e73f14ba3647583cfa92ef58da230f13366` |
| result | `bbd77544286b883668ce84f40928158900a0b6e563fdfe778152e7604509a094` |
| endpoint | `4b4fcce144ed784581cdaff691d0db0aa18090032baffda046bfe752faccdd15` |
| observer | `83c5c01ac8dd6a4ab5c04d459a10d65e46db0342efe6d8a4ab03a3cde29b5e74` |

Private task log: `.local/neo176-cable-cycle2.log`. Offline review is
`.local/neo176-cycle2-review.json`; separate assessment and owner-report logs
are `.local/neo176-cycle2-evidence.log` and
`.local/neo176-cycle2-observation.log`.

### Accepted cycle 3: removal

Awake rehearsal `84c58705d7fa4111875c8b24d86a9706` passes with RTC IRQ31
13 → 14 after 30.080 seconds, PM29/0 unchanged and
the starting cable state untouched. Actual sleep `806e5338cf484541b90680bab0e79070`
passes PM29 → 30, zero failures and RTC IRQ31
14 → 15. The original wake observation identifies an RTC event
and wake IRQ31.

Alarm-to-return is 32.092 seconds, with a
28.792-second BOOTTIME–MONOTONIC gap. All four CPU s2idle
counts advance once, to 9, and one timekeeping-freeze pair is observed.
Original memory, keypad, warning audio, console, traces, RTC and power-key
ownership restore, with SDIO usage unchanged at 2.

Final cable state is absent: UDC not attached, carrier0, PHY USB0/HOST0
and both external supplies absent/offline. Independent Wi-Fi proof and the
separate endpoint inspection pass before any later attachment. Absent USB is
explicitly not reported as USB recovery. The owner confirms the clear warning,
one removal during darkness and normal dim-console return.

Cable-handler deltas are `{'ACIN_PLUGIN': 0, 'ACIN_REMOVAL': 0, 'VBUS_PLUGIN': 0, 'VBUS_REMOVAL': 0}`,
accepted under the predeclared `masked-cable-v2` criteria. Handler counts do
not timestamp the physical edge.

Original collection errors are preserved:

- result: `SSHException: Timeout opening channel.`; `ChannelException: ChannelException(2, 'Connect failed')`; `ChannelException: ChannelException(2, 'Connect failed')`; `SSHException: Timeout opening channel.`.

All refer to collection of the original run; no sleep was resubmitted.

| Evidence | SHA-256 |
| --- | --- |
| rehearsal | `7e5f89f2ac8d902266ac4107132eae0ee72cdc2bcacc8c90da09dcb60b205830` |
| result | `f2484f6d0ba24a06d138a5eb05446b468abfbd930b545ef68c8c60ca2cb44afe` |
| endpoint | `6ba5708de8b574eeea1a3dba91c9c2172581a4506a01265f8141f924dadb38bc` |
| observer | `abee973fd8b66b1e49bf45337b866ff45eb6a801cd39c35496edef51456b2ea7` |

Private task log: `.local/neo176-cable-cycle3.log`. Offline review is
`.local/neo176-cycle3-review.json`; separate assessment and owner-report logs
are `.local/neo176-cycle3-evidence.log` and
`.local/neo176-cycle3-observation.log`.

### Accepted cycle 4: attachment

Awake rehearsal `ef008ec80cfb4e648e7a2523e339ef9a` passes with RTC IRQ31
15 → 16 after 30.605 seconds, PM30/0 unchanged and
the starting cable state untouched. Actual sleep `aeb5c6e48a0b48809688786a047e2e58`
passes PM30 → 31, zero failures and RTC IRQ31
16 → 17. The original wake observation identifies an RTC event
and wake IRQ31.

Alarm-to-return is 31.786 seconds, with a
27.947-second BOOTTIME–MONOTONIC gap. All four CPU s2idle
counts advance once, to 10, and one timekeeping-freeze pair is observed.
Original memory, keypad, warning audio, console, traces, RTC and power-key
ownership restore, with SDIO usage unchanged at 2.

Final cable state is attached: configured UDC, carrier1, PHY USB1/HOST0
and both external supplies present/online. Both USB and Wi-Fi proofs and the
separate endpoint inspection pass. The owner confirms the clear warning, one
insertion during darkness, the screen staying dark after insertion, and later
normal dim-console return on RTC wake. This is visible stay-asleep behavior,
not a measurement of charging current while asleep.

Cable-handler deltas are `{'ACIN_PLUGIN': 0, 'ACIN_REMOVAL': 0, 'VBUS_PLUGIN': 0, 'VBUS_REMOVAL': 0}`,
accepted under the predeclared `masked-cable-v2` criteria. Handler counts do
not timestamp the physical edge.

Original collection errors are preserved:

- result: `SSHException: Timeout opening channel.`; `SSHException: Timeout opening channel.`.

All refer to collection of the original run; no sleep was resubmitted.

| Evidence | SHA-256 |
| --- | --- |
| rehearsal | `0496745f5d853b69b0c6dba3d58e60ffea298c23313932d8e41c257dfc0d30f5` |
| result | `59e65b3771af13665176d7b34fb5e04438cf77d19d355edb1d2b35b7c6e4f384` |
| endpoint | `ecb2a54f4e5d24f82ff979e0b50fda36ce02d946c3362c498023a34e9116ff13` |
| observer | `4dff30f2a6155a70469edca17f9d686ebb0f3ab2be98220c0d4fc60ab275b6e9` |

Private task log: `.local/neo176-cable-cycle4.log`. Offline review is
`.local/neo176-cycle4-review.json`; separate assessment and owner-report logs
are `.local/neo176-cycle4-evidence.log` and
`.local/neo176-cycle4-observation.log`.

## Final validation and completion boundary

The batch is `complete`, `passed=true`, with four accepted cycles and no
pending observation. Independent offline review revalidates every original
awake/sleep pair and its ancestry, unchanged source/image/boot identity,
matching RTC sequence, parent claim, observer hash and endpoint continuity.
No extra awake cable change or repeated debug baseline occurs between steps.
The completed session cannot admit a fifth cycle.

Final `device:pm-inspect ROUTE=usb`, independent Wi-Fi boot access and
`device:power-policy-inspect` pass. The snapshot follows the final original
without additional PM activity or journal loss. PM remains 31 successes and
zero failures; all four CPU s2idle counts remain 10. SDIO stays at usage 2
with its original policy, the dim display is brightness1/backlight power0,
and battery monitoring is valid at 96%/Charging. The effective power-key policy
exactly matches the restored final original, with no diagnostic owner or
drop-in. Ordinary product sleep remains disabled.

| Final artifact | SHA-256 |
| --- | --- |
| Batch `20261009T071557.123299Z/batch.json` | `3d092fa69bc1f1de98016d91527516e20a49a079bf36b833c1b5ad33cc105d04` |
| PM `20261009T073208.126221Z/inspection.json` | `ed13728049c289b3b7e852d5402827eb65383ebdd2c619d4772ef855933c1dab` |
| Policy `20261009T073233.446358Z/before.json` | `f838e6b867d1193cc8750950ab5154beef0f300ad6013681f1d8a35c4ea2dd1a` |

Paths are relative to `.local/diagnostics/`. Final logs are
`.local/neo176-final-{pm,wifi,policy}.log`; the saved offline review is
`.local/neo176-final-validation.json`. Each separate RTC/trace/paired-clock/WFI
assessment passes without altering the original results. All recorded
collection errors remain preserved; the existing runner collects each original
run rather than repeating a sleep submission. No transport investigation or
network policy change accompanies this qualification.

No implementation changes were needed, so the previously passing source tests
were not repeated. Documentation validation checks artifact hashes, local links
and whitespace. Together with reports 233–237, this completes diagnostic.25's
planned bounded startup, staged PM, connected/battery sleep, awake reconnect
and cable-transition coverage. It does not demonstrate that the deferred
endpoint race occurred on the board, nor establish broad reliability, energy
savings, charge acceptance during sleep, deep retention or power-button wake.
Integration review remains separate under NEO-108.
