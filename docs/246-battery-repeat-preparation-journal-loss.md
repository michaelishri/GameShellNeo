# Battery-repeat preparation stopped by lost journal history

9 October 2026. NEO-182, following the offline
[NEO-183 collection fix](245-sleep-collection-reply-recovery.md).

The fresh battery-repeat preparation stopped at check **6 of 7**. Its fourth
late/noirq result failed because earlier kernel journal entries, including the
firmware-identification message, disappeared between snapshots. The PM counter
advanced normally and the owner confirmed the warning and normal dim console,
but the incomplete evidence cannot qualify the sequence. **No new battery
rehearsal or actual sleep was submitted.**

This is separate from the malformed collection reply in the
[original 60-second battery trial](244-first-60-second-battery-rtc-trial.md).
The new failure is a complete, saved, failed debug result. Neither original
result is rewritten or promoted to a pass.

## Admission and preparation

Image `0.1.0-diagnostic.25`, kernel `6.18.54-gameshellneo24`, boot
`2170b296-d964-4d16-bdb1-c135b0e7b812` remain unchanged. The host collector SHA-256
is `22ed94f47ebb364dd48a1078a0b1162f97e6ae38944221ac7a72035dc84f7ec0`;
all nineteen device-helper hashes match the preceding battery attempt.

Independent USB and Wi-Fi PM inspections pass on the original boot, with
PM47/0 and battery 100%/Charging at 4.1646 V. Power-key ownership is absent;
the RTC alarm is inactive/nonpending. The ten-second awake RTC smoke check
passes and restores its state. The owner explicitly confirms readiness for
one freezer, one driver and five late/noirq checks, with USB connected and
controls untouched. This readiness does not cover unplugging or actual sleep.

Each command runs once, sequentially, with its result reviewed before the next:

```sh
task device:pm-test STAGE=freezer CYCLES=1
task device:pm-power-key STAGE=devices CYCLES=1 KEYPAD_TRACE=1 WIFI_TRACE=1
task device:pm-platform
```

The last command is invoked individually four times; the fifth invocation
never runs. Captures below are under `.local/diagnostics/`, with originals in
`cycle-1/result.json`.

| Check | Capture | Run ID | PM successes | Result |
| --- | --- | --- | --- | --- |
| Freezer | `20261009T101912.472774Z` | `868deaae75c94d8db2d94ef690dd3651` | 47 → 48 | Passed |
| Driver | `20261009T102014.999491Z` | `968901317a5f4697bb67d795c4ec4620` | 48 → 49 | Passed |
| Late/noirq 1 | `20261009T102132.826395Z` | `7d52658007ab41219c2049fae16c21c3` | 49 → 50 | Passed |
| Late/noirq 2 | `20261009T102249.035551Z` | `4fd43ed5bbe648e89fb6e5e7a80edbba` | 50 → 51 | Passed |
| Late/noirq 3 | `20261009T102402.912847Z` | `f76d0f204af24a2fb84c2386386cd6ac` | 51 → 52 | Passed |
| Late/noirq 4 | `20261009T102514.956719Z` | `608ed3582d874cf4aa2889fb0d387078` | 52 → 53 | Failed: missing journal history |

The first five accepted records contain both route proofs, stable SDIO usage
2, zero PM failures and the applicable warning/input/restoration checks. The
five-record history is incomplete and cannot authorize a battery rehearsal.

## Failed original and owner observation

The sixth result has `event=failed`, `passed=false` and
`ValueError: Unexpected firmware identity or kernel fault evidence`. Its
SHA-256 is `cb30a535e369393202fcf9245a003a915e49916da5690dc76d67a89082bb4d14`.

The before journal contains 1,633 lines and 127,107 characters beginning with
boot messages. The after journal contains 1,139 lines and 83,120 characters,
beginning at monotonic 1724.849732. Its remaining old entries exactly match the
before snapshot's suffix after a 45,947-character removed prefix, followed by
the new cycle entries. The expected firmware message is absent; none of the
configured fault markers matches. The PM reader requested the whole current
boot's kernel journal, without a line-count limit.

The saved before/after snapshots show PM52→53 with all failure counters zero,
taint zero, no failed units and brightness 1 / `bl_power=0`. Memory validation
passes. The original keypad handle remains connected, power-key ownership is
handed back, and the warning record reports successful playback/restoration.
The platform trace contains late/noirq suspend and early/noirq resume phases.
These individual observations do not substitute for the missing evidence or
establish actual sleep. The failed result has no host postflight route flags.

