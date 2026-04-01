"""
Benchmark for terminal command execution strategies.

Spins up a real Modal sandbox + tmux session and compares:
  1. Sequential (baseline) — send cmd, sleep duration, repeat
  2. Marker-sequential — send cmd+marker, poll per-cmd, repeat
  3. Pipelined — send ALL cmds+markers, poll for last marker only

Measures wall-clock time and verifies output correctness for each strategy.

Usage:
    cd /home/tianhao/terminal-bench-hard
    python benchmark/bench_cmd_exec.py
"""

import asyncio
import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from harbor.environments.modal import ModalEnvironment
from harbor.models.task.config import EnvironmentConfig
from harbor.models.trial.paths import TrialPaths
from harbor.agents.terminus_2.tmux_session import TmuxSession


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Cmd:
    """A single command to send."""
    keystrokes: str
    duration: float = 1.0          # how long the agent *would* wait
    expect_substr: str | None = None  # substring expected in output (for correctness)


@dataclass
class BenchCase:
    """A named list of commands to benchmark together."""
    name: str
    commands: list[Cmd]
    description: str = ""


@dataclass
class BenchResult:
    case_name: str
    strategy: str
    wall_sec: float
    correct: bool
    detail: str = ""


# ---------------------------------------------------------------------------
# Test cases — realistic patterns from agent trial logs
# ---------------------------------------------------------------------------

