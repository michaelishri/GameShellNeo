# Diagnostic.6: direct USB diagnostics and pinned A0 firmware

Date: **29 September 2026 NZDT**. Tickets: **NEO-28**, **NEO-31**;
physical USB qualification continues under **NEO-22**.

Status: **built, offline-verified and packed on the Intel host; transfer,
flashing and hardware qualification pending**. The last connected board
was running diagnostic.5. The owner is disconnecting for travel; large
transfers must wait for the Mac to reconnect on a non-hotspot network.

## Why this image

The completed [battery comparison](45-usb-polling-idle-comparison.md) showed
about 72% fewer aggregate PMIC bus interrupts with experimental polling. It
did not resolve an energy saving or measure USB poll callbacks directly.
Diagnostic.6 supplies that missing measurement and a narrow recovery test.

It also incorporates the exact BCM43430 revision-0 firmware candidate from
[reports 48](48-a0-firmware-trials.md) and
[49](49-connected-firmware-validation.md). That candidate passed bounded
AP-unavailable scans, association and four software reconnects. Cold-start,
long-term, sleeping and energy behavior remain unqualified.

The image identity is **0.1.0-diagnostic.6**, kernel
**6.18.54-gameshellneo6**. Linux, compiler container, Debian snapshots,
bootloader, board NVRAM, charger configuration and polling intervals retain
their existing pins/policy. Sleep remains disabled. Diagnostic.4/5 and the
original-card backup remain recovery paths.

## Verified artifact

| Item | Value |
| --- | --- |
| Image under `.local/artifacts/` | `GameShellNeo-0.1.0-diagnostic.6-cpi31-1e1f931ccf1a.img` |
| Image size | 4,294,967,296 bytes (4 GiB) |
| Image SHA-256 | `1e1f931ccf1aa907353655dd5d186d6c24ee04c89394553fcd095ded16c475a7` |
| Transfer archive under `.local/flash/` | `GameShellNeo-0.1.0-diagnostic.6-cpi31-1e1f931ccf1a.img.gz` |
| Compressed size | 264,330,876 bytes (about 264 MB) |
| Archive SHA-256 | `08d60bcc99ab090aef437ceea935bbc6fb12761f634bda83bb23e7a528a32fa2` |

`task build` and `task image:pack` completed successfully. The bundled image
manifest matches the final project source inputs. All eight pre-existing image
hashes still match the archived pre-build checksum manifest. No image was
transferred to the Mac or written to a physical card in this work.

## Driver interface and cost

[Patch 0009](../kernel/patches/0009-axp-usb-diagnostics.patch) wraps only the
initial `AXP20X_PWR_INPUT_STATUS` read in `axp20x_usb_power_poll_vbus()`.
The independent, runtime-read-only
`axp20x_usb_power.gameshellneo_diagnostics=1` boot option exposes:

| Path below `/sys/kernel/debug/gameshellneo-usb/` | Access | Meaning |
| --- | --- | --- |
| `status` | root read, 0400 | One coherent JSON snapshot; reopen for the next snapshot. Read with a buffer of at least 4096 bytes. Short buffers fail rather than splice snapshots. |
| `control` | root write, 0200 | Exact command below; optionally one trailing newline. Unknown text, embedded NULs and oversized writes fail. |

Commands are `enable`, `disable`, `disarm`, and `inject 1` through `inject 4`.
`enable` starts a new counter generation, initially with zero observations;
it fails if already enabled or a counted callback is in flight. `disable`
turns observation off and clears the unused fault budget. `disarm` clears
the budget without resetting counters. Neither changes PMIC registers.

Both stock and experimental boots require the same complete existing
CPI/A33/AXP223/topology/USB-role/IRQ/PMIC gate for diagnostics. The policy's
own opt-in remains independent. With both boot options off, neither gate
adds configuration reads. An opted-in probe exposes files only after all
interrupt handlers have been registered.

Counting defaults off, including on the diagnostic image. The disabled
callback path checks a boolean and uses the original register read. Enabled
counting adds two short spinlock sections per callback, without per-callback
allocation, timestamps or printk. Status reads allocate their formatting
buffer and take a monotonic timestamp at snapshot time. The saved device
task reports its own userspace CPU time; the incremental kernel counter cost
has not been measured on hardware.

