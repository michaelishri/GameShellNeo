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
[latest refresh](docs/27-diagnostic-integration-refresh.md), `0.1.0-diagnostic.2`,
includes that correction, explicit New Zealand provisioning and the kernel/
userspace integration fixes. Its first boot, USB/Wi-Fi access and live integration
checks passed on the owner's accepted AU-advertising access point. Repeated
hardware tests remain under NEO-5. [Hardware qualification](docs/29-hardware-qualification.md)
records ten cold starts, ten USB reconnections, basic keypad/backlight and load
checks, power transitions, installed battery-policy simulations, the first
awake-idle power estimate and the remaining Lightkey/charging findings.
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
| `GAMESHELL_USB_IP` | Board's USB address; defaults to `192.168.10.1` |
| `M2_MACBOOK_AIR_IP`, `M2_MACBOOK_AIR_USERNAME`, `M2_MACBOOK_AIR_PASSWORD` | Mac SSH connection |
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

`task build` compiles the kernel, validates the device tree, then builds and
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
| `task kernel:reset` | After changing the patch queue; archives old kernel source/output under `.local/previous-kernels/`, then run `task build` |
| `task build:rootfs` | Exercise Debian bootstrap/cache preparation independently |
| `task check` | Python and C regressions, Bash syntax and ShellCheck |
| `task check:kernel` | Resolved Kconfig assertions and kernel artifact manifest |
| `task check:dt` | Binding and compiled device-tree validation in the pinned container |
| `task image:verify` | Repeat filesystem/content checks on the current bundled image |
| `task image:pack` | Compress the verified image and record raw/transfer checksums |

Image assembly automatically runs offline verification and collects its image,
checksums, manifests, logs and package inventory in `.local/artifacts/`.
`verification.json` identifies the current bundle. `IMAGE='/path/to/image.img'`
can select an explicit image for verification; packing requires a match to the
current bundle's verified hash and size. The image contains private credentials
and firmware; do not publish it.

Build-stage logs are `.local/build/kernel.log`, `prepare.log`, `devicetree.log`
and `image.log`. For example, use `tail -f .local/build/image.log` while building.
Older logs are retained under `.local/build/logs/`. A failed stage returns a
failure and prints the log tail. The wrappers reject overlapping build stages;
run build tasks sequentially on this memory-constrained host.

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
task device:stability ROUTE=usb # Keep the board connected throughout
task device:battery-check ROUTE=wifi # Isolated simulation; no real power-off or charger writes
task device:idle-sample ROUTE=wifi SECONDS=600 # USB unplugged; leave controls alone for 11 minutes
task device:boot-cycles CYCLES=4 # Wait for ready, then operate the power button
task device:boot-cycles CYCLES=0 # Capture/check this boot without starting a batch
task device:exec ROUTE=usb -- systemctl --failed --no-pager
```

The default route is Wi-Fi. `ROUTE=usb` tunnels through Mac SSH to the board's
USB address, so the Intel host needs no route to that USB subnet. Status and
diagnostic archives are retained privately in `.local/diagnostics/<timestamp>/`.
`device:exec` runs the explicitly supplied command and returns its failure
status. Shell operators require an explicit `sh -c '...'` command.

`device:backlight` runs a roughly 30-second visual check on an unblanked panel:
brightness 1, 16 and 31, followed by three cycles of 0 (off) and 31 (on).
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
preserves brightness and governor settings and samples every ten seconds.
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
A complete result is required before interpreting the run. No charger, gauge,
radio, display or CPU setting is written, and no image rebuild is needed.

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
access. Each new boot must follow the previously captured boot in the saved
journal and contain evidence that the previous short power press reached
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
