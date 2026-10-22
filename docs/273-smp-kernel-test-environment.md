# SMP kernel test environment

12 October 2026 NZDT. NEO-103. Branch `work/musb-callback-kernel`, based on
`35c6460`. A separate ARM system-emulation container is now built and its two
virtual CPU threads verified. This prepares the missing concurrency tests;
it does **not** yet run a guest kernel or qualify the MUSB callback contract.

## Why this environment is needed

The locked Linux 6.18.54 `arch/um/Kconfig` restricts `NR_CPUS` to one. The
existing UML tests are valuable for real locks, allocation and endpoint
restart/giveback behavior, but cannot exercise an atomic gadget callback
running on one CPU while unbind drains it on another. The native callback
fixture uses controlled scheduler/IRQ substitutes. Neither result should be
relabelled as the missing SMP kernel evidence.

The pinned build container has QEMU user emulation, not the system emulator.
`qemu-arm` executes ARM userspace; it does not boot an SMP ARM kernel. No
`qemu-system-arm` or `qemu-system-x86_64` executable was present on the host.

## Saved setup

```sh
task setup:kernel-qemu
python3 -m unittest discover -s tools/tests -p test_kernel_qemu.py -v
```

Setup builds a separate container from the existing immutable Armbian builder
digest. APT uses only the project's pinned Debian/security snapshots and
archive signing key. Before installing `qemu-system-arm`, it verifies both
downloaded InRelease files against the existing lock's SHA-256 values. The
resolved package inventory, emulator version and executable hash are retained.
This does not modify the original builder or any image build inputs.

Only four small public build inputs enter the Docker context. The derived
image is inspected for the expected host architecture; execution uses its
immutable local image ID. `.env`, device credentials and physical devices are
not needed. Snapshot access is needed for the initial package installation;
the VM smoke test itself runs with networking disabled, a read-only container,
no added capabilities and bounded memory/process/CPU resources.

The smoke test starts a paused ARM `virt` machine with Cortex-A15 emulation,
two CPUs and multithreaded TCG. QMP must report exactly CPU indexes 0 and 1,
ARM targets and distinct virtual CPU thread IDs, then acknowledge normal quit.
An in-container watchdog and separate host timeout bound execution. The
original container exit status is saved, then the uniquely owned container is
stopped, inspected and removed only after terminal state is confirmed.
Partial output and failed cleanup evidence are retained; a stop request alone
does not establish completion.

## Evidence and limits

Accepted evidence:
`.local/build/kernel-qemu/61f3a6c172ef67fe0f26f2b8edbbc699921fbf6ac753d2522ea24a3b67cb8793/20261011T132929.424781Z/`.

- QEMU package: `1:10.0.13+ds-0+deb13u1`.
- Emulator executable SHA-256:
  `0dfd6c04c472cf2e6478092caf090a963a6e9ae354ffe39cfc309966430c093e`.
- Derived local image ID:
  `sha256:c4d03996159b9d0899c0abbb21d8942ca7ef947d9b1aa056de4ca965bda75a79`.
- Original exit code 0, no emulator stderr, both virtual ARM CPU threads
  present, owned-container removal confirmed.
- All retained source and evidence hashes independently rechecked.

Three offline regression groups cover pinned inputs, malformed/partial QMP
results, wrong CPU/target/thread evidence, timeout-output preservation,
stop-timeout follow-through and refusal to remove a still-running container.
The live smoke check was repeated after tightening those gates; earlier
evidence remains intact. Neither invocation accessed the GameShell or Mac.

Next add a guest-kernel runner and actual MUSB callback/UDC concurrency cases.
Use non-sleeping callback handshakes, demonstrate distinct online guest CPUs,
exercise drain/gating and IRQ/timer contexts, and retain kernel diagnostics
and bounded termination. A Cortex-A15 virtual machine does not model the
GameShell's USB controller, Cortex-A7 timer behavior or electrical recovery.
Hardware qualification stays separate. NEO-103 remains in progress.
