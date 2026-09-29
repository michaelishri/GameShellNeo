# Diagnostic.5 USB polling experiment

Date: **29 September 2026 NZDT**. Preparation: **NEO-21**;
hardware qualification: **NEO-22**.
Target: the owner's **CPI v3.1**. Hardware qualification is pending.

The subsequent [remote-network preparation](42-remote-network-preparation.md)
records the private provisioning refresh for the owner's current Wi-Fi network.
The original preparation artifact below remains the historical build record.

## Purpose and status

The owner approved implementing the [report 36 design](36-usb-polling-policy.md)
and preparing a test image overnight without interactive input. Diagnostic.4's
tested baseline is retained; see [report 40](40-diagnostic4-hardware-validation.md).
This work adds the opt-in policy, reusable regressions and boot selection.
The full diagnostic.5 build and offline image verification passed. No card has
been flashed, device rebooted or battery improvement measured during this preparation.

The driver defaults off. Diagnostic.5 explicitly selects the experiment in
its source lock and boot script, subject to runtime eligibility:

```text
axp20x_usb_power.gameshellneo_slow_poll=1
```

The parameter is read-only at runtime. Both stock and experimental boot scripts
are included for comparisons without repeated reflashing. A board match alone
never activates the experiment.

## Driver behavior and eligibility

[Patch 0008](../kernel/patches/0008-axp-usb-absent-poll.patch) uses
[the generated policy header](../kernel/overlay/drivers/power/supply/axp20x_usb_gameshellneo.h).
Patch 0006's work-lifetime correction remains in place.

| Situation | Behavior |
| --- | --- |
| Parameter off or gate refused | Existing polling behavior |
| Eligible probe | Request a fresh immediate read, including after an early IRQ |
| Successful absent and unused VBUS reading | Next recurring read after 250 ms |
| Present but unused, or used without present | Retry after 50 ms |
| Read failure | Retain previous valid state; retry after 50 ms, including previously online state |
| Successful present and used reading | Existing IRQ-driven operation; no recurring offline poll |
| IRQ | Immediate supply notification and existing 50 ms debounced read |
| Probe failure or teardown | Release IRQs, cancel work synchronously, then release the supply |

Experimental recurring work uses `queue_delayed_work()` so it cannot replace
an IRQ's pending fast deadline. IRQs retain `mod_delayed_work()` and can bring
a slower timer forward. `READ_ONCE`/`WRITE_ONCE` publish the eligibility flag;
it stays false during IRQ registration, so early work uses stock behavior.

All gates are required:

- Explicit opt-in, CPI3/A33 root compatibles, actual AXP223 variant and matching
  PMIC/supply nodes. Software compatibles do not distinguish every board
  revision; physical qualification remains limited to the owner's v3.1.
- Gadget-only sunxi MUSB, with host/dual-role, system sleep and dynamic device
  tree changes disabled. The build workflow also asserts these settings.
- Exactly one enabled A33 PHY using this supply and one enabled A33 MUSB
  consumer of PHY port 0, explicitly peripheral. Disabled ancestors and
  malformed/ambiguous references are handled conservatively.
- MUSB's inherited `extcon` must reference the same PHY, port 0. Alternate
  providers/ports, role switches, GPIO detection and USB0 sources are refused.
  USB1's separate EHCI/OHCI keypad consumers remain allowed.
- No PMIC drive-VBUS property; both expected IRQ registrations succeeded;
  successful configuration reads with `0x30` bits 7/2 and `0x8f` bit 4 clear.

These normal regmap reads may be cached; they are not pin-voltage measurements.
There are no new charger/current/PMIC-mode writes, cache bypass, governor or
OPP changes, or sleep support.

Compiled-DTB review caught the inherited extcon connection. The first draft
would have refused it and retained stock polling. It was corrected before
producing the image; an actual-board fixture now prevents relying solely on
the initial hand-written topology model.

The nominal confirmed-absent rate changes from about 20 to four checks per
second: 80% fewer checks in this specific steady state, not 80% less CPU use,
RSB traffic or battery consumption. Scheduling, IRQs and errors affect actual
execution. The 250 ms timer is not a physical connection-time guarantee.

## Reusable verification

```sh
task test:usb-policy
task check:usb-policy-driver
task test:usb-policy-board       # Completed kernel's DTB; override with DTB=path
task check
```

The checker extracts the actual patched probe and poll/IRQ callbacks from the
hash-verified Linux 6.18.54 archive and includes the actual policy header.
Native and ARM32 runs each passed **4,662 policy cases and 160 probe/cleanup
cases**. Coverage includes all status bytes across cached states and read
success/failure, gate rejection, OF reference ownership, PMIC control bits,
IRQ/rearm ordering, early IRQ/work execution, partial probe and cleanup.
Two deliberately broken candidates (absent interval and IRQ-deadline rearm)
must fail the harness; both negative controls did fail as intended.

The compiled-DTB task uses the pinned builder's `libfdt` to pass all **184
nodes** through the actual C gate. The real graph is accepted; host-role and
connector-port mutations are rejected. This raises the count to **4,665 policy/
board cases plus 160 lifecycle cases**, on both native and ARM32. Both the
preserved diagnostic.4 DTB and the newly compiled diagnostic.5 DTB passed.

These are deterministic OF/register/workqueue shims and instruction emulation,
not live kernel concurrency, physical IRQ or electrical qualification.
The existing lifetime negative control, clock and current-limit regressions
remain in the shared workflow.

Host checks passed 13 runtime and 66 tool tests (one optional user-systemd
skip), current-selector regression and shell lint. Eight new boot-selection
tests cover both modes, repeated selection, invalid input, corrupt hashes/
CRCs/source, manifest names/symlinks, custom-script preservation, failed replace
and interruption between source and executable replacement.

