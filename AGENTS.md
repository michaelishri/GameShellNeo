## Driver engineering

- Driver changes are authorized throughout GameShellNeo's agreed scope, including fixes, refactoring, extensions and replacements. Do not seek separate approval merely because a change belongs in a driver.
- Prioritize a stable, fast, power-efficient driver stack. Fix the underlying driver issue at the appropriate layer where practical rather than accumulating userspace workarounds, retries or delays that mask it.
- Treat existing upstream, vendor and ClockworkPi implementations as reference material, not prescribed code. Prefer maintainable upstream-compatible fixes when suitable, but do not preserve a defective design solely to avoid driver changes.
- If a hardware constraint or unresolved cause requires a temporary workaround, document the evidence, tradeoff and removal criteria, and track the underlying work in `FOLLOW-UP.md`.
- Validate changes with reproducible tests and relevant hardware qualification. Keep claims of stability, latency and energy savings tied to evidence; source-level improvements alone do not establish hardware results.

## Kaneo

- This project tracks work using Kaneo on the "GameShellNeo" (NEO) project in the "OpenSource" workspace.
- After a plan is approved, create tickets in Kaneo instead of the `PLAN.md` file.
- Whenever a bugfixes or tweaks are requested, please assess what needs to be done, then create the ticket and progress it through the board.
- When working on a ticket, move it to the "In Progress" column.
- Commit and push after each ticket has been completed and update the ticket with a summary of the implementation before closing it off.
- When a review is required before closing the ticket off, move the ticket to the "In Review" column.
