# MUSB system-sleep connection candidate (NEO-95)

3 October 2026, Pacific/Auckland. Diagnostic.18 is being prepared to test an
underlying USB controller lifecycle correction. The installed diagnostic.17
remains unchanged after the [failed actual-sleep attempt](125-traced-rtc-wake-usb-failure.md).
Its RTC wake, keypad, Wi-Fi and owner-confirmed dim console returned, while USB
did not enumerate again. The failure remains authoritative; source tests do not
requalify it.

## Ownership change

[Patch 0025](../kernel/patches/0025-musb-system-sleep-pullup.patch) implements the
controller-owned disconnect described in [the source audit](126-musb-system-sleep-design.md).
The temporary gate applies only to a fixed peripheral whose system-wake policy
is disabled, excluding preserve-session controllers. Host, OTG and wake-enabled
peripheral system-sleep paths do not acquire this gate.

| Stage | Candidate behavior |
| --- | --- |
| Suspend admission | Obtain the existing runtime-PM reference first. On failure, balance it and return without touching the pull-up or gate. |
| Quiesce connection work | Set `gadget_suspended` under the controller lock. Pull-up requests keep updating `softconnect` but cannot queue connection work. Existing workers check the same gate. Cancel/drain outside the lock. |
| Detach | Clear SOFTCONN while the runtime reference is held, before disabling the platform, interrupts or session. Do not overwrite requested connection intent. |
| Save/restore context | Save the detached state. Independently mask SOFTCONN during gated restoration so even stale saved context cannot reconnect early. Preserve existing SUSPENDM/RESUME handling. |
| Resume | Restore controller/endpoint registers, enable interrupts/platform and execute pending resume work. Under the lock, clear the gate and apply the latest intent only if a gadget driver remains bound. |
| Resume-work failure | Preserve the first callback error through later callbacks. Keep the gate and physical disconnect, release the system-PM reference, and return the error from the gated system-resume path. |
| Unregister/remove | Stop clears intent and the driver pointer under the controller lock and removes the pull-up. Cleanup drains work after UDC unregister, including work queued by unregister itself. |

The ordinary gadget worker now checks `pm_runtime_resume_and_get()` and avoids
register access on failure. Successful work still takes/releases only its own
temporary PM reference. Outside system sleep, its connection decision also
requires a bound gadget. Start publishes its reset intent and driver under the
same lock used by these decisions.

The gate is a separate `bool`, rather than another bit in the existing flag
word: some older neighboring flags are written without the controller lock.
Separate storage prevents those read/modify/write operations from sharing the
new gate's memory location. Review caught this before installation; the kernel
build was restarted after that refinement and the 61 source scenarios passed
again. It was not an observed hardware race.

No gadget disconnect callback was added. The normal interrupt/reset paths own
protocol teardown and enumeration; raw interrupt acknowledgment and stage-0
ordering remain unchanged. The patch does not set carrier or configuration
state to simulate a recovered connection. A later-device suspend abort takes
the ordinary MUSB resume path; physical host detection of a very short abort
still needs separate hardware evidence.

## Sunxi readiness and wake policy

The fixed CPI peripheral uses `PHY_MODE_USB_DEVICE`. The pinned Sunxi glue's
system disable only clears its enabled flag; it does not power down its clock
or peripheral PHY. Its resume work controls host VBUS/role transitions and
requested mode changes. Fixed-role mode changes are rejected; the PHY's
peripheral mode supplies the fixed device-side ID policy. The existing PHY PM
patch drains detection work and schedules cable reconciliation on resume; it
does not shut down the initialized PHY. The candidate therefore reconnects
after controller readiness, without treating a newly scheduled glue worker as
proof of asynchronous hardware completion. Cable changes during sleep and
non-Sunxi glue remain unqualified.

A read-only check found the installed MUSB device's system-wake policy enabled:
`/sys/class/udc/musb-hdrc.2.auto/device` resolves to the controller at
`/sys/devices/platform/soc/1c19000.usb/musb-hdrc.2.auto`. The new image's
[gadget startup script](../runtime/usr/local/sbin/gameshellneo-usb) explicitly
selects `power/wakeup=disabled`, checks readback, and does so even if the gadget
is already bound. This expresses the product's POWER/RTC wake policy and the
owner's acceptance that USB may disconnect during sleep. It is not a userspace
reconnect operation and changes no charging settings.

