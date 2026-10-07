# GameShellNeo

A modern, maintainable Linux foundation for the ClockworkPi GameShell **CPI v3.1**.

The first milestone is a diagnostic image: Linux 6.18.54, minimal Debian 13,
standard device interfaces, and the bootloader already proven on the owner's
board. Normal sleep, a launcher, OTA and other board revisions are later work.

Diagnostic.22 is installed with the shared ADC width correction. Full card
readback, owner-confirmed login, both network routes, startup checks and the
read-only schema-4 inventory pass. The first sample reports about 4.157 V with
no unused ADC bits set; this does not resolve the earlier voltage discrepancy
or establish physical accuracy. Seven staged PM debug checks and the awake RTC
rehearsal also pass, with owner-confirmed warnings/normal display returns;
six actual connected-USB RTC sleeps pass automated recovery checks, including
a four-cycle batch. The owner confirms the batch's clear warnings and untouched
normal display returns. Both routes recover each time, with final PM13/0 and
stable SDIO usage. [Report 195](docs/195-diagnostic22-pm-qualification.md)
preserves the initial tests and first missed warning;
[report 196](docs/196-diagnostic22-connected-sleep-repeatability.md) records the
completed batch. CPU retention, energy and other power/cable profiles remain open.
[Report 194](docs/194-diagnostic22-installation-and-adc-validation.md) records
the hardware checks; [report 193](docs/193-diagnostic22-adc-integration.md)
records the build, checksums and recovery checkpoint.

Diagnostic.21 previously qualified the AXP223 gauge-status cache correction.
Full card readback, startup, both network routes and the live volatile-B8
inspection pass. Seven attended suspend-debug checks and the awake RTC rehearsal
also pass, followed by five actual connected-USB RTC sleeps, including a
four-cycle batch. Both routes recover every time, and the owner confirms clear
warnings and normal display returns without intervention. Fresh B8 reads survive
resume. [Report 190](docs/190-diagnostic21-pm-qualification.md) records the initial
checks; [report 191](docs/191-diagnostic21-connected-sleep-repeatability.md)
records bounded repeatability. Other power/cable profiles, broader reliability
and energy savings remain open.
[Report 189](docs/189-diagnostic21-installation-and-gauge-validation.md) records
the hardware results and continuing voltage/capacity uncertainty.
[Report 187](docs/187-diagnostic21-gauge-integration.md) records its build,
inspection contract and checksums.

Diagnostic.20 has booted after verified full 4 GiB card readback. Both SSH
routes, integration and awake journal/POWER/RTC checks pass. The MUSB and both
supply wake controls are disabled as intended
([report 167](docs/167-diagnostic20-installation-and-awake-checks.md)).
One freezer, one driver and five late/noirq debug checks also pass, with both
routes recovering, the original keypad connection retained, PM7/0 and stable
SDIO usage 2. The owner confirmed clear warnings and normal console returns
throughout the complete sequence
([report 168](docs/168-diagnostic20-attended-debug-qualification.md)).
The awake RTC rehearsal also passes with full restoration and both routes
verified. The first connected-USB actual RTC sleep/wake passes, with both routes
recovering, unchanged wake settings and owner-confirmed clear warning/normal
dim console ([report 169](docs/169-diagnostic20-first-rtc-wake.md)). Independent
attachment prerequisites and rehearsal passed ([report 170](docs/170-diagnostic20-usb-attachment-preparation.md)).
One attended USB-attachment-during-sleep case now passes: the owner confirmed
the screen stayed dark after insertion, the RTC woke it later, both routes
recovered and Charging was reported after resume. PM16/0 and SDIO usage 2 remain
healthy ([report 171](docs/171-diagnostic20-usb-attachment-sleep-validation.md)).
The independent removal debug baseline and connected awake rehearsal pass,
with owner-confirmed warnings/display and PM23/0 ([report 172](docs/172-diagnostic20-usb-removal-preparation.md)).
One attended removal-during-sleep case then passed: RTC wake, Wi-Fi recovery,
correct absent USB state and normal dim-console return. The separately requested
awake reconnect restored both SSH routes and external-power detection, with
PM24/0 and SDIO usage 2 unchanged ([report 173](docs/173-diagnostic20-usb-removal-sleep-validation.md)).
The subsequent four-cycle removal/attachment batch passed all RTC wakes,
endpoint checks and owner observations, including staying asleep after both
insertions ([report 178](docs/178-guided-cable-batch-hardware-validation.md)).
Direct charging evidence during sleep and standby-energy qualification remain open.

The previous diagnostic.19 installation passed full card readback and owner-confirmed boot.
Both SSH routes, integration, journal rotation, awake power-key ownership and
awake RTC checks pass; [report 155](docs/155-diagnostic19-installation-and-awake-checks.md)
records the evidence. Fresh office startup checks and one freezer, one driver
and five late/noirq debug cycles also passed, with owner-confirmed normal display,
both SSH routes recovering, PM 7/0 and stable SDIO usage 2
([report 158](docs/158-diagnostic19-attended-debug-qualification.md)).
The first actual connected-USB RTC sleep/wake test also passed: both SSH routes
recovered, the keypad connection survived and the owner confirmed normal display
([report 160](docs/160-diagnostic19-first-rtc-wake.md)). Refreshed debug checks
confirmed the long audible warnings ([report 162](docs/162-diagnostic19-long-cue-debug-qualification.md)).
One attended USB-removal-during-sleep case now passes: RTC wake, normal display,
Wi-Fi recovery and correct disconnected USB state, followed by a separately
verified awake reconnect ([report 163](docs/163-diagnostic19-usb-removal-sleep-validation.md)).
A fresh, owner-observed attachment prerequisite sequence also passed
([report 164](docs/164-diagnostic19-usb-attachment-debug-qualification.md));
The attachment attempt then woke early through the PMIC, before the RTC:
both supply insertion-wake policies were enabled. USB/Wi-Fi and the normal
console recovered, but the RTC test remains failed ([report 165](docs/165-diagnostic19-usb-attachment-early-wake.md)).
Before the card swap, diagnostic.19 reached PM24/0 with stable SDIO usage 2. The agreed policy is:
**connecting USB during sleep leaves the device asleep and charging**.
NEO-117 has built and offline-verified diagnostic.20 using the existing supply
wake controls. Host checks pass, and the 270 MB archive is now staged on the
Mac with compressed/decompressed checksums verified. Card flash/readback also
passed, followed by first boot, awake startup checks and the bounded attended
sleep cases above
([report 166](docs/166-stay-asleep-usb-charging-policy.md)).
The old diagnostic guard explained the suppressed POWER button before the
card swap. Long speaker warnings preceded the requested remote shutdown
(report 166). No retained key guard exists on diagnostic.20's new boot.
The first connected-USB RTC wake and one attended case in each cable direction pass.
Wider repetition remains open.
[Report 154](docs/154-usb-sleep-session-retirement.md) covers the driver change,
callback lifetime protection, masked-interrupt findings and verification.
Diagnostic.18's removal-during-sleep failure remains preserved in
[report 153](docs/153-usb-removal-sleep-state-failure.md), with a recovery image
retained. Ordinary sleep is disabled; production sleep, energy and wake-button
qualification remain ahead. Historical image reports are in the research index.

Start with the [first-build specification](docs/23-first-build-spec.md),
[build workflow](docs/24-building-and-testing.md),
[first-build results](docs/25-first-build-validation.md), [research index](docs/README.md)
and [follow-up activities](FOLLOW-UP.md).
Implementation is tracked in Kaneo's OpenSource / GameShellNeo (NEO) project.
The first private image has booted on the owner's board; Wi-Fi and USB SSH are
verified. [First-boot results](docs/26-first-card-and-boot-validation.md) record
the live USB correction and initial qualification findings. The
[installed refresh](docs/27-diagnostic-integration-refresh.md), `0.1.0-diagnostic.2`,
includes that correction, explicit New Zealand provisioning and the kernel/
userspace integration fixes. Its first boot, USB/Wi-Fi access and live integration
checks passed on the owner's accepted AU-advertising access point. Repeated
hardware tests remain under NEO-5. [Hardware qualification](docs/29-hardware-qualification.md)
records ten cold starts, ten USB reconnections, basic keypad/backlight and load
checks, power transitions, installed battery-policy simulations, two consistent
awake-idle power estimates, the backlight-off comparison and the remaining
Lightkey/charging findings. It also records the first real automatic low-battery
shutdown: the guard requested poweroff after three low samples, the system
synced filesystems, and USB/Wi-Fi access recovered on the next boot.
[Awake-power profiling](docs/31-awake-power-profile.md) identifies substantial
CPU time in the frequency-governor worker and records the next optimization
priorities, instrumentation limits and reusable capture task.
[Governor comparison and function profiling](docs/32-governor-rate-comparison.md)
records a reversible halving of governor-worker CPU time, only a 2–3% estimated
power reduction, and directly sampled NKMP clock-search cost. Original settings
are restored. The [clock-search optimization](docs/33-nkmp-clock-search-optimization.md)
preserves the selected clock factors in native and ARM32 comparisons. Candidate
`0.1.0-diagnostic.3` has been flashed and booted, with passing integration,
storage and CPU/memory load/recovery checks. With the original governor timing,
recorded governor CPU time fell about 92% (35.5% → 2.7% of one core), supported
by separate function samples. Estimated battery power was 2.7% lower; differing
charge state and uncalibrated readings limit that comparison. Final checks
passed and the original governor setting is restored.
The earlier image, `0.1.0-diagnostic.4` / `6.18.54-gameshellneo4`, adds the USB
work-lifetime fix and once-per-search NM/NKM clock constraints. Its
[validation report](docs/40-diagnostic4-hardware-validation.md) records build
and flash verification, hardware results and the exact repeatable test sequence.
Diagnostic.3 remains available for recovery. The new changes do not yet have
an attributed battery-power or clock-latency measurement.
The [diagnostic.5 USB polling experiment](docs/41-usb-polling-experiment.md)
passed the stock/experimental cable and startup tests in
[report 44](docs/44-diagnostic5-hardware-validation.md). The
[battery comparison](docs/45-usb-polling-idle-comparison.md) found about 72% fewer
aggregate PMIC bus interrupts, with no resolved battery-power difference.
The driver defaults off; diagnostic images explicitly opt in after
board/topology/PMIC checks. Diagnostic.4/5 recovery images are retained.
The earlier candidate, `0.1.0-diagnostic.6` / `6.18.54-gameshellneo6`, adds direct
USB callback diagnostics and the tested upstream A0 firmware candidate.
It has passed the build/offline checks, Mac transfer verification and guarded
card flash with full readback. [Report 51](docs/51-diagnostic6-preparation.md)
records implementation and host verification;
[report 52](docs/52-diagnostic6-hardware-validation.md) tracks ongoing hardware
qualification. First boot, integration, battery-policy simulation and connected/
unplugged USB count/error tests passed in both modes. Direct unplugged polling
fell from 16.65 to 3.85 callbacks/second (76.9%) in matched one-minute windows;
this does not establish an energy saving. Four subsequent physical cable cycles
passed in each mode, including USB SSH and plug/removal IRQ delivery. Four
consecutive physical cold starts passed with the expected firmware and both
SSH routes. The saved installed-firmware test also passed four software
reconnections, unavailable-network scanning and connection restoration.
Physical AP-loss Wi-Fi qualification is deferred; the random-SSID simulation
provides the current unavailable-network evidence. Broader power/sleep work remains.
The previous image, `0.1.0-diagnostic.7` / `6.18.54-gameshellneo7`, passed
flash/readback, first-boot/integration, hotspot connection and both SSH routes.
One freezer and five devices PM debug tests passed under NEO-37, including
the owner's confirmation of normal console/backlight return after the first
driver test and repeated batch. Normal sleep stays disabled. This image uses stock
USB polling and retains SDIO power for driver tests; it is a separate
configuration from diagnostic.6's polling experiment.
[Report 54](docs/54-staged-pm-diagnostic.md) records preparation and
[report 55](docs/55-diagnostic7-hardware-validation.md) records hardware
evidence and outstanding keypad/MUSB recovery work. Diagnostic.6 remains
available as a recovery image.
The previous image, `0.1.0-diagnostic.8` / `6.18.54-gameshellneo8`, has passed the
full kernel, device-tree and offline image checks, and its 266 MB archive is
verified on the Mac. It adds the AXP USB polling
suspend fix, the Sunxi MUSB unsupported-register correction, and bounded keypad
PM tracing. Diagnostic.7's recovery image and matching metadata are retained.
[Report 59](docs/59-diagnostic8-preparation.md) records the artifacts and next
hardware sequence.
The DEV-card flash, full readback, safe ejection, first boot, USB SSH and all six
integration checks passed. One freezer and seven devices debug cycles also
passed with both SSH routes recovering, zero unsupported-ULPI warnings and no
PM failures. Two keypad traces confirmed supply cycling and an exhausted
persistence wait, with about three seconds in the keypad USB resume callback.
That power-off image did not preserve keypad input continuity;
[report 60](docs/60-diagnostic8-hardware-validation.md) records the evidence and
next reversible persistence comparison.
The qualified keypad-retention image, `0.1.0-diagnostic.9`, retains that same kernel binary and
modules while adding one experimental device-tree property to retain the
internal keypad supply. [Report 62](docs/62-keypad-supply-retention-preparation.md)
records its preparation, diagnostic.8 recovery path and repeatable continuity
test. Flash/readback, boot, integration, one freezer and six devices debug stages
passed, including four consecutive cycles preserving the original keypad input
handle without disconnection. The healthy-handle observation was about 1.5 s
earlier than the previous fastest power-off candidate; this is diagnostic timing,
not real wake latency. [Report 63](docs/63-keypad-retention-hardware-validation.md)
records the results and remaining USB reset cost. Normal sleep stays disabled;
retention energy and physical input behavior remain to be measured.
[Report 64](docs/64-keypad-physical-input-validation.md) subsequently qualified
A/B/X/Y presses and releases before and after a driver test through that same
handle. Linux deliberately cleared held A during its input suspend callback;
fresh taps worked afterward, with no stuck key. Other input cases and actual
sleep remain unqualified.
The `0.1.0-diagnostic.10` image added the upstream A33 speaker path
for audible button-registration cues. Offline verification, card flash/full
readback, boot/integration, three quiet speaker cues and the audio-assisted
physical-input/driver PM test passed. All nine input cues completed, mixer and
idle amplifier state were restored, and the owner confirmed clear tones and
normal screen return. Diagnostic.9 remains the recovery baseline.
[Report 65](docs/65-speaker-confirmation-cues.md) records preparation;
[report 66](docs/66-speaker-hardware-validation.md) records hardware results.

The saved keypad port comparison subsequently measured ~359 ms (33%) faster
USB resume with a single-reset enumeration sequence, and ~90 ms (8%) with a
separate shorter-recovery-wait trial. Twelve automatic cycles and a physical
button test with the single-reset candidate passed; all experimental settings
were restored. These are driver debug measurements, not actual wake latency.
[Report 67](docs/67-keypad-port-recovery-comparison.md) records the evidence.
Actual sleep and audio-enabled idle power remain unqualified.

Diagnostic.11 introduced USB PHY detection draining during suspend
and deferred power-supply notification work until suppliers have resumed.
[Report 73](docs/73-diagnostic11-installation.md) records verified installation
and integration; [report 74](docs/74-diagnostic11-pm-validation.md) records
driver, input and cable qualification, including an intermittent Wi-Fi recovery
failure. Five subsequent traced driver cycles passed in
[report 78](docs/78-wifi-resume-metadata-capture.md), but the original failure
remains unresolved. Normal sleep stays disabled.

Diagnostic.12 passed full card readback, owner-confirmed
login, independent USB/Wi-Fi access and all six integration groups. It integrates
four brcmfmac patches for truthful transition errors, bounded worker collection,
failed-wake isolation and PM/reset/removal/IRQ ordering. Diagnostic.11 is preserved as the verified
recovery checkpoint. [Report 85](docs/85-diagnostic12-preparation.md) records
preparation; [report 86](docs/86-diagnostic12-installation.md) records installation
and the read-only PM/keypad/audio baseline. One freezer and five traced driver
cycles subsequently passed, including a four-cycle batch with the original
keypad connection retained and both SSH routes recovered each time.
[Report 87](docs/87-diagnostic12-pm-validation.md) records the results, transient
Wi-Fi retries and aggregate IRQ/CPU observations. Speaker-assisted physical
input and four USB reconnects also passed in
[report 90](docs/90-diagnostic12-input-usb-validation.md). The intermittent
recovery failure and actual sleep remain open.

The preceding `0.1.0-diagnostic.13` added packet-worker error isolation and
checked interrupt rearm ownership. [Report 91](docs/91-diagnostic13-preparation.md)
records the verified build and diagnostic.12 recovery;
[report 93](docs/93-diagnostic13-installation.md) records full card readback,
owner-confirmed startup, both SSH routes, integration and read-only peripheral
baselines. [Report 94](docs/94-unattended-diagnostic13-validation.md) records
passing unattended Wi-Fi recovery/scanning, storage/load, battery-policy and
final health checks. [Report 96](docs/96-diagnostic13-attended-validation.md)
records passing attended qualification: one freezer check, six driver debug
cycles including speaker-assisted physical input, and four USB reconnects.
Both SSH routes and final restoration passed. The earlier journal loss was
traced to inherited RAM-log hooks in scheduled log rotation; the running device
and runtime sources now have the verified policy correction in
[report 97](docs/97-journal-loss-investigation.md). The retained diagnostic.13
image artifact predates that correction. [Report 98](docs/98-shallow-sleep-readiness.md)
defines the wake-error, power-key ownership, RTC and late/noirq preparation
needed before actual low-power sleep, which remains unqualified and disabled.
Fatal checked radio errors still require a cold restart. The saved
`task device:qualify-awake` now combines the awake sequence into one command
with persistent progress and a final report; its full live run passed in about
eleven minutes ([report 95](docs/95-awake-qualification-workflow.md)).