CASES: list[BenchCase] = [
    # --- Fast commands (agent uses 0.1s duration) ---
    BenchCase(
        name="fast_batch_5",
        description="5 instant commands (ls, echo, pwd, cat, whoami)",
        commands=[
            Cmd("ls /\n", 0.1, "usr"),
            Cmd("echo HELLO_WORLD\n", 0.1, "HELLO_WORLD"),
            Cmd("pwd\n", 0.1, "/"),
            Cmd("cat /etc/hostname\n", 0.1),
            Cmd("whoami\n", 0.1, "root"),
        ],
    ),

    # --- Independent reads (parallelizable) ---
    BenchCase(
        name="parallel_reads",
        description="4 independent file reads that don't depend on each other",
        commands=[
            Cmd("cat /etc/os-release\n", 0.5, "VERSION"),
            Cmd("cat /etc/passwd | head -3\n", 0.5, "root"),
            Cmd("ls -la /usr/bin/ | head -5\n", 0.5),
            Cmd("df -h /\n", 0.5, "Filesystem"),
        ],
    ),

    # --- Medium commands (1-2s duration) ---
    BenchCase(
        name="medium_batch",
        description="Commands with real work: find, grep, wc",
        commands=[
            Cmd("find /usr/lib -name '*.so' -maxdepth 2 2>/dev/null | wc -l\n", 2.0),
            Cmd("grep -r 'root' /etc/passwd\n", 1.0, "root"),
            Cmd("apt list --installed 2>/dev/null | wc -l\n", 2.0),
        ],
    ),

    # --- Slow command (agent uses 5-30s) ---
    BenchCase(
        name="slow_single",
        description="One slow command that takes ~3s",
        commands=[
            Cmd("sleep 3 && echo SLOW_DONE\n", 5.0, "SLOW_DONE"),
        ],
    ),

    # --- Mixed fast+slow (realistic agent pattern) ---
    BenchCase(
        name="mixed_batch",
        description="Fast setup then slow command then fast verify",
        commands=[
            Cmd("mkdir -p /tmp/bench_test\n", 0.1),
            Cmd("echo 'data' > /tmp/bench_test/file.txt\n", 0.1),
            Cmd("sleep 2 && echo PROCESSED\n", 5.0, "PROCESSED"),
            Cmd("cat /tmp/bench_test/file.txt\n", 0.1, "data"),
            Cmd("rm -rf /tmp/bench_test\n", 0.1),
        ],
    ),

    # --- Large output (tests output handling) ---
    BenchCase(
        name="large_output",
        description="Command that produces lots of output",
        commands=[
            Cmd("seq 1 500\n", 2.0, "500"),
        ],
    ),

    # --- Dependency chain (must be sequential) ---
    BenchCase(
        name="dependency_chain",
        description="Each command depends on the previous one",
        commands=[
            Cmd("export MYVAR=42\n", 0.1),
            Cmd("echo $MYVAR > /tmp/chain_test.txt\n", 0.1),
            Cmd("cat /tmp/chain_test.txt\n", 0.1, "42"),
            Cmd("rm /tmp/chain_test.txt\n", 0.1),
        ],
    ),

    # --- Install + build (realistic heavy pattern) ---
    BenchCase(
        name="apt_install",
        description="apt-get update + install a small package",
        commands=[
            Cmd("apt-get update -qq 2>&1 | tail -1\n", 15.0),
            Cmd("apt-get install -y -qq jq 2>&1 | tail -1\n", 10.0),
            Cmd("echo '{\"a\":1}' | jq .a\n", 0.5, "1"),
        ],
    ),

    # --- From trial logs: compile + run (gpt2-codegolf pattern) ---
    BenchCase(
        name="compile_run",
        description="Write C file, compile with gcc, run binary",
        commands=[
            Cmd("echo '#include <stdio.h>\nint main(){printf(\"COMPILED_OK\\n\");return 0;}' > /tmp/test.c\n", 0.5),
            Cmd("gcc -o /tmp/test /tmp/test.c\n", 2.0),
            Cmd("/tmp/test\n", 1.0, "COMPILED_OK"),
            Cmd("rm /tmp/test /tmp/test.c\n", 0.1),
        ],
    ),

    # --- From trial logs: heredoc file write (overestimated at 30-60s) ---
    BenchCase(
        name="heredoc_write",
        description="Heredoc file write — agents request 30s for a 0.5s op",
        commands=[
            Cmd("cat << 'HEREDOC_EOF' > /tmp/script.py\nimport sys\nprint('hello from python')\nprint(sys.version_info[:2])\nHEREDOC_EOF\n", 30.0),
            Cmd("python3 /tmp/script.py\n", 5.0, "hello from python"),
            Cmd("rm /tmp/script.py\n", 0.1),
        ],
    ),

    # --- From trial logs: git exploration burst (5 read-only cmds) ---
    BenchCase(
        name="git_exploration",
        description="Burst of 5 independent git/file reads (real pattern)",
        commands=[
            Cmd("apt-get install -y -qq git 2>&1 | tail -1\n", 10.0),
            Cmd("git init /tmp/testrepo && cd /tmp/testrepo && git commit --allow-empty -m init\n", 2.0),
            Cmd("cd /tmp/testrepo && git --no-pager log --oneline -5\n", 0.5),
            Cmd("cd /tmp/testrepo && git --no-pager diff HEAD\n", 0.5),
            Cmd("cd /tmp/testrepo && git status\n", 0.5),
            Cmd("rm -rf /tmp/testrepo\n", 0.1),
        ],
    ),

    # --- STALL TEST: generic pager trap ---
    BenchCase(
        name="pager_stall",
        description="less pager opened on large output — tests stall detection + recovery",
        commands=[
            Cmd("PAGER=less seq 1 5000 | less\n", 5.0),
            Cmd("echo RECOVERED_OK\n", 1.0, "RECOVERED_OK"),
        ],
    ),

    # --- STALL TEST: git pager trap (the #1 real failure mode from logs) ---
    BenchCase(
        name="git_pager_trap",
        description="git log without --no-pager triggers less in a real repo (exact failure from fix-git trials)",
        commands=[
            Cmd("apt-get install -y -qq git 2>&1 | tail -1\n", 10.0),
            Cmd("git init /tmp/pgtest && cd /tmp/pgtest && for i in $(seq 1 60); do git commit --allow-empty -m \"commit $i\" 2>/dev/null; done\n", 15.0),
            # This WILL trigger less — the real trap
            Cmd("cd /tmp/pgtest && git log --oneline --all --graph\n", 5.0),
            # If recovery works, shell must be usable
            Cmd("echo SHELL_ALIVE\n", 2.0, "SHELL_ALIVE"),
            Cmd("rm -rf /tmp/pgtest\n", 0.5),
        ],
    ),

    # --- STALL TEST: python REPL trap ---
    BenchCase(
        name="python_repl_trap",
        description="python3 without args opens REPL — marker never executes until exit",
        commands=[
            Cmd("python3\n", 2.0),
            Cmd("echo AFTER_PYTHON\n", 2.0, "AFTER_PYTHON"),
        ],
    ),

    # --- STALL TEST: partial stall in batch ---
    BenchCase(
        name="partial_stall_batch",
        description="First cmd stalls but subsequent cmds are independent — tests window failover",
        commands=[
            Cmd("PAGER=less seq 1 10000 | less\n", 5.0),
            Cmd("echo INDEPENDENT_1\n", 0.5, "INDEPENDENT_1"),
            Cmd("echo INDEPENDENT_2\n", 0.5, "INDEPENDENT_2"),
        ],
    ),

    # --- From synthesis: empty wait command (agent sends keystrokes="" duration=30) ---
    BenchCase(
        name="empty_wait",
        description="Empty keystroke with long duration — real agent pattern for async waits",
        commands=[
            Cmd("sleep 1 && echo ASYNC_DONE > /tmp/async_marker.txt &\n", 0.5),
            Cmd("", 30.0),  # agent's way of saying "wait"
            Cmd("cat /tmp/async_marker.txt\n", 0.5, "ASYNC_DONE"),
            Cmd("rm -f /tmp/async_marker.txt\n", 0.5),
        ],
    ),

    # --- From synthesis: iterative compile-run 5x (gpt2-codegolf pattern) ---
    BenchCase(
        name="iterative_compile_5x",
        description="5 iterations of write-compile-run with overestimated 5s durations (real: ~1.5s each)",
        commands=[
            *[cmd for i in range(5) for cmd in [
                Cmd(f"printf '#include<stdio.h>\\nint main(){{printf(\"%d\\\\n\",{i});}}' > /tmp/c{i}.c\n", 5.0),
                Cmd(f"gcc -o /tmp/c{i} /tmp/c{i}.c\n", 5.0),
                Cmd(f"/tmp/c{i}\n", 5.0, str(i)),
            ]],
            Cmd("rm -f /tmp/c*.c /tmp/c[0-9]\n", 0.5),
        ],
    ),

    # --- From synthesis: stdout flood recovery ---
    BenchCase(
        name="stdout_flood",
        description="Command that floods terminal buffer — tests recovery after massive output",
        commands=[
            Cmd("yes FLOOD | head -50000\n", 5.0),
            Cmd("echo POST_FLOOD_OK\n", 2.0, "POST_FLOOD_OK"),
        ],
    ),
]


