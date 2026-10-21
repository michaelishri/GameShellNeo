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

Containers keep daemon-owned JSON logs and are not automatically removed.
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
A never-started cancellation has `exit_code: null` and helper return code 125.
Cancellation after an interrupted creation records an explicit incomplete-log
outcome. A late creation can be recovered and retired but cannot restart a
previously cancelled job.

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

Seven fixture groups cover:

- Host process-group interruption while a container remains live, followed
  by recovery of the same container and exit zero.
- Unobserved container exit 7, blocked successor before log rotation, full
  log recovery and readmission only after verified retirement.
- Preserved stdout, stderr, exit code, environment, bind mount, user and
  working directory.
- Failed start, unavailable daemon, foreign ID rejection, missing-ID
  reconciliation and truthful never-started cancellation.
- Failed creation reservation, absent cancellation, a controlled late-create
  seam, refusal to restart that cancelled job and original-result retention.
- Explicit running-container stop concurrent with the foreground observer,
  retaining its actual trapped exit 23 and stop intent.
- Injected removal failure after terminal evidence is saved, continued
  admission exclusion and retry without changing original evidence.

Attempt `47faf1a11aad492e96d186bf51ffc391` passes all seven groups with unchanged
recorded inputs. `test:build-workflow` passes 18 tests. The full host check
passes 24 runtime tests and 1,007 tooling tests (two existing optional skips),
both compiled C regressions, Bash syntax and ShellCheck, including the Docker
PATH shim. The first sandboxed full run retained five socket-write errors in
existing local SSH fixtures; rerunning with host socket access passes. Neither
run contacts the GameShell. Logs are retained in
`.local/build/{build-workflow.log,docker-ownership.log,neo194-check.log,neo194-check-host.log}`.

Independent Standards/Spec review is pending.

## Scope and limits

This establishes the bounded local Docker/host interruption contract, not
arbitrary daemon/storage failure recovery. Missing or mismatched Docker
identity and uncollectable logs remain explicit recovery errors. Manual
container/ledger deletion can destroy evidence and is not a supported way to
resume a build. Docker logging that rotates the full log is refused before
start. Retained logs consume host/Docker storage until collection; normal
artifact retention and disk preflight still apply.

Recovery collects a container result, not the original outer Task. It does
not replay host-side postprocessing, bundle an image or imply artifact validity.
Inspect the recorded result, run the existing artifact checks and continue the
appropriate build tasks. Never infer a completed image from exit zero alone.
The interrupted top-level log stays historical; `container.log` contains the
recovered full container output. Direct Docker commands and other worktrees
require deliberate adoption of this wrapper. No hardware access, PM work,
image rebuild or abandoned SSH-stall experiment is part of this ticket.
