# brcmfmac F2 reset ownership

23 October 2026 NZDT. NEO-231 is a bounded offline child of NEO-58 on
locked Linux 6.18.54. Candidate 0073 rejects reset after the F2 function driver
has been unbound. It remains outside the production 33-patch image queue.
No device, Mac, PM, reboot or radio operation was run.

## Reproduced boundary

The actual SDIO bus probe increments the card's bound-function count before
calling its function driver and preserves that increment on success. The actual
bus remove calls the function driver's remove callback and then decrements the
count. brcmfmac's F2 remove retires IRQs but leaves shared transport cleanup to
F1. Consequently, removing F2 independently can leave shared transport and
driver state present while the bound count falls from two to one. The fixture
reaches that state through both real generic probe callbacks followed by the
real F2 remove path; it does not assign an invented bound count.

This distinction changes MMC reset behavior. The locked SDIO implementation
returns 1 for an asynchronous hotplug request when multiple functions are
bound; an already-removed card returns 1 without another rescan. With one
function bound it power-cycles/reinitializes synchronously and returns 0 or
the exact negative error. The generic MMC wrapper returns that value and warns
on negatives. Its general zero/-errno documentation is narrower than the
specific SDIO implementation. These outcomes must not be called equivalent
completed recovery. [Locked SDIO source](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/mmc/core/sdio.c?h=v6.18.54),
[generic SDIO bookkeeping](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/mmc/core/sdio_bus.c?h=v6.18.54),
[MMC wrapper](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/mmc/core/core.c?h=v6.18.54).

Before this candidate, brcmfmac reset removes its transport before invoking
MMC and discards the return. After F2 unbind, synchronous zero leaves no
transport and schedules no hotplug; negative -EIO/-ETIMEDOUT are also reported
as callback zero after teardown. Adding synchronous reprobe there would
operate without the F2 driver owner. The demonstrated correction is admission
before teardown, rather than an invented recovery sequence.

Original private discovery used an earlier 14-case hypothesis: 12 observations
passed and two exact-negative-return assertions failed, raw aggregate exit 1.
That original source/functions, fixture, outputs and two preceding setup-only
path/queue-location failures remain unchanged under
.local/audit/neo231-discovery/. The refined 16-family contract below instead
requires -ENODEV before an unowned reset can touch transport or MMC. Those are
distinct contracts and executions.

## Candidate and lifetime

[Candidate 0073](../kernel/candidates/0073-brcmfmac-reset-ownership.patch) adds
device_is_bound(f2dev) under the existing F2 device lock, after all existing
failed-PM, retained/powered-off and missing-transport guards. An unbound F2
returns -ENODEV with no additional IRQ retirement, transport destruction,
host claim or MMC reset. The existing nonblocking trylock, guard priority,
unlock paths and bound-F2 reset behavior remain intact.