# ---------------------------------------------------------------------------
# Execution strategies
# ---------------------------------------------------------------------------

_marker_seq = 0
_MARKER_PREFIX = "__BENCHMARKER__"


def _next_marker() -> str:
    global _marker_seq
    _marker_seq += 1
    return f"{_MARKER_PREFIX}{_marker_seq}__"


def _strip_markers(text: str) -> str:
    """Remove marker echo lines from output."""
    return "\n".join(
        line for line in text.split("\n")
        if _MARKER_PREFIX not in line
    )


async def strategy_sequential_sleep(
    session: TmuxSession, commands: list[Cmd]
) -> tuple[float, str]:
    """Baseline: send each command, sleep its duration, then next."""
    t0 = time.monotonic()
    for cmd in commands:
        await session.send_keys(cmd.keystrokes, block=False, min_timeout_sec=0.0)
        await asyncio.sleep(cmd.duration)
    output = await session.get_incremental_output()
    return time.monotonic() - t0, output


async def strategy_marker_sequential(
    session: TmuxSession, commands: list[Cmd]
) -> tuple[float, str]:
    """Current agent approach: send cmd+marker, poll for marker per-cmd."""
    t0 = time.monotonic()
    markers = []
    for cmd in commands:
        marker = _next_marker()
        markers.append(marker)
        await session.send_keys(cmd.keystrokes, block=False, min_timeout_sec=0.0)
        await session.send_keys(f"echo '{marker}'\n", block=False, min_timeout_sec=0.0)

        # Poll for this marker
        await asyncio.sleep(min(0.3, cmd.duration))
        deadline = time.monotonic() + cmd.duration
        while time.monotonic() < deadline:
            pane = await session.capture_pane(capture_entire=False)
            if marker in pane:
                break
            await asyncio.sleep(0.5)

    output = _strip_markers(await session.get_incremental_output())
    return time.monotonic() - t0, output


