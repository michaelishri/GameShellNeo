# Diagnostic.19 installation and awake checks

4 October 2026; evidence timestamps are UTC. NEO-112.

Diagnostic.19 is installed on the owner's CPI v3.1. Full card readback passed,
the owner confirmed the normal login screen, and USB/Wi-Fi access and the awake
startup checks passed. **No driver debug or actual sleep test has run on this
image.** The USB sleep-session fix remains pending attended qualification.

[Report 154](154-usb-sleep-session-retirement.md) records the implementation,
source regressions, full build, offline image verification, Mac staging and
diagnostic.18 recovery checkpoint. The old removal failure remains unchanged.

## Card handoff and boot

The owner had five minutes available for the card swap. Remote shutdown of
diagnostic.18 succeeded before the owner moved the confirmed Samsung DEV card
into the Mac. This deliberately avoided relying on the old failed test's
suppressed power-button action.

Fresh `mac:status` and `mac:inspect DISK=disk16` identified the external physical
64,013,467,648-byte card with its existing GameShell boot/Linux partitions.
`task mac:flash DISK=disk16` then verified the staged source, enforced the mount
guard, wrote 4,294,967,296 bytes, verified their full readback, and safely ejected
the card. No other disk was written.

| Item | Evidence |
| --- | --- |
| Image | `GameShellNeo-0.1.0-diagnostic.19-cpi31-9e82bbfa4319.img` |
| Image/full readback SHA-256 | `9e82bbfa4319398add0a214bf05b18f01537b971eedd43f0e349658c74bd4ee6` |
| Flash capture | `.local/diagnostics/20261004T103653.270463Z/` |
| Flash-result SHA-256 | `fe42625b8c5914c56d023b014508eddd8b2bbfb00eb8d8c70cbdcfc2bd8e62e8` |
| Running kernel | `6.18.54-gameshellneo19` |
| New boot ID | `0751ae33-2930-4d73-a9c4-80b1f9660258` |

The owner reinserted the card, reconnected USB and confirmed the login screen,
then went to bed. Subsequent operations were awake checks only. No display
sequence, reboot, cable action, key press or suspend was requested after that
confirmation.

## Saved checks and results

```sh
task device:status ROUTE=usb
task device:status ROUTE=wifi
task device:check ROUTE=usb ACTIVE_COUNTRY=AU
task device:journal-rotation
task device:power-key-smoke
task device:rtc-smoke
task device:pm-inspect
task device:power-policy-inspect
```

| Check | Private capture beneath `.local/diagnostics/` | Result |
| --- | --- | --- |
| Initial USB status | `20261004T104008.606402Z` | Correct kernel, configured high-speed USB, services active, no failed units or kernel taint |
| Initial Wi-Fi status | `20261004T104008.405665Z` | Independent Wi-Fi SSH works with the same kernel |
| Integration | `20261004T104131.525813Z` | All six groups pass: identity, services, database/policy, journal ACL, disposable BPF loopback enforcement and expected country state |
| Journal rotation | `20261004T104142.688744Z` | Journald instance and retained kernel/displaced-journal evidence unchanged |
| Awake power ownership | `20261004T104147.614122Z` | Inhibitor and exclusive input ownership pass; no key events; checked release and descriptor handback |
| Awake RTC | `20261004T104151.631433Z` | One alarm event, flags `0xa0`, 10.251 seconds elapsed; owned alarm restored |
| Read-only PM inspection | `20261004T104204.975203Z` | PM success/fail 0/0, all failure counters zero; Wi-Fi SDIO usage 2; ordinary sleep masks retained |
| Effective power policy | `20261004T104254.195494Z` | No diagnostic owner/drop-in; normal diagnostic short-press poweroff and idle-ignore policy restored |
| Final USB/Wi-Fi status | `20261004T104425.535798Z` / `20261004T104425.570273Z` | Both routes still work after the awake checks, with the expected kernel and no failed units or kernel taint |

The initial integration invocation omitted `ACTIVE_COUNTRY=AU` and rejected
country state only; its unchanged failed record is retained at
`20261004T104041.668548Z`. Provisioning remains NZ, while the access point announces
AU, which the owner previously accepted. Repeating the saved check with that
established expectation passed. No radio setting or country database was changed;
firmware-country qualification remains false as before.

The PM snapshot SHA-256 is
`67907872b40144353a0cfa6fb8f28db929ceaabb6a6ccf28562bbe1f9fe98e94`;
the effective-policy snapshot SHA-256 is
`e31a16f4127bf52782972c961e28ab5664a2cf6b527fe83430c2475809c6f665`.
The PM snapshot retains USB system wake disabled, `pm_test=none`, the s2idle
selection, all ordinary sleep targets masked and the expected SDIO runtime hold.
Its kernel journal has none of the checked warning/BUG/oops/underflow/firmware-halt
markers. This is an awake snapshot, not a completed PM qualification sequence.

Battery monitoring reports valid telemetry and 100%. Its 4.2559 V charging
reading repeats the existing uncalibrated charging-voltage observation tracked
under NEO-10; it does not establish physical cell voltage or resolve that issue.
Charging settings were not changed. Startup reports local userspace ready at
17.430 monotonic seconds and systemd completion at 22.568 seconds; neither is a
physical power-button-to-interaction measurement or the under-five-second goal.

## Next attended work

Leave the device on USB with the Mac awake. The next session needs a fresh
health/ownership review, the staged freezer/devices/late-noirq checks with display
observations, an unchanged-cable RTC comparison, then a fresh removal baseline,
awake rehearsal and single removal-during-sleep test. Collect the original result
over Wi-Fi before any requested reconnect. Attachment needs separate evidence.

The functional sleep fix, callback concurrency, energy savings, deep retention,
production button gestures and automatic idle sleep remain unqualified by this
installation. The successful boot and awake checks do not close NEO-112 or
retroactively pass diagnostic.18's failed removal attempt.
