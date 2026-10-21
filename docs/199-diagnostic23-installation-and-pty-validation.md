# Diagnostic.23 installation and terminal validation

7 October 2026; timestamps are UTC. NEO-137. Diagnostic.23 is installed and the
owner confirms its normal login console. Full card readback, both SSH routes,
awake startup checks and modern terminal compatibility pass. Removing legacy
PTY preallocation eliminates 512 user-manager device-unit records; measured
unit loading falls from 3.440 seconds to 0.591–0.610 seconds. Observed PM
qualification of this new kernel remains separate work.

## Transfer and shutdown

[Report 198](198-legacy-pty-startup-candidate.md) records the configuration
change, baseline terminal inventory, build checks and artifact hashes.
After the owner confirmed regular Wi-Fi, `task mac:stage` completed with both
compressed and expanded image checksums verified on the Mac. Private transfer
log: `.local/neo137-stage.log`.

The owner then confirmed readiness for the DEV-card swap. The saved USB status
task reached diagnostic.22, kernel `6.18.54-gameshellneo21`, before shutdown.
Private status capture: `.local/diagnostics/20261007T093129.061170Z/`.

`task device:audio-test ROUTE=usb` passed three one-second warning cues and
restored the same boot's mixer/amplifier state. Run
`294dbc17ffd2487abba7ad200ff368ab` is saved in
`.local/diagnostics/20261007T093146.660595Z/`; result SHA-256:
`5cd678c4fec734f8a17c936dc3519613a9e1db1234360c04d32389f0bac1a9c0`.
Both audio snapshots identify boot `7884d229-2309-47df-9af0-b6fe500ad9ac`.
Four collection attempts returned `RuntimeError` before the original completed
result was retrieved; no second warning test was submitted. Audibility has not
been separately confirmed for this shutdown sequence.

`task device:exec ROUTE=usb -- sudo -n systemctl poweroff` returned success.
Private logs are `.local/neo137-before-shutdown.log`,
`.local/neo137-shutdown-warning.log` and `.local/neo137-shutdown.log`.
The owner confirmed moving the Samsung DEV card to the Mac reader after
shutdown.

## Verified card write

Fresh `task mac:status` found one external physical card with the existing
GameShell boot/Linux partitions. `task mac:inspect DISK=disk16` recorded its
64,013,467,648-byte capacity, physical USB reader path and existing boot-volume
UUID. `task mac:preflight` verified this identity and the source checksums.
`task mac:flash DISK=disk16` then verified the mount guard's veto, wrote the
image, read back every image byte and safely ejected the card.

| Evidence | Result |
| --- | --- |
| Image | `GameShellNeo-0.1.0-diagnostic.23-cpi31-bf64ca854137.img` |
| Written/readback bytes | 4,294,967,296 |
| Readback SHA-256 | `bf64ca85413711b991cfaafbe7d8c7dabcf4355fe1bb8590085850f68b13d726` |
| Readback / mount guard / ejection | Passed / verified / complete |
| Flash result SHA-256 | `56e2319903bddfa7f71434c7445b5ad1658c02dd37e1fb86099c47f982b0b607` |
| Hardware boot tested by flash helper | False |

Original evidence: `.local/diagnostics/20261007T093445.848672Z/`.
Private task logs are `.local/neo137-{mac-status,inspect,preflight,flash}.log`.
The owner reinstalled the card, reconnected USB and confirmed the normal login
screen. New boot: `7cc788ef-2070-4ab9-887a-1af70c074713`.

## Awake startup qualification

The installed manifest exactly matches the verified build, including all 298
recorded project inputs: `0.1.0-diagnostic.23`, kernel
`6.18.54-gameshellneo22`, manifest SHA-256
`f82d8dce7b40d0d31c057b0d723c5d97cea2488c6458a1e56c4a3d381506b3d3`.
Its hardware-qualified flag still describes the original offline build; it is
not rewritten to imply complete PM qualification.

