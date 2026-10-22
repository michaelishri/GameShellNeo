# MUSB role registration cleanup after failed probe

9 October 2026, Pacific/Auckland. NEO-164, a bounded NEO-106 continuation on
`work/musb-probe-unwind`, based on reviewed source commit `2d40f6f`. NEO-108's
image installation remains parked. No image or live device change is included.

## Problem and scope

The partial-initialization audit in [report 141](141-musb-removal-backend-contracts.md)
identified a gap in `musb_init_controller()`: successful host or gadget setup
publishes an HCD or UDC before `musb_platform_set_mode()` runs. A mode-setting
error then jumps to `fail3`, which releases controller resources without
unregistering those successful role registrations. Dual-role setup already
unwinds its host when gadget setup fails, but does not unwind either role on
a later mode error.

The change addresses registration ownership in that window. It does not
establish complete failed-probe or controller-removal safety. The failure is
source-observed in the shared driver; no matching CPI board failure has been
reproduced.

## Change

[Patch 0038](../kernel/patches/0038-musb-probe-role-unwind.patch) moves role
registration and mode selection into `musb_init_roles()`. Two local flags
record successful host and gadget registration. A failed setup owns no
registration to unregister; if gadget setup fails after host setup, only the
host is removed. If mode selection fails, the gadget is removed first, then
the host. The original failure result is returned to the existing `fail3`
resource cleanup.

This happens before the caller drains work or releases DMA, PHY, platform
and core allocation resources. The probe's existing runtime-PM reference
and core IRQ are still available to client cleanup. The change adds no
persistent flags, power references, background work or normal-transfer work.
Successful registrations retain their existing owner and cleanup path.
Unsupported port modes now return `-EINVAL` rather than logging an error
and publishing successful initialization without either role.

This relies on the existing setup API contracts: `musb_host_setup()` returns
an error if `usb_add_hcd()` fails, and `musb_gadget_setup()` handles its own
failed `usb_add_gadget_udc()` setup. The new flags track completed registration,
not every internal side effect. Existing PHY/OTG-pointer or timer effects
before failed registration are not claimed to be repaired by this change.

## Reproducible validation

Run sequentially from this worktree:

```sh
task test:musb-probe-roles
task check:musb-probe-drivers
task check
```

The first command extracts the actual helper from locked Linux 6.18.54 with
the relevant production patches. It also verifies that the only other core
change replaces the old role block with the helper call and unchanged error
jump. The fixture checks:

- Successful host, gadget and dual-role registration, including a nonnegative
  mode result, without premature cleanup.
- Two setup errors at each reachable host/gadget registration boundary.
- Three mode errors for each role, exact error preservation, only-owned
  cleanup, gadget-before-host ordering and forwarded host power budget.
- A successful retry after each failed supported-mode attempt, with no retained
  modeled registration; two unsupported modes rejected without registration.

There are **25 cases per execution, with 17 successful retry calls**, repeated
natively and under ARM32 qemu. The original source block is retained as a
negative control. Seven additional mutations omit cleanup, invert its order,
remove an unregistered role, hide a mode error or clean up successful setup.
Each must fail by assertion; timeout, build failure or arbitrary signal is
not accepted as a passing negative control.

The ARM task additionally compiles the current full patch queue's driver
objects in project gadget, host-only, dual-role and module configurations.
The module variant includes combined `musb_hdrc.o`. These are object/link
checks, not a complete image build. Receipts include source inputs,
native/ARM executable hashes, builder identity and ARM object/configuration
hashes under `.local/build/musb-probe-roles/`.

## Completed results

- Native and ARM32 candidate: all 25 cases and 17 retry calls passed.
- Original source and seven defective variants: all eight native negative
  controls failed by assertion as required. Negative controls were not run
  under ARM32.
- ARM project gadget, host-only, dual-role and module builds passed, including
  the combined module object. All recorded object/configuration hashes and
  patch identities were checked against the saved files.
- `task check`: 16 runtime tests and 814 tooling tests passed, with two optional
  tooling skips; compiled helper tests, Bash syntax and ShellCheck passed.
- Strict checkpatch on the production patch body: zero errors, warnings or
  checks. Independent standards and specification reviews found no issues.

| Artifact | SHA256 |
| --- | --- |
| Patch 0038 | `13564bf36f34e69f1102f6362e6069ee1b8805b0faafd52be67d1129563f8966` |
| `.local/build/musb-probe-roles/compile-evidence.json` | `16ee27d42792c6f5a231291ce9c565e983d90aed29798bac99c8a42dc040aa4c` |

The build log is `.local/build/musb-probe-drivers.log`; the host suite log is
`.local/neo164-host-check.log`. Receipt inputs and native/ARM executable hashes
also match. An initial fixture extraction check rejected an extra newline in
its expected caller boundary before executing any tests; its failed log is
retained under `.local/build/logs/`. Correcting that validator required no
production-patch change. The completed receipt above is the accepted result.

## Remaining NEO-106 work

The fixture controls registration and hardware APIs; it does not execute
actual USB-core registration, callbacks, physical mode changes or the entire
probe failure path in a running kernel. Its retries establish local registration
bookkeeping, not physical controller rebind reliability.

Core IRQ retirement before backend release, terminal work/timer admission,
runtime-PM and session-reference retirement, independent backend producers,
failed-power behavior and complete removal/rebind qualification remain open.
The older extcon/Sunxi lifetime candidates remain on their separate branch;
this work does not integrate them or supersede their evidence. Any later
installation needs its own image identity and appropriate attended hardware
qualification. No boot-time, power or battery saving is claimed.
