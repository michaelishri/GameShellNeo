# Diagnostic.19 attended debug qualification

5 October 2026, Pacific/Auckland; capture timestamps are UTC. NEO-112.

This report records qualification after the owner moved the Mac and GameShell
to the office, slept the Mac, and shut down and restarted the GameShell.
The installed image is unchanged from [report 155](155-diagnostic19-installation-and-awake-checks.md):
`0.1.0-diagnostic.19`, kernel `6.18.54-gameshellneo19`. The new boot ID is
`2fa86697-ead3-4e6f-a295-44e6ad203983`. The previous home's awake qualification
in [report 156](156-diagnostic19-unattended-validation.md) remains historical
evidence; fresh same-boot checks precede this attended sequence.

One freezer, one driver and five late/noirq debug cycles passed. PM successes
advanced from zero to seven with every failure counter zero; SDIO runtime usage
stayed at 2. Both SSH routes recovered after every cycle. The owner confirmed
normal display after the final batch. These results do not establish actual sleep,
cable-transition recovery or energy savings. Ordinary automatic and
button-triggered sleep remain disabled, and NEO-112 remains open.

## Network and awake admission

The owner updated `.env` with the current network credentials. The first saved
`task device:wifi-config` transaction associated the GameShell on 2.4 GHz,
but could not independently reach it through the Mac, which was still on a
different network. It failed verification after nine attempts and restored the
previous configuration with `cleanup_verified=true`. The original capture is
`20261004T215203.657539Z/wifi-change.json`; it remains failed rather than being
reclassified as a device fault or successful network change.

After the owner moved the Mac to the same network, a new transaction passed,
committed the configuration and verified cleanup. Its capture is
`20261004T220608.191123Z`. Credentials remain private in `.env` and the private
captures. There was no GameShell reboot between the two transactions.

The saved current-boot check (`device:boot-cycles CYCLES=0`) verified both SSH
routes. All six integration groups passed with global country NZ; this office
session does not use the home's earlier accepted AU announcement override.
Firmware-country readback remains a separate unqualified item.

| Check | Capture beneath `.local/diagnostics/` | Result |
| --- | --- | --- |
| Initial PM inspection | `20261004T214133.169195Z` | New boot, PM 0/0, SDIO runtime usage 2 |
| Effective power policy | `20261004T214133.143379Z` | Diagnostic short-press poweroff and idle-ignore; no retained owner/drop-in |
| Sequential journal inspection | `20261004T214155.803394Z` | Early boot evidence retained |
| Journal rotation | `20261004T214228.800982Z` | Continuity checks passed |
| Awake power-key ownership | `20261004T214238.647323Z` | No input events; ownership handed back |
| Awake RTC | `20261004T214243.274261Z` | Run `60b6315d9800415aa69b7606a2d2e2cb`; passed/restored, 10.552 seconds |
| Current boot and independent routes | `20261004T220651.370441Z` | Both USB and Wi-Fi SSH passed |
| Integration after network change | `20261004T220730.836209Z` | Six groups passed |
| Fresh PM inspection | `20261004T220742.930793Z` | Strict admission passed; PM still 0/0 |

An initial concurrent journal inspection, `20261004T214133.171599Z`, could not
acquire the host diagnostic lock. It stopped before contacting the board.
The sequential inspection above passed. The failed record is preserved and is
not a hardware failure.

## Attended debug sequence

The owner explicitly confirmed readiness before freezer/devices, separately
before the first late/noirq test, and again before the four-repeat batch.
USB remains connected and the controls are to remain untouched throughout.
The owner confirmed normal display after the first driver and first late/noirq
tests, then confirmed that all four repeats returned normally with normal
screen and brightness.

The saved commands are:

```sh
task device:pm-power-key STAGE=freezer CYCLES=1
task device:pm-power-key STAGE=devices CYCLES=1 KEYPAD_TRACE=1 WIFI_TRACE=1
task device:pm-platform
# After fresh observer readiness, repeat the last command four times,
# reviewing each complete result and both SSH proofs before the next.
```

Each platform command runs only one cycle. The controller validates restoration,
the original keypad handle, complete traces, power-key handback, PM counters,
and independent USB/Wi-Fi SSH. A five-second debug delay is included in the
reported stage times; they are not production suspend/resume latency.