| Check | Private capture beneath `.local/diagnostics/` | Result |
| --- | --- | --- |
| USB startup status | `20261007T093857.797821Z` | Expected kernel and configured high-speed gadget |
| Wi-Fi startup status | `20261007T093934.228992Z` | Independent Wi-Fi SSH works |
| ADC/gauge inventory | `20261007T094008.756810Z` | Exact diagnostic.23 profile, masked ADC and volatile B8 |
| Integration | `20261007T094021.298306Z` | All seven groups pass |
| Journal rotation | `20261007T094037.637398Z` | Policy and continuity pass without restart/repair |
| Awake POWER ownership | `20261007T094054.439750Z` | Passed and handed back |
| Awake RTC | `20261007T094112.274305Z` | Alarm delivery and restoration pass, 10.891 seconds |
| PM inspection | `20261007T094143.108922Z` | Expected image and health validator pass |
| POWER policy | `20261007T094143.146892Z` | No retained owner or diagnostic drop-in |

The configured country remains NZ; integration accepts the previously approved
AU announcement from the home access point. No Wi-Fi or regulatory setting was
changed. The charge inventory reports 100%, about 4.157 V, no unused voltage
bits and B8 `c0`. This does not calibrate the battery or resolve physical ADC
accuracy; no charging controls were changed.

PM success/fail stays 0/0, all failure counters remain zero, and each terminal
inspection preserves the same boot and full PM/display state. The PM inspection
has zero kernel taint and no failed units. Brightness stays 1 with backlight power
0. MUSB and both supply wake controls remain disabled, normal sleep is masked,
and the ordinary diagnostic power-key action remains poweroff. Both routes also
pass all subsequent timing probes. No sleep, reboot or display blanking ran
during these awake checks.

## Terminal population and manager startup

Four `task device:user-startup LEGACY=disabled` captures have distinct manager
startup timestamps. Every capture confirms zero legacy slave nodes and zero
legacy device units. The configured console, serial-console and Unix98 support
remain enabled. Bidirectional data and window-size propagation pass on an owned
Unix98 PTY, and an actual SSH terminal request succeeds as `/dev/pts/N` each time.
Both `passed` and `ssh_pty_verified` are true in every completed result.

| Measurement | Diagnostic.22 baseline | Diagnostic.23 |
| --- | ---: | ---: |
| Legacy sysfs slave devices | 256 | 0 |
| Legacy device-unit records | 512 | 0 |
| All user-manager device-unit records | 557 | 45 |
| All user-manager unit records | 588 | 76 |
| Unit-loading time | 3.440275 s | 0.590910–0.610492 s |
| Total recorded manager startup | 3.971636 s | 1.034780–1.100687 s |

The unit count drops by exactly the 512 removed legacy records. Unit loading is
about 82% shorter in these observations; total user-manager startup is about
72–74% shorter. The four generator intervals remain 0.111–0.129 seconds, near
the baseline's 0.121 seconds. These are manager startup phases, not whole-device
boot or resume time. The stable device-count change and repeated timings support
the intended optimization without disabling PAM, enabling linger or filtering
systemd's device events. This is a before/after comparison on one board across
two image boots, not a randomized multi-boot benchmark.

| Capture | Unit loading | Manager startup |
| --- | ---: | ---: |
| `20261007T093911.651991Z` | 0.606322 s | 1.100687 s |
| `20261007T094249.316370Z` | 0.590910 s | 1.091080 s |
| `20261007T094351.511469Z` | 0.610492 s | 1.034780 s |
| `20261007T094448.635675Z` | 0.606086 s | 1.064078 s |

Each contains `user-startup.json`; respective SHA-256 values are
`df80f79b8ffe41ebf158ecd407848a0d32a8a558b48fd6cd8f5b37347e6e125f`,
`3f018303ca1449254226fcdccbfa1be0f64243aca248c3a908c7a106013c3881`,
`11184132912964d1f2c4b3a64177aee0b5851263420ad591d3c6e0a008325d7b`,
and `c474d82400684e24a73bfbbbaa4908aa4a9d138f03884623ee91d37ed02d0d29`.
The baseline and its hash are preserved in report 198.

## Repeated fresh SSH sessions

Three isolated `task device:ssh-timing CYCLES=3` batches each pass one initial USB
discovery session and three fresh USB/Wi-Fi pairs: 18 measured route samples plus
three discovery sessions. All preserve this boot and PM0/0, and the validated
host timing captures contain no recorded failures. The manager is allowed to
stop through normal session teardown between batches; services are not restarted.
Other hardware diagnostics do not run concurrently with these batches.

