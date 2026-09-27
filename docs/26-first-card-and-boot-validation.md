# First card and boot validation

Date: 27 September 2026. Kaneo: NEO-5, in progress.

## Identified spare

The owner inserted the Samsung 64 GB spare into the Mac's USB card reader and
authorized flashing it. macOS reported the volume as `NO NAME`, rather than
`SAMSUNG-64GB`, with existing data. After this discrepancy was raised, the owner
explicitly confirmed that this was the intended spare and authorized erasing
its contents.

At inspection, the whole device was `/dev/disk16`, partition `disk16s1`, with
64,013,467,648 bytes and 512-byte sectors. It was physical, external, writable
USB media. **Disk numbers are session-specific:** inspect again before another
write. Private records under `.local/flash/` retain the original disk/partition
plists and expected volume UUID, size and reader path.

The separate original GameShell card has not been overwritten. Its full
offline backup is still outstanding. The owner authorized this spare-card
write after identification; that does not satisfy the remaining recovery or
hardware acceptance gates.

## Transfer and write

The source is the [offline-validated image from report 25](25-first-build-validation.md):

- Image: `GameShellNeo-0.1.0-diagnostic.1-cpi31-750fb8829d41.img`
- Image bytes: `4294967296`
- Image SHA-256: `750fb8829d41af96ed58db1b5e5cf6a9051799436bb69740c973afd9656e33ad`
- Transferred gzip bytes: `267878533`
- Gzip SHA-256: `f90f16fa1660fb75bc58ffff52f9bcacc6966e3195c6d619374b611d5caa6563`

The private transfer is staged on the Mac under
`~/.local/share/GameShellNeo/`, with directory mode 0700 and file mode 0600.
Both compressed and decompressed checksums passed on the Mac. The flash
helper's dry run confirmed the recorded target identity.