After the stop, the owner confirms: **“Yes—warning clear; dim console normal.”**
USB remains connected. There is no further screen or sleep test.

## Read-only investigation

The existing documented tasks capture the state without restarting services,
rotating/repairing logs or changing settings:

```sh
umask 077
task device:journal-inspect
task device:exec ROUTE=usb -- sudo -n journalctl -b --no-pager -o json --output-fields=SYSLOG_IDENTIFIER,_COMM,_UID,MESSAGE --all > .local/neo182-repeat-retained-journal.jsonl
task report:journal-volume -- .local/neo182-repeat-retained-journal.jsonl
task device:exec ROUTE=usb -- sudo -n journalctl --verify
task device:exec ROUTE=usb -- sudo -n wpa_cli -i wlan0 log_level
```

The journal inspection (`20261009T102715.300189Z/before.json`) passes the
existing storage-policy validator. Against the installation rotation check
(`20261009T053410.402039Z/after.json`):

- Boot, journal configuration, journald PID112 and its start time are unchanged;
  journald reports zero restarts.
- Logrotate's last start is unchanged; its inherited pre/post hooks remain absent.
- Armbian RAM logging and cron remain masked. The displaced
  `/var/log.hdd/journal` store remains absent.
- Persistent journal files remain open. The inventory contains eleven 4 MiB
  files, and all eleven retained files subsequently pass `journalctl --verify`.
- The separately inspected kernel journal exactly matches the failed result's
  after journal. This loss is not caused by the inspection's 4,000-line limit.
- Wi-Fi logging is restored to `INFO`, timestamp mode 0.

The persistent configuration remains `SystemMaxUse=32M`, `RuntimeMaxUse=8M`,
`MaxRetentionSec=7day`, with compression enabled. These observations are
consistent with bounded retention removing older entries. No deletion event
is retained, so the exact deletion mechanism is **not proven**. Verification
of remaining files does not recover or account for deleted history. See the
earlier [retention analysis](152-diagnostic-command-log-volume.md) for the
distinction between age limits and guaranteed history, and the independent
RAM-log relocation defect.

The private retained-journal capture is 22,674,873 bytes, SHA-256
`6a0b42a46d3759836ea1952835451044fb0186637de278d3b739fa96f6434aa2`.
The offline report counts 48,156 entries and 2,736,154 uncompressed message
bytes:

| Category | Entries | Message bytes |
| --- | ---: | ---: |
| Wi-Fi supplicant | 31,057 | 1,733,664 |
| Other | 13,914 | 756,046 |
| Sudo | 2,046 | 205,466 |
| Kernel | 1,139 | 40,978 |

There are 682 sudo command records and **zero inline Python command records**.
NEO-111's excessive source-command logging has not reappeared in this capture.
Wi-Fi messages account for about 63% of retained message bytes; this is not a
measurement of compressed file usage or proof that Wi-Fi logging caused the
deletion. Raw messages remain private. No SSH-stall investigation is reopened.

## Evidence and next work

The separate stopped-attempt review is
`.local/neo182-repeat-stopped-review.json`, SHA-256
`551855c63a791792aa69b6fb8581208cf8fafb2cd2e05832e5704a72edeab22a`.
The journal inspection SHA-256 is
`08a6c4edb0efc9137853b9f2577d6c84b353800e9fbbb09e34f634321fb702b3`.
The original failed debug result, original battery result and all device-helper
source hashes were checked unchanged. No image/runtime source was modified.

**NEO-182 remains open. NEO-184 tracks the evidence-retention correction.**
The current validator assumes early boot identity and the full earlier kernel
journal will remain available. The correction must preserve verified boot
identity and the actual test interval in bounded protected storage, with
explicit reboot/source mismatch, missing-sequence and overflow rejection.
It must preserve historical originals and strict fault checks; missing evidence
must never be filled from stale records or silently accepted.

Implement and test that path offline before spending another attended sequence
on the same failure mode. Subsequent hardware qualification still requires
fresh provenance, owner readiness and separate unplug instructions. No reboot,
alarm reprogramming, log repair, journal-limit change or actual-sleep retry is
performed in response to this failed preparation. No battery discharge or
sleep-energy claim follows from this attempt.