[USB status polling](docs/34-usb-status-polling-investigation.md) traces the
next optimization candidate. The PMIC can miss interrupts in some power-path
modes; reducing its polling requires board-specific detection tests first.
[Replacement battery identification](docs/30-bl5c-battery-identification.md)
records the owner's BL-5C listing and the charge limits still needing verification.
The original card has a
[verified recovery backup](docs/28-original-card-recovery-backup.md) on both hosts.

Passwords, Wi-Fi credentials and private connection settings belong in the
ignored **`.env`** file. Generated keys, captured firmware, personalized images,
downloads and build outputs belong under ignored `.local/`.
The original working card must be preserved; experimental images target a
separate microSD card. A successful build is not hardware qualification.

## Shared task commands

Use [Taskfile.yml](Taskfile.yml) for repeatable work, from this directory:

```sh
task                       # List commands
task setup                 # Pull and verify the pinned build environment
task doctor                # Check this build host
task check                 # Host tests and shell lint
task build:image           # Rebuild userspace/image using the completed kernel
task device:status         # Capture the running board's status over Wi-Fi
task device:status ROUTE=usb # Connect through the Mac's USB link
task device:ssh-timing CYCLES=3 # Fresh USB/Wi-Fi timing pairs while awake
task device:ssh-timing-report CAPTURE=.local/diagnostics/<capture> # Offline summary
task device:user-startup LEGACY=either # User-manager inventory and Unix98/SSH terminal checks
```

Both humans and coding agents should use these commands. When another routine
operation is needed, extend the Taskfile and its checked-in `tools/` helpers.

The SSH timing probe leaves the screen and power policy unchanged. It discovers
the current Wi-Fi address through USB, requires the same boot and unchanged PM
counters across both routes, and stops on failure. Credentials remain in `.env`.
It saves private `awake-ssh.json`, `host-timing.jsonl` and a timing summary.
Each PM debug cycle, RTC rehearsal/sleep attempt and explicit sleep collection
also records host timing automatically. The offline report accepts a capture
directory, including a batch's individual `cycle-N` directory. Nested durations
overlap; do not add them together or treat SSH command latency as wake latency.
[Report 197](docs/197-ssh-collection-timing.md) describes the clock brackets,
the awake session-startup delay and the remaining recovery investigation.

`device:user-startup` defaults to the USB route. Use `LEGACY=enabled` for the
diagnostic.22 baseline and `LEGACY=disabled` for the diagnostic.23 candidate;
`ROUTE=wifi` selects the configured Wi-Fi route. The task records manager startup
phases and device-unit counts, tests data transfer and resizing on its own
temporary Unix98 terminal, and requests a real SSH terminal as the ordinary
login user. It preserves the screen and checks unchanged boot/PM/display state.
It neither restarts the user manager nor changes session/SSH policy. The startup
times describe the manager serving that login, which may already have been
running. Allow ordinary session cleanup before comparing fresh logins; keep
unit counts, startup phases and host SSH timings as separate measurements.
[Report 198](docs/198-legacy-pty-startup-candidate.md) records the candidate and
the measurements required after installation.

### Prerequisites

Build on the **Intel x86-64 Linux host**. Install [Go Task v3](https://taskfile.dev/docs/installation)
first (tested with 3.53.1), then use:

```sh
task setup:host             # Once on a new Debian/Ubuntu host; uses sudo
task setup                 # Pull and validate the exact locked Docker image
```

`setup:host` installs missing native packages: certificates, build-essential,
curl, Git, Python, Paramiko, OpenSSH client, util-linux, xz, tar and ShellCheck.
It installs distribution Docker (`docker.io`) only if the `docker` command is
absent, and starts/enables that new engine on systemd hosts. It preserves an
existing Docker installation and does not upgrade already installed packages.
Repeated runs skip package installation when everything is present. Host package
versions come from the host's configured repositories; the builder is pinned.

Docker must be running and accessible to your normal account. For a newly
installed system Docker engine, an administrator can grant access with
`sudo usermod -aG docker "$USER"`; log out and back in before `task setup`.
For an existing Docker installation, use its normal account-access setup.
Image assembly requires privileged containers and loop devices on the Linux
host. Setup does not change account groups or run the project as root.

On other Linux distributions, install Docker, Python **3.11+**, Bash, Git,
curl, tar, a C compiler, `flock`, `ssh-keygen`, ShellCheck and Paramiko manually.
`setup:host` cannot supply a newer Python than the host's repositories provide;
`setup` checks the version. Paramiko is only needed for device/Mac operations
(tested with 4.0.0). Lint also accepts the existing builder's cached ShellCheck.

`task setup` checks host prerequisites, creates private workspace directories,
and creates `.env` from `.env.example` **only if absent**. It preserves existing
secrets and sets `.env` permissions to `0600`. It then pulls the single builder
image by digest and platform from [sources.lock.json](build/sources.lock.json),
verifies its identity and architecture, and runs a disposable container to
compile/execute a small ARM program and check the image/device-tree tools.
The smoke test runs without network access, host mounts or privileged mode.
That image supplies both the kernel and image build environments.

Setup is safe to repeat, including after a lock-file change. Docker reuses
cached layers; setup still checks the registry's pinned reference. Progress is
in `.local/build/setup.log`, and `.local/build/setup.json` records the last
successful verification. A failure returns a nonzero status. Setup does not
download private firmware, provision device identities, compile Linux or build
an OS image; continue with the steps below.

The Mac is the USB bridge/card-writing host; run Task on Linux. Enable Remote
Login on the Mac, keep it awake, and approve the attached USB accessory if macOS
asks. Its `/usr/bin/python3` must work (tested with macOS Python 3.9.6). Raw-card
access over SSH also needs **Allow full disk access for remote users** in Remote
Login settings; see [the first flash report](docs/26-first-card-and-boot-validation.md).

### Private configuration

Keep the existing `.env`. For a new checkout only, copy [.env.example](.env.example)
to `.env`, set its permissions to `0600`, and fill the blank values locally:

| Settings | Purpose |
| --- | --- |
| `GAMESHELL_WIFI_SSID`, `GAMESHELL_WIFI_PSK` | Image Wi-Fi network and passphrase or 64-digit hexadecimal PSK |
| `GAMESHELL_WIFI_COUNTRY` | Confirmed two-letter operating country; `NZ` for the owner's New Zealand device |
| `GAMESHELL_IP`, `GAMESHELL_USERNAME` | Running board's Wi-Fi address and SSH account |
| `GAMESHELL_WIFI_VIA_MAC` | `1` reaches that Wi-Fi address through Mac SSH; absent/empty/`0` connects directly |
| `GAMESHELL_USB_IP` | Board's USB address; defaults to `192.168.10.1` |
| `M2_MACBOOK_AIR_IP`, `M2_MACBOOK_AIR_USERNAME`, `M2_MACBOOK_AIR_PASSWORD` | Mac SSH connection |
| `M2_MACBOOK_AIR_TAILNET` | Optional preferred Mac transport address for all Mac tasks and `ROUTE=usb`; no automatic LAN retry |
| `M2_MACBOOK_AIR_KEY` | Optional Mac SSH key path, as an alternative to password/agent authentication |
| `M2_MACBOOK_AIR_SUDO_PASSWORD` | Optional separate Mac administrator password; otherwise uses the SSH password |
| `NEO_SSH_KEY` | Development SSH private-key path |
| `NEO_HOST_PUBLIC_KEY` | Provisioned board host-key path, used to verify its identity |

Quote values containing spaces or `#`. The helpers parse `.env` as data: shell
commands and variable references are never expanded. Do not `source` it or put
passwords in task arguments. Task itself does not import or echo `.env`.
Matching process environment variables can override the file for automation.
SSH key material stays in permission-restricted files referenced by `.env`.
The device commands use SSH keys; a legacy `GAMESHELL_PASSWORD` is not used.

Mac connections require a verified host key in the Linux account's SSH
`known_hosts` or `.local/ssh/known_hosts`. For a new Mac, establish that trust
with normal SSH after comparing its fingerprint. Device connections pin the
host key generated by `task provision`; a changed key is rejected.

For remote work, set `M2_MACBOOK_AIR_TAILNET` in `.env`. The same task commands
then connect to that address while checking the Mac's existing host key under
`M2_MACBOOK_AIR_IP`. Keep that original address as the identity alias; it need
not be reachable. An unavailable tailnet connection fails without trying the
LAN. Clear the tailnet value to use LAN transport again. If only the tailnet
address is configured, its own verified `known_hosts` entry is required.
This changes the Linux-to-Mac connection; the GameShell's USB address stays the
same. If the GameShell is also on a remote Wi-Fi network, set
`GAMESHELL_WIFI_VIA_MAC=1` and put its current local Wi-Fi address in `GAMESHELL_IP`.
Then `ROUTE=wifi` and the Wi-Fi observers in the USB/power tests use the Mac as
an SSH jump host. `ROUTE=usb` still reaches the separate USB address. Both routes
verify the provisioned GameShell host key; neither silently falls back to the
other. The Mac must be able to reach the board on that local Wi-Fi network.

When changing the image's Wi-Fi network, update its SSID/PSK in `.env`, run
`task provision`, then `task build:image` and `task mac:stage`. This reuses the
completed kernel and preserves the device's generated SSH identity. After
flashing, read the new Wi-Fi address through USB and update `GAMESHELL_IP`
before using Wi-Fi tasks.

### Building and provisioning

On a new checkout, provide the locked bootloader binary and the owner's radio
files, and create/select a development SSH key. The current workspace already
has these inputs. Provisioning prepares files locally and preserves the board's
existing generated identity across rebuilds:

```sh
task setup
task prepare
task provision
task build
```

`task build` runs the kernel regressions, compiles the kernel, validates the device tree, then builds and
verifies the image **in sequence**. It does not provision credentials implicitly.
Run `task provision` again after editing Wi-Fi settings, country or the authorized key,
then rebuild. This changes the next image, not the running board.
Country is explicit and is never inferred from timezone. A future launcher
region setting is tracked in [FOLLOW-UP.md](FOLLOW-UP.md); it is not implemented
in the diagnostic image.

The preparation defaults use the sibling GameShell bootloader and the private
radio baseline recorded on 2026-09-27. Override paths when needed; pass the same
overrides to `build`/`build:image`, which refresh preparation automatically:

```sh
task prepare BOOTLOADER='/path/to/u-boot-sunxi-with-spl.bin' RADIO_DIR='/path/to/radio-reference'
task provision AUTHORIZED_KEY='/path/to/development-key.pub'
task build BOOTLOADER='/path/to/u-boot-sunxi-with-spl.bin' RADIO_DIR='/path/to/radio-reference'
```

| Task | When to use it |
| --- | --- |
| `task setup` | New checkout or changed builder lock; prepare and verify the build environment |
| `task setup:host` | Install missing native prerequisites on Debian/Ubuntu |
| `task build:image` | Runtime/image changes; reuses the completed, verified kernel stage |
| `task build:kernel` | Kernel source/configuration work; preserves incremental build outputs |
| `task kernel:reset` | After changing the patch queue; archives old kernel source/output and artifact metadata/logs under `.local/previous-kernels/`, then run `task build`. Recovery images stay in `.local/artifacts/` |
| `task build:rootfs` | Exercise Debian bootstrap/cache preparation independently |
| `task build:prune-driver-scratch SUITE=brcmfmac-pm-tests` | Preview superseded compiler trees; add `APPLY=1` to remove them while retaining current normal/debug build evidence |
| `task build:compact-driver-sources SUITE=musb-sleep-tests` | Verify duplicate sources against the locked archive and patch queue; add `APPLY=1` to replace them with shared-source links, keeping compiled outputs and evidence |
| `task check:kernel-source-reuse` | Build two real ARM configurations and regenerate an object, checking isolated outputs and shared read-only source; no device access |
| `task build:prune-retained KEEP=3` | Preview older raw images and full kernel snapshots; `APPLY=1` verifies compressed recovery and preserves compact provenance before removal |
| `task check` | Python and C regressions, Bash syntax and ShellCheck |
| `task test:nkmp` | Compare original/patched clock searches natively and under ARM32 emulation; also runs before the kernel in `task build` |
| `task check:kernel` | Resolved Kconfig assertions and kernel artifact manifest |
| `task check:dt` | Binding and compiled device-tree validation in the pinned container |
| `task image:verify` | Repeat filesystem/content checks on the current bundled image |
| `task image:pack` | Compress the verified image and record raw/transfer checksums |
| `task image:checkpoint NAME=diagnostic7-before-usb-pm` | Verify the current raw/gzip image and retain its matching metadata before changing build identity; use a new name for each checkpoint |
| `task mac:stage-recovery NAME=diagnostic8-before-keypad-retention` | Verify and select a checkpoint's matching recovery archive on the Mac; no card write |

The base-rootfs cache ignores only image-version and kernel local-version
suffix changes. Builder, snapshots, package/APT hooks, configuration, wrapper
arguments and all other source-lock fields remain fingerprinted, and the
archive is hash-verified. Older cache records are rebuilt once. See
[the cache dependency contract](docs/130-rootfs-cache-identity.md).

Image assembly automatically runs offline verification and collects its image,
checksums, manifests, logs and package inventory in `.local/artifacts/`.
`verification.json` identifies the current bundle. `IMAGE='/path/to/image.img'`
can select an explicit image for verification; packing requires a match to the
current bundle's verified hash and size. The image contains private credentials
and firmware; do not publish it.

`image:checkpoint` saves the completed image's source lock, kernel/configuration,
patch queue, verification and transfer records under `.local/recovery/NAME/`.
It verifies both retained artifact hashes, refuses an existing checkpoint and
shares the build-stage lock so a running build cannot replace its inputs.
Raw/gzip files initially remain at their original paths. The saved retention
task can remove older raw copies after verifying their gzip expansion; retain
the gzip and checkpoint metadata together. This preserves recovery provenance
but does not change which image
the default packing/staging commands select.

`mac:stage-recovery NAME=...` rechecks the checkpoint metadata and compressed
hash. It verifies the raw copy when present, or streams and verifies the gzip
expansion when the raw copy has been pruned. A damaged present raw file still
fails verification. It then verifies compressed and decompressed hashes on the
Mac before selecting its transfer manifest. It reuses an existing Mac archive.
If absent, it stops; explicitly add `UPLOAD=1` on an appropriate network to
allow the large transfer. Current local build/transfer metadata remains intact.
Then identify the intended DEV card again with `mac:status` and
`mac:inspect DISK=diskN` before the normal preflight/flash/readback workflow.
Selecting a recovery archive alone does not change the running device.

Build-stage logs are `.local/build/kernel.log`, `prepare.log`, `devicetree.log`
and `image.log`. For example, use `tail -f .local/build/image.log` while building.
Older logs are retained under `.local/build/logs/`. A failed stage returns a
failure and prints the log tail. The wrappers reject overlapping build stages;
run build tasks sequentially on this memory-constrained host.

To reclaim superseded driver compiler trees, first preview the named
suite, then apply the reviewed selection:

```sh
task build:prune-driver-scratch SUITE=brcmfmac-pm-tests
task build:prune-driver-scratch SUITE=brcmfmac-pm-tests APPLY=1
```

Supported suites are `brcmfmac-pm-tests`, `brcmfmac-lifecycle-tests`,
`brcmfmac-irq-tests`, `brcmfmac-irq-worker-tests` and
`brcmfmac-lifecycle-worker-tests`. The task requires a completed normal/debug
`compile-evidence.json`, preserves both referenced trees and all parent evidence,
and holds the same lock as that suite's source/build tests. Missing evidence,
active tests, symlinks or unexpected scratch contents stop cleanup. Only older
`kernel-<16 hex digits>` source/output directories in the selected suite are
removed; recovery images, archived full kernels, downloads, provisioning and
diagnostic captures remain outside its scope. Each application saves an
incremental `prune-*.json` record alongside the retained suite evidence.

`usb-policy-tests` is also supported. Its single ARM build and any additional
references in saved `*evidence.json` files are retained; their object and
configuration hashes must verify before any deletion. Use `TARGET=/absolute/path`
to inspect a different checkout, applying the same target after reviewing its
preview. This lets the current saved tool maintain older compiler artifacts
without changing that checkout's source files.

Driver object checks now share one verified kernel source per patch queue within
each suite. Each configuration retains its own `kernel-<16 hex digits>/output`;
the source identity excludes the compiler, image version and configuration.
Docker mounts the shared source read-only and writes configuration merge
temporaries into the output directory. Source contents, owner executable bits and
symlink targets are checked on reuse. A changed archive or patch queue selects a
new source. This does not change full image/kernel builds.

To compact existing copies without losing their compiled objects or evidence:

```sh
task build:compact-driver-sources SUITE=musb-sleep-tests
task build:compact-driver-sources SUITE=musb-sleep-tests APPLY=1
```

Optional `TARGET=/absolute/path/to/worktree` selects another worktree of this
same repository. Supported suites are the five Wi-Fi suites above,
`musb-sleep-tests` and `cpuidle-s2idle-tests`. Preview may extract one verified
source into the selected suite's `.sources` cache (about 1.7 GiB of temporary
extra disk use for this kernel), but does not replace or delete legacy sources.
Leave that headroom available. The task requires the downloaded locked archive,
an idle suite, completed compiler evidence and matching object/configuration
hashes. Every selected source must match the freshly patched source, including
files left by `patch`; all selected trees are checked before any replacement.
The worktree's current archive and patch queue must still reproduce those
sources. If the checkout has advanced but the suite retains its original
`patches/manifest.json` and patch files, add `RECORDED_PATCHES=1` to both preview
and application. This explicitly replays that historical export against the
locked archive; it verifies every patch hash and still requires an exact match
to every selected source and the recorded compiled outputs. It does not apply
the old patches to the checkout or change its kernel build. For example:

