# Diagnostic.25 backlight power comparison

9 October 2026. NEO-179. Follow-up to the
[awake battery baseline](240-diagnostic25-battery-measurement-baseline.md).

All three measurement windows pass. Estimated awake power is **1.042 W lit →
1.015 W off → 1.027 W lit**. The dark window is 11.6–26.9 mW lower than the two
lit references, with current lower by 4.35–5.57 mA. This is directional evidence
of a small reduction at the minimum dim setting, not a precise calibrated
backlight-only power measurement. The two lit windows themselves differ by
15.3 mW as battery voltage and temperature drift.

## Protocol

Use a fresh continuous battery-only **lit → off → lit** sequence. USB charging
resumed after report 240's ten-minute reference, so that earlier window is
context rather than the first phase of an uninterrupted comparison. The fresh
sequence has three five-minute measured windows, each preceded by one minute
of settling, for about eighteen minutes overall.

| Phase | Saved command | Intended brightness |
| --- | --- | --- |
| A1 | `task device:idle-sample ROUTE=wifi SECONDS=300 BACKLIGHT=keep` | Original dim level, 1 |
| B | `task device:idle-sample ROUTE=wifi SECONDS=300 BACKLIGHT=off` | 0; restore 1 afterward |
| A2 | `task device:idle-sample ROUTE=wifi SECONDS=300 BACKLIGHT=keep` | Restored dim level, 1 |

Run these existing commands from `work/musb-restart-integration`, using its
shared `.env`, in order. Accept each complete original before starting the next;
stop on any failure. Do not run additional device diagnostics inside a phase or
reconnect USB between phases. The GameShell and Mac remain stationary, Wi-Fi
associated, controls untouched and headphone socket empty. Keep the Mac awake.
Ordinary sleep stays disabled, and no system-PM request is part of this test.

Obtain owner confirmation of USB removal and readiness for this described
sequence before beginning. Before phase B, the existing speaker helper plays
the one-second warning at the previously accepted level 5, restores the mixer
and confirms idle audio, then waits one second before darkness. The task checks
the zero-brightness readback and automatically restores the original level
before it can report success. The warning and settling interval are outside
the measured integral. Phase A2 needs no further blanking operation.

Each phase requires absent external power, a present discharging battery above
20%, valid recent guard data, Wi-Fi carrier, no taint and temperature below
80°C. Raw clock/PM evidence must remain consistent, with no change of boot,
governor or intended display state and no sampling gap above twenty seconds.
The temporary service has a 420-second runtime bound for a 300-second window;
the existing termination/restoration behavior remains in use.

After the last phase, save the battery-only endpoint before separately asking
for USB reconnection. Then verify the original image/boot, dim display, PM
counters and independent USB/Wi-Fi access. Owner observations remain separate
from automatic setting readbacks.

## Acceptance and interpretation

Each accepted phase contains 31 samples and an original completion record.
Recompute its current/power/charge/energy summary from raw samples with the
existing sampler function; validate the per-sample clock windows and complete
run proof independently. Require exact source/image/boot continuity and
verified backlight/audio restoration. Preserve incomplete attempts and their
failures rather than replacing them with later results.

Compare B against **each** lit window separately. Report the A1-to-A2 drift,
voltage, temperature, radio conditions and actual elapsed times, not just the
difference between B and an average of A1/A2. Percentage endpoints are battery
context, not a calibrated capacity or energy measurement. Ten-second
instantaneous samples include observer effects and do not resolve every load
transient. The windows are sequential; individual samples are not independent
experimental repetitions.

A lower B value than both surrounding A values is useful directional evidence,
with its uncertainty and drift retained. If the estimates overlap or drift
prevents attribution, record the result as inconclusive rather than forcing a
minimum saving or claiming zero physical benefit. Small reproducible savings
remain worthwhile. This test concerns minimum-dim backlight brightness versus
zero; it does not power down the whole display pipeline, measure asleep
consumption, or isolate CPU-idle savings.

## Admission

Fresh independent USB/Wi-Fi PM inspections pass on diagnostic.25 /
`6.18.54-gameshellneo24`, original boot
`2170b296-d964-4d16-bdb1-c135b0e7b812`, with the exact installed manifest and all
344 project-input hashes unchanged. PM is 31 successes and zero failures;
battery readings are valid at 99%/Charging, brightness 1 and backlight power 0.
The prospective sequence and helper hashes are saved in
`.local/neo179-admission.json`. Original preflight captures are
`20261009T081118.351421Z` (USB) and `20261009T081122.189677Z` (Wi-Fi).

The owner confirmed USB removal and readiness for the whole described sequence.
The three commands ran once each, in order, with each completed record reviewed
before the next submission. No other device diagnostic ran inside a window,
and no USB reconnection was requested between windows. The long warning, zero
brightness and complete original-brightness/mixer restoration all pass in the
middle window. After all three completed, the owner confirmed normal warning,
darkness and dim-console return, then the separately requested USB reconnect.

## Results

All values below describe the measured windows, excluding each settling minute,
the warning and the gaps between commands. Each window has 31 samples at
approximately ten-second intervals. The first-to-last measured endpoints span
1,121.690 seconds, including two unintegrated gaps of about 111 seconds that
contain the next task's startup/settling and host-side validation. They are not
reported as continuously sampled energy.