async def strategy_pipelined(
    session: TmuxSession, commands: list[Cmd]
) -> tuple[float, str]:
    """Pipelined: send ALL cmds+markers upfront, poll for last marker only."""
    t0 = time.monotonic()
    markers = []

    # Phase 1: fire all commands + markers without waiting
    for cmd in commands:
        marker = _next_marker()
        markers.append(marker)
        await session.send_keys(cmd.keystrokes, block=False, min_timeout_sec=0.0)
        await session.send_keys(f"echo '{marker}'\n", block=False, min_timeout_sec=0.0)

    last_marker = markers[-1]
    total_duration = sum(c.duration for c in commands)
    hard_timeout = min(max(total_duration, 10.0), 120.0)

    # Phase 2: poll for last marker (capture_entire=True for reliability)
    await asyncio.sleep(min(0.3, total_duration))
    deadline = time.monotonic() + hard_timeout
    while time.monotonic() < deadline:
        pane = await session.capture_pane(capture_entire=True)
        if last_marker in pane:
            break
        await asyncio.sleep(0.5)

    output = _strip_markers(await session.get_incremental_output())
    return time.monotonic() - t0, output


async def strategy_hybrid(
    session: TmuxSession, commands: list[Cmd]
) -> tuple[float, str]:
    """Hybrid: pipeline with markers, but skip polling when total duration < 1s.

    For fast batches (all durations tiny), polling overhead dominates.
    Instead, send all commands, sleep the max single duration + a small buffer,
    and skip marker polling entirely.

    For slow batches, use full pipelined marker polling.
    """
    t0 = time.monotonic()
    total_duration = sum(c.duration for c in commands)
    max_duration = max(c.duration for c in commands)

    # Threshold: if the longest command is very fast, don't bother polling
    if max_duration <= 0.5:
        # Fast path: send all, short sleep, grab output
        for cmd in commands:
            await session.send_keys(cmd.keystrokes, block=False, min_timeout_sec=0.0)
        # Sleep just enough for the shell to process everything
        await asyncio.sleep(max(total_duration, 0.5))
        output = await session.get_incremental_output()
        return time.monotonic() - t0, output

    # Slow path: pipelined with markers
    markers = []
    for cmd in commands:
        marker = _next_marker()
        markers.append(marker)
        await session.send_keys(cmd.keystrokes, block=False, min_timeout_sec=0.0)
        await session.send_keys(f"echo '{marker}'\n", block=False, min_timeout_sec=0.0)

    last_marker = markers[-1]
    hard_timeout = min(max(total_duration, 10.0), 120.0)

    await asyncio.sleep(min(0.3, total_duration))
    deadline = time.monotonic() + hard_timeout
    while time.monotonic() < deadline:
        pane = await session.capture_pane(capture_entire=True)
        if last_marker in pane:
            break
        await asyncio.sleep(0.5)

    output = _strip_markers(await session.get_incremental_output())
    return time.monotonic() - t0, output


async def strategy_hybrid_stall_aware(
    session: TmuxSession, commands: list[Cmd]
) -> tuple[float, str]:
    """Hybrid + stall detection/recovery.

    Same fast/slow path as hybrid, but during the polling loop:
    - Tracks whether pane content changed between polls
    - If pane is unchanged for 3 consecutive polls (~1.5s), assumes stall
    - Sends escape sequence (q, C-c, Enter) to break out of pagers/prompts
    - Re-sends the marker echo so polling can resume
    """
    t0 = time.monotonic()
    total_duration = sum(c.duration for c in commands)
    max_duration = max(c.duration for c in commands)

    # Fast path: same as hybrid
    if max_duration <= 0.5:
        for cmd in commands:
            await session.send_keys(cmd.keystrokes, block=False, min_timeout_sec=0.0)
        await asyncio.sleep(max(total_duration, 0.5))
        output = await session.get_incremental_output()
        return time.monotonic() - t0, output

    # Slow path with stall detection
    markers = []
    for cmd in commands:
        marker = _next_marker()
        markers.append(marker)
        await session.send_keys(cmd.keystrokes, block=False, min_timeout_sec=0.0)
        await session.send_keys(f"echo '{marker}'\n", block=False, min_timeout_sec=0.0)

    last_marker = markers[-1]
    hard_timeout = min(max(total_duration, 10.0), 120.0)

    await asyncio.sleep(min(0.3, total_duration))
    deadline = time.monotonic() + hard_timeout
    prev_pane = ""
    stall_count = 0
    stall_recovery_attempts = 0
    max_stall_recoveries = 3  # don't spam escape keys forever

    while time.monotonic() < deadline:
        pane = await session.capture_pane(capture_entire=True)
        if last_marker in pane:
            break

        # Stall detection: pane unchanged across polls
        if pane == prev_pane:
            stall_count += 1
        else:
            stall_count = 0
        prev_pane = pane

        # 3 unchanged polls (~1.5s) = stall detected
        if stall_count >= 3 and stall_recovery_attempts < max_stall_recoveries:
            stall_recovery_attempts += 1
            # Escape sequence: q (quit less/man), C-c (interrupt), Enter (dismiss)
            await session.send_keys("q", block=False, min_timeout_sec=0.0)
            await asyncio.sleep(0.2)
            await session.send_keys("C-c", block=False, min_timeout_sec=0.0)
            await asyncio.sleep(0.2)
            await session.send_keys("\n", block=False, min_timeout_sec=0.0)
            await asyncio.sleep(0.3)
            # Re-send the last marker so we can detect completion
            await session.send_keys(
                f"echo '{last_marker}'\n", block=False, min_timeout_sec=0.0,
            )
            stall_count = 0
            await asyncio.sleep(0.5)
            continue

        await asyncio.sleep(0.5)

    output = _strip_markers(await session.get_incremental_output())
    return time.monotonic() - t0, output


