# Charging inventory admission on the host (NEO-227 / NEO-10)

23 October 2026 NZDT. The inventory host previously accepted a stored
completion/assessment without replaying its raw evidence. The new host gate
checks the existing result and independently decodes the register bytes before
printing success. The collector and transport are unchanged. Source and local
qualification are complete; fresh independent review and serialized publication
remain required. No current device, electrical or clock/PM clearance follows.

## Retained actual-host baseline

The separate original baseline checkout is frozen at published
`4d680d73bf81cf1c841b0a2d002b7b25fdf83734`. One local run executes actual
`check-charge-inventory.main`, `remote.python_command` and `remote.run` with
explicitly private supported historical configuration fixtures and scripted
channel endpoints. The sent collector source is never executed.

| Original case | Original outcome | Corrected route |
| --- | --- | --- |
| A: complete-shaped diagnostic.20 control | Accepted | Accepts |
| B: completion/boot/assessment/limits without raw evidence | Incorrectly accepted | Refuses |
| C: changed boundary PM counts | Incorrectly accepted | Refuses |
| D: changed raw ADC byte, unchanged stored assessment | Incorrectly accepted | Refuses |
| E: invalid metadata/profile/width claims | Incorrectly accepted | Refuses |
| F: truncated JSON | JSONDecodeError; raw retained | Preserved |
| G: exit seven | Original RuntimeError; raw retained | Preserved |
| H: injected timeout after seven bytes | Same TimeoutError; partial raw retained | Preserved |

Its eight routes, 87 artifacts, actual old source/configuration, raw/provenance,
wire observations and terminal receipt remain unchanged under the ignored
`charge-inventory-admission-baseline` worktree. The original run is exec chunk
`6b1bd0`, PID `1247433`, terminal zero. Index SHA-256:
`3e8fd6f1eddd128a1674311de47736b7c81745b3af440fc39f953cc064a2c6b9`.
No old baseline is repeated or relabeled as new-source qualification.

The control uses a supported historical request; it does not establish an
actual producer's image/board/kernel identity. The unchanged producer map only
admits diagnostic.20–23 / kernel19–22. Diagnostic.27/kernel26 remains unsupported
and appears only as a negative host fixture. No filled private `.env`, SSH,
register/sysfs access or collector entrypoint runs in this qualification.

## Raw admission and existing pure functions

New `tools/inventory_result.py` reads one complete schema-4 JSON object. It
rejects duplicate JSON members before they can be discarded, requires the
original kind/completion/limits and matches the requested image/kernel/CPI3
labels. These are saved-stream consistency checks, not independent current
source/image/device attestation.

`charge_inventory.profile_for` determines the exact expected cache profile.
ADC-width policy comes from the existing maintained pair constants, rather
than a serialized width claim. The host requires exactly eleven register keys
`00,01,33,34,78,79,b8,b9,e0,e1,e6`, real integer-byte values, the profile-derived
source label and both raw clock brackets. Supply containers/string fields are
preserved without new electrical, health, voltage or charging-policy rules.

Published NEO-226's unchanged `charge_result.checkpoint` normalizes the two
observed boundary checkpoints and the 22 register-clock points in private
copies. It derives offsets from the three raw integer timestamps and ignores
stored derived bounds. The new module contains no copied normalizer, metadata
validator or decoder. Existing `charge_inventory.validate_continuity` and
`awake_clock.validate` check ordered raw points, stable boundary boot/decimal
PM counts, one common offset and the original one-millisecond clock-call
uncertainty limit. There is no requested sixty-second workload or new duration
floor for this single inventory.

Register clock records contain **no independent boot or PM observations**.
Their normalization wrappers explicitly carry context from the measured
boundary checkpoints. The receipt states this distinction; the 24 clock
observations must not be described as 24 independent PM reads. Stable boundary
counts/common clock bounds cannot establish exclusive sleep ownership or rule
out sub-bracket sleep and a pending final counter update. NEO-192 remains open.

The original five metadata strings are required. Unchanged `validate_metadata`
checks `axp20x-rsb`, range `0-e6`, normal cache mode, 231 ordered access rows and
the profile-derived per-register policy. Only one metadata snapshot is returned;
the producer's second-snapshot agreement cannot independently be replayed or
invented by the host.

Unchanged `decode` recomputes the entire assessment from validated bytes and
the independently selected width policy. Canonical JSON comparison preserves
numeric types. Raw ADC bits, both formulas, uncertain REG34 polarity, cached
values, separate voltage reads and all noncoherent/uncalibrated wording remain.
No accumulated-charge or sleep-charge measurement is introduced.

