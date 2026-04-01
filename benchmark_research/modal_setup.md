# Modal Sandbox + TmuxSession: Programmatic Setup Research

## 1. Required Environment Variables

From `.env.example`, three variables are needed:

```
ANTHROPIC_API_KEY=    # For the LLM (not needed for sandbox-only benchmarking)
MODAL_TOKEN_ID=       # Modal authentication
MODAL_TOKEN_SECRET=   # Modal authentication
```

Modal auth can alternatively come from `~/.modal.toml` (created by `modal token new`).
The `ModalEnvironment.preflight()` checks for either env vars or the toml file.

## 2. Creating a Modal Sandbox Programmatically

### 2.1 Direct Modal SDK (Lowest Level)

The simplest way to create a sandbox, bypassing harbor's abstractions:

```python
import asyncio
from modal import App, Image, Sandbox

async def create_raw_sandbox():
    app = await App.lookup.aio(name="__benchmark__", create_if_missing=True)
    image = Image.from_registry("ubuntu:22.04")

    sandbox = await Sandbox.create.aio(
        app=app,
        image=image,
        timeout=3600,          # 1 hour max lifetime
        cpu=1,
        memory=2048,           # MB
    )
    return sandbox
```

Key `Sandbox.create` parameters (from Modal SDK v1.4.1):
- `app`: Required. An `App` handle obtained via `App.lookup.aio()`.
- `image`: A `modal.Image`. Built from registry, Dockerfile, or ECR.
- `timeout`: Max sandbox lifetime in seconds (default 300).
- `idle_timeout`: Seconds of inactivity before auto-terminate (optional).
- `cpu`: Float or tuple `(min, max)`.
- `memory`: Int (MB) or tuple `(min, max)`.
- `gpu`: String like `"any:1"` or `"T4:1"`.
- `block_network`: Bool, default False.
- `secrets`: Collection of `modal.Secret`.
- `name`: Optional string identifier for the sandbox.

### 2.2 Using Harbor's ModalEnvironment

Harbor wraps Modal in `harbor.environments.modal.ModalEnvironment`. Its constructor requires several harbor-specific objects:

```python
import asyncio
from pathlib import Path
from harbor.environments.modal import ModalEnvironment
from harbor.models.task.config import EnvironmentConfig
from harbor.models.trial.paths import TrialPaths

async def create_harbor_sandbox():
    trial_paths = TrialPaths(trial_dir=Path("/tmp/benchmark-trial"))
    trial_paths.mkdir()

    env_config = EnvironmentConfig(
        docker_image="ubuntu:22.04",
        cpus=1,
        memory_mb=2048,
        storage_mb=10240,
        gpus=0,
        allow_internet=True,
    )

    env = ModalEnvironment(
        environment_dir=Path("/tmp/benchmark-env"),  # Only needed if using Dockerfile
        environment_name="benchmark",
        session_id="benchmark-test-001",
        trial_paths=trial_paths,
        task_env_config=env_config,
        sandbox_timeout_secs=3600,
    )

    await env.start(force_build=False)
    return env
```

Important: `ModalEnvironment.__init__` calls `_validate_definition()`, which checks for
a Dockerfile at `environment_dir/Dockerfile` UNLESS `docker_image` is set on the config.
When `docker_image` is set, no Dockerfile is needed.

### 2.3 How `ModalEnvironment.start()` Works Internally

1. Builds the image:
   - If `docker_image` is set: uses `Image.from_registry()` (or `Image.from_aws_ecr()` for ECR).
   - Otherwise: uses `Image.from_dockerfile()` with the Dockerfile in `environment_dir`.
2. Looks up or creates the Modal app: `App.lookup.aio(name="__harbor__", create_if_missing=True)`.
3. Creates the sandbox via `Sandbox.create.aio()` with cpu, memory, gpu, network, secrets, volumes.
4. Creates log directories inside the sandbox: `/logs/agent/` and `/logs/verifier/`.
5. Makes those directories world-writable with `chmod 777`.

### 2.4 How `ModalEnvironment.exec()` Works