async def strategy_multi_window(
    session: TmuxSession, commands: list[Cmd]
) -> tuple[float, str]:
    """Each command runs in its own tmux window. Stalled windows get killed.

    Architecture:
    - Creates a new tmux window per command
    - Sends keystrokes + marker to that window
    - Polls for marker in that specific window
    - If marker not found by deadline, kills the window (stall recovery)
    - Collects output from each window via capture_pane

    This is the most robust strategy: a stuck pager/process in one window
    cannot block subsequent commands. Kill the window, move on.
    """
    t0 = time.monotonic()
    env = session.environment
    sess_name = session._session_name
    outputs = []

    for i, cmd in enumerate(commands):
        win_name = f"cmd{i}"
        marker = _next_marker()

        # Create a new tmux window
        await env.exec(
            command=f"tmux new-window -t {sess_name} -n {win_name} -d",
        )
        await asyncio.sleep(0.1)

        target = f"{sess_name}:{win_name}"

        # Send the command + marker
        # Use env.exec to send keys to the specific window
        ks_escaped = cmd.keystrokes.replace("'", "'\\''")
        await env.exec(
            command=f"tmux send-keys -t {target} {_shlex_quote(cmd.keystrokes)}",
        )
        await env.exec(
            command=f"tmux send-keys -t {target} {_shlex_quote(f'echo {marker}' + chr(10))}",
        )

        # Poll for marker in THIS window
        deadline = time.monotonic() + max(cmd.duration, 2.0)
        found = False
        while time.monotonic() < deadline:
            result = await env.exec(
                command=f"tmux capture-pane -p -S - -t {target}",
            )
            pane = result.stdout or ""
            if marker in pane:
                found = True
                break
            await asyncio.sleep(0.5)

        if found:
            # Capture full output from this window
            result = await env.exec(
                command=f"tmux capture-pane -p -S - -t {target}",
            )
            outputs.append(result.stdout or "")
        else:
            # Stall detected — kill the window, record failure
            await env.exec(command=f"tmux kill-window -t {target}")
            outputs.append(f"[STALL: window {win_name} killed after {cmd.duration:.1f}s]")

        # Clean up window (if still alive)
        await env.exec(command=f"tmux kill-window -t {target} 2>/dev/null || true")

    combined = _strip_markers("\n".join(outputs))
    return time.monotonic() - t0, combined