```sh
task build:compact-driver-sources SUITE=brcmfmac-pm-tests RECORDED_PATCHES=1
task build:compact-driver-sources SUITE=brcmfmac-pm-tests RECORDED_PATCHES=1 APPLY=1
```

Unreferenced compiler trees are left alone. Historical compaction and the
diagnostic.21 disk-space recovery are recorded in
[report 188](docs/188-historical-driver-source-compaction.md).

`APPLY=1` replaces each matching source directory with a relative cache link.
It preserves outputs, configurations, logs and original evidence, and writes an
incremental `compact-*.json` audit with before/after evidence hashes and disk
space. If interrupted, rerun the same task with `APPLY=1`: its migration record
allows it to finish deleting only verified remnants. A changed remnant stops
cleanup for investigation. Object builds reject incomplete migrations. Suite
and cache locks reject concurrent compaction/build operations; older Wi-Fi
pruning removes superseded source links without deleting shared caches.
There is deliberately no automatic shared-cache eviction.
When extending an older candidate branch, bring forward `kernel_checks.py` and
`kernel_sources.py` together before adding new compiler configurations; an older
helper can still create full source copies for new scratch identities.

To prune older diagnostic images and full kernel snapshots, wait until the
entire build/pack/staging workflow finishes, then run:

```sh
task build:prune-retained KEEP=3         # Preview only
task build:prune-retained KEEP=3 APPLY=1
```

This keeps the newest three raw images and three timestamped kernel snapshots;
the currently verified raw image is always protected. `KEEP` must be at least
two. Every named recovery checkpoint and each candidate's full gzip expansion
must verify before deletion. All gzip images remain, and older kernel metadata
is copied and checksum-verified under `.local/retention/kernel-metadata/` before
its source/output/module trees are removed. The task holds the build-stage
lock, refuses unexpected paths/layouts, updates the artifact checksum catalog
and saves incremental `.local/retention/prune-*.json` records. It excludes
credentials, original-card backups, downloads, test captures and the current
kernel trees. See [report 92](docs/92-build-artifact-retention.md) for the policy,
recovery behavior and cleanup evidence. This task does not prune arbitrary
workspace temporary directories.

`test:nkmp` verifies (or downloads and verifies) the locked Linux archive, applies
the clock-search patch to a separate test copy, and compiles the actual old/new
functions. It compares the resulting rates and all selected factors at output
boundaries, neighboring requests, rounding gaps and the A33 CPU operating points.
The pinned builder supplies the ARM32 compiler and QEMU. Results and input hashes
are in `.local/build/nkmp-tests/`, with the task log in `.local/build/nkmp.log`.
These are correctness and search-work checks; emulation does not measure board
performance. Ordinary `task check` remains independent of Docker/downloads for
this test; run `test:nkmp` explicitly when working only on the clock patch.

For USB driver lifetime changes, use:

```sh
task test:usb-lifecycle # Actual-source host probe/IRQ/poll lifetime regression
task check:usb-driver   # Also cross-compile the complete driver in isolated scratch
```

Both verify the locked Linux archive (downloading it if missing) and retain
evidence in `.local/build/usb-lifecycle-tests/`. The negative control must
reproduce the original cleanup failure; the patched code must pass. The ARM
check uses the pinned Docker builder and its own source/output directory, so
it does not overwrite the current image's kernel artifacts. Normal `task build`
includes the lifetime regression; `task check` stays independent of this archive
and Docker. [Report 38](docs/38-usb-work-lifetime.md) explains coverage and limits.
After changing the patch queue, use the documented `task kernel:reset` before
the next full kernel build; isolated driver checks do not reset that workspace.

For AXP polling suspend/resume changes, use:

```sh
task test:usb-suspend          # Actual PM/IRQ callbacks, native + ARM32
task check:usb-suspend-driver  # Also compile the full ARM driver in isolated scratch
```

These cover worker quiescence, IRQ/requeue arrivals, repeated cycles and wake
setup/teardown errors. Evidence is in `.local/build/usb-suspend-tests/`.
`task build` includes the source regression. The change is installed in
diagnostic.8 and passed ordinary PM debug stages in report 60.
[Report 56](docs/56-usb-suspend-work.md) records the source checks and remaining
notification-work qualification before deeper PM tests.

For the Sun4i USB PHY detection worker's suspend lifecycle, use:

```sh
task test:usb-phy-suspend # Actual scan/IRQ/notifier/PM functions, native + ARM32
task check:usb-phy-driver # Also compile the complete ARM PHY driver in isolated scratch
```

The regression checks pending/running work, requeue attempts, repeated cycles,
resume cable-state reconciliation and scans of an exited PHY. Evidence is in
`.local/build/usb-phy-suspend-tests/`; `task build` includes the source regression.
[Report 69](docs/69-usb-phy-suspend-work.md) records patch 0012's source/ARM
validation. It is not installed in diagnostic.10. The
[PMIC ordering audit](docs/68-pmic-suspend-ordering-audit.md) identifies the
remaining power-supply notification and wake-policy gates before deeper sleep
tests. Use `task kernel:reset` before the next full build with the changed queue.

For power-supply notification freeze/replay, use:

```sh
task test:power-supply-suspend # Actual producer/worker, native + ARM32
task check:power-supply-driver # Also compile the full ARM power-supply core
```

The regression checks freeze-boundary arrivals, notification coalescing,
concurrent changes, wake holds, abort/thaw replay and repeated cycles.
`task build` includes it; evidence is saved under
`.local/build/power-supply-suspend-tests/`.
[Report 71](docs/71-power-supply-notification-freeze.md) explains patch 0013's
use of the kernel freezer and the remaining hardware/wake-policy qualification.
Both freezer options are required by the diagnostic configuration checks.

The integrated AXP223 gauge-status correction has saved host-only checks:

```sh
task test:axp223-gauge-status   # Actual MFD/regmap paths, native and ARM32
task check:axp223-gauge-driver  # Also compile the complete ARM MFD driver
```

They exercise live status, cache behavior and read failures without connecting
to a device. [Report 186](docs/186-axp223-gauge-status-candidate.md) records the
AXP223-only correction and validation limits. Diagnostic.21 includes it with
updated inventory admission; build and installation progress are recorded in
[report 187](docs/187-diagnostic21-gauge-integration.md). This is not an ADC or
battery-calibration fix.

The candidate ADC width correction has its own saved checks:

```sh
task test:axp-adc-width     # Actual helper/callers, exhaustive bytes, native + ARM32
task check:axp-adc-drivers # Also compile ARM ADC/USB users and no-IIO USB fallback
```

These preserve valid 9–16-bit readings and test unused low-byte bits, register
order and read failures. `task build` includes the regression task. Evidence
is saved under `.local/build/axp-adc-width-tests/`;
[report 192](docs/192-axp-adc-width-correction.md) records patch 0036's scope.
It is not installed in diagnostic.21 and does not establish ADC coherence,
calibration or a cause for the earlier voltage discrepancy.

For the separate deferred-registration/unregister lifetime audit, use
`task test:power-supply-lifetime`. It reproduces the original cancellation
order and a test-only reordered comparison using actual core functions on
native and ARM32 builds. Evidence is saved under
`.local/build/power-supply-lifetime-tests/`.
[Report 157](docs/157-power-supply-unregister-lifetime.md) explains the late
notification race, why ordinary AXP cleanup excludes it, and the independent
producers that must be stopped before unregister. This task changes neither
the production patch queue nor the installed image.

For the brcmfmac Wi-Fi sleep and clock error paths, use:

```sh
task test:brcmfmac-sleep   # Actual C helpers, scripted failures, native + ARM32
task check:brcmfmac-driver # Also compile the complete ARM SDIO object in isolated scratch
```

These check KSO timeout/error reporting, clock transitions, sleep prechecks,
state publication and retune cleanup. The original successful transfer/delay
sequence is compared with the candidate, and deliberately broken variants must
fail. Evidence is saved under `.local/build/brcmfmac-sleep-tests/`; `task build`
includes the source regression. [Report 81](docs/81-brcmfmac-sleep-error-propagation.md)
records the scope and results. This does not qualify real sleep or implement
the freezer transaction and failed-wake recovery work in
[report 80](docs/80-brcmfmac-suspend-failure-audit.md).

For Wi-Fi worker collection, timeout cleanup and repeated suspend attempts:

```sh
task test:brcmfmac-freezer          # Actual C workers/callbacks, concurrent native + ARM32 tests
task check:brcmfmac-freezer-drivers # Also compile both complete changed ARM driver objects
```

These check late workers, timeout/thaw, completion reuse, participant withdrawal,
watchdog exit accounting and successful resume ordering. The collector has a
five-second wait budget; workers still retiring from a previous thaw make a new
attempt return `-EBUSY`. `task build` includes this source regression. Evidence
is in `.local/build/brcmfmac-freezer-tests/`.
[Report 82](docs/82-brcmfmac-freezer-lifecycle.md) records patch 0015 and its
limits: hardware sleep/wake failure recovery and image qualification remain
separate work. Neither task accesses the GameShell or rebuilds its image.

For checked Wi-Fi PM transitions, rollback and failed-wake isolation:

```sh
task test:brcmfmac-pm          # Actual callbacks, workers, IRQs, control paths and I/O guards
task check:brcmfmac-pm-drivers # Also compile the full ARM driver, normal + CONFIG_BRCMDBG=y
```

These inject sleep/wake, IRQ-wake and host-flag failures and exercise late
workers and control requests. They verify that an unrecoverable restore reports
Wi-Fi unavailable and blocks further firmware I/O. The current recovery policy
for that exceptional case is a cold restart; automatic radio reset remains
separate work. Evidence is in `.local/build/brcmfmac-pm-tests/`; `task build`
includes the regression. [Report 83](docs/83-brcmfmac-pm-rollback.md) explains
the source validation, recovery limits and remaining hardware gates. The debug
build is isolated and does not change the image's kernel configuration.

For suspend/reset/removal ordering and interrupts arriving while Wi-Fi sleeps:

```sh
task test:brcmfmac-lifecycle
task check:brcmfmac-lifecycle-drivers # Also compile normal/debug ARM drivers
```

These rerun the PM regressions against patch 0017 and exercise competing device
callbacks, reset rejection, removal of parked workers and deferred interrupt
status reads. Evidence is saved in `.local/build/brcmfmac-lifecycle-tests/`.
`task build` includes the regression. [Report 84](docs/84-brcmfmac-pm-lifecycle.md)
records the lock ordering and qualification limits; these tasks do not access
the device or change its image.

For deferred interrupt consumption through the actual status reader and packet
worker, use `task test:brcmfmac-irq`. It runs native/ARM32 scenarios and negative
controls, with evidence in `.local/build/brcmfmac-irq-tests/`, and is included in
`task build`. [Report 88](docs/88-wifi-deferred-interrupt-service.md) distinguishes
successful service from existing wake/read/acknowledgement error limitations.
It uses modeled hardware and scheduling; it does not measure live IRQ rates.

The follow-up worker fix is tested with:

```sh
task test:brcmfmac-worker          # Faults, clock waits and concurrent control completion
task check:brcmfmac-worker-drivers # Also compile complete normal/debug ARM drivers
```

This adds patch 0018 to the source tests and is included in `task build`.
[Report 89](docs/89-wifi-worker-error-handling.md) explains the checked errors,
IRQ cleanup and cold-restart failure policy.
Diagnostic.13 is installed; [report 91](docs/91-diagnostic13-preparation.md)
records preparation and [report 93](docs/93-diagnostic13-installation.md) records
the running baseline. Source-test evidence is under
`.local/build/brcmfmac-{irq,lifecycle}-worker-tests/`.

Country-request ordering across suspend has saved checks:

```sh
task test:brcmfmac-regulatory         # Actual callbacks, deferred requests and error paths
task check:brcmfmac-regulatory-driver # Also compile the complete patched ARM cfg80211 object
```

`task build` includes the regression. Evidence is saved under
`.local/build/brcmfmac-regulatory-tests/`.
[Report 106](docs/106-brcmfmac-regulatory-suspend.md) describes patch 0020,
RTNL ownership, deferred-update failures and the pending hardware checks.
These tasks do not access the GameShell or replace its running modules.

Transmit admission across suspend also has saved checks:

```sh
task test:brcmfmac-tx-suspend         # Queue ownership and concurrent transmit drain
task check:brcmfmac-tx-suspend-driver # Also compile complete ARM core/cfg80211 objects
```

`task build` includes this regression. [Report 109](docs/109-wifi-transmit-suspend-ownership.md)
records patch 0021, its lock ordering, failed-resume behavior and source-test
limits. Evidence is under `.local/build/brcmfmac-tx-suspend-tests/`.
The source candidate is not installed in diagnostic.15.

Band-capability query failures have a separate saved regression:

```sh
task test:brcmfmac-band-queries
task check:brcmfmac-band-query-driver
```

[Report 110](docs/110-wifi-band-query-errors.md) records patch 0022's required
read checks, optional firmware-rejection defaults, transport errors and remaining
channel-transaction limits. `task build` includes the test; private evidence is
under `.local/build/brcmfmac-band-query-tests/`. This candidate is not installed.

Wake-reference ownership and parent-error propagation have saved checks:

```sh
task test:wake-irqs       # Actual IRQ-core/client functions, native + ARM32 failures
task check:wake-drivers   # Also compile all four complete ARM drivers
```

[Report 100](docs/100-wake-irq-error-ownership.md) records patch 0019's scope,
locking constraints and offline evidence. Hardware wake remains unqualified.

For the Sunxi MUSB context capability fix, use:

```sh
task test:musb-context  # Compare actual old/new register operations, native + ARM32
task check:musb-drivers # Also compile the complete MUSB core and Sunxi ARM objects
```

Evidence is in `.local/build/musb-context-tests/`; `task build` includes the
source regression. [Report 57](docs/57-musb-context-capability.md) records the
unsupported-register correction; report 60 records seven diagnostic.8 driver
cycles with zero unsupported-register warnings.

For accurate USB endpoint trace return values, use:

```sh
task test:udc-trace     # Execute the actual format, native + ARM32; reject old/wrong formats
task check:udc-driver  # Also compile the complete ARM USB device-controller core
```

`task build` includes the source check. [Report 127](docs/127-usb-endpoint-trace-format.md)
records the formatter correction and pending image qualification. USB captures
now label whether endpoint return text is trustworthy; diagnostic.17's trailing
endpoint arrow values must not be treated as operation results.

For the USB connection lifecycle across system sleep, use:

```sh
task test:musb-sleep          # Actual PM/pull-up functions, native + ARM32, failure controls
task check:musb-sleep-drivers # Also compile the complete ARM MUSB core/gadget/Sunxi glue
```

`task build` includes the source regression. The diagnostic.18 candidate removes
the peripheral pull-up before system sleep and restores the latest connection
request after the controller is ready. Startup explicitly disables USB system
wake; PM admission verifies that policy. This does not alter charging or resolve
the driver's separate probe-time IRQ-wake ownership. Normal user sleep remains
disabled pending hardware qualification. See [design](docs/126-musb-system-sleep-design.md)
and [implementation](docs/128-musb-system-sleep-candidate.md).

