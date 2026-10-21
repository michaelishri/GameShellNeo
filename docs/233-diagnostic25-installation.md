# Diagnostic.25 card installation and awake prerequisites

9 October 2026; evidence timestamps are UTC. NEO-171, under NEO-108.
Diagnostic.25 is installed after complete 4 GiB card readback and owner-confirmed
boot. Awake prerequisites pass: exact image identity, both SSH routes, battery,
all-CPU WFI/timer inventory, journal continuity, power-key ownership and RTC alarm
restoration. This establishes neither sleep qualification nor an energy saving.

## Warning and shutdown

[Report 232](232-musb-restart-image-integration.md) records the reviewed MUSB
restart correction, verified image and successful transfer on owner-confirmed
regular Wi-Fi. The owner subsequently confirmed readiness for the card swap.

Matching diagnostic.24 tools in `work/cpi-wfi-integration` verified USB access to
kernel `6.18.54-gameshellneo23`, boot
`a73c7c3c-5ed4-473d-85c4-8d71f4a89bc2`, with configured high-speed USB and no failed
services (capture `20261009T052251.655243Z`). The software battery sample reported
99% and Charging; this does not establish calibrated battery capacity.

`task device:audio-test ROUTE=usb` completed three one-second level-5 speaker
warnings and restored the same boot's mixer controls and amplifier idle state.
Audio run `249282aadb954043bb8982b56e711c3b` is retained in capture
`20261009T052309.049417Z`. Audibility was not separately confirmed for shutdown.

One `task device:exec ROUTE=usb -- sudo -n systemctl poweroff` returned success.
It was not retried. The owner confirmed moving the DEV card into the Mac after
the instruction to wait ten seconds after darkness and unplug USB.
Private logs in that worktree are
`.local/diagnostic25-{before-shutdown,shutdown-warning,shutdown}.log`.

## Fresh target identification and verified write

From `work/musb-restart-integration`, `task mac:status` found one external physical
64 GB card, `disk16`, with the existing GameShell FAT16 boot/Linux partitions.
`task mac:inspect DISK=disk16` recorded its 64,013,467,648-byte capacity, 512-byte
sector size, USB reader path and existing boot-volume UUID
`DBBBD048-2FA1-3768-816E-462B39615A0E`. The owner had freshly confirmed that the
DEV card was in the reader; disk numbering was not inferred from the previous
flash. `task mac:preflight` passed the target identity and both compressed and
complete decompressed source checksums without writing the card.

`task mac:flash DISK=disk16` verified the mount guard's veto, unmounted the card,
wrote the image, read every image byte back and safely ejected the card. The
owner was instructed to leave the reader's USB and power connections untouched
through completion. No disconnect or write/readback error was reported.

| Evidence | Result |
| --- | --- |
| Image | `GameShellNeo-0.1.0-diagnostic.25-cpi31-c88d158d446b.img` |
| Written/readback bytes | 4,294,967,296 |
| Readback SHA-256 | `c88d158d446b6ed14617b815ec17bfd2b3e90fee858ddd30e008ed74640aeb77` |
| Readback / mount guard / ejection | Passed / verified / complete |
| Flash-result SHA-256 | `903450e19d9449b34a2eb889be8ef6190bab63a7e8a00867d4c6d2bf7de9ceba` |
| Hardware boot tested by flash helper | False |

Original evidence is `.local/diagnostics/20261009T052623.051576Z/` in this
worktree, including `flash.log` and `flash-result.json`. Task logs are
`.local/diagnostic25-mac-status.log` and
`.local/diagnostic25-card-{inspect,preflight,flash}.log`. The original diagnostic.24
recovery image, compressed archive, metadata and matching tools remain retained
in `work/cpi-wfi-integration` as documented in report 232.

## Boot and awake qualification

The owner reinserted the card, reconnected USB and confirmed the login screen.
The new boot is `2170b296-d964-4d16-bdb1-c135b0e7b812`. Installed image
`0.1.0-diagnostic.25`, kernel `6.18.54-gameshellneo24` and the entire installed
manifest match the verified artifact. Manifest SHA-256 is
`d45bcea1e79e9d2518c9e8632642183eb06387a0868cce75e78838f50fd0faf9`;
all 344 project-input hashes match this worktree. The image's original
`hardware_qualified=false` is retained rather than rewritten after a partial
qualification slice.

Run the following saved tasks from `work/musb-restart-integration`. The table
also identifies the original private evidence under `.local/diagnostics/`.