```python
async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
    # If user is specified, wraps command with `su <user> -s /bin/bash -c '<command>'`
    # because Modal's exec doesn't natively support user=.
    process = await self._sandbox.exec.aio(
        "bash", "-c", command,
        workdir=cwd,
        secrets=[Secret.from_dict(env)] if env else [],
        timeout=timeout_sec,
    )
    stdout = await process.stdout.read.aio()
    stderr = await process.stderr.read.aio()
    return_code = await process.wait.aio()
    return ExecResult(stdout=stdout, stderr=stderr, return_code=return_code)
```

Returns an `ExecResult(stdout, stderr, return_code)` pydantic model.

## 3. Creating and Starting a TmuxSession

### 3.1 TmuxSession Constructor

```python
from harbor.agents.terminus_2.tmux_session import TmuxSession

session = TmuxSession(
    session_name="bench",
    environment=env,           # A BaseEnvironment (e.g., ModalEnvironment)
    logging_path=PurePosixPath("/tmp/bench.pane"),
    local_asciinema_recording_path=None,   # None to skip recording
    remote_asciinema_recording_path=None,  # None to skip recording
    pane_width=160,
    pane_height=40,
    extra_env={"MY_VAR": "value"},  # Optional env vars for the tmux session
    user=None,                      # Optional user to run tmux as
)
```

### 3.2 How `TmuxSession.start()` Works

1. **Installs tmux** if not already present (auto-detects package manager: apt, yum, apk, etc.; falls back to building from source).
2. **Optionally installs asciinema** if recording paths are set.
3. **Creates the tmux session** via `environment.exec()` running:
   ```bash
   export TERM=xterm-256color && export SHELL=/bin/bash && \
   script -qc "tmux new-session -e KEY=VALUE -x 160 -y 40 -d -s bench 'bash --login' ; \
   pipe-pane -t bench 'cat > /tmp/bench.pane'" /dev/null
   ```
   Uses `script -qc` to allocate a PTY for tmux without requiring Docker's `-it` flags.
4. Sets tmux `history-limit` to 10,000,000 lines.
5. If asciinema recording is enabled, starts `asciinema rec` inside the session.

### 3.3 Sending Commands

```python
# Non-blocking: sends keys and returns immediately (with optional minimum wait)
await session.send_keys(
    keys=["echo hello", "Enter"],
    block=False,
    min_timeout_sec=1.0,    # Wait at least 1s before returning
)

# Blocking: waits for the command to finish (uses `tmux wait -S done`)
await session.send_keys(
    keys=["ls -la /", "Enter"],
    block=True,
    max_timeout_sec=30.0,   # Timeout if command takes >30s
)
```

How blocking works internally:
- `_prepare_keys()` strips the trailing Enter, appends `"; tmux wait -S done"`, then re-adds Enter.
- After sending keys, it runs `timeout <N>s tmux wait done` to block until the command signals completion.

Key format:
- Commands are literal strings: `"echo hello"`
- Special keys: `"Enter"`, `"C-c"`, `"C-d"`, `"C-m"`, etc.
- The last element in the list determines if the command executes (must be an enter-like key).

### 3.4 Reading Output

```python
# Capture current visible pane (last pane_height lines)
visible = await session.capture_pane(capture_entire=False)

# Capture entire scrollback buffer
full_buffer = await session.capture_pane(capture_entire=True)

# Get incremental output (diff since last call)
output = await session.get_incremental_output()
# Returns either:
#   "New Terminal Output:\n<new lines>"
#   "Current Terminal Screen:\n<visible screen>"
```

`capture_pane` runs `tmux capture-pane -p -t <session_name>` (with `-S -` for full scrollback).

`get_incremental_output` tracks a `_previous_buffer` and tries to find only the new content since the last call.

## 4. Gotchas and Requirements

### 4.1 Authentication
- Modal requires either `MODAL_TOKEN_ID` + `MODAL_TOKEN_SECRET` env vars, or `~/.modal.toml`.
- Run `modal token new` interactively to create the toml file.

### 4.2 Image Selection
- When using `docker_image` on `EnvironmentConfig`, no Dockerfile is needed.
- Without `docker_image`, a `Dockerfile` must exist at `environment_dir/Dockerfile`.

