# Diagnostic.22 suspend/resume qualification

7 October 2026; capture timestamps are UTC. NEO-133 is in progress. The initial
freezer, driver and first late/noirq debug checks pass. The owner confirmed
the initial warning and normal dim-console return, then gave readiness for the
late/noirq check. Its display confirmation and four-repeat readiness are now
pending. No actual sleep has run on this image.
[Report 194](194-diagnostic22-installation-and-adc-validation.md) records the
verified installation and awake checks.

## Initial observed sequence

The owner explicitly confirmed watching/listening readiness for a freezer check
followed by one driver cycle, keeping USB connected and all controls untouched.
The freezer result was reviewed before the driver cycle started:

```sh
task device:pm-test STAGE=freezer CYCLES=1
task device:pm-power-key STAGE=devices CYCLES=1 KEYPAD_TRACE=1 WIFI_TRACE=1
```

The freezer uses the standard diagnostic inhibitor. The driver cycle additionally
owns the POWER input and retains original keypad handles with Wi-Fi tracing.
The freezer leaves the display on. The driver's long screen-warning record
passes with audio controls restored. The owner subsequently confirmed the
warning and normal dim-console return.

Both results belong to diagnostic.22/kernel `6.18.54-gameshellneo21`, boot
`7884d229-2309-47df-9af0-b6fe500ad9ac`. Each verifies both USB and independent
Wi-Fi SSH after completion. Private evidence beneath `.local/diagnostics/`:

| Stage | Capture | Run | Result SHA-256 |
| --- | --- | --- | --- |
| freezer | `20261007T053126.968157Z/cycle-1` | `8aef460d034944edb030bb5cca9fbcc5` | `d6a45454a7e9926aa572d49dbe91b8ecc63323dde0319ae54848b055290007eb` |
| devices | `20261007T053232.350714Z/cycle-1` | `dc9b081f2e2c4068b6c9e5bdbf1f7a28` | `d4b6a7234c6b7f610bc7682458b60204041bbf994f832a42870a2ad519f53039` |

The original task logs are `.local/neo133-freezer.log` and
`.local/neo133-driver.log`. Driver collection initially logged `No route to host`;
the original completed result was subsequently collected and both routes passed.
Preserve that transient without labeling it a kernel failure or deriving recovery
latency from an untimestamped collection error.

At this checkpoint PM success/fail is 2/0 with every failure counter zero.
SDIO usage stays 2 with active/on/forbidden runtime policy. The original keypad
connection is retained, process memory checks pass, power-key ownership is
handed back, and Wi-Fi tracing restores without loss. Brightness returns to 1
with backlight power 0. No further screen test is running at this checkpoint.

## First late/noirq check

After the owner confirmed “Yes and ready”, the saved task ran once:

```sh
task device:pm-platform WIFI_TRACE=1
```

Private capture: `.local/diagnostics/20261007T054331.905931Z/cycle-1/`;
run `69e5d1b3db6b4da8bbe1356f367ab482`. Result SHA-256:
`0cea3410af0f3072dfb41060cbfaa89a0100229ea91b89f9478957948974ad57`.
The task log is `.local/neo133-platform-initial.log`.

The completed result passes both independent SSH routes, process memory,
original keypad retention, POWER handback and loss-free Wi-Fi trace restoration.
The one-second level-5 warning completed with audio controls restored. The PM
stage took 7.897 seconds including the five-second debug delay; this is not a
real-sleep or wake-latency measurement.

Final PM is 3/0 with every failure counter zero. SDIO usage stays 2 with unchanged
active/on/forbidden runtime policy. Brightness returns to 1 and backlight power
0. The boot is unchanged. An initial collection `No route to host` is retained;
subsequent retrieval of the original result and both route proofs passed.
No further screen test is running while awaiting the owner's observation.

## Remaining qualification

Await the first late/noirq warning/display confirmation and readiness for four
repeats. The automated checks pass; owner observation remains separate. A completed seven-stage baseline is required
before the awake RTC rehearsal and a separately attended actual RTC sleep.
Battery/cable/POWER wake profiles, energy and physical battery accuracy remain
separate; these debug checks do not establish real sleep or charging in sleep.