Evidence is private under `.local/build/usb-policy-tests/`: `evidence.json`,
`board-evidence.json`, generated headers and binaries. These record input hashes,
negative controls and native/ARM32 results. `compile-evidence.json` records the
preliminary full ARM object build before the extcon refinement; the complete
final kernel build supersedes it for the final artifact. Build logs use the
standard `.local/build/` stage names.

The final kernel build passed **136 configuration assertions** and recorded
**15 kernel/module artifacts**. Schema and DTB validation produced no diagnostics.
Its configuration and DTB are byte-identical
to diagnostic.4:

| Artifact | SHA-256 |
| --- | --- |
| Resolved `.config` | `088d97999930260b6d8dd163df46a50487d48648a3a16841245d62434787de2e` |
| Compiled board DTB | `8280b127316f641aab60a1d341832adfc4fbc7cec3ae65a559bbd33224b40cd4` |

## Select the policy for the next boot

```sh
task device:usb-policy ROUTE=usb                    # Running/next-boot status
task device:usb-policy ROUTE=wifi MODE=stock        # Stock on the next boot
task device:usb-policy ROUTE=wifi MODE=experimental # Experiment on the next boot
```

[usb_poll_boot.py](../tools/usb_poll_boot.py) verifies image identity, mounted
`/boot`, all variant hashes, U-Boot CRCs and exact source/compiled pairs before
selection. It writes/fsyncs temporary files, replaces `boot.cmd`, then replaces
executable `boot.scr` last and verifies readback. Interruption between those
replacements leaves the previous executable selected; a later selection repairs
the informational source. This does not promise power-loss atomicity from FAT
or the SD controller. Keep the diagnostic.4 recovery image.

The task **never reboots**. The current policy stays active until a separately
requested orderly reboot/cold start. Status distinguishes the requested
parameter from the driver's acceptance/refusal message; refusal fails the
check with its reason. Stock selects parameter `0`; reverting all added code
uses diagnostic.4. Credentials remain in `.env` and captures remain private.

## Tomorrow's physical checks

1. Fresh Samsung DEV identity, verified Mac staging, flash/full readback/eject, then
   owner-confirmed normal login screen.
2. Exact image/kernel, actual policy acceptance, USB/Wi-Fi, integration,
   battery monitoring and keypad enumeration.
3. Startup with USB attached and detached; verify detached startup through
   Wi-Fi before reconnecting. Compare stock and experimental modes.
4. Recorder-ready batches of four cable cycles, plus rapid reconnection.
   Run detailed detection capture separately and retain failed/incomplete runs.
5. Matched battery-only idle comparisons after cooling, with brightness,
   governor and radio conditions recorded. The detailed detection recorder
   has substantial overhead and must not run during power comparison.
6. Qualify read-error/IRQ recovery and direct poll-call instrumentation before
   making measured-work claims or generally enabling the policy.

The unchanged diagnostic configuration has neither KPROBES nor FTRACE enabled.
Aggregate RSB interrupts are **not direct USB poll-call counts**. Host tests
prove scheduling decisions, not measured on-board call rates. Low-overhead
function-count instrumentation remains a follow-up; this image does not silently
enable tracing. No measured battery saving is claimed.

Physical connection timing, charging (NEO-10), broad acceptance (NEO-5), pack
capacity, endurance and sleep remain separate work.

## Artifact and recovery

Candidate: `0.1.0-diagnostic.5` / `6.18.54-gameshellneo5`, with source-lock
`experiments.usb_absent_poll: true`. Hardware remains unqualified.

- File: `.local/artifacts/GameShellNeo-0.1.0-diagnostic.5-cpi31-9f5e99c48e6f.img`
- Size: **4,294,967,296 bytes** (4 GiB).
- SHA-256: `9f5e99c48e6f0f2364bc636698eb2e87c6926d5c244f984344789dc963312524`.
- Offline checks passed: partition boundaries, bootloader readback, FAT16/ext4
  integrity, U-Boot CRCs/load addresses, kernel/DTB/modules/radio hashes,
  private identity/permissions and service policy. Both USB-policy script
  variants passed their hash, CRC and exact-source checks.
- Image provenance and verification are under `.local/artifacts/`; full stage
  logs are under `.local/build/`, including `image-verify.log`.

The repeatable preparation used `task kernel:reset`, `task build` and
`task check`. Mac transfer uses `task mac:stage`; it packs the verified image
and checks the compressed and decompressed source on the Mac without writing a card.
The Mac transfer passed: both compressed and decompressed checksums were
verified by the Mac's source-only check. The archive and transfer manifest are
ready in `~/.local/share/GameShellNeo/`. The Mac had no external card inserted;
no card inspection, flash or device reboot was requested.

- Compressed size: **264,463,020 bytes**.
- Compressed SHA-256: `e7cbc1e9fff3ad0b8ddfa8440b40db6938851feb4ab9f3be42aab84e77711f93`.
- Local transfer manifest: `.local/flash/transfer.json`.
- Transfer evidence: `.local/build/neo21-mac-stage.log`.

Diagnostic.4 source/output/modules and metadata are preserved at
`.local/previous-kernels/20260928T114349Z-766265/`. Its existing 4 GiB image
remains in `.local/artifacts/`; its SHA-256 was rechecked successfully:
`99e1abf3102c76afbad2dff99c98ad9dedceccef23734225d482f03a35d8dec3`.
The initial partial diagnostic.5 build was stopped for the gate correction and
archived through the reset task; it is not a completed candidate image.