| Capture | First USB command channel | Subsequent USB channels | Complete Wi-Fi sessions |
| --- | ---: | ---: | ---: |
| `20261007T094224.603590Z` | 1.959333 s | 0.201–0.276 s | 1.224–1.386 s |
| `20261007T094326.367915Z` | 1.926944 s | 0.194–0.250 s | 1.332–1.380 s |
| `20261007T094422.331865Z` | 1.908566 s | 0.223–0.244 s | 1.367–1.429 s |

The earlier three first-channel values were 4.677–4.792 seconds (report 197).
The new values are about 58–60% shorter, roughly 2.8 seconds saved per measured
cold user-manager session. Subsequent USB channel times remain near the earlier
0.205–0.258 seconds. The improvement is concentrated in starting the first
session, consistent with removing unnecessary manager enumeration. Complete
Wi-Fi sessions also depend on network conditions and are not a controlled radio
performance comparison. Inclusive timing spans must not be added together.

The respective `host-timing.jsonl` hashes are
`79af240d0992a3e8bcb8505a8c68a47393dc0ef4946f988f04603daf04911869`,
`95d6941af551083db27094d5ff1d6305dc07fb008f11036458795aad4e0d8a82`,
and `f92069ab58948808b3c7cf3b7ed0adeab2462e2f38dbc1f07d4501f150198974`.
Each capture also retains `awake-ssh.json` and the validated timing summary.

## Resource observations and reproducibility

Ordinary-user `systemctl show user@1000.service -p MainPID -p MemoryCurrent
-p MemoryPeak -p CPUUsageNSec` records these three different manager instances
after the route/terminal checks:

| PID | Current cgroup bytes | Peak cgroup bytes | CPU nanoseconds |
| --- | ---: | ---: | ---: |
| 1003 | 3,022,848 | 6,180,864 | 1,973,474,000 |
| 1130 | 2,953,216 | 5,824,512 | 1,975,164,000 |
| 1258 | 3,174,400 | 6,266,880 | 1,968,154,000 |

Report 198's single baseline instance recorded 4,317,184 current bytes,
6,860,800 peak bytes and 4,121,870,000 CPU nanoseconds. These new readings are
lower, but the instances have different diagnostic histories and lifetime
accounting. They do not establish a precise RAM/CPU saving, whole-device idle
power or battery-life improvement. The task logs and these resource captures
are `.local/neo137-user-startup-{1,2,3,4}.log`,
`.local/neo137-ssh-timing-{1,2,3}.log` and
`.local/neo137-user-resources-{1,2,3}.txt`.

The existing repeatable workflow was used throughout:

```sh
task device:status ROUTE=usb
task device:status ROUTE=wifi
task device:exec ROUTE=usb -- cat /etc/gameshellneo/image.json
task device:charge-inspect
task device:check ROUTE=usb ACTIVE_COUNTRY=AU
task device:journal-rotation
task device:power-key-smoke
task device:rtc-smoke
task device:pm-inspect
task device:power-policy-inspect
task device:user-startup LEGACY=disabled
# Allow ordinary session teardown before each isolated timing batch.
task device:ssh-timing CYCLES=3
task device:user-startup LEGACY=disabled
task device:exec ROUTE=usb -- systemctl show user@1000.service \
  -p MainPID -p MemoryCurrent -p MemoryPeak -p CPUUsageNSec
```

No new implementation changes or host regression runs were needed for this
installation ticket. The source/build validation remains in report 198; this
report adds live terminal and startup qualification.

## Next qualification

Observed suspend/debug and actual sleep qualification require a fresh ready
response on the new boot. Diagnostic.22's existing PM evidence is historical
evidence, not qualification of this candidate. Start with freezer and driver
checks, then late/noirq, before an awake rehearsal and actual RTC sleep. Use
the saved host timing instrumentation to distinguish collection intervals from
post-wake network availability. The earlier untimestamped connection failures
remain unattributed; faster awake SSH startup does not prove they are fixed.