| Saved task/check | Capture | Result |
| --- | --- | --- |
| `device:status ROUTE=usb` | `20261009T053219.846303Z` | Expected kernel; configured high-speed USB; no failed services |
| `device:status ROUTE=wifi` | `20261009T053247.949433Z` | Independent Wi-Fi SSH works |
| `device:pm-inspect`, offline full health and manifest validation | `20261009T053247.560173Z` | Board, CPU/timer, battery, image and existing health gates pass |
| `device:battery-check ROUTE=usb` | `20261009T053358.673209Z` | All 12 simulated tests against the installed guard pass |
| `device:check ROUTE=usb ACTIVE_COUNTRY=AU` | `20261009T053403.599784Z` | All seven integration groups pass |
| `device:journal-rotation` | `20261009T053410.402039Z` | Policy and continuity pass; no journal restart, move or repair |
| `device:power-key-smoke` | `20261009T053415.283421Z` | Exclusive ownership passes and is handed back |
| `device:rtc-smoke` | `20261009T053419.007606Z` | Awake alarm delivery and restoration pass in 10.109 seconds |
| `device:awake-clock-check ROUTE=usb` | `20261009T053432.817434Z` | 21 bounded observations pass; PM remains 0/0 |
| Final `device:pm-inspect`, offline full health and continuity validation | `20261009T053434.941115Z` | Same boot/image/counters/backlight; full health passes and initial kernel journal remains |
| `device:power-policy-inspect` | `20261009T053438.373120Z` | No retained owner/drop-in; ordinary diagnostic poweroff policy |

Private task logs are `.local/diagnostic25-{boot-usb,boot-wifi,pm-initial,
battery-check,integration,journal,power-key,rtc,clock,pm-final,policy}.log`.
The initial/final PM capture directories retain `awake-validation.json` with
the snapshot and validator hashes; the initial directory also retains
`image-validation.json`. The offline health check invokes the saved
`test-pm-stages.py` `validate(snapshot, lock)` function on the original
`inspection.json`, using `build/sources.lock.json`. Manifest validation compares
the snapshot's `image` object with `.local/artifacts/image-manifest.json` and
rehashes all its recorded project inputs. Final continuity checks compare boot,
image, PM counters and backlight with the initial snapshot and require the final
kernel journal to retain the initial journal prefix. These are evaluations of
saved evidence, not additional device transitions.

All four CPUs are online and expose one enabled `WFI` / `ARM WFI` state through
`cpi_wfi` with the `menu` governor. The architecture clocksource, four architecture
clock-event devices, `sun4i_tick` broadcast and live 24 MHz DT timer contract pass
the existing strict validator. Ordinary WFI usage is nonzero on every core;
all four `s2idle/usage` and `s2idle/time` counters remain zero. This shows ordinary
idle-driver use, not physical low-power residency or energy savings.

Initial and final battery samples use schema 2, `CLOCK_BOOTTIME` and the current
boot ID. Sample ages are 10.347 and 6.074 seconds; both report 100% and Charging.
The guard tests simulate invalid/low readings, delayed sampling and sleep gaps
with mocked shutdown requests. No real shutdown or charging-control change was
performed during this slice. The separate ADC/battery calibration uncertainty
remains unresolved.

The clock observer's maximum bracket is 53,620 ns. PM success/fail remains
**0/0**, every PM failure counter stays zero, kernel taint is zero and no failed
units are present. The screen remains at brightness 1 with backlight power 0.
The RTC smoke test is run `f657b99a0d2a40a08fa8c7ca7997d8cc`; the previously
disabled alarm was restored. Power-key ownership is released, without a retained
diagnostic owner or drop-in. The effective short power-key action is still the
diagnostic `poweroff` policy, not the future product sleep/menu policy.

Wi-Fi configuration remains NZ with the previously accepted AU home access-point
announcement. USB-controller and both supply system-wakeup controls remain
disabled, and normal product sleep remains masked. No screen blanking, suspend,
reboot, cable operation or live SSH-stall investigation occurred in these awake
checks.

## Remaining qualification

NEO-171's installation and awake prerequisites are complete. NEO-108 still needs
attended driver and sleep/USB qualification on this image. Fresh readiness has
been requested for freezer followed by one driver debug cycle. Then proceed to
late/noirq checks and the source-bound seven-debug receipt, awake RTC rehearsal
and separately attended actual sleep. Review every result, stop on failure and
preserve the original evidence; keep the long audible warnings before dark
intervals. Old qualification receipts do not authorize new-image sleep tests.
Repeated connected sleep and USB reconnect checks remain ahead, with battery and
cable profiles as appropriate. Awake passes do not prove that the deferred
restart race has occurred on this board, or establish reliable suspend/resume,
improved latency, reduced current or the week-long standby target.
