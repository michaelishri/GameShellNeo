# Diagnostic.24 installation and awake prerequisites

8 October 2026; evidence timestamps are UTC. NEO-157.
Diagnostic.24 is installed after verified full 4 GiB readback and owner-confirmed
boot. Awake prerequisites pass: both SSH routes, exact image identity, schema-2
battery readings, the all-CPU WFI/timer inventory, journal continuity, power-key
ownership and RTC alarm restoration. No PM or energy qualification is established
by these awake checks.

## Warning and shutdown

[Report 217](217-wfi-s2idle-image-integration.md) records the WFI driver,
BOOTTIME battery contract, awake measurement guards and verified artifact.
NEO-156 transferred the archive after the owner confirmed home regular Wi-Fi.
The owner then confirmed readiness for the card swap.

The matching diagnostic.23 tools in `work/power-insertion-wake` reached kernel
`6.18.54-gameshellneo22` over USB (private status capture
`20261008T102334.226852Z`). `task device:audio-test ROUTE=usb` passed three
one-second level-5 warning cues and restored the same boot's mixer and amplifier
state. Audio run `db952e6ccb0e421ba48e3ecfaf5eb710` is retained in capture
`20261008T102347.045368Z`. Audibility was not separately confirmed for shutdown.

`task device:exec ROUTE=usb -- sudo -n systemctl poweroff` returned success.
The owner confirmed moving the Samsung DEV card into the Mac reader after
shutdown. Private logs in that worktree are `.local/neo157-before-shutdown.log`,
`.local/neo157-shutdown-warning.log` and `.local/neo157-shutdown.log`.

## Verified card write

From `work/cpi-wfi-integration`, `task mac:status` found one external physical
64 GB card with the existing GameShell boot/Linux partitions.
`task mac:inspect DISK=disk16` freshly recorded its 64,013,467,648-byte capacity,
USB reader path and existing boot-volume UUID. `task mac:preflight` passed the
target identity and both compressed/decompressed source checksums.

`task mac:flash DISK=disk16` verified the mount guard's veto, wrote the image,
read every image byte back and safely ejected the card.

| Evidence | Result |
| --- | --- |
| Image | `GameShellNeo-0.1.0-diagnostic.24-cpi31-11fb47777b62.img` |
| Written/readback bytes | 4,294,967,296 |
| Readback SHA-256 | `11fb47777b6273667b4702845ffc3f2b4f223d1b63acfea82b86017cee4012c9` |
| Readback / mount guard / ejection | Passed / verified / complete |
| Flash result SHA-256 | `a95a34da1886046d8cdab8dbfc6fc2e31f68d1bb31c7981cb8616a2478d6b4e9` |
| Hardware boot tested by flash helper | False |

Original evidence is `.local/diagnostics/20261008T102614.682089Z/` in this
worktree. Task logs are `.local/neo157-{mac-status,inspect,preflight,flash}.log`.
The owner reinserted the card and confirmed the GameShell was back online.
USB access identified new boot `44b698ad-7fef-46d4-9e0f-71153f6f81e9`.

## Awake qualification

The installed manifest exactly matches the verified build: image
`0.1.0-diagnostic.24`, kernel `6.18.54-gameshellneo23`, manifest SHA-256
`bede8afee1bd321002b7563f8f2dd1ca948d1c33647ead79977273a646da9bd2`.
All 335 recorded project input hashes match the local source files. The original
manifest's `hardware_qualified=false` is preserved; the evidence below does not
claim complete sleep qualification.