## Preserved host flow and evidence

The narrow `check-charge-inventory.py` change invokes admission after the
original successful command and closed device context, while retaining the
original PM lock. The host prints the checked boot/assessment/limits in its
existing shape. Refusals keep original `inventory.json` and `provenance.json`;
a successful replay exclusively creates `inventory.admission.json`, including
the raw hash, recomputed assessment, limits and explicit false calibration,
charging-safety, sleep-charge, current-image/device and clock-reliability flags.
An existing admission receipt is never overwritten.

The collector remains the same 10,348-byte `charge_inventory.py`, SHA-256
`b4a6fbad64e95f4472ba52623b5e91d20af0c8c344b2f9cd157d6b20bb1682ba`,
sent unchanged on stdin. The command remains `sudo -n python3 -B -` with its
original kernel/image arguments, USB route, forty-second response inactivity
timeout and ten-second session-open timeout. This inventory command has no
separate remote process deadline. Original nonzero-exit/transport failures
propagate before admission; channel/context finally and PM-lock release remain.
No helper stage, settings/restoration write, retry, runtime replacement, profile,
image, kernel or hardware operation is added.

## Current qualification and exact source

The implementation checkout starts from accepted published
`9130cc719361fd042f3add6035aba96d4c5176c8`, retaining the independently published
NEO-223 dependency. Both saved checks execute clean source
`c3fba4e513deeca5ebb648c4f0b963001136e8d1`. Its six protected shared inputs,
including the published normalizer and collector, stay byte-identical.

```sh
task test:charge-inventory-result-admission
```

The focused Task passes **10 methods / exactly 51 actual-host routes**:

| Fixed family | Routes |
| --- | ---: |
| Four historical controls and valid raw/forged stored-offset control | 5 |
| Missing/raw-free/legacy evidence | 7 |
| Operation/profile/limits | 8 |
| Register records and duplicate member | 8 |
| Clock/PM/boot | 11 |
| Metadata | 5 |
| Recomputed assessment | 4 |
| Original JSON/exit/timeout failures | 3 |

Five controls accept and 46 expected refusals retain their bytes. The fixed
case names/families exactly match the approved proposal. Actual host main,
`python_command` and `run` execute with private fixture configuration; source
stdin, command, timeouts, PM lock/release, raw/provenance and channel/context
closure are asserted. Observations are retained **before assertions**, including
unexpected regressions. Pure guards additionally check direct normalizer
identity, no collector I/O, input immutability and exclusive receipt retention;
they do not add actual-host routes or copy validation formulas.

Focused original Task PID `1295053` / wrapper `1295041` exits zero. Attempt:
`.local/inventory-result-admission/qualification/c54059f60dde49878f2fa92ffd1cdaf9/`.
Receipt SHA-256 `10a66a8fc7e6431c5ef2aa79a48a3bac341907f0f7d0b9adfff40ebf22608d2b`;
log `72b937055e60f00871168447f33cdfe8bad2834dd30c351f749ef88a22979bb1`.
Twenty actual input pins match before/after. Normal import origins and the
actual saved Task import trace include `inventory_result`, the published
`charge_result`, current `remote` and its `awake_result` import. All 51 wire
receipts retain the original helper bytes and request/transport behavior.

One required combined `task check` passes **24 runtime and 1,438 tooling tests,
nine expected skips**, both compiled C guards, Bash syntax and ShellCheck.
Original session `14748`, Task PID `1295213` / wrapper `1295200`, runs
`2026-10-22T19:35:18.925585+00:00` to
`2026-10-22T19:35:54.117126+00:00`, terminal zero. All 942 tracked inputs match
before/after; both original jobs are terminal with absent PIDs.
Attempt `.local/inventory-result-admission/full/71b6e6c86cb340178a056b275be6d94b/`;
receipt `ce6373acab0a02eefc2ad5ef1b7f4fae3bf1582a7677c7186c2752ef5826d79a`;
log `e2c74899b0c00e38514ba286095a2f13fae1d3358f27ffe408b4872e819b598d`.

Only this report and own README/FOLLOW-UP/navigation prose are added afterward.
Tested executable, Task and protected input bytes remain exact. No redundant
focused/full, native/ARM/kernel/image or device run is performed. Complete
factual source/spec/evidence is frozen for entirely new additional Standards
and Spec reviewers. Publication/closure require their acceptance and a separate
serialized coordinator grant. Original NEO-121 evidence and parent
NEO-10/101/192 physical, electrical, pack-limit and clock/PM gates stay open.
