# Diagnostic.25 connected-USB sleep repeatability

9 October 2026; evidence timestamps are UTC. NEO-173 is complete under NEO-108.
All four attended actual sleep/wake repeats pass on diagnostic.25/kernel
`6.18.54-gameshellneo24`, boot `2170b296-d964-4d16-bdb1-c135b0e7b812`.
Both network routes recover each time, the original keypad remains connected
and all four CPU sleep callbacks run once per cycle, with independent
timekeeping-freeze evidence. The owner confirms clear long warnings and normal
dim-console returns after every cycle without touching the cable or controls.
Final PM success/fail is **12/0**: seven debug checks and five actual sleeps,
including the initial sleep in report 234. This qualifies the bounded
connected-USB functional batch; it does not establish broad reliability, a
hardware race reproduction, wake latency or energy savings.

## Saved workflow and starting state

[Report 234](234-diagnostic25-pm-qualification.md) records seven passing debug
checks, the awake RTC rehearsal and first actual connected-USB RTC sleep.
At source checkpoint `cfe806f`, a fresh read-only `device:pm-inspect ROUTE=usb`
capture at `.local/diagnostics/20261009T055825.666085Z` passes full health and
the existing controller's source-bound continuation admission. PM is 8/0, all
four s2idle counts are 1 and the same boot/image and dim backlight remain.
Inspection SHA-256:
`eae0f02387072c42c5a5e50bc726f8ad3d53a0c119a6e0eba2666a72ae8197ea`.
The saved check is `.local/neo173-preflight-validation.json`.

The owner confirmed readiness to watch and listen for all four cycles, keeping
USB connected, the headphone socket empty and controls untouched. The existing
saved task ran once from `work/musb-restart-integration`:

```sh
task device:sleep-batch \
  QUALIFICATION=.local/diagnostics/20261009T055321.131756Z/qualification-next.json \
  REHEARSAL=e2d0187e79604413907a92b22963d79e CYCLES=4 ATTENDED=1 SOCKET_STATE=0
```

The runner validates each original result and both independent route proofs
before admitting a successor. The 20-second awake gaps and recovery observation
intervals are diagnostic delays, not measured wake latency. No driver, source,
charger, warning level or ordinary sleep-policy change accompanies this batch.
The abandoned SSH-stall investigation is not resumed; original collection
errors are preserved without a transport root-cause claim.

Original log: `.local/neo173-sleep-batch.log`. Batch directory:
`.local/diagnostics/20261009T055911.699506Z/`. Each original cycle result is
stored in `cycle-N/result.json` there. Offline checks call the existing
`report:sleep-evidence` task for each completed result and revalidate full
result/lineage, keypad/control restoration, PM/SDIO continuity and all-CPU
callback participation. Derived summary:
`.local/neo173-batch-evidence-summary.json`. Original results stay unchanged.

## Four-cycle evidence

The saved `batch.json` records four requested and four completed cycles, with
`event=complete` and `passed=true`. SHA-256:
`3da683685da8e8b5779642c32548d10ca0e96ed2619da6853806bf808b198da9`.

| Cycle | Run ID | Alarm-to-return seconds | BOOTTIME–MONOTONIC gap seconds | PM afterward | All four s2idle counts afterward |
| --- | --- | ---: | ---: | --- | ---: |
| 1 | `02268771e1944328b65fdc0b5ca6c736` | 31.960 | 28.733 | 9/0 | 2 |
| 2 | `d14b709f80824398b2c0366c5e5e11a5` | 31.958 | 28.708 | 10/0 | 3 |
| 3 | `0a569157f1134c40ab80514a7eebc619` | 32.596 | 29.420 | 11/0 | 4 |
| 4 | `410eabf6615f4d18ab4da1a5427056be` | 31.844 | 28.540 | 12/0 | 5 |

Every original result verifies RTC wake, process memory, the original healthy
keypad handle and unchanged keypad USB device number/input identity. One-second
level-5 warning playback and mixer restoration pass, with complete restored
keypad, USB and Wi-Fi traces. POWER is handed back after verified logical
release and descriptor closure. No policy, drop-in, PM control, RTC or console
owner is retained. All failure counters remain zero and adjacent full PM
snapshots match. SDIO runtime usage remains 2 with unchanged
active/on/forbidden policy; brightness/backlight power returns to 1/0.

