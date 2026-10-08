# WFI s2idle and suspend-aware measurements: diagnostic.24

Date: 8 October 2026. Tracking: NEO-155; hardware dependencies NEO-96, NEO-100
and NEO-101 remain open. Branch: `work/cpi-wfi-integration`.

## Purpose and boundary

Diagnostic.23 repeatedly returns from the s2idle loop, but it has no registered
CPU-idle driver and has not established all-CPU tick/timekeeping suspension.
This integration adds the reviewed architectural WFI candidate from
[report 134](134-cpi-wfi-s2idle-candidate.md), after integrating the
[battery clock contract](133-battery-boottime.md) and
[awake measurement guards](135-awake-measurement-clock-guards.md).

The new identity is **0.1.0-diagnostic.24 / 6.18.54-gameshellneo23**. Linux remains
pinned to 6.18.54. The installed diagnostic.23 image, recovery artifacts, saved
observations and matching tools in `work/power-insertion-wake` remain available.
Do not reuse its source-bound qualification or rehearsal receipts on this image.

This is architectural WFI with the kernel's existing s2idle tick coordination.
It introduces no CPU power-off state, PSCI backend, DRAM self-refresh controller
or new charger setting. Even a successful RTC wake with frozen timekeeping is
not proof of lower battery current, sleep residency or the week-long standby goal.

## Integrated changes

- Patches 0027/0028 and the CPI-specific one-state driver permit valid state-zero
  s2idle entry. Successful zero is distinguished from no eligible state, including
  in the scheduler. The core correction is global, even with the board option off.
  Registration targets `clockwork,clockworkpi-cpi3`; all CPUs use the existing
  ARM simple-idle callback, not firmware power-off. The source configuration
  explicitly enables `CONFIG_ARM_CPI_WFI_CPUIDLE`.
- Battery schema 2 binds readings to boot ID and `CLOCK_BOOTTIME`, with separate
  monotonic observation metadata. Delayed/interrupted readings are rejected and
  consecutive low readings reset across detected sleep. Threshold, cadence and
  charger behavior are unchanged. This is an awake userspace guard, not battery
  protection while asleep or serialization with a future product sleep controller.
- Awake-only idle, governor, USB and RSB measurements use bounded paired-clock
  observations and PM counters. Detected sleep invalidates the measurement;
  existing cleanup restores temporary settings. Historical reports remain
  readable with missing-proof labels. Observer cost remains unmeasured.
- Remote bundles include the new helpers. The idle sampler retains its speaker
  warning and restoration path; the counter profiler now stages its dependencies
  together through SFTP. Existing SSH diagnostics and one-shot transport remain.
- `cpi_idle.py` records live CPU/timer configuration and checks candidate-specific
  admission. Linux publishes sleep counters in `state0/s2idle/usage` and `time`;
  the old flat-path collector missed them. The corrected collector preserves
  missing fields rather than treating missing values as zero.

## Hardware evidence required

Admission requires four online/possible CPUs, driver `cpi_wfi`, governor `menu`,
exactly one enabled `WFI` / `ARM WFI` state per CPU, architecture clocksource and
four architecture clock-event devices, plus `sun4i_tick` broadcast. It reads the
live DT timer's compatibility, 24 MHz frequency, four PPI interrupt cells and
firmware/tick property flags, comparing them with the pinned CPI v3.1 source.
This checks configuration, not physical clock continuity.
The state's one-microsecond latency/residency metadata is nominal driver
configuration, not a measurement of device or application resume latency.

For actual RTC sleep, **every CPU's s2idle callback count must advance**, and
the original paired trace/BOOTTIME-versus-MONOTONIC evidence must independently
show timekeeping freeze. Awake rehearsal must leave s2idle callback counts
unchanged. Identities must remain stable and counters cannot regress. Zero
`s2idle/time` is not itself a failure: the scheduler clock can stop while asleep.
The offline reporter recomputes these gates instead of trusting a saved pass flag.
All existing wake reason, RTC deadline, keypad, USB, Wi-Fi and restoration gates
still apply.

Read-only captures on the installed diagnostic.23 boot
`cc26703f-d9ef-4d71-8da1-9d766f3efdbe`, PM **12/0**, confirm:

- all four CPUs online, `menu`, driver `none`, no CPU-idle states;
- `arch_sys_counter`, four `arch_sys_timer` devices, `sun4i_tick` broadcast;
- the live DT matches the pinned A33 timer properties, including no
  `arm,no-tick-in-suspend` or `always-on` flag.

Private captures are `20261008T093025.234676Z/clock-inspection.json` in this
worktree, with earlier inventories `091735.020717Z` here and `091302.251571Z` in
the diagnostic.23 worktree. No alarm, display, PM, reboot or network-setting
operation was performed for these inspections.

The integrated `task device:awake-clock-check ROUTE=usb` also passes on that
unchanged boot: 21 observations, unchanged PM12/0, maximum bracket 48,875 ns
(capture `20261008T093426.773563Z`). This establishes that the observer runs on
the target Python/kernel. It does not exercise the new battery producer or
validate timekeeping across sleep on the candidate kernel.

## Reproduction and validation

Use the existing Taskfile rather than bespoke build scripts. From this worktree:

```sh
task check
task check:cpuidle-kernel
task build:kernel
task test:usb-policy-board
task check:dt
task build:image \
  BOOTLOADER=/home/mishri/workspace/clockworkpi/GameShell/Code/Kernel/v0.2/u-boot-sunxi-with-spl.bin \
  RADIO_DIR=/home/mishri/workspace/clockworkpi/GameShellNeo/.local/hardware-baseline/2026-09-27/radio-reference
task image:pack
task image:checkpoint NAME=diagnostic24-wfi-s2idle
```