The first write attempt unmounted the card, then macOS denied opening its raw
device with `Operation not permitted`, despite administrator access. **No image
bytes were written.** The owner then enabled Remote Login's full disk access
and asked to retry; the new SSH session passed the same pre-write checks.
Apple documents the setting under System Settings → General → Sharing → Remote
Login → “Allow full disk access for remote users”. The permission change must
be made through the Mac's settings; an alternative is running the prepared
helper locally from Terminal. [Apple Remote Login documentation](https://support.apple.com/en-mk/guide/mac-help/mchlp1066/mac).

The retry **completed successfully**: all 4,294,967,296 bytes were written,
flushed, and read back from `/dev/rdisk16`. The readback SHA-256 exactly matched
the image hash above. macOS then successfully ejected the card. The private
`flash-result.json` and `flash.log` under `.local/flash/` record this result;
the Mac also retains the report in its private staging directory. The original
card was not the write target.

## Repeatable flashing

[`tools/flash-macos.py`](../tools/flash-macos.py) runs on macOS with Python 3.9
or later. Its default is a dry run. It checks both transfer and expanded-image
hashes, requires physical external USB media, matches the inspected size,
reader path and existing partition UUID, and checks capacity and alignment.
It checks identity again after unmounting, immediately before opening the raw
device for a write. After writing it flushes, reads back the complete image
range, compares SHA-256, and ejects only after success.

Five tests cover rejection of internal, virtual, read-only, changed, undersized
and wrongly identified targets, including reuse of the same disk number for a
different volume. Run them with:

```sh
python3 -m unittest discover -s tools/tests -v
```

On the Mac, use the privately staged `transfer.json`, `target.json`, helper and
gzip file. The current `target.json` describes the original spare contents;
after flashing, its volume UUID changes, so another flash requires a fresh
inspection and target record. Never reuse a stale disk identifier.

```sh
cd "$HOME/.local/share/GameShellNeo"
python3 flash-macos.py \
  --image GameShellNeo-0.1.0-diagnostic.1-cpi31-750fb8829d41.img.gz \
  --manifest transfer.json --target target.json
```

Once the owner has identified and authorized the target, add `sudo`, `--write`
and `--report flash-result.json` to perform the write and save its evidence.
This writes the image's 4 GiB range; it is not a secure erase of the whole card.
The first image has a fixed root partition and does not expand to use 64 GB.

## First boot and acceptance

**The first physical boot succeeded.** The owner reported the console banner
and then confirmed `gameshellneo login:`. Wi-Fi SSH authenticated against the
new per-device host key, and the installed image identity and kernel matched
the build. After the USB fix below, SSH also worked through Intel → Mac → USB.

| Check | First-boot observation | Remaining qualification |
| --- | --- | --- |
| System | Debian 13, `6.18.54-gameshellneo1`, Samsung card with fixed 128 MiB boot and roughly 3.9 GiB root partitions | Repeated cold starts and recovery |
| CPU and memory | Four CPUs online; 1001 MiB reported usable RAM; about 68 MiB used in the initial sample | CPU/memory load and long-run stability |
| Display | Owner sees login console; sun4i DRM framebuffer active at 320×240 | Visual quality, transitions and initialization independently of the old bootloader |
| Backlight | OCP8178 driver bound; brightness/actual brightness 1 of 31 | Levels, physical off and restoration |
| Input | USB keypad (`4242:e131`, `rancidbacon.com UsbKeyboard`) and AXP power key registered | Every press/release and orderly power-button shutdown |
| Wi-Fi | Provisioned network and authenticated SSH work with the captured BCM43430/0 firmware | Reconnection, unavailable-AP behavior, regulatory configuration and power |
| USB | After NEO-6, ECM configured at high speed; Mac `en8` received a lease; authenticated USB SSH succeeded | Ten physical reconnects and post-fix cold boot |
| Battery | Valid readable telemetry, 100%, charging; reported voltage varied from approximately 4.256 V to 4.202 V during inspection | Calibration, pack specifications, charging transitions and endurance |
| CPU power management | `cpufreq-dt`, `schedutil`, advertised 120–1008 MHz OPPs; sampled frequency changes from 648 to 1008 MHz | Full OPP/voltage stability and representative idle efficiency |
| Temperature | CPU thermal zone read approximately 42–43°C | Sensor calibration and sustained-load behavior |
| Filesystem policy | Actual ext4 options include `data=ordered`, barriers and `commit=5` | Storage load and interrupted-power qualification |
| Runtime health | After USB correction, required services active/successful, USB restart count zero, kernel taint zero | Longer observation and repeated starts |

The captured kernel log contains no observed panic, oops or storage I/O fault.
Firmware filename fallback messages and the warnings listed below remain;
this is not a claim that the log is warning-free. Battery values are software
readings, not physical voltage/current measurements or proof of a calibrated
percentage. No charger, gauge or current-limit setting was changed.

`systemd-analyze` reported **2.456 s kernel + 19.783 s userspace = 22.239 s**
for this first boot. The local readiness marker was written at approximately
**17.166 s** on the monotonic clock. These omit pre-kernel/bootloader time and
do not establish power-button-to-visible-readiness latency. The first boot
included setup work and the USB retry defect; record subsequent boots
separately rather than treating this as an optimized result.

### USB startup correction — NEO-6

The initial `systemctl --failed` snapshot showed no failed units, but the USB
service was actually cycling through automatic retries. Explicit service-state
and journal inspection found `EINVAL` when writing literal `usb0` to the ECM
configfs `ifname` attribute. Linux's `gether_set_ifname()` requires an allocation
template containing exactly one `%d`.

Commit `64c5c43` changes the runtime to write literal `usb%d`, then verifies
that the allocated name is `usb0` to match networkd. An unexpected allocation
is cleaned up. Bash syntax and ShellCheck passed. The corrected script was
installed on the diagnostic card over Wi-Fi; the original was preserved, and
`/etc/gameshellneo/neo6-runtime-change.json` records both hashes. Initial start
and a subsequent stop/start completed successfully. USB SSH used the expected
new host key, and the observed connection endpoints confirmed the USB route.

The installed script SHA-256 is
`872b775781f36bc02644013e6666492ac4ca29ffb978567cd6a2097193a02daa`, matching
the repository source. **The original `750fb8829d41` image artifact still
contains the old script.** The NEO-8 task-runner rebuild includes the correction;
use the current verified bundle for a future fresh flash. The existing card
already has the fix.
These software restarts do not count as physical USB reconnects or cold boots.

### Remaining integration findings — NEO-7

The list below records the initial assessment. [Report 27](27-diagnostic-integration-refresh.md)
corrects the regulatory-database diagnosis: the package was already installed,
but cfg80211 requested it before root was mounted and its selected signing key
did not match this upstream kernel. The owner has since confirmed `NZ`.

- The image lacks `regulatory.db`. Confirm the owner's country and add the
  appropriate signed database; do not infer location from timezone.
- The kernel lacks `CONFIG_EXT4_FS_POSIX_ACL`, and journald reports inability
  to set its user-journal ACL. Root diagnostic collection still works.
- DHCP attempted to change the fixed hostname and was denied. Review the
  explicit networkd hostname policy.
- Review unused distro sysrq/ALSA rules, duplicate global/interface
  wpa_supplicant processes and the BPF firewall support warning.
- Classify clock-frequency, GPIO-supply, DMA-mask and USB-PHY warnings against
  the actual driver requirements and board schematics before changing them.
- Preserve the working firmware fallback while checking optional CLM/txcap
  data and redistribution provenance; the missing optional-file messages did
  not prevent the observed Wi-Fi connection.

Private evidence is under `.local/hardware-validation/2026-09-27/`, including
the original boot log, service states, CPU/power/input/display observations,
USB deployment and SSH checks, and a post-fix diagnostic archive. NEO-7 tracks
the remaining integration fixes and their subsequent rebuild; NEO-5 remains open for
hardware acceptance and the original-card backup.

### Physical preparation record

After the successful verified write and eject, the owner was given this sequence:

1. Shut down the GameShell normally and disconnect USB power.
2. Remove the original card and put it in the Mac's reader for a read-only
   offline backup, then insert the Samsung spare into the GameShell.
3. Reconnect the known-working USB data cable to the Mac and turn on the GameShell.
4. Establish USB SSH at `192.168.10.1` using the new per-device host key and
   development key. Wi-Fi is a separately provisioned fallback.
5. Capture the boot log, bound drivers, failed units, display/input observations,
   battery data, and frequency/temperature readings before changing settings.

One cold boot is observed. The ten-boot and ten-USB-reconnection acceptance
sequences, complete control/display checks, CPU/storage stability, supervised
power tests and offline original-card backup remain open. No external card was
visible on the Mac during this check, so that backup did not start. Serial
remains deferred. This establishes an initial working system, not reliability,
sleep/resume behavior or battery-life targets.

## Shared workflow validation — NEO-8

The [Taskfile workflow](../README.md#shared-task-commands) was exercised on
2026-09-27 using Go Task 3.53.1. Provisioning read the owner's Wi-Fi settings
from the private `.env` and retained the existing device identity. A real
`task build:image` rebuilt and verified the 4 GiB image with the USB fix;
`.local/artifacts/verification.json` identifies the current bundle. This is a
new artifact, separate from the first physically tested `750fb8829d41` image.

The final NEO-8 bundle is
`GameShellNeo-0.1.0-diagnostic.1-cpi31-8e3551bcc08d.img`, SHA-256
`8e3551bcc08d6bdd0b4dbfbfea2307cc0f5fda01e5591c602bb9b009d1fcf5e9`.
Its recorded hashes match all 63 current project inputs, including the Taskfile.

Validation passed: 16 Python tests, compiled current-selector regressions,
Bash syntax/ShellCheck, the 125 kernel configuration assertions and 13-file
kernel manifest, and device-tree binding/DTB validation. The command wrapper
preserves build failures and keeps previous logs. Argument handling preserved
spaces and literal shell syntax in a device command. Invalid disk identifiers
were rejected before connecting to a host or accessing a disk.

The new commands reached the running board over Wi-Fi and over USB through
the Mac. Required services were active/successful with zero restarts, no failed
units and zero kernel taint. Diagnostic collection downloaded a private archive
to `.local/diagnostics/`. `task mac:stage` uploaded the compressed image and
verified both compressed and decompressed checksums on the Mac without a card.
No additional physical write, reboot, cold start or reconnect test was made.
The new inspection/write guards have host regression coverage; a future spare
card session must validate the complete Taskfile flashing path on hardware.
