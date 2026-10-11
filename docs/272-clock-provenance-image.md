# Diagnostic.26: clock provenance integration

12 October 2026 NZDT. NEO-192. The new identity is
**0.1.0-diagnostic.26 / 6.18.54-gameshellneo25**. This is an investigation
image for the original clock regression, not a fix or PM qualification.

## Composition

`experiments.clock_provenance=true` explicitly adds generated patch
`0040-clock-provenance.patch` to the image queue. Its hooks and implementation
come directly from `kernel/candidates/clock-provenance`; the isolated UML and
ARM checks use that same canonical patch. A duplicate or different recorder
in the queue is rejected. Missing/false selectors omit it; non-boolean
selectors are errors. Other unintegrated driver candidates remain excluded.

The image enables `CONFIG_NEO_CLOCK_DIAG=y`, while Kconfig still defaults it
off. Test-only KUnit code is disabled on the board. The recorder is idle until
an owning task explicitly arms its root-only debugfs interface. It does not
record ordinary activity continuously or start a capture at boot. Its fixed
record arrays occupy 1,122,304 bytes when built in, and instrumented execution
perturbs timing; neither this image nor a clean window establishes an energy
improvement or rules out the original fault.

The kernel retains the original counter read and conversion. The bounded
record connects each selected syscall with its accepted timekeeping tuple,
counter value, CPU, namespace, final timespec and copy result. The prepared
reader in [report 270](270-clock-userspace-boundary.md) adds the returned raw
ABI buffers and C/Python conversions. [Report 271](271-clock-capture-deployment.md)
describes exact image, kernel build-ID, runtime and source admission, bounded
execution, original-result preservation and offline replay.

The ordinary image configuration checker requires the recorder and its
dependencies when selected and excludes the test-only kernel implementation.
The isolated ARM enabled/disabled variants have an explicit test flag that
changes only the recorder selection while retaining other project assertions.
Their receipts identify object-test scope; they cannot qualify an image.
`task build` now includes the canonical UML and both ARM object checks before
compiling the full image kernel.

This composition also includes the already prepared battery-clock fault
handling and evidence tooling from the current branch. Those changes retain
invalid clock evidence and degraded state; they do not clamp backwards
timestamps, clear the original fault or authorize a PM test. The installed
diagnostic.25 has not been modified.

## Recovery and reproducible build

Before changing build output, `task image:checkpoint` reverified diagnostic.25's
raw and compressed image hashes and saved matching metadata at
`.local/recovery/diagnostic25-before-clock-provenance`. Its raw image SHA-256
remains `c88d158d446b6ed14617b815ec17bfd2b3e90fee858ddd30e008ed74640aeb77`.
The existing reset task archived prior kernel source/output/module state at
`.local/previous-kernels/20261011T130715Z-1771834`; no old result was rewritten
as proof of the new image.

From `work/musb-restart-integration`:

```sh
task check
task check:clock-boundary
task build \
  BOOTLOADER=/home/mishri/workspace/clockworkpi/GameShell/Code/Kernel/v0.2/u-boot-sunxi-with-spl.bin \
  RADIO_DIR=/home/mishri/workspace/clockworkpi/GameShellNeo/.local/hardware-baseline/2026-09-27/radio-reference
task image:pack
```

Use `task kernel:reset` only when an existing completed/source tree has a
different patch queue; it archives the old state before rebuilding. The
explicit input paths matter when building inside an isolated worktree.
Private provisioning and `.env` remain outside Git.

## Validation and next hardware step

Host checks pass: **24 runtime and 1,007 tooling tests**, with one optional
skip, both existing C checks and Bash/ShellCheck. Added regressions exercise
actual patch application, selector rejection, exact canonical composition and
the two object-test configurations without dropping other project checks.
All existing driver regressions in `task build` passed. The recorder's five
real UML KUnit cases pass with KASAN/lockdep, and both ARM configurations pass
182 project assertions before compiling the timekeeping/syscall objects.
All seven hooks resolve when enabled and disappear from disabled objects.
The accepted serializer fixture also replays independently. Evidence is
`.local/build/clock-provenance-tests/compile-evidence.json`; its retained run
is `uml-ba2ec5b4933e266e/accepted-runs/8723a1389725468dbbb30b8d4b41e78f`.

The initial ARM pass stopped at the keypad policy's strict selector allowlist.
The integration now explicitly admits the boolean clock selector, which
changes no supply policy, while rejecting other unknown combinations. A test
loads the actual current image lock as well as malformed/mixed negative
controls. The complete host suite and both ARM variants were rerun after this
correction. No earlier failed result was relabelled.

The matching reader's native UBSan and ARM fixtures, raw-buffer replay and
production library checks pass: build `20261011T130856.669104Z`, 27 ARM raw
buffers, library SHA-256
`41f2dbb4b4b88e1014a1693277a64a95df39b81823ee515e70b2ce5845e680c1`.
The full kernel/image build is in progress; stage logs remain under
`.local/build/`. No completed-image claim is made until assembly and offline
verification finish.

Once verified, a physical card swap is needed. Transfer should occur on
confirmed regular Wi-Fi. After installation, collect fresh boot/runtime
identity and awake health evidence, inspect a fresh Kiyo baseline, and run
one matching bounded awake clock capture. Preserve the original result even
if admission, collection or replay fails. Do not repeat until clean or treat
a new boot's reset counters as resolution of the old failure. NEO-192 remains
open, and NEO-191/182 PM work remains dependent on the clock investigation.