Heavy build stages use the existing workflow lock and run sequentially. Private
credentials remain in `.env`; the isolated worktree has its own mutable kernel,
Armbian, image and evidence directories. Verified downloads may be shared.

The host's per-user `/tmp` quota filled during validation, despite ample workspace
space. The native compiler stopped before running a source case. Subsequent host
commands use `TMPDIR="$PWD/.local/host-tmp"` (a private directory) without changing
the compiler/test source or deleting unrelated temporary files. Container builds
retain their own temporary directory. The sandbox launcher also encountered this
host quota; the already-running full kernel build was unaffected.

Host validation passes: **16 runtime and 799 tooling tests**, two documented
optional skips, compiled C regressions and Bash/ShellCheck. New tests reject
missing CPU participation, wrong clocks/DT, disabled states, changed counters,
missing timekeeping evidence and forged saved pass flags. Transport tests execute
the actual transferred helper files outside the repository. Legacy cable fixtures
now use explicit historical policy rather than inheriting the shipping lock.
After preparing the pinned Armbian checkout, all nine journal-policy checks
pass, including the previously skipped source-dependent test. Only the opt-in
user-systemd recovery check remains unexecuted in this slice.

The complete ARM kernel and module build passes, with 177 configuration
assertions and 15 completed artifact hashes verified. The linked kernel contains
the WFI driver/registration, ARM callback, state-zero entry and freeze/unfreeze
functions (saved in `.local/neo155-linked-symbols.txt`). The `zImage` is 6,580,512
bytes. Source validation passes 618 scenarios on both native and ARM32 runners;
all eleven negative controls fail as intended. All four full ARM object
configurations pass (enabled, driver disabled, suspend disabled, CPU-idle disabled),
with the saved `dsb; wfi; bx` instruction sequence. Evidence is
`.local/build/cpuidle-s2idle-tests/compile-evidence.json` and
`.local/build/kernel-completed.json`.

DT bindings and the base/retained-keypad board trees pass with no schema
diagnostics. PM, speaker, supply and USB policy board checks pass, including
their altered-property negative controls (USB: 4,665 state/race cases and 160
probe/unwind cases).

Image assembly and offline verification pass: partition layout, bootloader
readback, FAT16/ext4 checks, U-Boot CRCs/addresses, exact kernel/DTB/module/radio
hashes, battery producer, service policy and private identity permissions.
All **335 recorded project input hashes** match the current files after assembly.
The private artifact and its verified archive are:

| Item | Value |
| --- | --- |
| Image | `GameShellNeo-0.1.0-diagnostic.24-cpi31-11fb47777b62.img` |
| Size | 4,294,967,296 bytes |
| Image SHA-256 | `11fb47777b6273667b4702845ffc3f2b4f223d1b63acfea82b86017cee4012c9` |
| Archive | Same filename with `.gz`, 269,452,866 bytes (about 257 MiB) |
| Archive SHA-256 | `b57d7ecbdc4480e65e1ded76feb51c95cecda236431fe2a1a44e0f6df620ee35` |
| Recovery checkpoint | `.local/recovery/diagnostic24-wfi-s2idle` |
| Qualification | Offline verified; explicitly `hardware_qualified=false` |

The raw image is under `.local/artifacts`, its archive/transfer manifest under
`.local/flash`, all in this worktree. The checkpoint rehashes both artifacts and
retains their build/transfer metadata without duplicating the image. Transfer to
the Mac awaits regular-network confirmation; no card or installed-image change
has occurred. `task mac:stage` performs the later verified transfer without a
card write. Existing diagnostic.23 tooling remains the correct choice for its
currently running image.

Build incident record:

The first attempted build correctly stopped on an experiment allowlist that had
not included the new WFI flag. The corrected helper validates the battery/PM
prerequisites and continues to reject unrelated experiments. Original failed logs
are retained. Two concurrent build-task attempts were refused by the workflow
lock; they did not alter the running build.

## First-install sequence

1. Coordinate regular-network transfer,
   the warning/shutdown/card swap, full flash readback and owner-confirmed boot.
2. Perform awake identity, journal, power-key ownership, battery schema/freshness,
   all-CPU/timer inventory and awake RTC alarm checks using this worktree's tools.
   Any missing driver, helper or CPU blocks PM testing.
3. With fresh owner readiness, run the staged freezer/driver/late-noirq checks,
   with the long warning before each dark interval. Collect and review each
   original result before advancing.
4. Use the fresh seven-debug receipt for an awake RTC rehearsal, then coordinate
   readiness for one attended RTC sleep with USB connected. Require all-CPU callback and
   timekeeping evidence as well as the existing recovery checks and visual return.
   Keep the original failure if any; do not weaken the gate or immediately repeat.
5. After the first success, qualify bounded connected repeats, battery-only sleep
   and USB cable transitions on this kernel. Then plan sleep/awake energy
   comparisons with USB physically removed. Separate clock/observer validation
   from an energy claim; software readings still have calibration limits.

NEO-96/100/101 need matching-image hardware results. NEO-154's intermittent SSH
setup cause stays open; use the existing diagnostics during these independently
justified tests rather than adding sleep cycles solely to provoke it. Power-button
product policy, deep CPU/DRAM retention and sleeping battery protection remain
separate work.