Each trace contains the s2idle boundary, one timekeeping-freeze pair and the
expected late/noirq and RSB suspend/resume phases. Clock sampling uncertainty
is 18.83, 24.40, 25.77 and 22.67 microseconds respectively. MONOTONIC excludes
the frozen interval; its short boundary spans are not physical sleep residency
or wake latency. All-CPU callback participation and timekeeping suspension do
not establish CPU/DRAM power-off or reduced battery consumption.

Post-return schema-2 battery samples pass current-boot and freshness checks.
BOOTTIME ages are 5.957, 1.554, 7.930 and 7.297 seconds. Valid readings across
these repeated sleeps exercise the sleep-inclusive timestamp path; gauge
calibration and physical battery protection during sleep remain separate.

| Cycle | Original `result.json` SHA-256 |
| --- | --- |
| 1 | `7e5585843471c6b7ebb7f3ea9a9a0b89d02f2cce8056fa9003f11f5ad5a2ddcf` |
| 2 | `3c4dc33aaefc139fc31fc7453abfb04b83ebd3ff58c8c4c61bb059cef22545f8` |
| 3 | `21645a204f5bcc7a5df6f1ebe87a6948b3b05b227e51dc9e47dc9aa5bdabc3a2` |
| 4 | `cc8dfa112f4d4d0e0ff3d2b2005b95091576986339327b81844bddb6acd52a7b` |

## Offline assessment and preserved collection errors

The existing task runs for each cycle, with the result path changed accordingly:

```sh
task report:sleep-evidence \
  RESULT=.local/diagnostics/20261009T055911.699506Z/cycle-1/result.json
```

All four RTC/trace/paired-clock/WFI assessments pass. Each retains
`overall_requalified=false`: it does not overwrite the original recovery
result. Assessment directories under `.local/diagnostics/`, in order, are
`20261009T060111.075242Z`, `20261009T060254.066855Z`,
`20261009T060450.888215Z` and `20261009T060640.292050Z`.
Private logs: `.local/neo173-cycle{1,2,3,4}-evidence.log`.

The original `collection-errors.txt` files retain these failed collection
attempts. All original results were subsequently retrieved, and each cycle's
independent USB and Wi-Fi proofs passed before its successor was admitted.

| Cycle | Recorded collection errors |
| --- | --- |
| 1 | One forwarded-channel failure, one channel-opening timeout, one `No existing session` |
| 2 | One `No existing session`, one forwarded-channel failure, one channel-opening timeout |
| 3 | Two channel-opening timeouts |
| 4 | Three forwarded-channel failures and one channel-opening timeout |

The task log also retains the corresponding `No route to host` and SSH banner
exception messages. These are not additional PM attempts; no sleep submission
was retried. We did not investigate their timing or root cause, enable socket
capture, change transport deadlines or revive the abandoned SSH-stall work.
Functional recovery passed, but this report does not claim uninterrupted
network availability or a measured network-ready latency.

## Final state and next gates

The owner confirms all four long warnings and normal untouched dim-console
returns. A fresh read-only `device:pm-inspect ROUTE=usb` capture at
`.local/diagnostics/20261009T060659.207304Z` passes full health and source-bound
continuation admission of all seven debug results and five actual sleeps.
It retains the original boot/image, PM12/0, all four s2idle counts at 5 and the
normal dim backlight. Inspection SHA-256:
`e255aa2ba6c8bb23c70d4d5038af67f1c0c445729f511769c09c066dd5cb77df`.
Saved validation: `.local/neo173-final-receipt-check.json`.

The unused continuation is
`.local/diagnostics/20261009T055911.699506Z/cycle-4/qualification-next.json`,
SHA-256 `8d8eb31261768f49dd82fea0fd06d24e72a595656c12dda072a9dea664c86aea`.
No further sleep or screen test is running.

Next, verify four awake USB reconnects after repeated sleep on this candidate,
with separate recorder preparation and physical instructions. Battery-only and
cable-transition profiles then require their own current-state admission and
attended tests. The bounded passes here do not demonstrate that NEO-108's
deferred-restart race occurred on this board. Broader reliability, efficiency,
product power-key/idle policy and deeper retention remain open.
