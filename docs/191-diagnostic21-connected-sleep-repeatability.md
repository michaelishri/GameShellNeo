# Diagnostic.21 connected sleep repeatability

7 October 2026; capture timestamps are UTC. NEO-129 qualifies four consecutive
attended connected-USB s2idle/RTC-wake cycles. All four automated results pass,
and the owner confirms clear warnings and normal dim-console returns without
touching the cable or controls. Together with [report 190](190-diagnostic21-pm-qualification.md),
this is five successful actual sleeps on the current boot.

## Admission and saved procedure

The image remains `0.1.0-diagnostic.21`, kernel `6.18.54-gameshellneo20`, boot
`50dc8224-95e2-4f92-b35e-e35ca5566340`. Source checkpoint is `3c2fc04` on
`work/power-insertion-wake`; no helper, driver or image changed in this slice.
The owner replied “go ahead” for this four-cycle batch and was instructed to
keep USB connected, the headphone socket empty and controls untouched.

Read-only PM inspection `20261007T032243.950106Z/inspection.json` passed the
existing health and continuation validators at PM8/0. The continuation binds
report 190's seven debug originals, original awake RTC rehearsal and first
actual sleep. The already-consumed first-sleep baseline was not reused.

The following historical command was submitted once:

```sh
task device:sleep-batch \
  QUALIFICATION=.local/diagnostics/20261007T031630.769742Z/qualification-next.json \
  REHEARSAL=b5fb1d15febe4f8c9a888f74662dd2b1 CYCLES=4 ATTENDED=1
```

The existing runner checks each original result and both independent SSH
routes before advancing, with a 20-second awake observation interval between
cycles. It stops on failure. No extra sleep submission, cable action, network
repair or gadget restart was used to recover a result.

## Results

Batch capture: `.local/diagnostics/20261007T032436.378194Z`. Each original is
`cycle-N/result.json` beneath it; `batch.json` reports four completed cycles
and a passing complete result.

| Cycle | Run ID | Submission interval, BOOTTIME seconds | In-loop s2idle, MONOTONIC seconds | RTC IRQ31 count | PM successes afterward |
| --- | --- | ---: | ---: | --- | ---: |
| 1 | `4cf16df387dd4cc4adb706cb917194a6` | 32.032 | 29.526 | 3 → 4 | 9 |
| 2 | `1f93205d976541eb9d3c8c26518e516b` | 31.644 | 29.073 | 4 → 5 | 10 |
| 3 | `007b894fdd88424b81d5244a4262f6f0` | 31.616 | 29.156 | 5 → 6 | 11 |
| 4 | `87a162d5e0534f56b3c243e48f726261` | 31.765 | 29.390 | 6 → 7 | 12 |

Every cycle records `freeze` with `pm_test=none`, one actual s2idle boundary,
RTC wake through IRQ31 and one event with flags `0xa0`. Original alarms are
restored. Both USB and Wi-Fi SSH reach the original boot independently after
each sleep. PM failures and all stage-failure counters remain zero; SDIO usage
remains 2 with unchanged active/forbidden policy and control `on`.

The original keypad handle survives all four cycles with no disconnect,
hangup, poll/ioctl error or held key. Keypad, Wi-Fi and USB traces retain their
integrity and restore their settings. Original power policy is restored, with
no retained policy, drop-in, controls, RTC or console owner. MUSB and both
power-supply wake settings remain disabled. Brightness/backlight power return
to 1/0; the process-memory check passes.

Each cycle plays the level-5, 1,000 ms `screen-blank` warning and restores the
mixer, with speaker/headphone amplifiers off afterward. After the batch, the
owner confirms: “Yes—warnings clear and all four returned normally, untouched.”

Collection retained transient SSH errors: cycle 1 had two channel-opening
timeouts; cycle 2 had two such timeouts and one connection failure; cycle 3
had one timeout and two connection failures; cycle 4 had one timeout and
three connection failures. All originals were eventually collected and both
routes verified. These delays are real diagnostic observations, with no
assigned device, Mac or network cause. They do not measure device wake latency.

