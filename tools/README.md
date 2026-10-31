# openpilot tools

## System Requirements

openpilot supports Linux alongside the [supported embedded hardware](https://github.com/commaai/openpilot#running-on-a-dedicated-device-in-a-car).

Most of openpilot should work natively on macOS. On Windows, you can use WSL for a nearly native Linux experience.

## Native setup on Linux and macOS

Follow these instructions for a fully managed setup experience. If you'd like to manage the dependencies yourself, just read the setup scripts in this directory.

**1. Clone openpilot**
``` bash
git clone https://github.com/commaai/openpilot.git
```

**2. Run the setup script**
``` bash
cd openpilot
tools/op.sh setup
```

**3. Activate a Python shell**
Activate a shell with the Python dependencies installed:
``` bash
source .venv/bin/activate
```

**4. Build openpilot**
``` bash
scons -u
```

## WSL on Windows

[Windows Subsystem for Linux (WSL)](https://docs.microsoft.com/en-us/windows/wsl/about) should provide a similar experience to native Linux. [WSL 2](https://docs.microsoft.com/en-us/windows/wsl/compare-versions) specifically has been reported by several users to be a seamless experience.

Follow [these instructions](https://docs.microsoft.com/en-us/windows/wsl/install) to set up WSL. We recommend installing the `Ubuntu-24.04` distribution. Once your WSL environment is set up, follow the Linux setup instructions to finish setting up your environment. See [these instructions](https://learn.microsoft.com/en-us/windows/wsl/tutorials/gui-apps) for running GUI apps.

**NOTE**: If you are running WSL 2 and experiencing performance issues with the UI or simulator, you may need to explicitly enable hardware acceleration by setting `GALLIUM_DRIVER=d3d12` before commands. Add `export GALLIUM_DRIVER=d3d12` to your `~/.bashrc` file to make it automatic for future sessions.

## CTF
Learn about the openpilot ecosystem and tools by playing our [CTF](/tools/CTF.md).

## Directory Structure

```
├── car_porting/        # Tools for porting new cars
├── release/            # Scripts for building openpilot releases
└── scripts/            # Miscellaneous scripts
```

Development tools such as cabana, plotjuggler, and replay live in [openpilot/tools/](/openpilot/tools/):

```
├── cabana/             # View and plot CAN messages from drives or in realtime
├── camerastream/       # Cameras stream over the network
├── joystick/           # Control your car with a joystick
├── lib/                # Libraries to support the tools and reading openpilot logs
├── plotjuggler/        # A tool to plot openpilot logs
├── replay/             # Replay drives and mock openpilot services
└── sim/                # Run openpilot in a simulator
```

## Private Odyssey workflow

Use `ody-op-test` for development, tooling, and supervised tests. `ody-op` is the public install
branch and repository default; target development pull requests to `ody-op-test`. GitHub Actions
publishes the latest `ody-op-test` every Sunday at 6:15 PM America/Chicago
after software checks pass. Monday at 6:15 AM, a separate job merges official master and its exact
opendbc pin into `ody-op-test`, validates it, and publishes opendbc before the parent. Both retain
existing history and stop for source conflicts or concurrent development. The small schedulers live
on `ody-op`; neither weekly job deploys to the device. Sunday publishes the exact checked revision.
`master` is inactive history; use `upstream/master` for
deliberate upstream updates. For a manual
release, preview with `.venv/bin/python .agents/publish_public.py`, then publish with
`.venv/bin/python .agents/publish_public.py --publish`. This retains vehicle code, tests, and submodule
pins, excludes custom tooling, and preserves public CI configuration. Publication never deploys to
the device; device build/health checks and road assessment remain separate gates.

Set `COMMA_SSH=comma@<tailnet-host>` or `ODYSSEY_DEVICE` in your local shell before using
live-device tasks. Private rlogs and route evidence live in the Git-excluded `.private/` folder.
Read `.private/README.md` for the local archive layout and `LOG_ROOT` setup. Downloads are manual,
use Tailscale SSH, and may run while driving or over cellular. Keep machine-specific addresses
and private route data out of Git.

This checkout also exposes a small set of explicit VS Code tasks in
[`../.vscode/tasks.json`](../.vscode/tasks.json):

- **Download and Validate New Logs (Tailscale)** SSH-pulls retained private full-rate rlogs and updates the
  authoritative validation ledger. The task sets `UV_CACHE_DIR` to a writable temporary cache.
- **Validate One Route** re-runs the authoritative validator for one already-local route without
  pulling anything. **Inspect Following Trace** prints the planner → `carControl` → wire → `aEgo`
  trace for the same route; both tasks prompt for a route ID or unique prefix.
- **Inspect Upstream Delta** fetches the two upstream remotes and prints history-only object counts
  plus the recent 20 commits in both directions of the parent and nested delta, along with the
  upstream-pinned nested commit. The counts describe commit identity, so a cherry-picked change
  can be source-equivalent while still appearing in both histories; inspect the actual diff before
  importing anything. **Sync Upstream Locally**
  runs `.agents/sync_upstream.py`; it preserves existing history and requires both repositories
  clean and on `ody-op-test`. It does not push unless explicitly invoked with `--publish` and both
  expected remote tips after validation.
- **Run Jotpluggler** and **Run Cabana** inspect a local route; build the binaries once with
  `tools/op.sh build openpilot/tools/jotpluggler/jotpluggler openpilot/tools/cabana/cabana` if they
  are not present. Cabana accepts `live` when `ODYSSEY_DEVICE` names the comma device.
- **Run Odyssey software checks** runs the focused lint, Odyssey rail/sync tests, and the nested
  `opendbc_repo/test.sh` suite. These are software/CAN-safety gates, not ride-quality evidence.
- **Publish and Deploy ody-op-test** is the guarded custom deployment. It requires clean paired
  repositories, matching parent/submodule SHAs, publishes `opendbc_repo` before the parent, requires
  a confirmed offroad device and preserves Alpha Long, recreates the frozen environment and managed Python under `/data`, builds,
  reboots, and verifies exact source and runtime health. The task calls
  `tools/deploy_ody_op.sh deploy`; its `verify` command is read-only.
The former **Recover device on sunnypilot/staging** and **Verify device on sunnypilot/staging**
VS Code tasks were removed after repeated unreliable swaps. `tools/deploy_staging.sh` remains only
as an explicit manual fallback for a deliberate recovery; it destructively switches
`/data/openpilot` to the official Sunnypilot `origin/staging`, sets `UpdaterTargetBranch=staging`
and `AlphaLongitudinalEnabled=0`, reboots, and verifies exact state after reconnecting. It accepts
`ODYSSEY_DEVICE` and `ODYSSEY_SSH_KEY` overrides.

Project agent guidance lives in [`../AGENTS.md`](../AGENTS.md) and [`../.agents/`](../.agents/).
