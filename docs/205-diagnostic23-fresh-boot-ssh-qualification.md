# Diagnostic.23 fresh-boot qualification and SSH observations

8 October 2026; capture timestamps are UTC. NEO-143 completes fresh-boot
qualification and captures the new SSH observations; the intermittent fault
remains open.
Both access routes and seven attended debug checks pass on diagnostic.23,
kernel `6.18.54-gameshellneo22`, boot
`cc26703f-d9ef-4d71-8da1-9d766f3efdbe`. One subsequent actual connected-USB
RTC sleep/wake also passes, with final counters PM8/0. The owner confirms
clear warnings and normal dim-console returns throughout, including the
actual sleep's untouched return.

## Access and awake checks

The first attempt was blocked on the Intel host when creating a network
socket, before contacting the Mac. After session network access was restored,
the same saved `device:pm-inspect` task succeeded. This was an execution
environment restriction, not evidence of a GameShell or Mac failure.

The boot differs from [report 201](201-diagnostic23-connected-sleep-repeatability.md).
Its continuation cannot qualify this boot. No image, firmware, kernel,
timeout or charging-policy change was made. No card swap was required for
[report 202's host SSH observations](202-post-return-ssh-investigation.md).

Saved awake tasks and private captures:

| Task | Capture beneath `.local/diagnostics/` | Result |
| --- | --- | --- |
| `device:pm-inspect` | `20261008T005056.639003Z` | Locked image/radio and PM health validation pass; PM0/0, brightness/backlight power 1/0, SDIO usage 2 |
| `device:ssh-timing CYCLES=3` | `20261008T005111.412686Z` | All six independent USB/Wi-Fi probes pass on the same boot, unchanged PM counters; all 14 Mac/device SSH observations authenticated |
| `device:user-startup ROUTE=usb LEGACY=disabled` | `20261008T005154.731309Z` | No legacy PTYs; bidirectional Unix98 PTY, resize and SSH terminal allocation pass |
| `device:power-policy-smoke` | `20261008T005210.468118Z` | Ownership survives worker termination and original policy/input handling restores |
| `device:rtc-smoke` | `20261008T005223.096526Z` | Awake alarm interrupt delivery and restoration pass |

The user manager reports 1.063251 seconds startup, including 0.114436 seconds
generators and 0.593551 seconds unit loading. This is an awake observation,
not a post-resume latency claim. Battery telemetry reports 100%; it does not
resolve the previously documented voltage or capacity uncertainty.

## Attended debug sequence

The owner explicitly confirmed watching/listening readiness for freezer,
driver and five late/noirq checks, with USB connected and controls untouched.
Existing saved tasks ran sequentially, reviewing each result before continuing:

```sh
task device:pm-test STAGE=freezer CYCLES=1
task device:pm-power-key STAGE=devices CYCLES=1 KEYPAD_TRACE=1 WIFI_TRACE=1
task device:pm-platform WIFI_TRACE=1
# Run the platform task four more times, reviewing each original result.
```

The freezer leaves the display on. Each driver/platform dark interval has the
one-second level-5 speaker warning, with software playback and restoration
checks passing. Every stage preserves boot, process memory and original
display state, with independent USB/Wi-Fi recovery. Driver/platform results
retain the original keypad handle and restore POWER ownership and tracing.
All five platform traces pass the late/noirq and RSB callback validation.
SDIO runtime usage remains 2 with unchanged on/active/forbidden policy.

All captures below have `cycle-1/result.json` beneath the listed directory.
Stage seconds include the five-second debug delay; they are not real sleep
duration or wake latency.

| Stage | Capture beneath `.local/diagnostics/` | Run ID | Stage seconds | PM after | Failed collection attempts |
| --- | --- | --- | ---: | --- | ---: |
| Freezer | `20261008T005245.975990Z` | `51ced65ab698421eaf4fa6f025ae754a` | 5.420 | 1/0 | 0 |
| Driver | `20261008T005349.596883Z` | `e850208a9e9f43ddb57dc41ea50ffc50` | 8.040 | 2/0 | 0 |
| Platform 1 | `20261008T005505.419776Z` | `193bc8ba5df546d4b6e50624f0854453` | 7.924 | 3/0 | 1 |
| Platform 2 | `20261008T005618.084366Z` | `498e58fbedad462698cf8a174f579312` | 7.968 | 4/0 | 2 |
| Platform 3 | `20261008T005729.912772Z` | `a66b5d565039453e899e0e652b2209fd` | 7.865 | 5/0 | 1 |
| Platform 4 | `20261008T005850.246022Z` | `c8abfec4f9dc4278bb3f7e06256c9767` | 7.895 | 6/0 | 0 |
| Platform 5 | `20261008T010005.349326Z` | `84a7e6bb32b841dea51c8a5df378ef21` | 7.902 | 7/0 | 1 |

`task check:sdio-ref-history -- --require-stable <the seven result.json paths>`
produces `.local/neo143-debug-qualification.json`, SHA-256
`3542a55ada4b2bf7971e2477e2bb95b6d7ada6d763e3d7b1600540bd9e669ae4`.
This is a candidate prerequisite receipt, subject to the full sleep admission
validator and a live unchanged-state inspection. It does not by itself authorize
sleep. Private `.local/neo143-debug-summary.json` preserves result and timing
hashes; original logs are `.local/neo143-freezer.log`,
`.local/neo143-driver.log` and `.local/neo143-platform-{1..5}.log`.
The summary SHA-256 is
`f095b0b2e1ed31b7ac23efd55f7a59cc5691a09274b0878291d63e02419324f0`.

## SSH evidence

Five collection attempts fail before later successful retrieval of the same
original completed results. Four fail opening the forwarded device TCP channel;
one fails device SSH setup. Each capture has one PM submission. No failed PM
submission was repeated and no physical recovery was requested.

The SSH failure in platform 2 takes 10.024 seconds. Its new pre-cleanup state
observation is complete and reports `banner_received=false`,
`initial_kex_complete=false`, `authenticated=false`, `active=true`. This
establishes that Paramiko had not observed the server identification greeting
at that snapshot. It does not prove that the server failed to send it, identify
where delivery stalled, or establish that this debug-case failure occurred
after PM return. It must not be equated with the older actual-sleep failure
merely because the error text is similar.

The platform-2 timing capture SHA-256 is
`d98fe9e50f279967bd67bd782cf61580a78e7b7c63923016675c39cbfb3af848`.
Each saved timing capture validates with `device:ssh-timing-report`; failed
attempts remain visible even though original-result collection ultimately
passes. No timeout, retry, SSH server or driver setting was adjusted.

The post-debug read-only inspection at
`.local/diagnostics/20261008T010153.807787Z/inspection.json` passes the full
PM-health and sleep-receipt validators at PM7/0. The owner confirms clear
warnings and normal returns. Inspection SHA-256:
`38e70150757ae12fe748143a37313813578e0685f5b8503d6cb9ed35187a2e3c`.

The awake rehearsal passes using:

```sh
task device:sleep-rehearse QUALIFICATION=.local/neo143-debug-qualification.json
```

Its capture is `.local/diagnostics/20261008T010247.260104Z/`, run
`e1afea155b864a79b04bb133496e4e26`. Both independent routes pass, all owned
controls/policy/RTC state restore and PM remains 7/0. There are no host timing
errors. Result SHA-256:
`36aeb3178cebcc3110affcef2ac482bc5e0f843c527c34751f0bb48b15c5ab37`;
timing SHA-256:
`6093583b3d8634e755045dbbba70798f86dcb30bd3976efdd94681373dde2472`.

## Actual sleep and final state

After separate watching/listening readiness, exactly one actual sleep ran:

```sh
task device:sleep-rtc QUALIFICATION=.local/neo143-debug-qualification.json \
  REHEARSAL=e1afea155b864a79b04bb133496e4e26 ATTENDED=1
```

Capture `.local/diagnostics/20261008T010429.034673Z/`, run
`011f9e5762824f389386816298763a9c`, passes functional RTC wake, process-memory,
original keypad, trace/restoration and independent USB/Wi-Fi checks. The owner
confirms the clear warning and normal dim console without touching the cable
or controls. PM advances exactly once, 7/0 to 8/0; SDIO remains 2 and brightness
returns to 1 with backlight power 0. All policy, RTC and diagnostic control
ownership is released. Nothing was resubmitted.

Measured alarm elapsed time is 32.028 seconds; the PM-call BOOTTIME interval is
31.313 seconds and the traced s2idle MONOTONIC boundary spans 28.840 seconds.
There are no observed timekeeping-freeze pairs. These observations establish
functional RTC return, not CPU retention or energy savings.

This actual-sleep capture has seven successful collection attempts and no host
timing errors. All captured Mac/device SSH states are complete and authenticated.
A 35.865-second successful collection attempt spans the sleep interval; its
duration must not be reported as an SSH recovery delay. Using report 201's
clock-bracketing method, the first post-return clock command completes
3.611–4.267 seconds after the recorded PM return. The narrowest successful
post-return clock bracket is span 75, width 0.655892 seconds. This assumes
negligible relative clock drift and does not measure exact network-ready time.
The historical post-return SSH failure did not reproduce in this single sleep.

| File | SHA-256 |
| --- | --- |
| Sleep `result.json` | `135a95bb98910df6a9c844ea39c2a3f9bc3fb0ae508e79e823570d9db2d6561c` |
| Sleep `host-timing.jsonl` | `7270207a1d3554f4517f8127d56400f66268849e5fb8f3eb11d20bee325dd11d` |
| Sleep `qualification-next.json` | `f9f09269f50530646d63c8634d30d237503b57a466c0951303430dc168aa29bd` |

The unused continuation is the sleep capture's `qualification-next.json`,
with original rehearsal `e1afea155b864a79b04bb133496e4e26`. The earlier
debug-only receipt is consumed. The post-sleep read-only inspection at
`.local/diagnostics/20261008T010617.918102Z/inspection.json` passes health and
full continuation validation at PM8/0. Private
`.local/neo143-final-receipt.json` preserves that proof and
`.local/neo143-return-alignment.json` preserves the bounded timing calculation.
No further sleep or screen test is running.

Final inspection, receipt and alignment SHA-256 values respectively:

- `0247d79247b08e38974a0d19cc4ce5b4ebeda458c225aa186d367938a9d02a27`.
- `956ddc2a87ecb7bd2d66d5613f7f64afcc472d62e3ae77fb3f2af0ee1cb2c1cc`.
- `ddac9e08541252611554e1a35d7bec6174a1e1acf947a2b73442a6950a2c3fcb`.

The next SSH investigation needs bounded connection metadata with matching
socket identities to distinguish server scheduling/greeting generation from
USB/TCP delivery or Mac forwarding if the fault recurs. The new missing-greeting
observation narrows one debug failure, but cannot explain the older post-return
failure by itself. Preserve the original evidence and existing retry/timeout
policy. CPU retention, energy, production sleep behavior and the SSH root cause
remain unqualified.
