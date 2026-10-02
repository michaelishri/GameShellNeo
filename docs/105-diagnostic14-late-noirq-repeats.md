# Diagnostic.14 late/noirq repeats (NEO-83)

3 October 2026, Pacific/Auckland. Four further attended `platform + freeze`
cycles passed after the initial cycle in [report 104](104-diagnostic14-hardware-qualification.md).
The owner confirmed that the dim console returned normally after all four.
No real sleep, power-key gesture or cable-disconnection test ran here.

## Protocol and evidence

The owner gave explicit readiness for all four cycles and left USB and controls
untouched. Each used the existing single-cycle task:

```sh
task device:pm-inspect
task device:pm-platform  # Run once, inspect its result, then repeat three times.
task device:pm-inspect
task device:audio-inspect
task device:check ROUTE=usb ACTIVE_COUNTRY=AU
```

Each invocation reran admission, produced its own run ID and retained its trace.
The next invocation started only after the previous result, restoration,
keypad continuity and independent USB/Wi-Fi SSH proofs passed. No failed or
ambiguous submission was repeated. `CYCLES` does not broaden this task: its
implementation deliberately fixes each invocation to one guarded cycle.

The boot remained `8131c0a8-0a8c-4f83-bf08-e63e493c020c`, image diagnostic.14,
kernel `6.18.54-gameshellneo14`.

| Repeat | Run ID | Private capture | Stage duration including 5 s debug wait |
| --- | --- | --- | --- |
| 1 | `dc6c331a0508411aa5ae704316247839` | `20261002T113516.963811Z` | 8.093 s |
| 2 | `1fdc23480ecf4fddaa2041f372e328f0` | `20261002T113650.686394Z` | 7.987 s |
| 3 | `33d59aa49d104753ab3b033098a5c9ad` | `20261002T113830.611209Z` | 7.935 s |
| 4 | `930800735bb34e65bf6db7a3674e0e93` | `20261002T113948.599568Z` | 7.799 s |

Captures are beneath `.local/diagnostics/<capture>/cycle-1/`. Host transcripts
are `.local/neo83-platform-{1,2,3,4}.log`; the extracted comparison is
`.local/neo83-repeat-summary.json`.

## Results and limits

All four traces qualified the ordered suspend-late/noirq and resume-noirq/early
boundaries, with zero callback errors or trace loss and restored instrumentation.
In every trace RSB noirq resume returned before the PEK noirq callback began.
All original keypad handles, USB device numbers and input paths survived;
there were no keypad disconnect or supply-disable events. Power-key ownership
handed back normally and both SSH routes independently verified the same boot.

Each run recorded a transient collection connection failure while the network
was recovering: an SSH channel timeout in repeats 1, 2 and 4, and a no-route
channel failure in repeat 3. The saved collector recovered each exact run;
these were not extra PM submissions. The connection failures are retained in
each `collection-errors.txt`.

PM success advanced from **3 to 7**, with every failure counter zero, no failed
units and taint zero. PM controls, masks, Wi-Fi profile, charging/CPU policy,
input/backlight and USB experiment settings matched preflight. Idle audio
matched the earlier baseline exactly and all six integration groups passed.
Final captures: PM `20261002T114135.535059Z`, audio
`20261002T114135.604336Z`, integration `20261002T114155.947186Z`.

Together with report 104 this establishes **five observed late/noirq debug
passes on one boot**, not broad reliability, physical wake, resume latency or
standby energy qualification. The kernel's five-second debug return remains
the escape path; normal sleep is still disabled.

## Radio control errors remain open

Repeats 1 and 2 logged the generic country-setting rejection. Repeat 3 logged
a country-read timeout, a rejected transmit while the bus was down, a delayed
control-frame warning and a subsequent channel-query timeout. Repeat 4 logged
a control timeout and country-setting rejection. They did not prevent final
recovery, but must not be described as a clean radio result. NEO-82 owns the
underlying investigation; no country or firmware policy was changed here.

Read-only raw kernel captures are `.local/neo82-kernel-raw.log` and
`.local/neo82-kernel-raw-after-repeats.log`. The original kernel timestamps
show the earlier devices-stage timeout at 361.227544 s, inside its debug hold
starting at 358.766614 s. Journal receipt times had grouped those messages
after resume; use the original timestamps or the separate PM trace for ordering.
Raw printk and ftrace clocks have different offsets, so do not subtract their
timestamps without aligning them.

The source allows regulatory notifier work outside the wiphy suspend callback,
while the SDIO transport parks its service workers. That is a concrete candidate
for preventing firmware requests across the suspended interval. The saved
observations do not yet attribute every delayed response or prove that fixing
this path resolves the older intermittent authentication failure.
