# Docker build ownership after host interruption

NEO-194, 22 October 2026 NZDT. Implementation is on
`work/build-stage-ownership`, based on `57a6c225e0001dd0e2cb0e7d11713cc5f333f438`.
This is local build orchestration. It changes no kernel patch, image identity,
completed build artifact or device setting.

## Problem and acceptance contract

The diagnostic.26 host command ended with status 143 while Docker container
`3b60e1000121` continued compiling. The host `kernel.log` stopped advancing;
Docker logs continued. That exact container later exited zero and all 16
kernel artifacts verified. No duplicate build was started.

Kaneo's NEO-194 requires explicit per-stage container identity, durable output
and terminal-result capture, and ownership-aware continuation or termination.
A lost parent or timeout must not imply a stopped build, admit another writer,
or cause unrelated-container cleanup. Required offline checks cover parent
interruption, live-container reattachment, eventual success/failure and log
retention. Existing completed artifacts must remain intact; no physical device
access is needed.

The old `run-logged.sh` holds `workflow.lock` in the host process tree. Killing
that entire tree releases the flock while an unnamed `docker run --rm`
container can keep writing. A bounded baseline copies the wrapper directly
from the fixed commit, starts the locked local builder with `--network=none`,
kills only the fixture's host process group and tries another logged writer.
Original attempt `30651dd05d794347a0c75631d7bea166` proves the second writer was
admitted while the original container remained running; its final exit was
zero. Evidence stays under
`.local/build/docker-ownership/attempts/30651dd05d794347a0c75631d7bea166/`.
The baseline Task intentionally fails after recording that defect.

## Ownership and recovery

`tools/run-logged.sh` retains its existing flock and checks container admission
before rotating a stage log or running host preparation. Its private PATH shim
routes foreground `docker run` calls through `tools/docker-stage.py`; other
Docker commands use the original executable. Existing arguments remain data,
including volume paths containing spaces, environment, user and working
directory. Interactive, detached and caller-supplied identity/lifetime/logging
flags are rejected for managed repository builds.

The helper atomically saves and fsyncs an ownership reservation before Docker
creation, then records the exact returned ID. A deterministic workspace name
provides daemon-side exclusion, and workspace/stage/run labels qualify any
recovery action. Container ownership operations are serialized separately
from the foreground workflow. A missing ID can be reconciled only against the
matching name and labels. A foreign identity or unavailable Docker state
blocks progress rather than authorizing cleanup.

One authoritative `start.json` receipt is initialized before publishing a new
reservation. Immediately before a start request it changes durably from
`unrequested` to `pending`; only a successful CLI acknowledgement changes it
to `acknowledged`. Nonzero CLI results and lost replies remain unresolved.
Older records without a receipt are unknown. Both start and created-cancel
paths consult the same receipt: neither issues another start nor removes a
created container unless its start is positively unrequested. Running or exited
state permits ordinary recovery and actual-result collection. A created
container that remains unresolved retains ownership for diagnosis; status
reports its start state. This prevents a delayed request from completing in
the inspection/removal gap and losing its terminal evidence.

Containers keep daemon-owned JSON logs and are not automatically removed.
One shared start gate rejects rotation and nonblocking delivery before both
the original start and recovery of a created container.
The foreground command follows those logs. Losing that observer leaves the
ownership record and container available. `build:stage:status` reports state;
`resume` follows the same running container, collects an exited container, or
starts the original created container. `stop` targets only the verified
container and requests termination with a ten-second grace period. See the
[build workflow](../README.md) for the saved commands.

Final collection rechecks exit state, writes and fsyncs the complete log,
records the actual Docker exit code and log SHA-256, then removes the exact
container and releases admission. Evidence lives in
`.local/build/container-stages/RUN/{job.json,container.log,result.json}`.
Observation, collection and removal failures retain ownership. A removal
retry preserves the first result and log; reconciliation records are additive.
Created cancellation saves the original observed state and start error in a
durable `cancellation.json` before removal; repeated snapshots are additive.
Only a positively unrequested start permits removal. Its result has
`exit_code: null`, helper return code 125 and `log_complete: false`.
Unresolved starts retain both ownership and the actual container rather than
replacing a potentially available terminal result. Cancellation after an
interrupted creation records an explicit incomplete-log outcome. A late
creation can be recovered and retired but cannot restart a previously
cancelled job. If one observer collects and removes a run before another can
attach, the latter reconciles the same run's saved exit code.