For the separate teardown audit, check out
[work/musb-teardown-audit](https://github.com/michaelishri/GameShellNeo/tree/work/musb-teardown-audit)
and run `task test:musb-teardown-audit`. The task executes extracted stop/remove,
endpoint and Sunxi functions natively and under ARM32, recording hashes and
results in `.local/build/musb-teardown-tests/evidence.json`. A pass reproduces
the expected source-order defects and diagnostic control effects; it does not
qualify safe removal. The task introduces no driver patch and is not an image
build gate. [Report 139](docs/139-musb-teardown-power-audit.md) documents the
coverage, modeled boundaries and follow-on implementation requirements.

For the opt-in USB polling experiment, use:

```sh
task test:usb-policy          # Actual gates, callbacks/probe, errors and races; native + ARM32
task check:usb-policy-driver  # Also compile the full ARM driver in isolated scratch
task test:usb-policy-board    # Run the gate against the compiled DTB; accepts DTB=path
```

`task build` includes the policy regression and checks the completed DTB before
image assembly. Evidence is in `.local/build/usb-policy-tests/`. These checks
use deterministic OF/register/workqueue shims; hardware testing is separate.
[Report 41](docs/41-usb-polling-experiment.md) records the experiment and limits.

For fixed-parent clock rate-constraint changes, use:

```sh
task test:clock-ranges   # Actual NM/NKM searches and constraints, native + ARM32
task check:clock-drivers # Also compile complete clock objects in isolated scratch
```

These verify the locked Linux archive and compare original/patched rates,
selected factors, constraints and getter counts. Results and hashes are in
`.local/build/clock-range-tests/`; logs use `clock-ranges.log` or
`clock-drivers.log` under `.local/build/`. Both need the pinned builder for the
ARM32 checks; the compile task preserves the current image's kernel artifacts.
Normal `task build` includes the equivalence check. [Report 39](docs/39-clock-rate-constraint-optimization.md)
records the results and hardware validation still required.

### Routine device work

```sh
task device:status
task device:logs
task device:exec -- uname -r
task device:status ROUTE=usb
task device:logs ROUTE=usb
task device:check ROUTE=usb
task device:backlight ROUTE=usb # Watch the screen during this test
task device:usb-reconnects CYCLES=4 # Wait for ready, then operate the USB cable
task device:usb-rapid CYCLES=4 # Immediate unplug/replug, then stay connected 30 seconds
task device:usb-detect CYCLES=0 SECONDS=8 # Unplugged smoke capture; no cable actions
task device:usb-detect CYCLES=4 # Start unplugged; detailed IRQ/events over Wi-Fi
task device:stability ROUTE=usb # Keep the board connected throughout
task device:qualify-awake-plan # Show the unattended sequence without connecting
task device:qualify-awake ACTIVE_COUNTRY=AU # Whole awake sequence; USB connected, Mac awake, Wi-Fi available
task report:awake CAPTURE='.local/diagnostics/awake-<timestamp>' # Read progress/report; never resumes tests
task device:battery-check ROUTE=wifi # Isolated simulation; no real power-off or charger writes
task device:wifi-config             # Apply .env Wi-Fi over USB and verify Wi-Fi SSH; no reflash
task device:wifi-visibility         # Cached target visibility; no network names in output
task mac:wifi                      # Mac Wi-Fi band/security; names may be redacted by macOS
task device:wifi-scan-test SECONDS=120 # USB-only firmware/host/firmware scan comparison; restores flag
task device:wifi-firmware-test SECONDS=120 # USB-only pinned A0 binary trial; always restores original
task device:wifi-firmware-connected SECONDS=120 # Four reconnections and Wi-Fi SSH on candidate/original
task device:wifi-recovery SECONDS=120 # Installed firmware: four reconnections, unavailable/connected windows
task device:rsb-compare SECONDS=120 DELAY_MS=100 # USB-powered bus-delay comparison
task device:rsb-restore # Stop/recover an interrupted RSB comparison
task device:pm-inspect # Read-only capabilities, counters and device links over USB
task device:charge-inspect # Read-only documented charger/gauge inventory; USB remains connected
task device:charge-baseline SECONDS=120 # Two-minute awake charging trace; USB stays connected
task device:pm-test STAGE=freezer # Diagnostic.7 only, owner present; one debug cycle
task device:pm-test STAGE=devices CYCLES=1 # Only after the freezer test passes
task device:wifi-trace-smoke # One awake reconnect; verify metadata recorder and restoration first
task device:pm-test STAGE=devices CYCLES=1 WIFI_TRACE=1 # Owner ready; trace intermittent Wi-Fi recovery
task device:pm-collect RUN=<32-character-run-id> # Recover saved evidence after SSH loss
task device:pm-restore # Stop a test and restore its owned debug controls
task device:idle-sample ROUTE=wifi SECONDS=600 # USB unplugged; leave controls alone for 11 minutes
task device:idle-sample ROUTE=wifi SECONDS=600 BACKLIGHT=off # Compare with backlight off, then restore
task device:power-profile ROUTE=wifi SECONDS=120 # Read CPU/interrupt/radio counters; keep settings unchanged
task device:usb-idle-compare          # Three battery comparison phases and two automatic reboots (~45 minutes)
task device:governor-compare ROUTE=wifi SECONDS=120 RATE_US=10000 # Three phases; automatically restore
task build:perf # Optional diagnostic tool from the locked source/container; no image rebuild
task device:governor-profile ROUTE=wifi SECONDS=30 # Separate kernel-function sample; USB unplugged
task device:boot-cycles CYCLES=4 # Wait for ready, then operate the power button
task device:boot-cycles CYCLES=0 # Capture/check this boot without starting a batch
task device:reboot ROUTE=usb # Three speaker warning tones, verified audio restoration, then one reboot
task device:exec ROUTE=usb -- systemctl --failed --no-pager
```

The general remote-task default route is Wi-Fi; audio and `device:reboot` default
to USB and accept `ROUTE=wifi`. `ROUTE=usb` tunnels through Mac SSH to the board's
USB address, so the Intel host needs no route to that USB subnet. Status and
diagnostic archives are retained privately in `.local/diagnostics/<timestamp>/`.
`device:exec` runs the explicitly supplied command and returns its failure
status. Shell operators require an explicit `sh -c '...'` command.

`device:backlight` runs a roughly 40-second visual check on an unblanked panel.
It prints a ten-second countdown and stage labels on the GameShell's `tty1`
console: brightness 1, 16 and 31 for four seconds each, followed by three
cycles of 0 (off) and 31 (on), held for two seconds each. Each dark interval
has a two-second on-screen notice first. The labels include requested levels
and software readbacks. It leaves the existing login session running; press
Enter afterward to redisplay the login prompt if needed.
It saves the initial brightness and restores it on completion or handled
termination signals. A temporary systemd service bounds the run to 60 seconds
and refuses a concurrent run under the same unit name. It changes brightness
through the normal sysfs interface; it does not suspend or reboot the board.
Requested values and software readbacks are captured in a private
`backlight.txt`. The person watching must confirm visible levels, darkness and
recovery: successful sysfs readbacks alone do not establish those results.

`device:usb-reconnects CYCLES=4` uses USB SSH through the Mac. A temporary
device service records USB state changes while the cable is disconnected;
it does not depend on GameShell Wi-Fi. It checks the initial connection,
then prints `ready`.
For each cycle, unplug USB for three seconds, reconnect it, and leave it
connected for at least 30 seconds. Keep the board running on its battery.
The device recorder must see `not attached` followed by `configured`, and a
fresh SSH connection through the Mac must reach the same boot at the USB
address before a cycle counts. Initial attachment is not a cycle. The task
records state changes and successful cycles privately as `usb-reconnects.jsonl`
with a `summary.json` and `device-states.jsonl`; interruption or timeout
preserves partial results. If multiple removals occurred before SSH was checked,
the task fails instead of counting unchecked cycles. The recorder is stopped
and its temporary files removed on completion. If USB is unavailable for
cleanup, its runtime is bounded to the test timeout plus one minute and the
private capture prints the retained device path.
Use batches of four, four and two for ten cycles. The default overall wait is
ten minutes; `CYCLES` accepts 1–10. This task always uses USB and ignores `ROUTE`.
It does not qualify idle power while a temporary recorder is running.

`device:usb-rapid CYCLES=4` uses the same checks and cleanup with nominal
20 ms controller-state sampling instead of the normal 250 ms interval. Start
connected and wait for `ready`. For each cycle, unplug and promptly reinsert
the GameShell's USB cable without a deliberate pause, then keep it connected
for at least 30 seconds. Finish connected. The recorder must still observe
`not attached` followed by `configured`, and USB SSH must reach the same boot
before a cycle counts. A missed observation is not silently counted as a pass.
Both modes share a lock and temporary service, so they cannot run together.
The summary records the mode/interval and events include monotonic observation
times. Sampling can be delayed, and manual cable motion has no measured edge
timestamp: this checks recovery from quick manual reconnection, not a precise
minimum disconnect duration or detection-latency guarantee. Keep power
measurements separate from either recorder.

`device:usb-detect CYCLES=4` is the detailed CPI v3.1 diagnostic, using Wi-Fi
for control and the Mac's USB route for a separate SSH check on each attachment.
Start with USB **unplugged**, the board running and battery monitoring valid
above 20%. Wait for `ready`, then repeat four times: connect USB for 20 seconds,
disconnect it for 10 seconds. Finish unplugged. Each cycle requires USB SSH on
the same boot followed by a stable disconnected observation; an unchecked or
overlapping cycle fails. `CYCLES=0 SECONDS=8` checks the recorder without cable
actions. This task always uses Wi-Fi for control and ignores `ROUTE`.

The temporary on-device recorder samples cached controller/OTG/extcon state
and PMIC IRQ counters every nominal 20 ms. It also receives kernel power-supply
uevents and reads supply properties about once a second or when sampled state
changes. It records monotonic read windows, gaps, CPU overhead and separate
Mac/USB SSH checks. These are software observation times: there is no physical
cable-edge timestamp, and 20 ms scheduling is not guaranteed. A successful test
does **not** certify the 100 ms hardware detection deadline or measure energy.
The fast sampler adds substantial observer work; use it only for bounded
detection tests, never concurrently with idle-power measurements.

At startup it reads only PMIC registers `00`, `30`, `40` and `8f` through the
locked debugfs layout, plus live DT/regulator configuration. Control values
`30`/`8f` may be cached; these are not independent pin-voltage measurements.
No IRQ-status registers or hardware settings are written. Trace sequence/boot
changes, counter resets, malformed data, netlink truncation/receive errors and
missing completion fail the task. Captures remain private under `.local/diagnostics/`
as `device-trace.jsonl`, `usb-detection.jsonl` and `summary.json`.

`SECONDS` defaults to 600 (5–900 accepted); the recorder has its own duration
and a systemd runtime cap. The host fetches only newly appended trace bytes in
bounded SFTP reads and reconnects once after a stale Wi-Fi transport. Startup
mutations are not automatically replayed. It stops the recorder and removes
staged files after a clean capture. On failure, inspect the printed temporary
directory and captured journal if retained; the automatic runtime cap still
applies if Wi-Fi is lost. To stop a running recorder explicitly:

```sh
task device:exec ROUTE=wifi -- sudo -n systemctl stop gameshellneo-usb-detection.service
```

Local evidence is retained on failure; remote staged files remain when final
trace validation or cleanup cannot be verified. Failed runs are not reported
as successful results. [Report 35](docs/35-usb-detection-capture.md) records
preparation, hardware evidence and measurement limits.

[Report 36](docs/36-usb-polling-policy.md) defines the next experimental USB
polling policy: a slower fallback only for confirmed absence in this fixed
peripheral configuration, retaining interrupt notifications and fast checks
for uncertainty. It is implemented as an opt-in diagnostic.5 experiment in
[report 41](docs/41-usb-polling-experiment.md). Diagnostic.5 is now installed
for qualification; [report 44](docs/44-diagnostic5-hardware-validation.md)
records its live results. The diagnostic.4 recovery image uses the existing policy.

On diagnostic.5 and later, use these repeatable commands:

```sh
task device:usb-policy ROUTE=usb                     # Verify running and next-boot policy
task device:usb-policy ROUTE=wifi MODE=stock         # Select stock on the next boot
task device:usb-policy ROUTE=wifi MODE=experimental  # Select experimental on the next boot
```

Selection verifies the image and both prebuilt U-Boot variants, replaces the
executable script last, and verifies readback. It never reboots or changes the
running policy. Status checks both the read-only requested parameter and the
driver's acceptance/refusal message; a refused experiment fails the check.
Keep diagnostic.4 for full recovery. See report 41 for interruption limits and
the physical qualification sequence. A successful host test or build does not
establish USB detection latency or a battery improvement.

Diagnostic.6 also provides direct callback counts and bounded error tests:

```sh
task device:usb-counts ROUTE=usb SECONDS=60  # Connected-state count; no extra poll requested
task device:usb-errors ROUTE=usb ERRORS=1   # One isolated poll-read failure
task device:usb-errors ROUTE=usb ERRORS=4   # Maximum finite fault budget
task device:usb-diag-restore ROUTE=usb      # Stop/recover an interrupted diagnostic test
```

For **natural unplugged polling counts**, use `ROUTE=wifi`, leave USB unplugged
throughout, and repeat the same duration in stock and experimental boots.
Keep other diagnostic observers stopped; the task rejects known active test
services. These are count measurements, not battery-power tests. Enabling
counting and reading snapshots never schedules a poll. An online count can
legitimately be zero.

The error task explicitly requests synthetic work, skips only the poll
callback's status read and returns `-EIO` at most four times. Any unused budget
expires after one second. It checks retained status, the policy's retry
selection and automatic real-read recovery where that policy requests it.
Stock online polling can stop after the first failure until another IRQ;
the report distinguishes this from experimental recovery. Keep USB and the
power state unchanged during this test. It does not simulate electrical bus
faults or prove physical cable-IRQ recovery.

Both tasks run in a bounded device-side systemd service, save before/after
snapshots and boot/kernel/policy identity under `.local/diagnostics/`, and
restore counting to off on exit. A device-side exit hook remains responsible
for restoration if the host connection disappears. Failed runs retain the
helper and evidence; use the restore task if needed. Diagnostics are exposed
only with the independent boot opt-in; both prebuilt policy variants enable
the interface, while counting remains off until explicitly requested.

`task prepare` now retrieves the exact hash-pinned upstream firmware and its
license on the Intel host. It still takes the board-specific NVRAM from the
private radio reference, verifies its original hash and preserves its bytes.
The image records both sources and contains the matching upstream license.
The earlier reversible firmware-trial tasks target diagnostic.5's original
firmware and deliberately refuse an unexpected installed binary; use the new
image qualification sequence in report 51 after flashing diagnostic.6.

`task device:usb-idle-compare` runs the saved experimental/stock/experimental
comparison over Wi-Fi, including two software reboots. Start with experimental
polling active, USB unplugged, brightness 1, the normal schedutil settings and
Wi-Fi power saving off. Keep the Mac awake, the hotspot available and the device
stationary with controls untouched for about 45 minutes. Run no concurrent device
diagnostics. Connection details come from `.env`; the configured Wi-Fi route
through the Mac is supported.

Each phase gets five minutes to settle, a five-minute battery sample and a
two-minute counter profile; each measurement also has its own settling period.
The task checks the actual running policy, new boot identity and matched settings
before accepting a phase. After a reboot it restores Wi-Fi power saving to the
baseline `off` setting before cooling, if the driver default changed it to `on`;
any other configuration mismatch fails. It stops if firmware crashes or SDIO removal events
occur during a measurement. A successful run leaves experimental polling active
and selected for the next boot. A failed run stops the sequence and retains its
partial evidence; inspect the last policy before resuming. It does not reboot to
roll back after a failure.

The printed private directory contains `comparison.json` and phase logs with
links to each raw capture. To count an already observed cooling period, pass
`COOLING_STARTED=<ISO-8601 timestamp with timezone>`; otherwise five minutes are
always allowed initially. Only completed phases count as results. See
[the comparison protocol and evidence](docs/45-usb-polling-idle-comparison.md)
for measurement limits.

After a successful run, generate the comparison table entirely from its saved
captures, without contacting the device:

```sh
task report:usb-idle CAPTURE=.local/diagnostics/COMPARISON_DIRECTORY
```

This saves `summary.json` and `summary.md` beside `comparison.json`. It rejects
partial comparisons and raw captures that do not match the accepted phases.
It reports both experimental windows separately so drift remains visible.

If the wrapper stops **between completed phases**, keep USB unplugged and the
device stationary. Within thirty minutes of the last profile starting, continue
with `task device:usb-idle-compare RESUME=.local/diagnostics/COMPARISON_DIRECTORY`.
It validates the saved captures and current settings, preserves earlier logs and
the pre-resume record, and gives the next phase a fresh settling period. It
cannot resume an incomplete measurement or bypass a mismatched policy.

To explicitly **discard and repeat** an incomplete final phase, add
`RETRY_INCOMPLETE=1` to that resume command. The interrupted phase is preserved
under `discarded_phases`, its logs and original report remain available, and the
replacement starts after fresh settling. This never joins partial samples into
a complete measurement. Resolve the interruption first and keep the same
physical setup; the thirty-minute continuation limit still applies.

`task device:qualify-awake` runs the saved unattended awake qualification on
the current locked suspend-diagnostic image with retained keypad supply and
speaker audio. Keep USB connected, the Mac awake, the configured Wi-Fi network
available and controls untouched; do not run other diagnostic/configuration
commands concurrently. Connection credentials remain in `.env`. Use
`ACTIVE_COUNTRY=AU` for this board's accepted AP announcement; omit the override
when the active country matches `GAMESHELL_WIFI_COUNTRY`.

The guard checks ownership of the persistent PM experiment lock with a
nonblocking `flock`; an unlocked inode left by a completed RTC/key check is
normal. A held lock, an invalid lock path, another diagnostic service or any
recovery record still stops qualification. Never delete a lock file to bypass
this check. This is a preflight snapshot, not exclusive ownership for the
whole sequence; the prohibition on concurrent diagnostics still applies.

The fixed sequence checks the current boot and both SSH routes, saves read-only
PM/keypad/audio baselines, runs installed-firmware recovery with four software
reconnections and two 120-second windows, verifies restoration, then runs the
storage/load, simulated battery-policy and integration checks. Final snapshots
must retain the same boot, firmware, configuration, charging/CPU/display policy,
PM counters, keypad identity and idle mixer state. This command never enters a
PM stage, plays a tone, requests physical input, reboots or replaces firmware.
It takes approximately 12–15 minutes under normal conditions. Inherited
`ROUTE`, `CYCLES` and `SECONDS` cannot change its fixed USB control route,
zero physical boot cycles or observation windows.

`device:qualify-awake-plan` lists the exact commands and host deadlines without
connecting. Each run creates one private `.local/diagnostics/awake-<timestamp>/`
folder with atomically saved `progress.json`, `report.md`, source hashes and
per-step controller logs/raw evidence. Progress is written before starting each
step. `task report:awake CAPTURE=<that-folder>` reads it without connecting or
resuming anything; a saved `running` state remains incomplete if the host died.
There is no automatic retry or resume. Old evidence cannot satisfy a new step.

The first failure stops the sequence and marks later steps skipped. Child
controllers have wall-clock deadlines; interruption first allows their existing
cleanup hooks to run, then kills an unresponsive controller after a bounded
grace period. The Wi-Fi trial's device-owned service and `ExecStopPost` remain
responsible for network restoration even if the host disappears. The load
service also has its own runtime limit. Losing the host does **not** prove
cleanup succeeded: failed/interrupted runs report restoration as unverified.
Inspect the retained logs and recovery records before starting another test;
follow the `device:wifi-recovery` recovery instructions below when applicable.
The initial/final guard refuses other active diagnostic services or leftover
ownership records and never deletes them. Source changes during a run also
stop it. A local lock excludes a second copy of this workflow; it is not a
global lock shared by every legacy diagnostic command.

A pass qualifies this bounded awake sequence only. Sleep/wake, physical
buttons/cables, visual/audio quality, battery endurance, charge calibration and
energy savings still need their own evidence. See [report 95](docs/95-awake-qualification-workflow.md).

`device:stability ROUTE=usb` writes a new temporary 128 MiB random file, flushes
it to storage and checks its SHA-256 with a direct read that bypasses the file
data cache. It then runs five minutes of `stress-ng` with four CPU workers,
one 256 MiB memory worker and verification enabled. It records temperature,
CPU frequency and kernel taint, stops if the sampled temperature reaches
80 °C or USB disconnects, and removes its temporary files. It requires at
least 512 MiB of available memory and free filesystem space before starting.
A transient service runs at reduced scheduling priority with a seven-minute
limit. Results are private `stability.jsonl`; collect `device:status` and
`device:logs` afterwards to inspect services and kernel messages. This bounded
check does not qualify long-term endurance or idle power consumption.

To change Wi-Fi, update `GAMESHELL_WIFI_SSID`, `GAMESHELL_WIFI_PSK` and the
confirmed `GAMESHELL_WIFI_COUNTRY` in `.env`. Keep USB connected and the Mac
awake. For remote work, put the Mac on the same new network and retain its
tailnet endpoint plus `GAMESHELL_WIFI_VIA_MAC=1`. Run `task device:wifi-config`.
The task always uses USB for the change, refreshes private build provisioning,
and verifies Wi-Fi SSH against the provisioned host key, same boot and new
Wi-Fi address before committing. It updates only `GAMESHELL_IP` in `.env`.
If a worktree's `.env` links to the shared file, the update preserves that link
and atomically replaces its target; later credential edits remain shared.
No image rebuild or reboot is needed; the Wi-Fi service restarts.

Credentials travel by SFTP in a private directory, not in command arguments or
logs. A bounded device service preserves the previous config and restores it
unless the host verifies the new route within two minutes. Its `ExecStopPost`
also runs restoration on service termination. This needs a functioning
kernel/systemd; it cannot undo sudden power loss. If SSH disappears or cleanup
fails, retain the printed private evidence and device transaction directory;
reconnect over USB and verify restoration before removing it. An unavailable
previous access point may still prevent association after a correct rollback.
Host tests cover commit, deadline, stale-address rejection, interrupted-state
restoration and `.env` preservation; these are not physical power-loss tests.

`device:wifi-scan-test SECONDS=120` investigates firmware resets while scanning.
Keep USB attached; the task always controls the device through USB and takes
roughly seven minutes. It requires `disable_scan_offload=0`, then compares that
setting with `1` and finally `0` again. These are runtime supplicant settings;
credentials, radio firmware and persistent configuration stay unchanged.
Each phase has ten seconds settling, followed by `SECONDS` of nominal
ten-second samples (multiples of ten in 60–180). Private output records the
flag, supplicant state, interface recreation and firmware/SDIO event counts,
without SSIDs, BSSIDs or keys. This is a functional diagnostic, not a power test.

The bounded service and its independent `ExecStopPost` restore the saved flag.
If interrupted, retain the printed helper directory and private evidence until
restoration is confirmed. `task device:wifi-scan-restore` first stops a running
comparison and its exit hook, then restores any remaining record through USB.
A temporarily rejected reassociation during radio recovery
is distinct from setting readback; both are recorded where applicable.
[Report 46](docs/46-wifi-transition-and-scan-recovery.md) records observed
failures and qualification status.

`device:wifi-firmware-test SECONDS=120` fetches the exact A0 candidate and its
license from [the pinned manifest](build/wifi-firmware-candidate.json), verifies
their hashes, and runs a bounded USB-only trial. It requires the original
firmware and GameShell NVRAM hashes, CPI v3.1 image identity, normal scan policy
and a configured USB link. It stops the supplicant, reloads the radio modules
with the candidate, checks a **new** firmware-identification message, and records
scan state plus firmware/SDIO events. Board NVRAM and Wi-Fi credentials are
preserved. `SECONDS` accepts multiples of ten in 60–300.

The task always restores the original binary, file mode and loaded version;
it does not adopt the candidate or update image provenance. Restoration also
runs through `ExecStopPost` on termination. Leave USB connected, do not reboot
or run another radio test concurrently, and retain the printed helper directory
on failure. Recovery state lives in `/run/gameshellneo-firmware-trial`; do not
remove it before checking restoration. This needs a functioning kernel/systemd
and is not sudden-power-loss recovery. A completed trial includes successful
restoration; its event counts and network behavior determine whether the
candidate helped. [Report 47](docs/47-wifi-firmware-options.md) explains candidate
provenance and why Pi A1/B0 firmware is not interchangeable.
[Report 48](docs/48-a0-firmware-trials.md) records actual trials and their limits.

For the separate **network-transition** trial, first complete the unchanged-profile
120-second scan trial above. Then run `task device:wifi-firmware-test SECONDS=300`
in one terminal. After its `candidate_loaded` event, run `task device:wifi-config`
in a second terminal, with the Mac already on the intended network. This is the
one intentional concurrent operation: it tests the new credentials on the
candidate, with its own independent verification/rollback. A committed network
configuration remains when the firmware trial restores the original binary.
Keep the two captures together and recheck Wi-Fi afterward; the firmware task's
completion alone does not establish successful association. Do not count this
mixed connected/disconnected workload as another offline-scan comparison.

Once the GameShell and Mac can communicate over a compatible network, run
`task device:wifi-firmware-connected SECONDS=120`. Keep USB connected, the Mac
awake and the hotspot/AP enabled. This requires the same original-firmware,
board-data, scan-policy and USB gates as the ordinary trial. It verifies a
fresh Wi-Fi SSH connection on the original firmware, loads the candidate,
verifies candidate Wi-Fi, then performs four software disconnect/reconnect
cycles. Each cycle must observe `DISCONNECTED` before reconnecting and verify
`COMPLETED` plus an IPv4 address. Every checkpoint requires a fresh independent
Wi-Fi SSH session through the configured route, with the pinned host key,
same boot and correct endpoint. USB supplies control and acknowledgements.

After the cycles, the task observes `SECONDS` of connected operation, restores
the original firmware, and requires original-firmware Wi-Fi SSH again. The
seven checkpoints use fresh tokens to reject stale acknowledgements. Private
`firmware-trial.jsonl` and `wifi-ssh.jsonl` preserve device and host evidence.
Any crash/SDIO removal during candidate loading or the connected test fails
this mode; the original observation-only task still reports such events as
data. Credentials/NVRAM stay unchanged. On host verification failure, the
controller stops the service and invokes its recovery helper; the bounded
device service also restores independently if the host disappears. Retain a
failed helper until restoration is verified.

This tests software reconnection to an available AP. It does not simulate an
AP disappearing, cold startup, sleep/resume or battery operation, and leaves
the original firmware installed. Checkpoint times include polling, DHCP and
host SSH verification; they are not precise radio reassociation latency.

For the A0 firmware already installed in diagnostic.6, use
`task device:wifi-recovery SECONDS=120`. Keep USB connected, the Mac awake and
the usual Wi-Fi network available. The task requires the source lock's exact
image/kernel, firmware and NVRAM hashes, one connected network profile, normal
scan offload and a clean single firmware load. It performs four software
disconnect/reconnect cycles, scans for a randomly generated unavailable test
network for `SECONDS`, restores the persistent network configuration, then
observes `SECONDS` connected. Seven checkpoints require independent pinned-key
Wi-Fi SSH on the same boot. No firmware file/module reload, persistent network
edit or router change is performed. `SECONDS` accepts multiples of ten in
60–300; the default is 120 for each observation window.

The temporary credential-free profile exists only in supplicant memory.
Restoration reloads the unchanged persistent configuration, requires association
to the original network with only its profile remaining, and verifies the
scan policy. A recovery record in `/run/gameshellneo-wifi-recovery` is retained
until this succeeds. The bounded device service invokes the same idempotent
restoration through `ExecStopPost`, independently of the host. Do not run other
radio/configuration tasks concurrently. On failure, retain the printed helper
directory and recovery record; the host attempts restoration before reporting
failure. If needed after reconnecting USB, stop `gameshellneo-firmware-trial`
and run its retained helper with `--installed --restore` through `device:exec`.
This recovery assumes a functioning kernel/systemd and an available original AP.

The private `firmware-trial.jsonl`, `wifi-ssh.jsonl` and source lock preserve the
sequence, sampled states, firmware identity/fault counts and SSH evidence.
Firmware crashes, reloads, SDIO removals, PM underflows or changes to boot,
firmware, NVRAM, persistent configuration, scan policy or USB state fail the test.
The synthetic network exercises scanning while the requested network is
unavailable; it does not reproduce physical loss of an associated AP's beacon.
Cold starts, physical AP disappearance, sleep, long-term stability and energy
need their own evidence. The original-firmware trial tasks above require the
old binary and are separate from this installed-firmware task.

`device:rsb-compare` measures RSB runtime-active/suspended accounting with USB
connected, the Mac awake and Wi-Fi available. It requires the currently locked
image/kernel/radio and a healthy device. `SECONDS` is a multiple of 30 in
60–300, per window; `DELAY_MS` is 10–500. Three original/candidate/original
windows each have 15 seconds of settling. The default is 120 seconds and 100 ms.
Keep controls untouched and other diagnostic tasks stopped. Evidence is saved
privately under `.local/diagnostics/`, including the source lock. This measures
runtime residency, not battery power or a count of runtime resumes.

The original delay must be 1,000 ms. A device-side ownership record, `finally`
restoration and independent `ExecStopPost` restore it after the comparison.
`device:rsb-restore` stops the unit and retries restoration after an interruption;
retain the printed helper directory and ownership record until recovery passes.
The device service is bounded to `3 * (SECONDS + 15) + 90` seconds, assuming a
functioning kernel/systemd. The [first comparison](docs/53-rsb-runtime-pm-comparison.md)
found zero runtime-suspended time at both 100 ms and 20 ms; the default remains
1,000 ms. Diagnostic.7's initial advanced counters show RSB usage 1 and
Wi-Fi-host usage 2 with runtime PM forbidden; these sequential reads support
further dependency analysis, not an energy-saving claim. See
[report 55](docs/55-diagnostic7-hardware-validation.md).

### Staged power-management diagnostics

Use `device:pm-inspect` for read-only kernel capabilities, runtime counters and
RSB supplier/consumer links. It also works on diagnostic.6, where sleep support
is absent. Full private evidence includes radio/network state and kernel logs;
only a small capability summary is printed. The task never enters suspend.

`device:pm-test` requires the currently locked image/kernel/radio, stock USB
polling, normal sleep masks, SDIO power retention, USB power, healthy services
and working USB/Wi-Fi SSH. Be present for the initial hardware tests and retain
the preceding verified recovery image. Leave USB connected, the Mac awake, Wi-Fi
available and the controls untouched. Start with one `STAGE=freezer`, then one
`STAGE=devices`. After those pass and the console/backlight return normally,
`STAGE=devices CYCLES=4` repeats four identical cycles with 20 seconds between
them. `CYCLES` defaults to one and accepts 1–4; there is no default stage.

Each snapshot records the named USB and AC supplies' type, presence and online
state. The power gate requires the AXP USB supply to be present and online as
well as a configured USB controller. Battery status describes battery current
flow; it is recorded independently and is not used as proof of external power.
Battery monitoring, freshness and capacity checks still apply. Missing input
evidence fails the gate. [Report 75](docs/75-pm-external-power-gate.md) records
the correction and the limitations of earlier captures.

Each before/after snapshot also saves raw interrupt and CPU counters from
`/proc/interrupts` and `/proc/stat`. Differences cover the complete observation,
including awake work and the network recovery wait; they do not isolate the
radio's sleep interval or establish energy savings. The recorder adds no
periodic polling for these counters.

These use the kernel's **five-second debug test**: `freezer` freezes/thaws
processes; `devices` additionally invokes ordinary driver suspend/resume
callbacks. They stop before late/noirq/platform stages and actual s2idle.
The task refuses `none`, `platform`, `processors`, `core`, `mem` and other
stages. It does not implement normal sleep, wake-button testing, DRAM retention
or the desired low-power runtime. The temporary process-memory checksum is
only an integrity check across this debug cycle.

For an intermittent Wi-Fi recovery failure, first run `device:wifi-trace-smoke`
with USB connected. It performs one awake software reassociation and requires
EAPOL observations in both directions, a supplicant security-completion event,
restored logging/tracing, unchanged PM counters/configuration and both SSH
routes. It does not suspend or modify the saved network. The service has a
90-second runtime limit and independent cleanup; its private `wifi-smoke.json`
contains the metadata capture. A failed run retains its helper and evidence.

After that passes, `device:pm-test STAGE=devices CYCLES=1 WIFI_TRACE=1` adds the
same recorder to one owner-observed ordinary driver cycle. Wait for explicit
readiness before starting, keep USB connected and leave controls untouched.
The existing 30-second postflight is sampled before metadata collection, so
the additional collection time does not extend the acceptance window. The
option cannot be combined with physical button prompts or keypad policy
experiments; `KEYPAD_TRACE=1` may be added for the existing observational trace.

The recorder uses its own 256 KiB/CPU trace instance, filtered to `wlan0` EAPOL
metadata plus ordinary PM callbacks. It temporarily selects supplicant DEBUG,
preserving its timestamp setting and restoring the original level. It requires
the exact installed launch arguments without key display or D-Bus debug
controls. Raw debug messages remain in the device's private journal; exported
supplicant evidence uses an allowlist of state/handshake/timer events without
network names, addresses, keys or packet contents. Trace loss and oversized
journal captures fail. Transmit events establish host submission, not delivery
over the radio; absent userspace messages alone do not establish frame loss.

Both recorders use a saved ownership record and `ExecStopPost` cleanup. After
an interrupted PM run, use the usual `device:pm-collect RUN=...` and
`device:pm-restore`. If the awake recorder is still active, stop its named
`gameshellneo-wifi-trace-smoke` unit over USB first, then use `device:pm-restore`
to retry owned logging/trace cleanup. Keep its private helper until cleanup
passes. Neither task changes firmware, credentials or authentication timers.

Initial hardware checks found that the internal keypad re-enumerates during
devices-stage recovery, and the separate MUSB controller emits two warnings
about an unsupported ULPI register. Reports 56–57 implement fixes for AXP
polling lifetime and the MUSB accesses. Diagnostic.8's ordinary driver-stage
qualification passed in report 60, with zero unsupported-ULPI warnings.
The updated recorder checks an existing keypad input handle as well as the
returned device: diagnostic.7 returns at the same path but leaves the old
handle disconnected. A stage pass proves peripheral recovery, not uninterrupted
input continuity. Held-button behavior still needs a physical test.

`task device:keypad-inspect` saves read-only identity, stable input paths,
persistence, wake capability and supply state. On diagnostic.8,
`task device:pm-test STAGE=devices CYCLES=1 KEYPAD_TRACE=1` additionally records
selected USB PM messages, keypad regulator transitions and driver callback
timings. The bounded recorder
uses a private trace instance, restores debug flags and rejects overflow.
The older diagnostic.7 lacks the required tracing facilities and refuses that
option before entering PM. Use `device:pm-restore` for interrupted trace/control
recovery. [Report 58](docs/58-keypad-pm-investigation.md) records the source trace,
live handle failure, saved commands and remaining retention/reopen comparison.

`task device:keypad-compare` runs three traced devices debug cycles with the
internal keypad's USB persistence **on, off, then on**. It requires the normal
PM preflight and an initial persistence value of `1`; it validates the known
low-speed HID identity and internal OHCI port before touching that device's
`power/persist`. Each phase restores the original value with readback, including
after re-enumeration or failure. Independent service cleanup retries restoration;
`task device:pm-restore` recovers an interrupted owned change. A failed restore
retains its ownership record and prevents a new comparison.

Leave USB connected, Wi-Fi available and controls untouched during the roughly
three-minute automatic sequence. The recorder checks a fresh input handle every
100 ms for up to ten seconds after the PM stage, without grabbing the keypad or
injecting events. That measures healthy-handle availability, not the first
physical button event. Every phase retains the same 30-second minimum recovery
window, trace configuration, rail policy and independent USB/Wi-Fi SSH checks.
Private results and the incomplete/complete summary are stored in the printed
diagnostic directory. No storage-device persistence, keypad power/wake policy,
boot setting or normal sleep policy is changed.

[Report 61](docs/61-keypad-persistence-comparison.md) records the comparison,
recovery checks and recorder qualification. The accepted on/off/on run found
roughly 1.8 seconds earlier healthy-handle availability with persistence off:
about 3.3 seconds shorter in the debug stage, offset by about 1.5 seconds more
re-enumeration delay afterwards. All three phases passed and restored the
original policy. This does not yet fix input continuity or establish real
sleep/wake latency; persistence remains enabled by default.

On the separately identified diagnostic.9 retention image, use
`task device:keypad-retention CYCLES=1`, then `CYCLES=4` after reviewing the first
result. This runs traced devices debug stages with the same timing/restoration
and independent SSH gates. It checks the live supply-retention property against
the image lock and records original-handle health, USB/input identity, disconnect
count and fresh-handle delay in each cycle's private `retention.json`. A lost
original handle remains a negative continuity observation even when the device
recovers successfully. Regulator-disable events, trace loss and restoration
failures reject the observation. Physical input delivery and energy are separate
tests. `device:keypad-compare` remains scoped to the power-off image.

On the retention image, compare the internal keypad port's USB reset policy:

```sh
task device:keypad-quirks QUIRK=old-scheme CYCLES=2
task device:keypad-quirks QUIRK=fast-recovery CYCLES=2
```

Each command runs baseline/candidate/baseline, with `CYCLES=1..4` tests per
phase. Keep USB connected and Wi-Fi available; leave the controls untouched.
`old-scheme` selects one reset rather than two; `fast-recovery` changes the
post-reset recovery wait from 50 ms to 10–12 ms. They are tested separately,
using the exact internal OHCI port's `quirks` attribute. Device quirks, global
USB policy and persistence are unchanged. Each cycle restores the original
port value, checks the original input handle, device identity, supply retention,
complete tracing and both SSH routes, and records the USB resume callback time.
An interrupted test also has device-owned restoration through `ExecStopPost`;
use `device:pm-collect RUN=...` and `device:pm-restore` if collection fails.
Do not resubmit an uncertain PM operation. A failed restoration retains its
ownership record rather than silently accepting a changed policy.

Results are in the printed private evidence directory: `comparison.json` and
each phase's `result.json`/`quirks.json`. The means describe instrumented driver
debug recovery, including neither real sleep qualification nor an energy result.
Physical qualification uses `task device:keypad-input QUIRK=old-scheme AUDIO=1`
(or `QUIRK=fast-recovery`) with the owner ready to follow the prompts. That
interactive run restores the candidate afterward and is not a timing comparison.
See [report 67](docs/67-keypad-port-recovery-comparison.md) for the locked-source
analysis, validation and measured results.
See [report 62](docs/62-keypad-supply-retention-preparation.md) for the exact
build/recovery sequence. This candidate reuses `6.18.54-gameshellneo8` deliberately:
the experimental difference is in the image's DTB, not the kernel binary.

To qualify physical input on this retention image, run
`task device:keypad-input` with the owner watching and USB connected. It runs
one devices debug cycle and displays the complete sequence on the GameShell:
tap/release A, B, X and Y as prompted; press and hold A through the driver test;
release only at `RELEASE A`; then repeat the four taps. Each button prompt has
a 30-second deadline and a two-second recorded confirmation after a ten-second
initial countdown; the whole device service is bounded to seven minutes.
Keep all other controls untouched, including power. Both SSH routes must pass
preflight; the device repeats its health checks after the initial button input.

The recorder reads physical evdev events through the same original handle,
temporarily grabs only the internal keypad to keep input out of the login
console, and checks held-key bitmaps before/after PM and release. It distinguishes
continuous holds, a kernel-cleared hold and a cleared/reasserted hold. A cleared
hold is accepted as an observation only when its release timestamp falls inside
the keypad input device's traced suspend callback; it is never reported as
continuous. If Linux already cleared A, its later physical release need not
produce another event; successful fresh A taps still must follow. Queue loss,
unexpected edges, a changed device or a failed cleanup reject the sequence.
The screen contents/cursor are restored, and closing the fd releases the grab
even if the worker is killed. Independent PM recovery also restores the owned
console snapshot. Use the existing `device:pm-collect RUN=...` and
`device:pm-restore` tasks after an interrupted run; never blindly resubmit it.
Evidence is in `result.json`, `retention.json` and, after full success,
`physical-input.json`. Human interaction makes these runs unsuitable for latency
comparisons. This exercises four face buttons and one held key, not every
chord, physical release during the dark interval, actual sleep or energy.
See [report 64](docs/64-keypad-physical-input-validation.md) for qualification.

On the audio-enabled diagnostic.10 image, first use
`task device:audio-inspect`, then `task device:audio-test` with the owner
listening. The latter now plays three bounded one-second cues at level 5 after a ten-second
lead-in and checks mixer restoration and amplifier power-down. Once sound is
confirmed, `task device:keypad-input AUDIO=1` adds a speaker cue for each
accepted tap and hold. Without `AUDIO=1`, key confirmations remain silent, but
the screen-blanking warning still plays. Playback closes and both
amplifiers must be idle before entering PM. The upstream amplifier startup
delay is retained, so confirmation is not instantaneous.
Use `task device:audio-collect RUN=...` to retrieve an interrupted standalone
test and `task device:audio-restore` for its owned mixer recovery. The existing
PM recovery tasks also restore audio after an audio-assisted keypad run.
The owner observed a significant delay on every button confirmation: each cue
powers the amplifiers up again and repeats the upstream 700 ms startup wait.
Improving that latency is recorded for later investigation.
See [report 65](docs/65-speaker-confirmation-cues.md) for routing, levels,
recovery and qualification status.

For quiet or unheard cues, `task device:audio-path ROUTE=usb` runs a saved audio-only
check after fresh listening readiness: ten seconds of lead-in, then one
one-second tone at **level 5**. It leaves the screen
on and records active PCM, amplifier and GPIO states during playback before
restoring the original mixer. Observations are bounded to eight seconds/400
samples per cue; individual reads are sequential, not an atomic hardware
snapshot. Successful capture does not establish audibility. Collect and recover
with the same `device:audio-collect` and `device:audio-restore` tasks above.
`LEVEL=3/4/5` selects headphone volume 48/54/57 (-15/-9/-6 dB);
the default is 5. All normal warnings, button confirmations and this diagnostic
use long tones, as requested after the owner confirmed the short tone works
but the long one gets their attention. The historical short/long comparison and
original results remain in [report 161](docs/161-active-audio-path-investigation.md)
and its referenced source commits.
This uses uploaded helpers, with their source hashes saved in `run.json`; it
does not require a reflash. Changes to the shared audio helper invalidate older
sleep source receipts: do not rewrite evidence or reuse a stale rehearsal.

As requested on 5 October, saved workflows warn through the **GameShell speaker**
before planned reboots and screen blanking. Devices/platform debug tests, actual
RTC sleep, every off-cycle in the backlight test, and `BACKLIGHT=off` sampling
play one one-second tone at level 5 and leave a one-second lead-in. Playback and amplifier
power-down complete before the blanking operation; a failed warning stops that
operation. The lead-in is outside reported PM-stage and energy-sampling windows.
The timed power-key release test warns before asking for the one-second hold.
Freezer checks and awake rehearsals do not blank the display and remain silent.

Use `task device:reboot ROUTE=usb` (or `ROUTE=wifi`) for planned reboots instead
of a raw `device:exec ... reboot`. It uses three one-second speaker
tones at level 5, verifies audio restoration and the unchanged boot, then queues one reboot
after two seconds. `reboot.json` records submission and acceptance; an uncertain
SSH submission is never automatically retried. Verify the resulting boot
separately. The USB idle comparison uses this same task for both of its reboots.
Warnings do not replace fresh readiness for an attended test. These are helper
changes; the installed power-button and normal sleep policies are unchanged.
[Report 159](docs/159-audible-diagnostic-warnings.md) records validation and limits.
[Report 161](docs/161-active-audio-path-investigation.md) records the subsequent
audibility comparison and updated warning level/duration.

The helper serializes driver callbacks with `pm_async=0`, records the original
controls, and restores them on exit and through independent `ExecStopPost`.
A temporary logind inhibitor covers power-key/sleep/idle handling. Evidence is
written on the device under `/var/lib/gameshellneo/pm-tests/<RUN>/` before and
after the test; the host stores copies and the source lock under
`.local/diagnostics/`. The systemd service owns execution independently of SSH,
and a rejected device preflight also preserves its snapshot in the failed
result, with the failed health-gate names. It does not enter a PM stage.
For completed stages, both routes must reconnect to the original boot before a host pass is
recorded. A 120-second service limit and 180-second host collection deadline
bound ordinary failures; **they cannot recover a kernel or driver deadlock**.
No automatic retry is made after missing evidence.

If a result is interrupted, retain its printed run ID and helper path. Use
`device:pm-collect RUN=...` after access returns, then `device:pm-restore` if
owned controls still need restoration. Collection retrieves evidence and does
not by itself repeat the network qualification. Helpers, ownership records and
device results remain available for investigation. No remote task guarantees
recovery from a hung kernel; physical power cycling/reflashing may be needed.
The stage tests passed on diagnostic.7 and diagnostic.8; diagnostic.8 also
passed two bounded keypad traces. Real sleep and later PM stages remain
unqualified. The keypad still requires reopening after driver-stage recovery.

`device:battery-check ROUTE=wifi` runs the battery policy regressions against
the **installed** guard after verifying its SHA-256 matches the tracked source.
It includes the real main loop with fake power-supply files and simulated time:
three low readings, invalid/missing telemetry, charging or capacity recovery,
sampling gaps and retry after a rejected shutdown request. Output is retained
privately as `battery-policy.txt`.

The checks run as the SSH user with a 60-second bound. Temporary state replaces
the real `/run/gameshellneo` path inside that process, and a test function
records every would-be shutdown command. The live battery service continues
running; no real shutdown request, charger write or gauge change occurs. This
qualifies simulated behavior of the installed software, not physical low-battery
shutdown reserve, percentage accuracy or charging limits. It needs no image rebuild.

`device:charge-inspect` captures one awake charger/gauge inventory over USB.
Keep USB connected. It checks the matching image/kernel and AXP223 identity,
reads existing battery/input sysfs telemetry and eleven documented registers,
and saves the original JSON plus helper/source-lock hashes under
`.local/diagnostics/`. No charger, gauge, cache, screen or sleep setting is written.
The local PM lock prevents overlap with another saved PM workflow.

The targeted regmap reads verify the Linux 6.18.54 map layout and use exact
seven-byte reads without buffered read-ahead. Undocumented charge registers
E2/E3 and IRQ status are excluded. Nonvolatile fields, including calibration
status on diagnostic.20 and configured capacity on all supported images, are
explicitly labeled as possibly cached. Schema 4 accepts only the audited pairs
diagnostic.20/kernel `6.18.54-gameshellneo19` and diagnostic.21/kernel
`6.18.54-gameshellneo20`, requiring cached and volatile B8 respectively,
plus diagnostic.22/kernel `6.18.54-gameshellneo21` with volatile B8 and the
corrected ADC width mask. The report preserves both masked and legacy unmasked
formulas and selects `linux_helper_formula_uv` from the admitted image's behavior.
Unexpected pairings or observed cache metadata are rejected before register reads.
A completed
inventory is not a charging test: instantaneous current and percentage do not
measure charge gained while asleep. See [measurement design](docs/180-sleep-charge-measurement-design.md)
and [inventory validation](docs/181-charge-inventory-validation.md). The inventory
preserves raw REG34 and battery-voltage bytes 78/79. REG34 bit 2 is recorded without
an enabled/disabled interpretation because the manuals disagree. The voltage
bytes are separate reads: masked and existing Linux formula results are
diagnostic comparisons, not coherent or calibrated samples. The
[extended inventory report](docs/185-axp223-voltage-inventory.md) records the
source limits, tests and historical hardware observation. Schema 3 moves B8's
decoded controls/status into `assessment.gauge_control` with its explicit source
label; E0/E1 capacity stays under `cached_configuration`. The embedded inventory
in `device:charge-baseline` uses the same schema; previous captures stay unchanged.

`device:charge-baseline SECONDS=120` records a connected, awake baseline with
one sample every ten seconds. `SECONDS` must be a multiple of ten from 60 to
600. Keep USB connected and the screen/controls unchanged. It uses the same
read-only inventory first, then directly samples battery and external-power
sysfs values with BOOTTIME/MONOTONIC brackets and boot/PM counters. It rejects
detected sleep, missing/late samples, slow reads, lost external power, discharge,
invalid battery readings, low capacity, excess temperature, taint, and observed
changes to brightness or charger/input-limit settings. No setting is changed.

Original JSON-lines observations (including a rejected sample), source hashes
and requested duration remain private under `.local/diagnostics/`. A remote
deadline bounds execution independently of SSH collection. Lost SSH or partial
output cannot pass and does not cause an automatic rerun. A successful summary
includes a trapezoidal **uncalibrated sampled charge estimate** for the awake
interval only; it does not account for unseen current variation between samples
and is not a sleep-charge measurement. A full-battery plateau is not evidence
that charging during sleep is broken. [Baseline validation](docs/182-awake-charging-baseline.md)
records the initial full-battery result. The subsequent
[partial-discharge and charging session](docs/183-partial-discharge-charging-validation.md)
passed an awake baseline below 100%, while preserving an earlier transport
failure and the unresolved voltage/gauge and sleep-charge qualifications.

`device:idle-sample ROUTE=wifi SECONDS=600` records a repeatable awake-idle
scenario after one minute of settling. Unplug USB, keep Wi-Fi associated and
leave the controls alone; avoid other diagnostics during the run. The task
preserves brightness and governor settings by default (`BACKLIGHT=keep`) and
samples every ten seconds.
It stops sampling if external power returns, brightness/governor changes,
Wi-Fi disconnects, the guard becomes invalid/stale, capacity reaches 20%,
temperature reaches 80 °C or the kernel is tainted. These stops do not request
power-off; the existing battery guard continues independently.

The private `idle-sample.jsonl` records raw software readings, temperature,
frequency, signal context and timing. Its final summary integrates current and
voltage using actual sample intervals, reporting **uncalibrated estimates** of
charge and energy. It does not establish true pack capacity, electrical meter
accuracy or future runtime. This scenario includes an open Wi-Fi SSH connection,
one transmitted sample per ten seconds and the ordinary ten-second battery
guard; it is not an observer-free idle measurement. The temporary service has
a runtime bound of the requested sample duration plus two minutes. `SECONDS`
accepts multiples of ten from 60 to 3600; the initial settling minute is extra.
A complete result is required before interpreting the run. With the default
`BACKLIGHT=keep`, no charger, gauge, radio, display or CPU setting is written.
No image rebuild is needed.

Use `BACKLIGHT=off` for the backlight comparison. Start with a lit, unblanked
display; the task checks battery/health first, saves brightness, sets it to
zero and verifies the driver's `actual_brightness` before settling. It restores
and verifies the original brightness on completion, sampling errors or handled
HUP/INT/TERM termination. A successful final result requires restoration to
succeed. A forced SIGKILL cannot run cleanup; if necessary, restore the original
value using `device:exec` over Wi-Fi. The display controller/panel, Wi-Fi and CPU
settings stay unchanged: this measures backlight savings while awake, not full
display power-down or sleep. Leave USB unplugged and controls alone for the
entire run, including the automatic return to the original brightness.

`device:governor-compare ROUTE=wifi SECONDS=120 RATE_US=10000` compares the saved
schedutil update interval, the requested slower interval, and the saved interval
again. `SECONDS` is **per phase**, with thirty seconds settling before each:
the default takes about 7½ minutes. Allowed durations are multiples of thirty
in 60–300 seconds; `RATE_US` is 1,000–100,000 microseconds and must exceed the
current value. This is a temporary diagnostic setting, not a production policy.

Leave USB unplugged, controls untouched and other diagnostics stopped. The task
requires valid discharging battery monitoring above 20%, Wi-Fi connectivity,
schedutil, no kernel taint and temperature below 80 °C. It checks every ten
seconds and aborts on changes to the boot, CPU set, display, governor, frequency
limits or Wi-Fi power-save setting. Only `rate_limit_us` is written; no OPP,
voltage, charger, gauge or radio setting is changed. The live battery guard
continues throughout. Counter snapshots and software current/voltage samples
are retained in private `governor-comparison.jsonl`; the console prints a short
summary afterward. The readings remain uncalibrated, and the sampling itself
adds work at the same cadence in all phases. Compare the three phases with each other;
their observer differs from the earlier counter-only profile.

The original value is saved in `/run/gameshellneo-governor-comparison.json`
before any setting change. Normal completion and handled signals restore it
with readback. The transient `gameshellneo-governor-comparison.service` also
uses `ExecStopPost` to run restoration independently after a crash or forced
kill, with a bounded runtime. This requires a functioning kernel/systemd; it
cannot repair a hung kernel. No value is persisted across boots.

If SSH drops, let the bounded service finish or stop it after reconnecting:

```sh
task device:exec ROUTE=wifi -- sudo -n systemctl stop gameshellneo-governor-comparison.service
task device:exec ROUTE=wifi -- cat /sys/devices/system/cpu/cpufreq/schedutil/rate_limit_us
```

Verify the **saved** original value (366 µs on the previously inspected boot).
The task prints a temporary helper directory and retains it on failure so the
cleanup hook can still run. If restoration itself failed, inspect the retained
JSON and run `sudo -n /usr/bin/python3 -B <printed-directory>/compare-governor.py
--restore` through `device:exec`, after the service has stopped. Do not delete
the helper directory or restoration record until recovery is verified. A
failed restoration keeps its record; a successful one removes it. Missing
measurement output or an unsuccessful service is never a passing comparison.

`task test:governor-recovery` checks this recovery with temporary files and
user-systemd units on the Intel host, including forced termination and timeout.
It needs a working user service manager, uses no sudo and never touches CPU
settings. The ordinary host checks include the rollback tests but skip the
real-systemd case. [Report 32](docs/32-governor-rate-comparison.md) records which
checks have actually run; the new task is not yet qualified on the GameShell.

`device:power-profile ROUTE=wifi SECONDS=120` collects an awake activity profile
after thirty seconds settling. Keep USB unplugged, Wi-Fi connected and controls
untouched; avoid concurrent diagnostics. It preserves display, CPU, radio and
charger settings. The existing battery guard continues, and the profiler checks
its health every thirty seconds. A changed boot/CPU set/brightness/governor,
external power, invalid/stale monitoring, reported capacity at or below 20%,
excessive temperature or kernel taint fails the run. Failure ends profiling,
not the running system.

The private `power-profile.jsonl` contains before/after CPU accounting,
interrupts, softirqs, process CPU ticks, Wi-Fi packet counters/power-save state,
available idle/frequency counters and peripheral runtime-PM state. Clock,
regulator and timer debug snapshots are read after the measurement. Twenty
best-effort kernel-stack snapshots of up to three busiest surviving processes
are also taken afterward; they are diagnostic clues, not statistical samples.
Missing optional instrumentation is recorded as unavailable; the task does not mount
tracing filesystems or enable tracers. It retains process names but avoids
command lines, environment values, SSIDs and BSSIDs. Raw endpoint snapshots stay
in memory until collection ends to reduce SSH traffic; the terminal shows a
shortened summary and all records remain in the private capture.

CPU percentages use accounting ticks, not clock-frequency samples; aggregate
CPU busy percentage is across all online CPUs, while each process percentage
uses one CPU as 100%. Accounting coverage compares recorded CPU ticks with
elapsed wall time; inspect any shortfall before treating percentages as precise.
Guest time is not double-counted, PID reuse is excluded, and decreasing counters
fail rather than produce misleading rates. Process
deltas cover processes present at both endpoints; short-lived work can be
missing. Interrupt/softirq counts are not unique wakeups or energy attribution.
Snapshots are sequential and include the observer's overhead. This diagnostic
profile complements the idle-power samples; it is not another power/endurance
measurement. `SECONDS` accepts multiples of thirty in 30..300, with the settling
period extra and a transient-service limit of `SECONDS + 90` seconds.

For function attribution, run `task build:perf` once, then
`task device:governor-profile ROUTE=wifi SECONDS=30` as a separate experiment.
The build uses the locked Linux archive and Docker image and writes a minimal
ARM hard-float `perf` binary, hash, compiler and ELF dependency records under
`.local/build/perf/`. It needs the Linux source already prepared by the kernel
build. It does not rebuild the kernel, install packages or alter the image.

The device task stages the tool temporarily and samples only the existing
`sugov:0` worker's kernel instruction pointers using `cpu-clock:k` at a requested
99 Hz (10–60 seconds supported). It checks the worker's PID/start time and
unchanged power configuration, plus the battery-only profiler's health rules.
No callchains or power-setting changes are requested. Health checks and sampling
add overhead; run this separately from power comparisons. A runtime bound and
the transient service's process-group cleanup contain failed captures.

Private evidence includes `governor-profile.jsonl`, `perf.data`, record/report
text and the same boot's kernel symbol map. The report must contain samples;
inspect lost-sample warnings and unresolved symbols before interpreting it.
Successful runs remove their staged files; failed runs retain the printed
temporary directory for diagnosis. Instruction samples attribute where this
worker was executing when sampled, not individual component watts. Software
timer sampling can miss work while interrupts are disabled; symbol names do
not provide caller stacks or exact per-function wall time.

`device:boot-cycles CYCLES=4` observes physical shutdown/startup cycles over
USB SSH through the Mac and checks direct Wi-Fi SSH on every captured boot.
It issues no power commands. Start with the device running, USB connected and
Wi-Fi available; wait for the `ready` message. For each cycle, briefly press
power to shut down, wait ten seconds after the screen goes dark, power on
normally, then wait for the login screen and leave it there for another
60 seconds. Repeat four times, leaving the final boot running. Stop the batch
if the screen fails to turn off or the login screen fails to return.

The recorder checks image/kernel identity, four CPUs and expected memory,
services, input enumeration, backlight state, battery monitoring and USB/Wi-Fi
access. When the source lock pins a radio `runtime_identity`, each boot must
have exactly one matching loaded firmware identity and no firmware-crash,
SDIO-removal or runtime-PM-underflow markers. Per-boot JSON preserves these
identities and fault counts; older locks without an expectation explicitly
skip firmware qualification. Each new boot must follow the previously captured
boot in the saved journal and contain evidence that the previous short power press reached
systemd power-off and filesystem syncing. It saves private per-boot JSON,
kernel/shutdown journals and a summary under `.local/diagnostics/`. It retries
transient SSH failures and rejects missed boots; a default 15-minute timeout
bounds the batch. Physical darkness and the visible console still need owner
confirmation. Software logs do not measure rail current or exact power-off
time, and readiness timestamps exclude bootloader time. `CYCLES=0` checks only
the current boot and adds no power-cycle credit. This task needs no image rebuild.

`device:check` compares the running kernel/image with the source lock, verifies
required services, the journal's effective user ACL, selected regdb files and
the configured/active country. It also creates a temporary IPv4 loopback listener
and three disposable systemd services to test a control connection, BPF denial,
and a localhost allow exception. Those filters apply only to the test services;
the task does not reconfigure Wi-Fi, restart production services or reboot.
The uploaded helper is removed afterwards. Results remain in a private
`integration.json`; any failed assertion returns a nonzero task status.

For journal storage and the inherited Armbian log-rotation interaction:

```sh
task device:journal-inspect   # read-only storage/configuration/history capture over USB
task device:journal-policy    # apply the saved two-file policy; save original contents
task device:journal-rotation  # run ordinary text-log rotation and verify journal continuity
```

The inspector's exit status describes collection, not persistence health.
The policy disables direct RAM-log calls and removes their rotation hooks;
ordinary text-log rotation and journald's existing size limits remain active.
It briefly pauses the rotation timer and restores its previous active state.
The rotation check requires that policy first and uses no `--force`. Both
actions verify the same boot, unchanged journald process, retained kernel
history and unchanged displaced-journal inventory. They do not restart
journald or merge/remove old evidence. Inspect an interrupted task's private
capture and timer state before retrying. [Report 97](docs/97-journal-loss-investigation.md)
records the recovered journals and hardware verification.

The active country normally must match `GAMESHELL_WIFI_COUNTRY` in `.env`.
For the owner's explicitly accepted AU access-point announcement while the
device is provisioned for NZ, use `task device:check ROUTE=usb ACTIVE_COUNTRY=AU`.
That verifies the declared test setup and records both values; it does not
qualify NZ operation or the radio firmware's country mapping.

### Backing up the original card

Insert the original card in the Mac while the GameShell runs from the DEV card.
Identify its current disk number, then run:

```sh
task mac:status
task mac:backup DISK=diskN
```

This task unmounts the selected external USB card and opens it **read-only**.
It archives the entire card, including its bootloader and both partitions,
verifies that decompressing the archive reproduces every captured byte, and
ejects after success. It supports Linux filesystems that macOS cannot mount.
It does not change the flash target inspection or authorize a write.

Private archives and checksum/identity reports are kept on the Mac under
`~/.local/share/GameShellNeo/backups/` and copied to Linux `.local/backups/`.
The downloaded copy is checked against the Mac's SHA-256. Operation logs are in
`.local/diagnostics/`. Allow free space on the Mac for the whole card plus 1 GiB,
and on Linux for the compressed archive plus 1 GiB. A failed run preserves any
partial archive as `.part` for diagnosis and does not report a successful backup.
Verification checks archive integrity; booting a restored card is a separate test.

### Staging and flashing the spare card

```sh
task mac:status            # Inspect connectivity and external physical disks
task mac:stage             # Pack, upload, and verify image bytes on the Mac
```

Staging uses the Mac's private `~/.local/share/GameShellNeo/` directory and does
not require a card. After identifying the intended spare in the current disk
listing, substitute its actual identifier for `diskN`:

```sh
task mac:inspect DISK=diskN # Record size, reader identity and existing volume UUID
task mac:preflight         # Recheck the staged image and recorded card; no write
```

**The next command erases the selected spare card:**

```sh
task mac:flash DISK=diskN
```

Only `mac:flash` requests a disk write. It requires the explicitly named disk
to match the inspection, rechecks physical external USB media and volume
identity, verifies the image, writes it, reads back every written byte, and
ejects after success. Flash logs/results stay under `.local/diagnostics/`.
Never reuse a disk number without a fresh inspection. A recognizable existing
volume UUID is required; blank/unrecognized cards need separate preparation.
The task does not reboot the GameShell or establish hardware acceptance.

Flashing requires Apple's command-line developer tools (`xcrun clang`) on the
Mac. The task compiles a small Disk Arbitration helper that temporarily blocks
mounts of the selected card and its partitions. Before writing, it unmounts the
card and requires an actual rejected mount attempt from that helper. The guard
stays active through full readback and ejection, preventing macOS metadata
writes from changing the image. It exits when the operation ends and makes no
persistent mount-policy changes. A missing compiler, failed veto or exited
guard stops the operation. [Report 43](docs/43-macos-card-mount-guard.md) records
the failure that prompted this change and its validation.

Keep the reader's USB and any dongle charging connections intact until ejection.
Disconnecting dongle power interrupted diagnostic.18's first readback; a fresh
guarded flash then passed. [Report 140](docs/140-diagnostic18-card-installation.md)
retains that failure, comparison and successful retry.

If readback fails, keep the card in the reader and retain the failed log.
Reinspect it because writing an image changes the boot volume UUID, then use:

```sh
task mac:inspect DISK=diskN
task mac:compare DISK=diskN
```

`mac:compare` opens the raw card read-only and compares the complete image
region. It records both SHA-256 values, differing sector counts, up to 64
sector ranges and the volume's mount state before/after. It never prints image
bytes, unmounts, writes or ejects the card. A mismatch returns failure and
preserves `.local/diagnostics/<capture>/card-compare.json` and its log.
This diagnoses differences; it does not turn a failed flash into a passed one.

Power-key ownership preparation has repeatable commands:

```sh
task device:power-key-inspect  # Read-only identity/recovery-marker check
task device:power-key-smoke    # Untouched power key, awake acquisition/handoff only
task device:pm-power-key STAGE=devices CYCLES=1 # Explicitly attended PM debug test
```

[Report 101](docs/101-diagnostic-power-key-ownership.md) explains ownership,
bounded cleanup and abnormal-termination limits. The final short/2-second/
8-second gestures remain the agreed product policy; these commands do not
implement normal sleep or a power menu.

For a diagnostic policy that survives worker failure:

```sh
task device:power-policy-inspect # Effective logind policy and unresolved owner
task device:power-policy-smoke   # Awake only; keep the power button untouched
task device:power-policy-collect RUN=<original-run-id> # Evidence retrieval only
```

The smoke task temporarily ignores both logind power-key actions, kills a
disposable worker, verifies the policy survived and restores the original
settings while the parent retains untouched-key ownership. It passed on
diagnostic.16. Failed/uncertain handoff retains the boot-local policy for
inspection and cold-restart recovery; do not remove its files or resubmit blindly.
[Report 113](docs/113-diagnostic-power-key-policy.md) records the design, tests
and remaining physical-release/real-sleep gates. The normal diagnostic shutdown
policy is restored after a successful run; this does not enable product gestures.

For the attended **awake** power-key sequence, first confirm the operator is
watching the screen, USB is connected and the headphone jack is empty:

```sh
task device:power-key-input
```

Follow the on-screen prompts: two quick POWER taps, a roughly one-second hold,
then a final tap. During the hold, release at **RELEASE POWER NOW**, or after
two seconds if the prompt does not appear. Tones confirm each completed
press/release pair; their known startup delay remains. The screen stays on.
The test kills a disposable policy worker during the hold and checks released
input, unchanged PM counters, and policy/console/audio restoration. It neither
enters sleep nor tests the product's two-/eight-second gestures. The four-pair
sequence passed on diagnostic.16, with the owner confirming prompts, tones
and the return of the dim console.

If the sequence stops, release POWER and leave it untouched. Inspect the saved
result and any retained owner before recovery; do not rerun or delete the
policy files to bypass a failure. `device:power-policy-collect` retrieves the
original printed run ID after a collection failure. [Report 114](docs/114-awake-power-key-input.md)
describes the checks, evidence and remaining wake qualification.

The separate PM-release task uses a different hold instruction:

```sh
task test:power-key-events    # Locked C event semantics; no hardware
# One attended devices debug cycle, after fresh operator readiness:
task device:pm-power-key-input
```

Follow two POWER taps, then hold POWER for **one second and release even if
the screen is dark**. Never wait for resume or a tone and never hold longer
than two seconds. Follow the fresh tap prompt after return. The existing
five-second debug pause is too long for a hold-until-resume test with the
currently configured six-second cutoff. The task records Linux's synthetic
clear and the release IRQ evidence, then requires a separate fresh awake pair
before restoring shutdown handling. It does not enter real sleep. See
[source findings](docs/115-power-key-release-semantics.md) and
[the sequence and recovery contract](docs/116-bounded-power-key-pm-release.md).
The attended logical-clear and fresh awake handoff passed on diagnostic.16;
the owner's approximate release does not prove physical hold through the
callback. Report 116 also records a separate SDIO runtime-reference increase
across seven saved PM cycles, tracked in NEO-92.

NEO-92's driver candidate makes SDIO interrupt reference accounting depend on
enable/disable transitions, preserving repeated hardware rearming. Its saved
source checks run without a device:

```sh
task test:sunxi-sdio-refs       # Actual host/core functions, native and ARM32
task check:sunxi-sdio-driver    # Also compile the complete ARM host/core files
task check:sdio-ref-history -- --require-stable path/to/cycle-1/result.json path/to/another/result.json
```

[Report 117](docs/117-sdio-runtime-reference-ownership.md) records the cause,
source tests, diagnostic.17 preparation and required hardware comparison.
[Report 118](docs/118-diagnostic17-hardware-qualification.md) records the
completed installation and attended comparison: SDIO usage stays at 2 through
one freezer, one driver and five late/noirq cycles, with display, input-handle,
network and restoration checks passing. Battery savings and actual sleep
remain separate acceptance questions.

RTC and late/noirq preparation is repeatable:

```sh
task device:rtc-inspect  # RTC time and logical alarm; no change
task device:rtc-smoke    # Ten-second alarm while awake, then restore
task device:rtc-restore  # Explicit recovery of an interrupted owned alarm
task device:pm-platform # One attended late/noirq debug cycle; never real sleep
```

The platform task requires the wake-fixed image, same-boot RTC qualification,
power-key ownership and complete PM traces. Run it only after explicit observer
readiness. [Report 102](docs/102-rtc-and-platform-diagnostic-preparation.md)
records the awake evidence, guards and prepared hardware sequence.

The first actual-s2idle experiment has its own commands:

```sh
# Requires the seven accepted same-boot PM records; keeps the screen awake.
task device:sleep-rehearse QUALIFICATION=.local/neo92-final-reference-history.json
# After fresh observer readiness, use the successful rehearsal's printed run ID.
task device:sleep-rtc QUALIFICATION=.local/neo92-final-reference-history.json REHEARSAL=<run-id> ATTENDED=1
# On uncertain SSH, collect the original attempt instead of resubmitting it.
task device:sleep-collect RUN=<original-run-id>
# If USB has not recovered but the configured Wi-Fi route works:
task device:sleep-collect RUN=<original-run-id> ROUTE=wifi
# Capture the Mac side before reconnecting or changing network settings:
task mac:usb-inspect
```

The rehearsal never writes the sleep state. Actual sleep requires matching
helper sources, boot/image, RTC and late/noirq qualification, unchanged SDIO
references, healthy USB/Wi-Fi and independent power-key protection. It arms a
30-second RTC deadline, checks the wakeup counter, and submits at most once.
Keep USB connected and all controls untouched. An early wake or incomplete
result fails qualification; do not automatically repeat the command.

Repeat testing has a bounded batch command. After a fresh same-source awake
rehearsal and observer readiness, run up to four cycles together:

```sh
task device:sleep-batch QUALIFICATION=<current-history.json> REHEARSAL=<run-id> CYCLES=4 ATTENDED=1
```

Each cycle is an independent one-shot attempt with its own device result. The
host rechecks RTC wake, original boot/image/helper identity, PM/reference
continuity, restored controls and independent USB/Wi-Fi SSH before the next
cycle. There is a 20-second awake observation interval between cycles. Keep
USB connected and all controls untouched for the whole batch; allow roughly
six to eight minutes for four cycles, including collection. Report anything
unexpected immediately while leaving the cable and controls untouched.

The batch saves `batch.json` and each accepted cycle's
`qualification-next.json` under its private diagnostic directory. A later
attended batch can use the final `qualification-next.json` with the **original**
rehearsal ID. This retains the seven original debug records and every accepted
sleep result rather than pretending the consumed baseline is unused. The
chain is bounded to 16 actual sleeps; changed helper sources, image/boot,
unrecorded PM/RTC activity or an incomplete result require investigation and
a fresh baseline. A new alarm rehearsal is not inserted midway through a chain.

Both host and device revalidate the saved evidence; the device additionally
checks original result hashes and a persistent single-successor claim. That
claim is written before the alarm or sleep request and is never automatically
removed, including after interruption. Do not delete claims or replay a failed
batch. Collect the original run and review its state. If host collection fails
after the device succeeded, missing route proofs still prevent automatic
continuation. Ordinary sleep policy is unchanged.

The first successful diagnostic.18 result predates this repeat-runner source
and remains valid historical evidence ([report 142](docs/142-diagnostic18-first-rtc-wake-success.md)).
It cannot seed the new chain: establish one fresh seven-debug sequence and
new-source awake rehearsal before the first batch. No card reflash is needed.
[Report 143](docs/143-repeat-rtc-wake-runner.md) records the admission design,
failure tests and remaining hardware qualification.

The separate battery-only workflow uses Wi-Fi SSH and requires physical USB
absence. Finish a fresh seven-debug sequence while USB is connected, verify
Wi-Fi independently, then ask the observer to unplug and leave the cable
untouched. After checking the absent state and current battery health:

```sh
task device:sleep-connection-inspect ROUTE=wifi  # Passive PHY/power/UDC/IRQ capture
task device:sleep-battery-rehearse QUALIFICATION=<fresh-history.json> UNPLUGGED=1
# Only after a passing same-source battery rehearsal and fresh observer readiness:
task device:sleep-battery QUALIFICATION=<fresh-history.json> REHEARSAL=<run-id> UNPLUGGED=1 ATTENDED=1
# Uncertain result: collect the original attempt; do not submit another sleep.
task device:sleep-collect RUN=<original-run-id> ROUTE=wifi
```

`UNPLUGGED=1` records a fresh physical confirmation; it is not inferred from
elapsed time or a failed USB connection. Software also requires both external
supply objects to report absent/offline, battery discharge with fresh valid
telemetry above 20%, UDC unattached, carrier 0 and PHY cable/host state 0. Three
passive cable snapshots and unchanged AC/VBUS interrupt counts detect observed
state changes, but cannot prove every electrical edge occurred or was reported.
Keep the cable untouched until the original result is reviewed; inspect USB
reattachment separately afterward. This mode does not qualify USB recovery or
energy savings. It leaves `usb_ssh_verified=false` explicitly and requires
fresh Wi-Fi route proof on the original boot.

Connection profile is bound into the receipt, rehearsal and sleep history;
USB and battery histories cannot be mixed. The existing USB tasks remain
strict about external power, configured USB and independent proofs over both
routes. Battery tests are one-shot commands, not an automatic batch. Each
accepted attempt may provide a continuation for another separately attended
one-shot; all original-result/source/boot/counter and successor-claim rules
still apply. Sources changed for this addition: report148's earlier chain
remains historical evidence and cannot admit this new helper. Establish a fresh
seven-debug baseline and same-source battery rehearsal; no card reflash is
needed. Normal product sleep remains masked. See
[report 150](docs/150-battery-rtc-qualification.md) for validation and live limits.

USB changes during sleep have two separately qualified one-shot scenarios.
Diagnostic.20 has one attended pass in each direction, recorded in
[reports 171](docs/171-diagnostic20-usb-attachment-sleep-validation.md) and
[173](docs/173-diagnostic20-usb-removal-sleep-validation.md).
Both submit and collect through Wi-Fi, keeping an uncertain USB result from
triggering a second sleep. The Mac must remain awake on the same Wi-Fi; this
is not the Mac-sleep test. Start each scenario with its own fresh, reviewed
seven-debug baseline and matching awake rehearsal:

```sh
# Removal: start connected, and keep it connected throughout this awake rehearsal.
task device:sleep-cable-remove-rehearse QUALIFICATION=<fresh-history.json> CABLE_ACTION=1
# After successful rehearsal and fresh observer readiness:
task device:sleep-cable-remove QUALIFICATION=<fresh-history.json> REHEARSAL=<run-id> CABLE_ACTION=1 ATTENDED=1

# Attachment: finish another debug baseline connected, then confirm physical unplug.
# Keep USB absent throughout this awake rehearsal.
task device:sleep-cable-attach-rehearse QUALIFICATION=<fresh-history.json> CABLE_ACTION=1 UNPLUGGED=1
# After successful rehearsal and fresh observer readiness:
task device:sleep-cable-attach QUALIFICATION=<fresh-history.json> REHEARSAL=<run-id> CABLE_ACTION=1 UNPLUGGED=1 ATTENDED=1
```

`CABLE_ACTION=1` records that the observer has confirmed the starting state and
understands the single requested action. It does not mean the action already
happened. `ATTENDED=1` still requires fresh readiness for the actual sleep.
`UNPLUGGED=1` is additionally required whenever the starting state is battery.
No cable action is performed during either awake rehearsal.

The actual test displays instructions for ten seconds before arming the RTC.
When the screen goes dark, wait ten seconds, then perform **one** requested
action at the GameShell: remove USB, or attach the cable connected to the awake
Mac. Leave it in that resulting state. If the screen returns before the action,
do not change the cable; report that the action was not performed. Leave all
buttons untouched. After return, a message says to leave the cable alone while
the original result is collected; the original console is then restored.

Removal must finish with absent external power, UDC/carrier/PHY disconnected,
valid battery discharge and independent Wi-Fi recovery. Attachment must finish
with external power, configured USB/carrier/PHY and independent USB **and**
Wi-Fi recovery. The before/entry states must match; a premature transition
rejects admission before the handshake or sleep write. Diagnostic.19 requires
one AC/VBUS insertion dispatch per supply with no opposite events. Its explicit
`masked-removal-v1` policy permits zero or one dispatch per removal handler,
with no insertion dispatch, regression or extra counts: a masked removal status
can be acknowledged before its handler runs. Older images retain the exact
count policy ([report 154](docs/154-usb-sleep-session-retirement.md)).

Diagnostic.20's prospective `masked-cable-v2` policy also permits zero or one
insertion dispatch per supply. It requires matching image provenance and both
supply wake controls disabled before and after the test. Opposite events, extra
counts and regressing counts still fail. All RTC, endpoint and independent route
recovery gates remain required. [Report 166](docs/166-stay-asleep-usb-charging-policy.md)
records the startup policy and source tests; reports 171 and 173 record the
first attended attachment and removal passes.
Neither handler counts nor screen darkness measures the electrical-edge time.

RTC delivery is checked immediately at return, never after an awake wait.
An early wake, another wake source or incomplete recovery is a failed RTC
qualification, even if the cable seems to work. Wake observations and recovery
state are preserved for diagnosis. No cause is assigned from IRQ counts alone.
The original run is not retried and no continuation history is published for
either cable scenario. On uncertainty:

```sh
task device:sleep-collect RUN=<original-run-id> ROUTE=wifi
```

After reviewing that result, record the observer's answer separately:

```sh
task report:sleep-cable RESULT=<capture/result.json> OBSERVATION=during-dark DISPLAY=normal
```

Use `during-dark` only for one requested action after the ten-second dark wait
and before visible return. Other answers are `after-return`, `no-action` or
`uncertain`; display answers are `normal`, `abnormal` or `unknown`. Do not guess
on the observer's behalf. The offline task creates a separate, non-overwriting
`result-cable-observation.json`, hashes the original, and cannot turn an
automated failure into a pass. Even a successful attended result leaves precise
electrical-edge timing and energy unqualified.

New helper sources require fresh qualification; report150's consumed chain
cannot admit these tasks. The original helper-only addition needed no card
flash; diagnostic.20 adds an image-bound startup policy and requires a new
installation and baseline. Failure can
retain the existing diagnostic power-key suppression pending review; console,
RTC, trace and PM cleanup remains bounded and ownership-checked. See
[report 151](docs/151-usb-cable-sleep-diagnostics.md) for implementation and limits.

The first attended removal attempt woke on RTC with a normal console but failed:
external power/PHY reported removal while the gadget retained its connected state.
[Report 153](docs/153-usb-removal-sleep-state-failure.md) records the preserved
failure and NEO-112 driver investigation. The candidate correction is installed
in diagnostic.19; its connected-USB sleep comparison and one freshly qualified
removal-during-sleep case passed. The latter includes the owner's physical
observation, an independently saved absent state and a separate successful
awake reconnect ([report 163](docs/163-diagnostic19-usb-removal-sleep-validation.md)).
The first attachment attempt returned early with supply insertion wake enabled
([report 165](docs/165-diagnostic19-usb-attachment-early-wake.md)). NEO-117 tracks
the owner's selected stay-asleep-and-charge policy and fresh qualification.
Both historical failures remain unchanged.

For repeat coverage, the saved guided batch uses **remove → attach → remove →
attach**, starting and ending connected. It requires diagnostic.20's qualified
`masked-cable-v2` image/wake policy and one fresh seven-debug baseline. Each
step runs its own matching awake RTC rehearsal, then exactly one actual sleep.
The screen identifies the cycle and cable action; the long warning precedes
darkness. The runner stops after collection and a separate endpoint inspection
to await the owner's observation. It never advances on a timer or interprets
silence as confirmation.

```sh
# After the fresh debug baseline passes, explain cycle 1 and confirm readiness.
# Keep USB connected through the awake rehearsal; follow the later screen prompt.
task device:sleep-cable-batch-start QUALIFICATION=<fresh-history.json> ATTENDED=1 CABLE_ACTION=1

# Use the printed private batch directory for every remaining command.
task report:sleep-cable-batch-status BATCH=<batch-directory>

# Only after the owner confirms one action during darkness and normal return:
task report:sleep-cable-batch BATCH=<batch-directory> OBSERVATION=during-dark DISPLAY=normal

# After readiness for the next described direction; runs just that next step.
task device:sleep-cable-batch-next BATCH=<batch-directory> ATTENDED=1 CABLE_ACTION=1
# Repeat observe/next through cycle 4, then record its final observation.
```

Use the same honest `OBSERVATION`/`DISPLAY` choices as the one-shot report above.
An uncertain action, abnormal display, failed recovery or incomplete command
stops the session; a later answer cannot overwrite the first observer report.
The final observation marks the batch complete and does not run a fifth cycle.
Readiness includes leaving the cable in the preceding cycle's ending state:
unplugged after removal, connected after attachment. Do not perform an extra
awake reconnect between steps. The previous physical observation and fresh
cable/IRQ checks establish the next starting state; the batch does not require
another `UNPLUGGED` flag. Every step still requires explicit `ATTENDED=1` and
`CABLE_ACTION=1`.

Keep the Mac awake on the same Wi-Fi and leave all buttons untouched. A removal
must prove Wi-Fi recovery while USB stays absent; an attachment must prove
both routes. Each original result, rehearsal, observation and endpoint capture
is retained beneath its numbered cycle directory. Same-source/boot/image,
PM/RTC continuity and durable single-successor checks bind the sequence.
These records cannot be used to extend an ordinary connected-sleep chain.

On a failed or interrupted step, read `batch.json` and the original
`cycle-N/awake/run.json` or `cycle-N/sleep/run.json`, then use
`task device:sleep-collect RUN=<original-run-id> ROUTE=wifi`. Collection never
retries PM or advances the batch. A `running`/`failed` batch is deliberately
not resumable through `next`; preserve it for diagnosis. If a command stopped
before creating a run ID, do not invent one or submit another attempt through
that session. The old one-shot tasks retain their original admission rules.

This tooling change needs no image build or card swap. The previous consumed
baselines and rehearsals cannot admit it; a new baseline is required.
[Report 174](docs/174-guided-cable-sleep-batch.md) records the implementation and
offline tests. The first full attended four-cycle batch now passes on
diagnostic.20, with both insertions staying dark until RTC wake, correct cable
endpoints and all owner observations accepted
([report 178](docs/178-guided-cable-batch-hardware-validation.md)). This is bounded
coverage on one boot; charging during sleep, energy, Mac sleep and power-button
wake remain separate qualifications. Normal product sleep stays disabled.

Diagnostic inspections send their Python helper source over SSH standard input.
Only the short interpreter command and its arguments enter the usual sudo command
audit; this avoids repeatedly logging the full helper source. The source payload
is bounded to 1 MiB, and transport failures never trigger command resubmission.
Uploaded independent PM workers keep their existing execution and recovery paths.
Journal limits, audit settings and strict evidence-continuity checks are unchanged.

To inspect retained journal volume without printing its potentially private messages:

```sh
umask 077
task device:journal-inspect
task device:exec ROUTE=usb -- sudo -n journalctl -b --no-pager -o json --output-fields=SYSLOG_IDENTIFIER,_COMM,_UID,MESSAGE --all > .local/journal-volume.jsonl
task report:journal-volume -- .local/journal-volume.jsonl
```

The offline report hashes the original and counts message bytes in fixed categories;
it does not equate uncompressed text with disk usage or infer a deletion cause.
Keep the raw capture private. Missing boot logs still fail PM admission: do not
clear logs, substitute old records or repeat PM to bypass that failure.
[Report 152](docs/152-diagnostic-command-log-volume.md) records the stopped
prerequisite sequence, excessive command logging and the transport correction.

[Report 119](docs/119-guarded-rtc-sleep-preparation.md) records admission,
recovery limits and the two successful awake rehearsals. Ordinary sleep remains
masked. Interrupted ownership can deliberately leave power-key actions ignored;
preserve the evidence and review recovery before further tests. The device-side
cleanup restores only its owned alarm/PM/trace resources, never an uncertain
poweroff policy. Collection saves the unchanged original result plus a separate
read-only snapshot of current CPU-idle/USB/ownership state and boot identity;
collecting over Wi-Fi does not count as USB recovery.
The Mac inspection saves its USB tree, interface addresses, hardware ports,
service order, route to the configured USB address and its last 100 logged
sleep/wake transitions in a private diagnostic folder. It does not renew DHCP
or change network or power settings.

[Report 120](docs/120-first-rtc-sleep-findings.md) records the first actual
attempt: RTC wake, retained keypad and Wi-Fi return, but USB remains unattached.
The CPU-idle driver is absent and stopped timekeeping is not demonstrated; the
recorder's original residency assumption needs correction. Overall sleep
qualification remains open. [Report 121](docs/121-usb-reconnect-and-clean-boot.md)
records a cable reconnect that restored USB and an observed normal reboot that
cleared the failed attempt's boot-local power-key suppression. Both routes and
the normal dim console now pass; ordinary diagnostic short-press shutdown is
restored. Do not reuse the earlier boot's consumed sleep qualification.

Focused USB resume tracing is available on diagnostic.17 without rebuilding:

```sh
task device:usb-trace-sample                       # Ten passive awake seconds
task device:usb-trace-collect RUN=<run-id> ROUTE=wifi # Read the original result
```

The sample captures controller/gadget events and audited ECM notification
messages in bounded buffers, restores tracing/logging, checks unchanged USB/PM
state and verifies both SSH routes. It never changes network interfaces or
submits sleep. If interrupted, collect the original run before deciding whether
to repeat it. Results and source hashes are saved privately on both machines.
An idle trace validates recorder operation, not notification delivery or resume.

The separate sleep diagnostic now includes this recorder and requires a fresh
same-source rehearsal. [Report 122](docs/122-usb-resume-metadata-recorder.md)
records ownership, failure tests, awake evidence and the remaining qualification.

Sleep measurement now reports functional RTC wake, timekeeping behavior and
power qualification separately. A stopped MONOTONIC clock is not required for
functional s2idle on the current WFI fallback. USB recovery and all other
device checks remain mandatory. The recorder also rejects long resume delays
being counted as time spent in the sleep loop.

```sh
task device:sleep-clock-inspect  # Awake CPU-idle/timer inventory and bounded clock samples
task report:sleep-evidence RESULT=<saved-final-result.json> # Offline; preserves original failure
```

[Report 123](docs/123-sleep-measurement-criteria.md) documents the corrected
criteria, tests and CPU-idle implementation still required. The original USB
failure remains failed; neither command qualifies battery savings or enters
sleep. Changed recorder sources require a fresh awake rehearsal before a new
attended sleep attempt.

The USB sleep/disconnect candidate has saved source and configuration checks:

```sh
task test:musb-sleep            # Native/ARM32 sleep and callback-lifetime regressions
task check:musb-sleep-configs   # Those regressions plus six ARM driver configurations
task test:power-irq-mask       # Actual regmap mask/ack behavior with modeled registers
```

Diagnostic.19's removal test records observed PMIC handler deltas separately.
Masked removal may produce zero dispatches; stale UDC/carrier or supply state
still fails. Attachment and awake rehearsal retain their exact-count criteria.
Changed helper/image inputs require fresh debug prerequisites and rehearsal.
[Report 154](docs/154-usb-sleep-session-retirement.md) explains the prospective
policy, source-test limits and required hardware qualification. Report 153's
original failed result is unchanged.