The source lock records `features.usb_system_wakeup=false`. Offline rootfs
verification requires that setting and the exact startup script. PM admission
requires one controller reporting disabled; missing, enabled or ambiguous
readings fail. USB metadata capture records the live policy. Earlier images
without this feature retain their old evidence interpretation.

This flag alone does **not** balance MUSB's unconditional probe-time
`enable_irq_wake()` reference. IRQ-wake ownership remains a separate follow-up;
this image must not be described as having repaired hardware wake routing.

## Reproducible source checks

```sh
task test:musb-sleep
task check:musb-sleep-drivers
task check
```

The test extracts the pinned, hash-verified Linux source, applies the relevant
MUSB patches with zero fuzz, and compiles the actual PM, pull-up, worker, stop,
cleanup, context and pending-work functions. Deterministic API/register shims
check role/wake/quirk eligibility, connection intent, bound/unbound drivers,
work admission/draining, early restore, PM reference failure/balance, resume
failure, later-device abort, stop and unregister-generated work. Runtime-style
ungated context restoration must preserve its previous pull-up behavior.

Native and emulated ARM32 executions pass 61 scenarios, including
already-disconnected intent with and without queued work. Eight faulty
variants are required to fail: omitted detach,
ignored latest intent, ungated worker, premature context reconnect, reconnect
despite resume failure, loss of the first callback error, enqueue during the
gate and omitted stop-time disconnect. The complete ARM `musb_core.o`,
`musb_gadget.o` and `sunxi.o` compiled in isolated scratch before image assembly.
These are source/integration checks, not real scheduler or electrical timing
tests. Host-only and dual-role kernel configurations are not hardware-qualified.

Four startup-script tests run the real script against isolated sysfs/configfs
fixtures, including repeated startup, missing/ambiguous controllers, bad policy
and failed readback. PM admission tests cover wrong or missing wake policy.
Repository checks pass: 13 runtime tests, 457 tooling tests with one existing
optional skip, compiled selector/mount-guard checks, Bash syntax and ShellCheck.

Local evidence is retained under `.local/build/musb-sleep-tests/`,
`.local/build/musb-sleep-drivers.log` and `.local/neo95-check.log`.

## Image and next hardware boundary

Diagnostic.18 uses Linux 6.18.54 with local version `-gameshellneo18`. It adds
patch 0025 and [patch 0024's trace formatting correction](127-usb-endpoint-trace-format.md),
plus the explicit USB wake policy. CPU-idle configuration is unchanged to keep
the USB comparison focused. Normal sleep stays masked; no production sleep,
latency or battery-life claim is made.

The shared build task is running after a verified diagnostic.17 checkpoint at
`.local/recovery/diagnostic17-before-musb-sleep-fix/` and archived kernel state at
`.local/previous-kernels/20261003T103010Z-1155126/`. The interrupted first
candidate's partial build is separately archived at
`.local/previous-kernels/20261003T104418Z-1181147/` and is not a recovery image.
Artifact verification and
transfer details will be recorded when complete. No new image is installed yet.

After card installation, collect a fresh boot baseline and verify the new wake
policy and trace format. Requalify freezer, driver and late/noirq stages with
fresh screen observation, then create a same-source awake RTC rehearsal. A
separately attended real sleep must show fresh USB enumeration, ECM activation,
carrier, independent USB and Wi-Fi SSH, unchanged boot/keypad identity, normal
display and complete PM/RTC/trace restoration. Only then repeat real sleep and
test cable absence, reconnect and host sleep separately. Diagnostic.17's
consumed prerequisites and failed result cannot authorize or pass those tests.

The failed boot remains untouched during preparation, including its retained
diagnostic power-key suppression. A later controlled shutdown or reboot must
account for that guard rather than instructing the owner to use the currently
suppressed short press.