| Saved task/check | Private capture under `.local/diagnostics/` | Result |
| --- | --- | --- |
| `device:status ROUTE=usb` | `20261008T103349.990802Z` | Expected kernel; configured high-speed USB; services healthy |
| `device:status ROUTE=wifi` | `20261008T103413.132805Z` | Independent Wi-Fi SSH works |
| `device:pm-inspect`, offline full health and image validation | `20261008T103411.253214Z` | All CPU/timer, battery, identity and existing health gates pass |
| `device:battery-check ROUTE=usb` | `20261008T103435.489075Z` | All 12 tests pass against the exact installed guard, using simulated readings |
| `device:check ROUTE=usb ACTIVE_COUNTRY=AU` | `20261008T103456.919595Z` | All seven integration groups pass |
| `device:journal-rotation` | `20261008T103517.825701Z` | Policy and continuity pass; no journal restart, move or repair |
| `device:power-key-smoke` | `20261008T103535.684489Z` | Exclusive ownership passes and is handed back |
| `device:rtc-smoke` | `20261008T103557.525964Z` | Awake alarm delivery and restoration pass, 10.286 seconds |
| `device:awake-clock-check ROUTE=usb` | `20261008T103629.587963Z` | 21 bounded observations pass; PM remains 0/0 |
| Final `device:pm-inspect` and offline full health validation | `20261008T103657.298388Z` | Same boot, image, PM counters and backlight state; all gates pass |
| `device:power-policy-inspect` | `20261008T103700.696200Z` | No retained diagnostic owner or drop-in; ordinary diagnostic poweroff policy |

Private task logs use `.local/neo157-{boot-usb,boot-wifi,pm-inspect,battery-check,
integration,journal,power-key,rtc,clock,pm-final,policy}.log` in this worktree.
The PM inspection directories also retain `awake-validation.json`; the first
retains `image-validation.json`. These apply the existing `test-pm-stages.py`
validator to the original saved inspection and compare the installed manifest
with `.local/artifacts/image-manifest.json`.

All four CPUs are online. The driver is `cpi_wfi`, the governor is `menu`, and
each CPU exposes exactly one enabled `WFI` / `ARM WFI` state. Ordinary idle
usage counters are nonzero on every CPU. The architecture clocksource, four
architecture clock-event devices, `sun4i_tick` broadcast and the live 24 MHz DT
timer configuration match the candidate's strict inventory. These counters show
driver use during ordinary idle; they do not establish physical low-power
residency or energy savings. The earlier kernel also had an architectural idle
fallback, so WFI's presence alone is not evidence of a new energy benefit.

The first validated battery sample uses schema 2 and `CLOCK_BOOTTIME`, matches
the current boot ID and is 1.505 seconds old. It reports 100%, Charging and about
4.157 V. Final freshness is 7.084 seconds. These software readings do not resolve
the separate battery/ADC calibration uncertainty. The installed guard tests
exercise sleep gaps, delayed/interrupted sampling, clock-bracketing and
low-reading reset behavior with mocked shutdown requests. They do not issue a
real shutdown or alter charging controls. The live health validator separately
checks the sample's clock type, current boot identity and age.

The clock observer passes with a maximum bracket of 52,917 ns. This validates
bounded awake observations on the new kernel, not exclusive sleep ownership or
reliable detection below the observation resolution. Across this slice, all four
s2idle callback counters stay zero, PM success/fail stays **0/0**, every PM failure
counter stays zero, kernel taint is zero and no failed units are present. Backlight
brightness remains 1 with power 0. No screen blanking, suspend, reboot or cable
change was requested during the awake checks.

Wi-Fi configuration remains NZ with the previously accepted AU home access-point
announcement. MUSB and both supply wake controls remain disabled, normal sleep
remains masked, and the product's quick-press sleep/wake policy is not enabled.

## Remaining qualification

Use this worktree's diagnostic.24 tools. Obtain fresh readiness for freezer and
driver debug checks, then staged late/noirq checks. Use their matching seven-debug
receipt for an awake RTC rehearsal before the first attended actual sleep.
Require all four s2idle callback counts to advance and independently establish
timekeeping freeze, alongside existing display/keypad/network recovery gates.
NEO-96/100/101 remain open for sleep evidence. Broader connected, battery-only
and cable-transition qualification and later energy comparisons remain pending;
an installed driver alone does not establish lower current or the standby target.