| Stage | Capture beneath `.local/diagnostics/` | Run ID | Stage seconds | Final PM successes |
| --- | --- | --- | ---: | ---: |
| Freezer | `20261004T220803.998939Z` | `7ffd925adb384cd38a862c4dffbe1473` | 5.580 | 1 |
| Driver | `20261004T220925.488467Z` | `4b5248e2e07b48b0af87b650ffcbbbf7` | 7.750 | 2 |
| First late/noirq | `20261004T221127.784076Z` | `234120b5949644dc99892cc28291e54b` | 7.718 | 3 |
| Repeat 1 | `20261004T221534.322381Z` | `7d9b8bd1c994486394799906410e63eb` | 7.886 | 4 |
| Repeat 2 | `20261004T221655.152885Z` | `9a716ea0db0b423888e5855885aba370` | 7.942 | 5 |
| Repeat 3 | `20261004T221824.192754Z` | `4c3584b0214e487daabd314a750b51d5` | 7.932 | 6 |
| Repeat 4 | `20261004T221959.631744Z` | `e3532a6087494e58876cc4a87dcf8765` | 7.976 | 7 |

Each capture contains `cycle-1/result.json`. Every controller exited zero,
and each completed original result has both independent route proofs. All six
driver/platform runs preserve the original keypad handle, with no held keys at
completion. Keypad and Wi-Fi traces have no recorded loss and restore correctly;
power-key ownership is handed back. Each platform trace includes
`dpm_suspend_late`, `dpm_suspend_noirq`, `dpm_resume_noirq` and
`dpm_resume_early`, plus RSB noirq suspend/resume. These are debug returns,
not entries into real sleep.

Each driver/platform capture retains one transient
`SSHException: Timeout opening channel.` during result collection. The saved
collector subsequently retrieved that same original run and independently
verified both routes; it never resubmitted the PM command. These timeouts do
not invalidate the completed evidence, but their cause and contribution to
recovery latency remain unassigned. Follow-up transport timing work should
separate Mac forwarding, the device's SSH service and actual USB recovery.

The saved offline `task check:sdio-ref-history -- --require-stable` command,
given the seven explicit result paths above, confirms unchanged SDIO usage 2,
control `on`, runtime status `active`, and runtime PM `forbidden`. Its summary
is `.local/neo112-office-debug-history.json`, SHA-256
`efb2c48897ca7613b949d8fdf844cf8686701c13920f286099aff42ef843a6ab`.
This is the seven-debug baseline for the next unchanged-cable rehearsal;
later sleep admission must still revalidate all originals and current state.

The final cycle's result SHA-256 is
`74ae8834f1605e71a858995c1488ae6cba38ff5037e8d4b644b8ed550fa441ef`.
Its final snapshot has PM 7/0, kernel taint zero, no failed units, `pm_test=none`,
s2idle selected, and all ordinary sleep targets still masked. Battery telemetry
reports 94%. No charging configuration was changed. Private controller logs
are `.local/neo112-office-*.log`. No further screen test is running at this
checkpoint.

## Remaining qualification

After the owner's final display confirmation, the saved
`task device:sleep-rehearse QUALIFICATION=.local/neo112-office-debug-history.json`
passed on the same boot. Run `22984d31403f44dea440a785c88e2295`, capture
`20261004T222244.932964Z/result.json`, delivered its alarm after 30.451 seconds,
restored RTC and power policy, retained no ownership/drop-in/console record,
and verified both SSH routes. PM remained 7/0. Its result SHA-256 is
`386aa5860e5425965a11d85e576548c02d42bfcb3ac8ea12e1124041832a778b`.

Before confirming readiness for actual sleep, the owner requested a GameShell
speaker warning before every reboot and screen blanking. No actual sleep was
submitted. NEO-115 adds that behavior to the saved workflows. This historical
rehearsal must not be used with changed helper sources; repeat the matching
awake rehearsal after the warning implementation is validated.

The next hardware step is a separately attended unchanged-cable actual sleep
comparison after its current-source admission checks. The removal scenario then needs its
own fresh prerequisites and matching rehearsal. Collect its original result
over Wi-Fi before any requested cable reconnection; attachment remains a
separate scenario. Diagnostic.18's failed removal result in
[report 153](153-usb-removal-sleep-state-failure.md) remains unchanged.