Snapshots contain actual entries, completed callbacks, successful reads,
real errors, injected errors, in-flight count, generation, policy, enabled
state, unused error budget, retained status and synthetic-request count.
`status_valid` means a counted completion has copied the driver's retained
software status into this generation. It is not a freshness/success flag:
an error can retain the driver's initial zero or an earlier unobserved value.
Use `success`, the error counters and the bounded event results to distinguish
a successful read from retained state; never treat it as a physical measurement.
Counters are coherent on ARM32: entries equal completed plus in-flight;
completed equals successes plus both error classes. A callback admitted
before `disable` still completes in its original generation; a new generation
cannot reset its counters before it finishes.

The timestamp follows the locked state copy. It is a userspace diagnostic
endpoint with small sampling skew, not an electrical edge timestamp. Nominal
50/250 ms delays do not guarantee exactly 20/4 callbacks per second because
worker scheduling and execution also take time.

## Error-test boundary and recovery

An accepted `inject N` command arms **at most four** skipped poll status
reads for **one second**, returning `-EIO` at that call site. Expiration is
checked against kernel jiffies before consumption and when controls/status
are accessed. Later cable activity cannot consume an expired budget.
An overlapping request is rejected, including during the original request's
unexpired interval after its budget has been consumed.

The command makes one explicit synthetic work request because connected
polling normally stops. `queue_delayed_work()` preserves an existing work
deadline. Synthetic windows are excluded from natural count comparisons.
Normal property reads, shared regmap users, hardware IRQs and PMIC writes
are unaffected.

At most eight completion records are retained around that request. Each
contains the result, whether it was injected, retained status and requested
retry interval. Recording stops at the first successful real read or the
array bound. Retry intervals describe the callback's scheduling decision;
an already queued IRQ may determine the actual execution deadline.

Experimental read errors retain `old_status`/`online` and request the existing
50 ms retry even when previously online. Stock preserves its historical
`needs_polling && !online` decision: a stock online failure can stop polling
after one injected error; the remainder expires without automatic recovery.
The script checks this difference rather than treating stock as experimental.
Only a later hardware cable test can establish physical IRQ recovery.

## Lifetime and concurrency review

The diagnostic lock and control mutex are initialized immediately after
allocation, before IRQ registration or any possible callback. All counter
fields use the spinlock; the fast enabled check uses `READ_ONCE`, followed
by a locked recheck. A stack-local admission flag pairs entry and completion.
The control mutex serializes command changes and the explicit work request;
the worker never takes that mutex. No regmap access, user copy, formatting,
allocation or workqueue operation occurs under the diagnostic spinlock.

Files use ordinary `debugfs_create_file`, whose locked Linux 6.18.54
`fs/debugfs/file.c` full proxy protects active reads/writes with
`debugfs_file_get/put`. `simple_open` does not replace that proxy. No custom
release operation dereferences driver data after removal. The devm cleanup
action is registered after IRQ resources, preserving reverse teardown:
**remove diagnostic files → release IRQs → cancel work → remove supply → free
memory**. Partial file creation and cleanup-action allocation failures unwind
through the same order.

The host harness models that proxy contract and checks an open descriptor
after device removal, but does not execute concurrent VFS removal in a live
kernel. It is not a substitute for kernel concurrency or hardware testing.

## Firmware and build provenance

The [source lock](../build/sources.lock.json) now pins:

| Input | SHA-256 |
| --- | --- |
| Upstream `brcmfmac43430a0-sdio.bin` | `ad85074b7919517d7e1a7e463e0176d46e7b312216bd7aa372e4aee2bfe8e07a` |
| Matching `LICENCE.broadcom_bcm43xx` | `b16056fc91b82a0e3e8de8f86c2dac98201aa9dc3cbd33e8d38f1b087fcec30d` |
| Owner's original board NVRAM | `5f977a2a3916ef795ceb184cf928231d587249606d1750dacecb5f16ed941ae6` |

Firmware and license URLs use linux-firmware commit
`58a9869598b606fc2e5531298932b8757292f9a0`. `task prepare` downloads and verifies
them on the Intel host, then stages them from a verified content-addressed
cache. The NVRAM stays owner-supplied, exact and private. The image installs
the license beside the firmware and verifies all three hashes offline.
The image remains private and marked hardware-unqualified.

The expected runtime message is **7.13.53.9 (r664949), May 29 2017,
FWID 01-130000**; its binary footer separately says **01-93c3a6da**.
Do not confuse those identities. The original binary remains in the private
hardware reference and diagnostic.5 recovery image.