class TmuxWindowPool:
    """Pre-allocated pool of tmux windows for zero-overhead command isolation."""

    def __init__(self, env, sess_name: str, size: int = 5):
        self._env = env
        self._sess = sess_name
        self._size = size
        self._ready: asyncio.Queue[str] = asyncio.Queue()
        self._seq = 0

    async def start(self):
        """Pre-create the pool."""
        coros = [self._create_window() for _ in range(self._size)]
        names = await asyncio.gather(*coros)
        for n in names:
            await self._ready.put(n)

    async def _create_window(self) -> str:
        self._seq += 1
        name = f"pool{self._seq}"
        await self._env.exec(
            command=f"tmux new-window -t {self._sess} -n {name} -d"
        )
        return name

    async def acquire(self) -> str:
        """Get a ready window. If pool is empty, create one on the fly."""
        try:
            return self._ready.get_nowait()
        except asyncio.QueueEmpty:
            return await self._create_window()

    async def release(self, name: str):
        """Return a healthy window to the pool after resetting it."""
        # Send C-c + reset to clean up any leftover state
        target = f"{self._sess}:{name}"
        await self._env.exec(command=f"tmux send-keys -t {target} C-c")
        await self._env.exec(command=f"tmux send-keys -t {target} ' reset' Enter")
        await asyncio.sleep(0.2)
        await self._ready.put(name)

    async def kill_and_replace(self, name: str):
        """Kill a stalled window and create a fresh replacement."""
        target = f"{self._sess}:{name}"
        await self._env.exec(command=f"tmux kill-window -t {target} 2>/dev/null || true")
        new_name = await self._create_window()
        await self._ready.put(new_name)


async def strategy_window_pool(
    session: TmuxSession, commands: list[Cmd]
) -> tuple[float, str]:
    """Window pool with stall-tolerant fallover.

    Runs commands in the main tmux window (window 0) using the fast hybrid
    approach. If a command times out (possible stall), it does NOT kill the
    window. Instead it:
    1. Captures whatever output is visible (the model will see it)
    2. Grabs a fresh window from the pool for the NEXT command
    3. The stalled window stays alive — the model can check/kill it later

    This gives hybrid speed on the happy path, with pool-based isolation
    only when something actually stalls.
    """
    t0 = time.monotonic()
    env = session.environment
    sess_name = session._session_name

    # Pre-create spare windows (only used if main stalls)
    pool = TmuxWindowPool(env, sess_name, size=3)
    await pool.start()

    # Start on the main window (index 0)
    current_target = f"{sess_name}:0"
    outputs = []

    for cmd in commands:
        marker = _next_marker()

        await env.exec(command=f"tmux send-keys -t {current_target} {_shlex_quote(cmd.keystrokes)}")
        await env.exec(command=f"tmux send-keys -t {current_target} {_shlex_quote(f'echo {marker}' + chr(10))}")

        deadline = time.monotonic() + max(cmd.duration, 2.0)
        found = False
        await asyncio.sleep(min(0.3, cmd.duration))
        while time.monotonic() < deadline:
            result = await env.exec(command=f"tmux capture-pane -p -S - -t {current_target}")
            pane = result.stdout or ""
            if marker in pane:
                found = True
                break
            await asyncio.sleep(0.5)

        # Capture output either way
        result = await env.exec(command=f"tmux capture-pane -p -S - -t {current_target}")
        pane_out = result.stdout or ""
        outputs.append(pane_out)

        if not found:
            # Stall: leave this window alive, switch to a pool window
            new_win = await pool.acquire()
            current_target = f"{sess_name}:{new_win}"

    combined = _strip_markers("\n".join(outputs))
    return time.monotonic() - t0, combined


def _shlex_quote(s: str) -> str:
    """Quote a string for tmux send-keys."""
    import shlex
    return shlex.quote(s)


STRATEGIES = {
    "sequential_sleep": strategy_sequential_sleep,
    "marker_sequential": strategy_marker_sequential,
    "pipelined":         strategy_pipelined,
    "hybrid":            strategy_hybrid,
    "hybrid_stall_aware": strategy_hybrid_stall_aware,
    "multi_window":      strategy_multi_window,
    "window_pool":       strategy_window_pool,
}


# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------

async def create_sandbox() -> ModalEnvironment:
    trial_dir = Path(tempfile.mkdtemp(prefix="bench-"))
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
        environment_dir=trial_dir,
        environment_name="benchmark",
        session_id=f"bench-{int(time.time())}",
        trial_paths=trial_paths,
        task_env_config=env_config,
        sandbox_timeout_secs=600,
    )

    print("Starting Modal sandbox...")
    t0 = time.time()
    await env.start(force_build=False)
    print(f"  Sandbox ready in {time.time() - t0:.1f}s")
    return env