The predicate reads the driver's bound-list node. The driver core attaches
that node after successful binding and removes it under the device lock during
unbind; cleanup also clears the driver's pointer and drvdata. Checking under
the same existing F2 lock therefore selects the completed binding/unbinding
boundary. The fixture models both F2 pointer clears and the node change under
that lock, while retaining F1 drvdata. It does not execute the real kernel
driver-core/list scheduler. [Driver-core source](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/base/dd.c?h=v6.18.54),
[klist predicate](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/lib/klist.c?h=v6.18.54),
[driver-binding documentation](https://docs.kernel.org/driver-api/driver-model/binding.html).

The existing generic reset worker discards the bus callback return; debugfs
queues that work and returns the write count. The transport teardown reaches
brcmf_free(), which clears bus_if->drvr and releases driver storage. This
candidate does not add post-callback logging or dereference the old drvr/work
item. It does not promise synchronous errno delivery to a debugfs writer.

For the tested two-bound-function route, asynchronous MMC 1 still produces
callback 0 as before. This accepts the request; it does not establish completed
hotplug, firmware reattachment or recovered networking. The F2 guard alone is
not a proof that every possible admitted lifetime has exactly two bound
functions or that MMC always returns 1. F1/global lifetimes and broader MMC
result/reprobe policy remain with NEO-58. The existing lifecycle argument and
limits remain in [report 84](84-brcmfmac-pm-lifecycle.md) and
[report 297](297-brcmfmac-startup-ownership.md).

## Finite qualification

The maintained fixture projects actual MMC reset/detection, generic SDIO
probe/remove, brcmfmac F2 remove/transport remove/reset/state and
device_is_bound()/klist predicate bodies. Actual klist-node and bus/SDIO-state
type definitions come from the same source. Hardware/reinitialization,
runtime PM, callback allocation, device locking, binding-list changes,
scheduling and final transport destruction are synchronous modeled seams.
It explicitly preserves both F2 pointer clears, host/device balance and
transport/drvr observations. The parked brcmfmac probe investigation is not
part of this fixture.

| Family | Required numeric/ownership result |
| --- | --- |
| mmc_multifunc_schedule | 1; one rescan, removed flag, no power cycle |
| mmc_multifunc_already_removed | 1; no duplicate rescan |
| mmc_after_f2_unbind_sync | 0; one power cycle/reinit, no rescan |
| mmc_after_f2_unbind_eio | -5; one existing MMC warning |
| mmc_after_f2_unbind_timeout | -110; one existing MMC warning |
| reset_bound_async | 0; one retirement and one queued rescan |
| reset_bound_already_removed | 0; retirement, no duplicate rescan |
| reset_unbound_f2_sync_refused | -19 before extra retirement or MMC |
| reset_unbound_f2_eio_refused | -19 before scripted reinit -5 is reached |
| reset_unbound_f2_timeout_refused | -19 before scripted reinit -110 is reached |
| f2_remove_preserves_shared | bound count 2 to 1; shared transport/drvr retained |
| reset_lifecycle_busy | -16; no acquired F2 lock or teardown |
| reset_pm_failed | -112; balanced lock, no teardown |
| reset_pm_retained | -16; balanced lock, no teardown |
| reset_pm_powered_off | -16; balanced lock, no teardown |
| reset_no_transport | -19; balanced lock, no teardown |

Eight mutations compile the same fixture and must fail exactly the declared
assertion/value. Compile/setup failures are inconclusive.

| Control | Case assertion | Expected / observed |
| --- | --- | --- |
| Omit F2 guard | unbound sync: reset_errno | -19 / 0 |
| Invert F2 guard | bound async: reset_errno | 0 / -19 |
| Wrong owner errno | unbound sync: reset_errno | -19 / -5 |
| Guard after IRQ retirement | unbound sync: irq_retirement | 1 / 2 |
| Guard after transport retirement | unbound sync: transport_retirement | 0 / 1 |
| Omit F2 unlock | unbound sync: f2_lock | 0 / 1 |
| Omit host release | bound async: host_balance | 0 / 1 |
| Duplicate rescan | multi-function MMC: rescan_requests | 1 / 2 |

The observer saves each raw command/exit/stdout/stderr before admission.
Admission requires the complete exact numeric observation plus exactly one
PASS or declared FAIL line, empty stderr and original integer exit 0 or 1
respectively. It rejects numeric prefixes, extra/wrong cases or assertions,
diagnostics, changed saved hashes and an expected-negative result from raw 0.
Twenty-five focused host checks pass, including real observation-route
raw-0/extra-failure rejection and distinct fresh executions with identical
valid negative output.

## Workflow and current evidence

```sh
task test:brcmfmac-reset-reference -- --archive /path/to/linux-6.18.54.tar.xz
task test:brcmfmac-reset -- --archive /path/to/linux-6.18.54.tar.xz
```

Supply the existing regular locked archive explicitly. No download/copy occurs.
The checker verifies its whole hash, projects only 14 named files (634,256
uncompressed bytes in this execution), replays the eight whole selected
production patches, then applies 0073 in a separate candidate projection.
The complete selected-member ceiling is 2 MiB. Suite locking and unique
attempts retain original outputs; source caches and prior receipts are untouched.

Original Task session 97967 completed exit 0, terminal observer ea0bd1.
Attempt 20261023T003014Z-a72b0be9262a48948f44a8c12753738d contains:

- Original production source: 13 PASS and three exact owner-refusal FAIL
  outcomes, each failing command raw 1; the admission wrapper recognizes the
  declared baseline rather than claiming the source passed.
- Candidate native: 16 PASS; ASan/UBSan: 16 PASS.
- All eight controls compiled and failed their exact numeric assertions.
- Maximum child RSS 48,424 KiB; retained artifacts approximately 2.72 MiB.

| Artifact | SHA-256 |
| --- | --- |
| Candidate 0073 | cb5dad289177ab72eebc72568bcd152d4317d59adbd8c73b2c3f522996df477c |
| Original source/member/queue receipt | 1f14ec4d87e8ddb2a1c7b568a12cb18dce1e5af7e063550a32631ef976aac497 |
| Original native/sanitizer/control result | 3fe74a1d86d010604f63f1d6c5efa2aa1482e42dafacdfc08650963aa2382930 |

ARM/reference and complete normal/debug objects require the separately
serialized resource lease and are not yet qualified. The final current host
check and fresh independent Standards/Spec reviews also remain pending.
No image selection or hardware result follows from the source qualification.

The versioned source pages were unavailable to the web fetcher; the exact
locked local member/function hashes and retained archive identity establish
these specific source facts. The official driver-binding document was read
successfully. No secondary source is used.

NEO-58 remains open for its wider startup/asynchronous firmware, reset/reprobe,
deliberate composition, image and physical gates. This source defect is not
an established cause of NEO-55's original authentication delay; the original
failure and unchanged deadline remain. NEO-192 still blocks fresh PM work.