| Metric | A1: dim | B: backlight off | A2: dim again |
| --- | ---: | ---: | ---: |
| Brightness | 1 | 0 | 1 |
| Measured seconds | 299.998 | 300.001 | 300.007 |
| Time-weighted current estimate, mA | 263.067 | 257.500 | 261.850 |
| Time-weighted power estimate, mW | 1,042.245 | 1,015.348 | 1,026.904 |
| Sampled current magnitude range, mA | 256–268 | 254–263 | 256–265 |
| Voltage range, V | 3.9523–3.9754 | 3.9380–3.9501 | 3.9160–3.9270 |
| Temperature start → end, °C | 45.198 → 44.388 | 44.226 → 43.092 | 43.092 → 42.606 |
| Gauge start → end, % | 96 → 91 | 90 → 89 | 88 → 87 |
| Wi-Fi signal start → end, dBm | −49 → −50 | −51 → −50 | −53 → −50 |
| Sampled charge estimate, mAh | 21.922 | 21.458 | 21.821 |
| Sampled energy estimate, mWh | 86.853 | 84.613 | 85.577 |

These software estimates remain uncalibrated. The same governor is retained;
actual CPU frequency can vary normally. No failed health samples, external
power, taint or unexpected display-state changes were observed in the sampled
windows. The middle completion follows successful readback of brightness 1;
the warning record confirms the one-second level-5 cue and restored audio.

| Comparison | Current difference | Power difference |
| --- | ---: | ---: |
| B minus A1 | −5.567 mA (−2.12%) | −26.896 mW (−2.58%) |
| B minus A2 | −4.350 mA (−1.66%) | −11.555 mW (−1.13%) |
| A2 minus A1, lit-window drift | −1.216 mA | −15.341 mW |

The current and power averages both rise again when dim brightness returns,
despite the continuing fall in voltage and temperature. This supports the
direction of the backlight effect within this session. However, the lit-window
power drift exceeds the smaller off-versus-lit difference, and sample ranges
overlap. The 11.6–26.9 mW range lists two comparisons; it is **not** a confidence
interval or a bound on the physical backlight's consumption. No fixed saving
to milliwatt precision is established by this one sequence.

Even with the backlight off, the software estimate remains about 1.02 W while
awake. This characterizes the present diagnostic workload and interfaces; it
does not measure asleep draw or justify an endurance projection. No new
optimization setting or driver change follows from these readings. The tested
diagnostic sleep path already turns the backlight off; ordinary product sleep
remains disabled pending its separate qualification.

## Evidence validation

For each original capture, all summary fields reproduce exactly using
`sample-idle.py:summarize()`. Its 62 sample-window observations and 40 run-proof
observations pass the existing awake-clock validators. The combined 120
run-proof observations retain one consistent BOOTTIME–MONOTONIC offset on the
same boot, with PM31/0 unchanged. Maximum sample-window brackets are 120.210,
28.751 and 27.833 µs, all below the 1 ms limit. The largest sample lateness in
the sequence is 23.809 ms; adjacent samples stay within 9.991933–10.005608 seconds.
The documented short-interruption/pending-PM-counter limitation remains; these
observations are not exclusive ownership of system sleep.

| Phase capture under `.local/diagnostics/` | Raw `idle-sample.jsonl` SHA-256 |
| --- | --- |
| A1 `20261009T081348.612342Z` | `e499c0015ee6eae2d9236ba2a7d278c10229d24ecc3e3f68189f2c17d143d484` |
| B `20261009T082034.392978Z` | `8b1087ec0da92c10e1925159611140fbf82b5ba5657a76f11f0377622c8ba645` |
| A2 `20261009T082730.148082Z` | `68793941ef19f0ea76f423946f1a8bef05ec72240a5fe9c43e59884bb0827b1f` |

Original task logs are `.local/neo179-{a1,b,a2}.log`. Individual recomputations
are `.local/neo179-{a1,b,a2}-review.json`; the combined review is
`.local/neo179-comparison-review.json`. The raw results were not rewritten.

The final unplugged inspection, saved before requesting reconnection, is
`20261009T083421.656294Z/inspection.json`, SHA-256
`36d877e029a6aa935df9ee4054481f4c1956019c1aadb5adc16b99c273e99dbb`.
It passes the battery-profile health validator with the exact manifest and
original boot, both external supplies absent, valid 87%/Discharging readings,
normal dim brightness and unchanged PM31/0.

After the owner confirmed the warning/display behavior and reconnected USB,
independent inspections passed over both routes:

| Final capture under `.local/diagnostics/` | `inspection.json` SHA-256 |
| --- | --- |
| USB `20261009T083555.223593Z` | `363b27a911bacec6c45d7698162038f57dfd5080e09dc255ff6b4f6d6b499151` |
| Wi-Fi `20261009T083558.306896Z` | `a8d32a04120378f7eaacf3651a81aeba1aeee590d11fb8502a9fc39fff3f91b4` |

Both retain the original boot and exact image manifest, unchanged PM31/0,
brightness 1/backlight power 0 and valid 87%/Charging readings with both external
supplies online. All 344 project-input hashes still match. Admission SHA-256 is
`3f8760ba0a64400f3a8cd80acf56066b6ecb42a7109093a1e9ec6a88afb94b45`;
the completed combined-review SHA-256 is
`f861b529cb20662fbcccf622e3ffb9dfe3001626b7c93e18cd89d6c7a7817002`.
Raw captures and local reviews remain private evidence rather than tracked
repository files.

## Completion and next boundary

NEO-179 is complete: all three existing tasks exited successfully, their 93
samples and summaries passed validation, the owner confirmed the visible and
audible behavior, and the reconnected device passed both route checks. This
slice changes documentation only; it requires no new image or driver change.

The next planned slice is the bounded longer-RTC protocol described in
[report 240](240-diagnostic25-battery-measurement-baseline.md). Its duration,
qualification, recovery deadlines and battery safeguards need explicit support
before any longer sleep trial. No longer sleep test ran here, and these awake
measurements do not establish sleep energy or week-long standby endurance.
