# GameShellNeo

A modern, maintainable Linux foundation for the ClockworkPi GameShell **CPI v3.1**.

The first milestone is a diagnostic image: Linux 6.18.54, minimal Debian 13,
standard device interfaces, and the bootloader already proven on the owner's
board. Sleep, a launcher, OTA and other board revisions are later work.

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
The installed image, `0.1.0-diagnostic.9`, retains that same kernel binary and
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
```

Both humans and coding agents should use these commands. When another routine
operation is needed, extend the Taskfile and its checked-in `tools/` helpers.

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
| `task check` | Python and C regressions, Bash syntax and ShellCheck |
| `task test:nkmp` | Compare original/patched clock searches natively and under ARM32 emulation; also runs before the kernel in `task build` |
| `task check:kernel` | Resolved Kconfig assertions and kernel artifact manifest |
| `task check:dt` | Binding and compiled device-tree validation in the pinned container |
| `task image:verify` | Repeat filesystem/content checks on the current bundled image |
| `task image:pack` | Compress the verified image and record raw/transfer checksums |
| `task image:checkpoint NAME=diagnostic7-before-usb-pm` | Verify the current raw/gzip image and retain its matching metadata before changing build identity; use a new name for each checkpoint |
| `task mac:stage-recovery NAME=diagnostic8-before-keypad-retention` | Verify and select a checkpoint's matching recovery archive on the Mac; no card write |

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
Raw/gzip files remain at their original paths; keep those files with the
checkpoint. This preserves recovery provenance but does not change which image
the default packing/staging commands select.

`mac:stage-recovery NAME=...` rechecks the checkpoint metadata and both retained
artifact hashes, then verifies the compressed and decompressed archive on the
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

For the Sunxi MUSB context capability fix, use:

```sh
task test:musb-context  # Compare actual old/new register operations, native + ARM32
task check:musb-drivers # Also compile the complete MUSB core and Sunxi ARM objects
```

Evidence is in `.local/build/musb-context-tests/`; `task build` includes the
source regression. [Report 57](docs/57-musb-context-capability.md) records the
unsupported-register correction; report 60 records seven diagnostic.8 driver
cycles with zero unsupported-register warnings.

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
task device:pm-test STAGE=freezer # Diagnostic.7 only, owner present; one debug cycle
task device:pm-test STAGE=devices CYCLES=1 # Only after the freezer test passes
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
task device:exec ROUTE=usb -- systemctl --failed --no-pager
```

The default route is Wi-Fi. `ROUTE=usb` tunnels through Mac SSH to the board's
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

These use the kernel's **five-second debug test**: `freezer` freezes/thaws
processes; `devices` additionally invokes ordinary driver suspend/resume
callbacks. They stop before late/noirq/platform stages and actual s2idle.
The task refuses `none`, `platform`, `processors`, `core`, `mem` and other
stages. It does not implement normal sleep, wake-button testing, DRAM retention
or the desired low-power runtime. The temporary process-memory checksum is
only an integrity check across this debug cycle.

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