### 4.3 Async Everything
- All Modal SDK calls are async (`.aio` suffix). The entire harbor environment API is async.
- Must run inside `asyncio.run()` or an existing event loop.

### 4.4 User Execution
- Modal's `exec` does not natively support a `user=` parameter.
- Harbor works around this by wrapping commands with `su <user> -s /bin/bash -c '<cmd>'`.

### 4.5 tmux PTY Requirement
- tmux needs a TTY. Harbor uses `script -qc "..."` to allocate a pseudo-TTY inside the sandbox.

### 4.6 tmux Command Length Limit
- tmux silently drops commands exceeding ~16KB. `TmuxSession._tmux_send_keys()` auto-splits long commands across multiple `tmux send-keys` calls.

### 4.7 Sandbox Lifetime
- Default timeout is 24 hours (`86400` seconds) in harbor.
- Modal's own default is 300 seconds. Always set `timeout` explicitly.

### 4.8 Cleanup
- Always call `env.stop(delete=True)` (or `sandbox.terminate.aio()`) to avoid leaked sandboxes billing your Modal account.

### 4.9 TrialPaths Requirement
- `ModalEnvironment` requires a `TrialPaths` object. For benchmarking, create a temporary directory:
  ```python
  trial_paths = TrialPaths(trial_dir=Path(tempfile.mkdtemp()))
  trial_paths.mkdir()
  ```

### 4.10 Retry Logic
- `_create_sandbox`, `_terminate_sandbox`, `upload_file`, `download_file` all use `tenacity` retry with 2 attempts and exponential backoff.

## 5. Minimal Working Benchmark Harness