## Reusable validation

```sh
task test:docker-ownership-baseline  # Expected nonzero on the old wrapper
task test:docker-ownership
task test:build-workflow
task check
```

The Docker fixtures use the digest-locked, already cached builder with
`--pull=never` and `--network=none`. They create private workspaces containing
spaces and copy the actual wrapper/helper/shim. Fixture cleanup checks only
the recorded IDs and labels. Input hashes are saved before execution and
rechecked after the run; original attempts are retained.

Twelve fixture groups cover:

- Host process-group interruption while a container remains live, followed
  by recovery of the same container and exit zero.
- Unobserved container exit 7, blocked successor before log rotation, full
  log recovery and readmission only after verified retirement.
- Preserved stdout, stderr, exit code, environment, bind mount, user and
  working directory.
- Failed start, unavailable daemon, foreign ID rejection, missing-ID
  reconciliation and preservation of an unresolved created state.
- Failed creation reservation, absent cancellation, a controlled late-create
  seam, refusal to restart that cancelled job and original-result retention.
- Explicit running-container stop concurrent with the foreground observer,
  retaining its actual trapped exit 23 and stop intent.
- Injected removal failure after terminal evidence is saved, continued
  admission exclusion and retry without changing original evidence.
- Rotating and nonblocking Docker logging configurations, injected at actual
  container creation; original and recovery starts must both refuse them.
- Removal of a created container followed by a lost removal reply; its original
  state must survive recovery without a fabricated exit code.
- Pausing one log observer until a second has collected and removed the same
  run; the late observer must return the saved success or failure code.
- A delayed original start that can finish in the cancellation/removal gap;
  unresolved and missing legacy metadata must block cancellation/restart,
  followed by collection of the original output and actual exit 7.

Attempt `47faf1a11aad492e96d186bf51ffc391` passes all seven groups with unchanged
recorded inputs. `test:build-workflow` passes 18 tests. The full host check
passes 24 runtime tests and 1,007 tooling tests (two existing optional skips),
both compiled C regressions, Bash syntax and ShellCheck, including the Docker
PATH shim. The first sandboxed full run retained five socket-write errors in
existing local SSH fixtures; rerunning with host socket access passes. Neither
run contacts the GameShell. Logs are retained in
`.local/build/{build-workflow.log,docker-ownership.log,neo194-check.log,neo194-check-host.log}`.

## Independent review and reproduced corrections

The code-review skill ran Standards and Spec reviews independently against
`57a6c225e0001dd0e2cb0e7d11713cc5f333f438...6c52ab3`. The initial reports found:

### Standards

Two documented-standard violations: created-container recovery bypassed the
original logging gate, and created cancellation removed the container before
preserving its observed state. The duplicated start paths were also a possible
Duplicated Code smell; no additional actionable smell was reported.

### Spec

Two findings: the same logging-admission gap violated durable-output retention,
and a late log observer could return helper failure 1 after another observer
had already saved the actual container result. No unsolicited scope was found.

### Corrections and regression evidence

Three distinct review findings were accepted. A shared start gate now applies
to original and recovered starts; cancellation state is saved before removal;
and an attachment error reconciles the original durable result through the
existing collection path. The logging audit also identified inherited
nonblocking delivery as incompatible with a complete log; the same gate now
rejects it. Created cancellation explicitly retains uncertainty about a delayed
start and uses a null process exit/incomplete-log result.

The expanded fixtures first ran against helper commit `6c52ab3` and failed at
the intended assertions:

