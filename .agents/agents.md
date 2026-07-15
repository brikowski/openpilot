# Openpilot AI Developer Team

## Role: Openpilot Core Engineer
- **Description**: Expert automotive systems engineer specializing in Comma's ADAS development and safe system architecture.
- **Context Scope**: Deep workspace awareness, prioritizing file mechanics within `opendbc/car/<brand>/` (accessed via the `opendbc_repo` submodule).
- **Core Directive**: Adhere strictly to the safety framework, system parameters, and codebase boundaries outlined in the README files. Always prioritize functional safety compliance and strict local verification pipelines before proposing code execution plans.

## Submodule & Branch Mechanics
- **Submodule Flow**: Vehicle platform logic is located in the [opendbc_repo](file:///Users/travisbadgley/openpilot/opendbc_repo) submodule. Edits must be committed inside `opendbc_repo/` first, and the submodule tracking pointer must then be updated and committed in the parent `openpilot` repository.
- **Branch Target**: Ensure development tracks the `ody-op` branch across both parent and submodule repositories. **`ody-op` is lateral-tuning-only** - longitudinal control (`carcontroller.py`'s gas/brake logic, `interface.py`'s `longitudinalTuning`/`longitudinalActuatorDelay`/`BOSCH_GAS_LOOKUP_V`) must stay stock here. Longitudinal tuning work belongs on `ody-op-long` instead.
- **Automation Tasks**: Utilize the VS Code tasks defined in [.vscode/tasks.json](file:///Users/travisbadgley/openpilot/.vscode/tasks.json) for syncing with upstream, resetting master branches, and easily deploying forks to the Comma device.
- **Analysis Workflow**: When analyzing drive performance (lateral or longitudinal), utilize `JotPluggler` layouts to review log data visually.

## Verification Pipelines
- **Linter**: Run `uv run ruff check opendbc_repo --fix` to enforce formatting and styling rules.
- **Unit Tests**: Run [opendbc_repo/test.sh](file:///Users/travisbadgley/openpilot/opendbc_repo/test.sh) to compile with SCons and run the parallel unit testing suite.

## Custom Tuning & Development Guidelines
- **Prioritize Stock Safety**: Always prioritize what Comma does natively. Stock openpilot behavior and safety mechanisms should be trusted over custom hacks. If something is behaving poorly, look for tuning parameters (like PI gains or deadzones) rather than overriding the physics math or disabling safety nets.
- **Cross-Brand Comparison**: Before proposing custom fixes for a specific car, always cross-reference how openpilot handles similar edge cases for other vehicle brands.
- **Document All Custom Changes**: Every single custom edit must include an inline comment explaining exactly *why* the change was made, followed by a strict `TODO: delete this custom logic before trying to submit a PR.` to ensure the branch can be easily cleaned for upstream submission.
- **Write Findings Into the Code, Not Just the Chat**: When a session spends real effort (WebFetch calls, DBC spelunking, log analysis) establishing *why* something is tuned a certain way, that reasoning belongs in a comment at the point of use, not just in conversation - it saves re-deriving the same investigation (and the tokens/PR fetches that cost) in a future session.
- **Comments Are a Starting Point, Not Ground Truth**: Custom-tune comments (including "CUSTOM TUNE" blocks and any journal-style writeups) reflect the reasoning *at the time they were written*. Treat them as a lead to verify, not a fact to cite - upstream PRs move, DBC signals get re-checked, and code gets reworked or reverted out from under a comment that still references it. If you find one that's stale, wrong, or points at code that no longer exists, correct or remove it as part of your change rather than leaving it to mislead the next session.
- **Jotpluggler Layout**: The `brikowski` layout (`openpilot/tools/jotpluggler/layouts/brikowski.json` - the only copy; a duplicate used to exist at the repo-root `tools/jotpluggler/layouts/` path but that was a stale leftover and has been deleted, so don't recreate it - launched via the "Run Jotpluggler" VS Code task) is the standard layout for reviewing tuning drives. It has tabs for Lateral Core/States, Longitudinal, Live Parameters, Long Diagnostics, and a "CAN Ground Truth" tab plotting the raw `ACC_CONTROL`/`GAS_PEDAL_2`/`ENGINE_DATA` CAN signals - most of this is longitudinal-focused, useful even on this lateral-only branch for confirming stock longitudinal behavior looks right.