## Final awake state and gauge inventory

`task device:pm-inspect` capture `20261007T033247.338909Z/inspection.json`
passes both the image/health validator and the final continuation validator,
which recomputes the seven debug and five actual-sleep records. PM remains
12/0, SDIO usage 2 and normal dim-console settings. No further sleep was run.

The read-only `task device:charge-inspect` capture
`20261007T033300.133938Z/inventory.json` passes schema 3's
`axp223-volatile-b8` admission. B8 is fresh `c0`, with calibration disabled
and not in progress. REG33/34/B8/E0/E1/E6 remain `c6/45/c0/00/00/a0`.
Nonvolatile configuration still has possible-cache provenance; E0/E1 report
no configured capacity. The reported 4.2 V target, 1.2 A charging limit and
900 mA USB input limit are unchanged.

This awake inventory reports 100%, Charging, 2 mA and 4.158 V; raw voltage
bytes are `ec/04`, with unused low bits zero. It does not resolve the earlier
4.2559 V discrepancy, validate physical voltage/capacity or prove charging
during sleep. No charger/gauge writes, raw-bus access, cache bypass or forced
calibration were performed.

## Evidence and continuation

Original result SHA-256 values in cycle order:

```text
944e14351a7fdaf6f4c91c7f5bf9a9fd655df0790a7f47220622a4456c54642c
40b25e12d3533c5083f42b364e10bb52aedd3e4c935b4ee695286e481eba738d
4c872314129333ccb2499fa709c5b2dcb7fe169621c5ad3e6b17429fc9f1c1f9
04350c39717970f1323aac9cbfc1ef24ffbacb7edd55864dd56d55505b2ddd9e
```

| Evidence | SHA-256 |
| --- | --- |
| `batch.json` | `a43da5d5d1e76c9e78a4f2c8027d746ae3da5a3852ac0fcedce50b98f62f72ca` |
| `cycle-4/qualification-next.json` | `698b2b5545bfe2bae8ab6c407003ea855fe0416ebbfe1e7a2c581233c252289c` |
| Final PM inspection | `afc9805533c56eaac718c7d7ef2c2bd7f69a7f5645b6d807ee61993ede3e2412` |
| Final charge inventory | `3c9cb63efc34cf2e3e036202cb2f7fc79256e44f51406d0d0bd7402b5c562a30` |

The current continuation is the batch's `cycle-4/qualification-next.json`;
earlier continuations are consumed. Other cable/power profiles need their
own qualifying sequence.

The saved offline `task report:sleep-evidence RESULT=<original-result>` was
run once for each cycle. All four RTC/trace/clock assessments pass without
rewriting or requalifying the original. Their `sleep-evidence.json` captures
and hashes are:

| Cycle | Capture | SHA-256 |
| --- | --- | --- |
| 1 | `20261007T032730.424802Z` | `04a786d7eb131831adfb7a8b9d2f7c407a774fb809caf2c7e5a03fa2ed5f0a00` |
| 2 | `20261007T032930.626780Z` | `81087dd9580a8aee5c0528b47e6a4114b64dd4ae7bb2f88090ddda40ac72926a` |
| 3 | `20261007T033128.458334Z` | `c054646b46dab8fb120c4247471ac1ff9c76ae6b292cfc67619c4562e313f9a1` |
| 4 | `20261007T033247.349433Z` | `55dde7a883f27f4aae1d038dbe64e4c88708a9d694f176bd68f3472bcf74bd6e` |

No timekeeping-freeze pairs were observed, and clock gaps remain below
sampling uncertainty. This bounded repeatability result does not establish
CPU retention, standby energy or sub-second product resume. Battery/cable,
host-sleep, cross-boot and POWER-wake coverage remain separate work; normal
button/automatic sleep stays disabled. NEO-10/NEO-117 retain the electrical
measurement and direct sleep-charge gaps. The GameShell is awake with USB
connected and no test running.
