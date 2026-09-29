# RSB runtime autosuspend comparison

Date: 30 September 2026 (New Zealand). Kaneo: NEO-35.

## Result

Shortening the PMIC bus's autosuspend delay from 1,000 ms to either 100 ms or
20 ms did **not** increase runtime-suspended time on the USB-powered CPI v3.1.
The original 1,000 ms setting is restored. There is no basis for adopting a
shorter default or claiming an energy improvement from this change.

The board ran diagnostic.6 / `6.18.54-gameshellneo6`, boot
`6c38af94-5335-41a5-aa97-3d17a549be6d`, throughout. USB remained connected,
Wi-Fi remained associated, and the normal battery monitor continued running.
Firmware, NVRAM, charger settings, governor settings and backlight settings
were checked at the boundaries. No new kernel messages were recorded by the
comparison. This is a connected-USB result, not a battery-only measurement.

## Saved method and evidence

```sh
task device:rsb-compare SECONDS=120 DELAY_MS=100
task device:rsb-compare SECONDS=120 DELAY_MS=20
```

Each run uses original/candidate/original windows, each preceded by 15 seconds
of settling. Private records include the source lock, runtime-PM counters,
interrupt/process deltas, cached health samples and boundary kernel logs:

- `.local/diagnostics/20260929T112627.606571Z/rsb-comparison.jsonl`
- `.local/diagnostics/20260929T113804.281954Z/rsb-comparison.jsonl`

| Run | Window | Delay | Elapsed | Runtime active | Runtime suspended |
| --- | --- | ---: | ---: | ---: | ---: |
| 100 ms | Original before | 1,000 ms | 120.028 s | 120,032 ms | 0 ms |
| 100 ms | Candidate | 100 ms | 120.029 s | 120,033 ms | 0 ms |
| 100 ms | Original after | 1,000 ms | 120.028 s | 120,032 ms | 0 ms |
| 20 ms | Original before | 1,000 ms | 120.028 s | 120,032 ms | 0 ms |
| 20 ms | Candidate | 20 ms | 120.028 s | 120,032 ms | 0 ms |
| 20 ms | Original after | 1,000 ms | 120.014 s | 120,013 ms | 0 ms |

Small accounting differences come from sequential counter/time reads. All
coverage checks passed. The initial 155 ms of historical suspended time stayed
unchanged. Aggregate RSB interrupt rates in the first run were 4.49, 4.41 and
4.54 per second respectively. Interrupt counts are neither transaction counts
nor runtime-resume counts. No resume counter was available; results record
`null` instead of inferring one. A read-only PM inspection overlapped the last
20 ms run's original window; process/IRQ deltas from that window are not an
isolated performance comparison. Runtime residency remained zero.

The scripts avoid direct PMIC property reads inside measurement windows;
health samples use the existing ten-second battery cache. Boundary inspection
and ordinary services still cause work. Connected-USB battery current is not a
measure of system energy consumption. No battery-power estimate is made here.

## Recovery and regression coverage

The saved host task uses an exclusive host lock and a bounded device service.
Before changing the delay, the helper saves a private, same-boot ownership
record. Its `finally` block restores the original value and checks readback;
`ExecStopPost` independently invokes the same idempotent recovery if the helper
is killed. A failed restoration retains its ownership record. After an
interruption, `task device:rsb-restore` stops the service and restores the owned
setting without requiring healthy radios or a battery-health pass first.

Eight host regression tests cover policy/counter rejection, ordinary and
exceptional restoration, corrupt ownership, failed readback, service bounds,
and a real child-process SIGKILL followed by fresh-process restoration.
Both live comparisons completed with `passed: true` and `restored_ms: 1000`.

## Interpretation and next investigation

The locked Linux source's `drivers/bus/sunxi-rsb.c` balances transaction
`pm_runtime_resume_and_get()` calls with `pm_runtime_put_autosuspend()` and
sets the default delay to one second. Runtime callbacks gate its clock;
system-suspend noirq callbacks additionally reset/reinitialize the controller.
Those are distinct paths.

The six windows show that delay reduction alone is insufficient in this
configuration. They do not identify the cause. Low aggregate interrupt traffic
does not prove the absence of an outstanding runtime-PM reference,
supplier/consumer constraint, or another policy constraint. The current kernel
does not expose the advanced PM usage/enabled counters needed to distinguish
these possibilities.

The next diagnostic image enables those read-only counters. Inspect usage
references and device links before changing reference ownership or the RSB
driver. Any later optimization needs repeatable residency/functional tests
and a separate battery-only comparison. Do not disable firmware-derived device
links or force clock gating merely to make a counter increase.