async def create_session(env: ModalEnvironment) -> TmuxSession:
    session = TmuxSession(
        session_name="bench",
        environment=env,
        logging_path=PurePosixPath("/tmp/bench.pane"),
        local_asciinema_recording_path=None,
        remote_asciinema_recording_path=None,
        pane_width=160,
        pane_height=40,
    )
    print("Starting tmux session...")
    t0 = time.time()
    await session.start()
    print(f"  Tmux ready in {time.time() - t0:.1f}s")
    # Give shell a moment to initialize
    await asyncio.sleep(1.0)
    # Drain initial output
    await session.get_incremental_output()
    return session


def check_correctness(output: str, commands: list[Cmd]) -> tuple[bool, str]:
    """Verify expected substrings appear in output."""
    failures = []
    for cmd in commands:
        if cmd.expect_substr and cmd.expect_substr not in output:
            failures.append(f"  missing '{cmd.expect_substr}' from: {cmd.keystrokes.strip()}")
    if failures:
        return False, "\n".join(failures)
    return True, "all checks passed"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run_benchmarks(filter_cases: list[str] | None = None,
                         filter_strategies: list[str] | None = None):
    env = None
    try:
        env = await create_sandbox()

        results: list[BenchResult] = []
        cases = CASES
        if filter_cases:
            cases = [c for c in CASES if c.name in filter_cases]
        strats = STRATEGIES
        if filter_strategies:
            strats = {k: v for k, v in STRATEGIES.items() if k in filter_strategies}

        for case in cases:
            print(f"\n{'='*60}")
            print(f"Case: {case.name} — {case.description}")
            print(f"  {len(case.commands)} commands, "
                  f"total agent-duration={sum(c.duration for c in case.commands):.1f}s")
            print(f"{'='*60}")

            for strat_name, strat_fn in strats.items():
                # Fresh tmux session per strategy per case for isolation
                session = await create_session(env)
                try:
                    wall, output = await strat_fn(session, case.commands)
                    correct, detail = check_correctness(output, case.commands)
                    results.append(BenchResult(
                        case_name=case.name,
                        strategy=strat_name,
                        wall_sec=round(wall, 3),
                        correct=correct,
                        detail=detail,
                    ))
                    status = "PASS" if correct else "FAIL"
                    print(f"  {strat_name:25s}  {wall:6.2f}s  [{status}]"
                          + ("" if correct else f"  {detail}"))
                except Exception as e:
                    results.append(BenchResult(
                        case_name=case.name,
                        strategy=strat_name,
                        wall_sec=-1,
                        correct=False,
                        detail=f"ERROR: {e}",
                    ))
                    print(f"  {strat_name:25s}  ERROR: {e}")

        # --- Summary table ---
        print(f"\n{'='*80}")
        print("SUMMARY")
        print(f"{'='*80}")
        print(f"{'Case':<25s} {'Strategy':<25s} {'Wall(s)':>8s} {'OK?':>5s} {'Speedup':>8s}")
        print("-" * 80)

        # Group by case to compute speedup
        from collections import defaultdict
        by_case: dict[str, list[BenchResult]] = defaultdict(list)
        for r in results:
            by_case[r.case_name].append(r)

        for case_name, case_results in by_case.items():
            baseline = next((r for r in case_results if r.strategy == "sequential_sleep"), None)
            for r in case_results:
                speedup = ""
                if baseline and baseline.wall_sec > 0 and r.wall_sec > 0:
                    speedup = f"{baseline.wall_sec / r.wall_sec:.2f}x"
                ok = "PASS" if r.correct else "FAIL"
                print(f"{r.case_name:<25s} {r.strategy:<25s} {r.wall_sec:>8.3f} {ok:>5s} {speedup:>8s}")

        # Save JSON results
        out_path = Path(__file__).parent / "results.json"
        with open(out_path, "w") as f:
            json.dump(
                [{"case": r.case_name, "strategy": r.strategy,
                  "wall_sec": r.wall_sec, "correct": r.correct, "detail": r.detail}
                 for r in results],
                f, indent=2,
            )
        print(f"\nResults saved to {out_path}")

    finally:
        if env:
            print("\nTearing down sandbox...")
            await env.stop(delete=True)
            print("Done.")


if __name__ == "__main__":
    import sys
    filter_cases = None
    filter_strats = None
    for arg in sys.argv[1:]:
        if arg.startswith("--case="):
            filter_cases = arg.split("=", 1)[1].split(",")
        elif arg.startswith("--strategy="):
            filter_strats = arg.split("=", 1)[1].split(",")
    asyncio.run(run_benchmarks(filter_cases, filter_strats))