```python
"""
Minimal benchmark harness: creates a real Modal sandbox with tmux,
sends commands, reads output, and measures execution time.

Requirements:
    pip install modal harbor
    Set MODAL_TOKEN_ID and MODAL_TOKEN_SECRET env vars (or run `modal token new`).

Usage:
    python benchmark_harness.py
"""

import asyncio
import tempfile
import time
from pathlib import Path, PurePosixPath

from harbor.environments.modal import ModalEnvironment
from harbor.models.task.config import EnvironmentConfig
from harbor.models.trial.paths import TrialPaths
from harbor.agents.terminus_2.tmux_session import TmuxSession


async def create_environment() -> ModalEnvironment:
    """Create and start a Modal sandbox with a standard Ubuntu image."""
    trial_dir = Path(tempfile.mkdtemp(prefix="benchmark-"))
    trial_paths = TrialPaths(trial_dir=trial_dir)
    trial_paths.mkdir()

    env_config = EnvironmentConfig(
        docker_image="ubuntu:22.04",
        cpus=1,
        memory_mb=2048,
        storage_mb=10240,
        gpus=0,
        allow_internet=True,
    )

    env = ModalEnvironment(
        environment_dir=trial_dir,           # Not used when docker_image is set
        environment_name="benchmark",
        session_id=f"benchmark-{int(time.time())}",
        trial_paths=trial_paths,
        task_env_config=env_config,
        sandbox_timeout_secs=600,            # 10 min max for benchmark
    )

    print("Starting Modal sandbox...")
    t0 = time.time()
    await env.start(force_build=False)
    print(f"Sandbox started in {time.time() - t0:.2f}s")

    return env


async def create_tmux_session(env: ModalEnvironment) -> TmuxSession:
    """Create and start a tmux session inside the sandbox."""
    session = TmuxSession(
        session_name="bench",
        environment=env,
        logging_path=PurePosixPath("/tmp/bench.pane"),
        local_asciinema_recording_path=None,
        remote_asciinema_recording_path=None,
        pane_width=160,
        pane_height=40,
    )

    print("Starting tmux session (installs tmux if needed)...")
    t0 = time.time()
    await session.start()
    print(f"Tmux session started in {time.time() - t0:.2f}s")

    return session


async def benchmark_command(
    session: TmuxSession,
    command: str,
    block: bool = True,
    max_timeout_sec: float = 60.0,
) -> dict:
    """Send a command and measure round-trip time. Returns timing and output."""
    t0 = time.time()

    await session.send_keys(
        keys=[command, "Enter"],
        block=block,
        min_timeout_sec=0.5 if not block else 0.0,
        max_timeout_sec=max_timeout_sec,
    )

    elapsed = time.time() - t0
    output = await session.get_incremental_output()

    return {
        "command": command,
        "elapsed_sec": round(elapsed, 4),
        "output": output,
    }


async def benchmark_exec(
    env: ModalEnvironment,
    command: str,
    timeout_sec: int = 60,
) -> dict:
    """Benchmark a raw exec (no tmux) for comparison."""
    t0 = time.time()
    result = await env.exec(command=command, timeout_sec=timeout_sec)
    elapsed = time.time() - t0

    return {
        "command": command,
        "elapsed_sec": round(elapsed, 4),
        "return_code": result.return_code,
        "stdout": (result.stdout or "").strip(),
        "stderr": (result.stderr or "").strip(),
    }


async def main():
    env = None
    try:
        # --- Phase 1: Create sandbox ---
        env = await create_environment()

        # --- Phase 2: Benchmark raw exec (no tmux) ---
        print("\n=== Raw exec benchmarks ===")
        for cmd in ["echo hello", "ls /", "cat /etc/os-release", "sleep 1 && echo done"]:
            result = await benchmark_exec(env, cmd)
            print(f"  {cmd:40s} -> {result['elapsed_sec']:.4f}s  rc={result['return_code']}")

        # --- Phase 3: Create tmux session ---
        session = await create_tmux_session(env)

        # --- Phase 4: Benchmark tmux commands ---
        print("\n=== Tmux session benchmarks (blocking) ===")
        for cmd in ["echo hello", "ls /", "cat /etc/os-release", "sleep 1 && echo done"]:
            result = await benchmark_command(session, cmd, block=True)
            print(f"  {cmd:40s} -> {result['elapsed_sec']:.4f}s")

        print("\n=== Tmux session benchmarks (non-blocking, 0.5s min wait) ===")
        for cmd in ["echo hello", "ls /"]:
            result = await benchmark_command(session, cmd, block=False)
            print(f"  {cmd:40s} -> {result['elapsed_sec']:.4f}s")

        # --- Phase 5: Verify output correctness ---
        print("\n=== Output correctness check ===")
        result = await benchmark_exec(env, "echo MARKER_12345")
        assert "MARKER_12345" in result["stdout"], f"Expected marker in: {result['stdout']}"
        print("  exec output correctness: PASS")

        await session.send_keys(["echo TMUX_MARKER_67890", "Enter"], block=True)
        pane = await session.capture_pane(capture_entire=True)
        assert "TMUX_MARKER_67890" in pane, f"Expected marker in pane: {pane[:200]}"
        print("  tmux output correctness: PASS")

        print("\nBenchmark complete.")

    finally:
        if env is not None:
            print("\nTearing down sandbox...")
            await env.stop(delete=True)
            print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
```

## 6. Key Source File Locations

| Component | Path |
|-----------|------|
| ModalEnvironment | `/home/tianhao/miniconda3/lib/python3.13/site-packages/harbor/environments/modal.py` |
| BaseEnvironment + ExecResult | `/home/tianhao/miniconda3/lib/python3.13/site-packages/harbor/environments/base.py` |
| EnvironmentFactory | `/home/tianhao/miniconda3/lib/python3.13/site-packages/harbor/environments/factory.py` |
| EnvironmentConfig | `/home/tianhao/miniconda3/lib/python3.13/site-packages/harbor/models/task/config.py` |
| TrialPaths / EnvironmentPaths | `/home/tianhao/miniconda3/lib/python3.13/site-packages/harbor/models/trial/paths.py` |
| TmuxSession | `/home/tianhao/miniconda3/lib/python3.13/site-packages/harbor/agents/terminus_2/tmux_session.py` |
| Terminus2 agent (usage example) | `/home/tianhao/miniconda3/lib/python3.13/site-packages/harbor/agents/terminus_2/terminus_2.py` |
| EnvironmentType enum | `/home/tianhao/miniconda3/lib/python3.13/site-packages/harbor/models/environment_type.py` |