| Regression | Original failing attempt | Observed defect |
| --- | --- | --- |
| `logging-rotation` | `09daa14be88747c6a51bbc68ee8efca7` | Resume started the rejected created container |
| `logging-nonblocking` | `06370e7e4f80412c8ea1fbd16c793346` | Original start accepted nonblocking output |
| `created-cancellation` | `93609d1907964b0f81013c1ca28e6a93` | Lost removal reply erased the created-state snapshot |
| `attachment-race` | `977e19a2dd474378af40955379651145` | Late observer returned 1 for a saved exit of zero |

All attempts and original failures remain private in
`.local/build/docker-ownership/attempts/`. Individual regressions can be selected
through `task test:docker-ownership CASE=attachment-race` (or another case name
above). The eleven-group checkpoint `70fa425b12964c318190ceb27eccf920` passed;
all five recorded input hashes matched at that checkpoint. Its ownership records are retired,
and final Docker inspection shows no fixture containers and the same unrelated
containers as the initial inspection. The full host check passes again:
24 runtime tests, 1,007 tooling tests (two existing optional skips), both C
regressions and Bash syntax/ShellCheck. Its log is
`.local/build/neo194-check-reviewed.log`.

The Standards recheck at `568ad1e` cleared both original violations and the
duplicated-start smell. The Spec recheck cleared its original two findings but
identified one remaining delayed-start cancellation race: an explicit null
result preserved uncertainty but could still discard available terminal
evidence. New case `delayed-start` reproduced this against `568ad1e` in attempt
`e94fd18abd134143a6d96ea4ca073b40`. The durable start receipt above now excludes
removal and repeated start while a request is unresolved. Failed-executable
fixture cleanup is explicitly confined to its known, nonexecuting test object;
production recovery retains that ambiguous created state. The corrected
twelve-group attempt `87f5a037f59c472ab0607ba0655ac940` passes, all five input
hashes match, and no ownership records remain. Full host checks pass again
(24 runtime, 1,007 tooling with two optional skips, C regressions and shell
checks); see `.local/build/neo194-check-start-receipt.log`. Docker Engine/client
29.8.1 (daemon commit `464cd50`) was used for these fixtures.

### Final Standards recheck

The independent reviewer cleared all documented-standard and smell findings at
`3eeffc8`. The authoritative receipt preserves unresolved requests, both guarded
operations require positive unrequested evidence, and the documentation records
the recovery limits. The reviewer independently verified all twelve saved
groups, five current input hashes and retired ownership records without
running Docker or changing files.

### Final Spec recheck

The independent reviewer cleared every Spec finding at `3eeffc8`, including
the delayed-start race, and found no unsolicited scope. Original/recovery
logging gates, late-observer reconciliation and unresolved/legacy start
ownership now meet the ticket contract. The reviewer independently verified
the same twelve results, input hashes and retired records without rerunning
the fixtures.

Final review: Standards zero outstanding findings; Spec zero outstanding
findings. NEO-194's bounded local implementation, documentation and offline
qualification are complete. Other worktrees require deliberate adoption; no
new image or hardware qualification is implied.

## Scope and limits

This establishes the bounded local Docker/host interruption contract, not
arbitrary daemon/storage failure recovery. Missing or mismatched Docker
identity and uncollectable logs remain explicit recovery errors. Manual
container/ledger deletion can destroy evidence and is not a supported way to
resume a build. Docker logging that rotates the full log is refused before
each start. Nonblocking delivery is also refused. Retained logs consume
host/Docker storage until collection; normal
artifact retention and disk preflight still apply.

Recovery collects a container result, not the original outer Task. It does
not replay host-side postprocessing, bundle an image or imply artifact validity.
Inspect the recorded result, run the existing artifact checks and continue the
appropriate build tasks. Never infer a completed image from exit zero alone.
The interrupted top-level log stays historical; `container.log` contains the
recovered full container output. Direct Docker commands and other worktrees
require deliberate adoption of this wrapper. No hardware access, PM work,
image rebuild or abandoned SSH-stall experiment is part of this ticket.
