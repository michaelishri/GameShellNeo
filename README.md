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
the live USB correction and remaining NEO-5/NEO-7 qualification work. The
[latest refresh](docs/27-diagnostic-integration-refresh.md), `0.1.0-diagnostic.2`,
includes that correction, explicit New Zealand provisioning and the kernel/
userspace integration fixes. It passes offline verification and is flashed to
the DEV card with a matching full-image readback; its first boot remains pending.
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
task device:exec ROUTE=usb -- systemctl --failed --no-pager
```

The default route is Wi-Fi. `ROUTE=usb` tunnels through Mac SSH to the board's
USB address, so the Intel host needs no route to that USB subnet. Status and
diagnostic archives are retained privately in `.local/diagnostics/<timestamp>/`.
`device:exec` runs the explicitly supplied command and returns its failure
status. Shell operators require an explicit `sh -c '...'` command.

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