The build exposed an existing patch-queue validation limitation: concatenated
`patch --dry-run` checked a later overlapping patch against an unchanged file.
Validation now replays the complete queue in scratch containing only its input
files, with zero fuzz, before applying that same sequence to source. A regression
proves a later failure leaves the original source untouched.

## Verification and saved qualification sequence

Host verification currently completed:

- `task check`: 13 runtime tests and 157 tooling tests, with one optional
  systemd integration test skipped; C current-selector/mount-guard checks and
  shell lint passed. Private log: `.local/build/diagnostic6-host-checks.log`.
- `task check:usb-policy-driver`: actual patched callbacks/probe ran natively
  and on ARM32; the complete ARM driver compiled successfully in isolated
  scratch. Evidence: `.local/build/usb-policy-tests/compile-evidence.json`.
- The full kernel build, NKMP, USB lifetime/policy and NM/NKM clock-range
  stages passed. The new kernel is `6.18.54-gameshellneo6`.
- `task test:usb-policy-board`: **4,665 gate/state/race cases**, **160
  probe/unwind cases** and **96 diagnostic scenarios** passed on native and
  ARM32 runs against the actual **184-node** compiled DTB. All eight negative
  controls failed as intended: absent interval, IRQ deadline, fault bound,
  expiry, state retention, in-flight reset, file cleanup and cleanup order. Recorded input
  hashes match the final source/test files. Evidence:
  `.local/build/usb-policy-tests/board-evidence.json`.
- Binding/schema validation completed with **no diagnostics**. Complete image
  assembly and offline checks passed: MBR boundaries, bootloader readback,
  FAT16/ext4 checks, boot CRCs/load addresses, kernel/DTB/module hashes, radio
  and license hashes, signed regulatory database, private identity/permissions
  and service policy. Logs: `.local/build/devicetree.log`,
  `.local/build/image.log` and `.local/build/image-verify.log`.
- The final cleanup-order negative control was added during assembly and
  verified in a post-build `task test:usb-policy-board` run. The final USB
  script validation change also passed its six targeted host tests. These
  checks changed no image contents; image source-input hashes still match.
- `task image:pack` verified the full source-image hash while producing the
  local transfer archive and its compressed-file hash. Mac transfer/readback
  remains a later step, not an inferred success from local packaging.

The standalone ARM object SHA-256 is
`466ded561f575ff29abee61d8e9c129f72c124af78cff1c2f9765885a1b0333a`.
The complete kernel build produced a byte-identical USB driver object.
Object checks and deterministic shims do not prove live kernel concurrency.

The diagnostic.5 kernel/source/module stage and prior artifact metadata were
archived under `.local/previous-kernels/20260929T084115Z-907738/` before the clean
build. The existing diagnostic.4 and both diagnostic.5 image artifacts remain
under `.local/artifacts/`. No preserved recovery card/image was overwritten.

The README documents `device:usb-counts`, `device:usb-errors` and
`device:usb-diag-restore`. The host wrapper uploads the checked-in script and
runs it in a bounded systemd service. A device-side `ExecStopPost` hook restores
owned controls even if the host connection is lost. Kernel error bounds do not
depend on either host or userspace staying alive. Private captures record
boot identity, image/kernel, actual policy, exact settings and before/after
snapshots; unsuccessful tests retain their helper for diagnosis/recovery.

Known active test observers are rejected at the endpoints. Do not start other
profilers, fast sysfs readers or cable tests within a natural count window;
the endpoint guard cannot detect an arbitrary observer that starts and stops
between those checks.

After offline verification and staging on the Mac's non-hotspot network:

1. Flash/read back the separately identified Samsung DEV card, then verify
   diagnostic.6 identity, USB SSH, battery guard and kernel/service health.
2. With a supported 2.4 GHz network available, verify the candidate's loaded
   firmware identity and Wi-Fi SSH. Complete a saved four-cycle cold-start
   batch and bounded AP-absent/reconnection checks. Keep NEO-31 open until those
   results are recorded.
3. Run connected count/error tests in both stock and experimental boots,
   then matched unplugged natural counts over Wi-Fi with other observers stopped.
   Check real errors separately from injected ones and restore controls off.
4. Repeat physical USB recovery checks after the injected window, and qualify
   counter/observer cost if it matters to the next battery comparison. Preserve
   diagnostic.5's original-firmware measurements as their own baseline.

Further RSB autosuspend-delay work remains a separate experiment. This image
does not change that delay or attribute an energy improvement to diagnostics
or firmware replacement.
