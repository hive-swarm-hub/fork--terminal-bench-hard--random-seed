"""
Reproduce EXACT stall patterns from real agent failures in Modal sandboxes.

Each case replays the real command sequence that stalled the agent,
testing whether the executor can handle it without burning time.

Usage:
    python benchmark/bench_stalls.py
"""

import asyncio
import shlex
import tempfile
import time
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from harbor.environments.modal import ModalEnvironment
from harbor.models.task.config import EnvironmentConfig
from harbor.models.trial.paths import TrialPaths
from harbor.agents.terminus_2.tmux_session import TmuxSession


@dataclass
class Cmd:
    keystrokes: str
    duration: float = 1.0
    expect_substr: str | None = None


@dataclass
class StallCase:
    name: str
    description: str
    commands: list[Cmd]
    expected_wall_max: float  # max acceptable wall time for a good executor


# Real stall reproductions
CASES = [
    # --- query-optimize: sqlite3 hangs, C-c fails ---
    # The agent ran a slow SQL query, then waited 660s with empty commands.
    # A good executor should: detect the stall, let model know, and allow
    # subsequent commands to run without waiting.
    StallCase(
        name="stuck_sqlite3",
        description="Reproduce query-optimize: long-running process that ignores C-c",
        expected_wall_max=15.0,
        commands=[
            # Simulate sqlite3 that ignores SIGINT (trap INT)
            Cmd("bash -c 'trap \"\" INT TERM; sleep 300' &\n", 0.5),
            # Agent's real pattern: empty waits
            Cmd("", 30.0),
            Cmd("", 60.0),
            # Agent tries C-c (won't work on background process but shell is free)
            Cmd("echo SHELL_FREE\n", 1.0, "SHELL_FREE"),
            # Clean up
            Cmd("kill -9 %1 2>/dev/null; wait 2>/dev/null; echo DONE\n", 2.0, "DONE"),
        ],
    ),

    # --- train-fasttext: model training with 7x empty waits ---
    # The agent launched training, then sent 7 empty commands at 60s each = 420s waste.
    # A good executor should: poll for completion, recover time from empty waits.
    StallCase(
        name="training_empty_waits",
        description="Reproduce train-fasttext: long command + 7 empty 60s waits",
        expected_wall_max=20.0,
        commands=[
            # Simulate training that takes ~5s
            Cmd("bash -c 'for i in $(seq 1 5); do echo \"epoch $i/5\"; sleep 1; done; echo TRAINING_COMPLETE' &\n", 0.5),
            # Agent's real pattern: 7 empty waits at 60s each
            Cmd("", 60.0),
            Cmd("", 60.0),
            Cmd("", 60.0),
            Cmd("", 60.0),
            Cmd("", 60.0),
            Cmd("", 60.0),
            Cmd("", 60.0),
            # Check result
            Cmd("wait; echo ALL_DONE\n", 2.0, "ALL_DONE"),
        ],
    ),

    # --- db-wal-recovery: python script hangs, C-c fails 11 times ---
    StallCase(
        name="hung_python_no_sigint",
        description="Reproduce db-wal-recovery: python ignoring SIGINT, 11 C-c attempts fail",
        expected_wall_max=15.0,
        commands=[
            # Python script that ignores SIGINT (like the real failure)
            Cmd("python3 -c \"\nimport signal, time\nsignal.signal(signal.SIGINT, signal.SIG_IGN)\nwhile True: time.sleep(1)\n\" &\n", 0.5),
            # Empty waits (real pattern)
            Cmd("", 15.0),
            Cmd("", 20.0),
            # C-c attempts (won't kill the background python)
            Cmd("C-c", 2.0),
            Cmd("C-c", 2.0),
            Cmd("C-c", 1.0),
            # But shell should still be responsive
            Cmd("echo SHELL_OK\n", 1.0, "SHELL_OK"),
            # Kill properly
            Cmd("kill -9 $(pgrep -f 'signal.signal') 2>/dev/null; echo KILLED\n", 2.0, "KILLED"),
        ],
    ),

    # --- Real pattern: apt-get install blocks terminal ---
    # Agent sends apt-get, then can't do anything else for 30-60s
    StallCase(
        name="apt_blocks_terminal",
        description="apt-get install blocks terminal, agent wants to work on code in parallel",
        expected_wall_max=25.0,
        commands=[
            # Start apt install (takes ~15s)
            Cmd("apt-get update -qq 2>&1 | tail -1\n", 15.0),
            Cmd("apt-get install -y -qq sqlite3 2>&1 | tail -1\n", 30.0),
            # Agent immediately wants to write code (shouldn't wait for apt)
            Cmd("echo 'SELECT 1;' > /tmp/test.sql\n", 0.5),
            Cmd("sqlite3 :memory: < /tmp/test.sql\n", 1.0, "1"),
            Cmd("rm /tmp/test.sql\n", 0.1),
        ],
    ),

    # --- Normal fast case (control) ---
    StallCase(
        name="fast_control",
        description="Control: 5 fast commands, no stalls",
        expected_wall_max=5.0,
        commands=[
            Cmd("echo A\n", 0.1, "A"),
            Cmd("echo B\n", 0.1, "B"),
            Cmd("echo C\n", 0.1, "C"),
            Cmd("pwd\n", 0.1),
            Cmd("whoami\n", 0.1, "root"),
        ],
    ),
]

_marker_seq = 0
_MARKER_PREFIX = "__STALL_BENCH__"

def _next_marker():
    global _marker_seq
    _marker_seq += 1
    return f"{_MARKER_PREFIX}{_marker_seq}__"

def _strip_markers(text):
    return "\n".join(l for l in text.split("\n") if _MARKER_PREFIX not in l)


async def exec_baseline(session, commands):
    """Baseline: sequential sleep (Terminus2 parent class behavior)."""
    t0 = time.monotonic()
    for cmd in commands:
        if cmd.keystrokes:
            await session.send_keys(cmd.keystrokes, block=False, min_timeout_sec=0.0)
        await asyncio.sleep(cmd.duration)
    output = await session.get_incremental_output()
    return time.monotonic() - t0, output


async def exec_original(session, commands):
    """EXACT original agent code before fixes.

    This is the marker-sequential approach that was in agent.py before changes:
    - Send cmd + marker per command
    - Poll capture_pane(capture_entire=False) per command
    - Wait up to cmd.duration per command
    - No fast path, no pipelining, no empty-cmd handling
    """
    t0 = time.monotonic()
    seq = 0
    for cmd in commands:
        seq += 1
        marker = f"__ORIG__{seq}__"
        start = time.monotonic()

        if cmd.keystrokes:
            await session.send_keys(cmd.keystrokes, block=False, min_timeout_sec=0.0)
        # Always send marker (original code did this for every command)
        await session.send_keys(f"echo '{marker}'\n", block=False, min_timeout_sec=0.0)

        # Poll per-command with capture_entire=False (original used visible screen only)
        await asyncio.sleep(min(0.3, cmd.duration))
        while time.monotonic() - start < cmd.duration:
            pane = await session.capture_pane(capture_entire=False)
            if marker in pane:
                break
            await asyncio.sleep(0.5)

    # Filter markers
    output = await session.get_incremental_output()
    for i in range(1, seq + 1):
        output = output.replace(f"__ORIG__{i}__", "")
    return time.monotonic() - t0, output


async def exec_hybrid(session, commands):
    """Current hybrid from agent.py."""
    t0 = time.monotonic()
    total_dur = sum(c.duration for c in commands)
    max_dur = max((c.duration for c in commands), default=0)

    if max_dur <= 0.5:
        for cmd in commands:
            if cmd.keystrokes:
                await session.send_keys(cmd.keystrokes, block=False, min_timeout_sec=0.0)
        await asyncio.sleep(max(total_dur, 0.5))
        return time.monotonic() - t0, await session.get_incremental_output()

    markers = []
    for cmd in commands:
        marker = _next_marker()
        markers.append(marker)
        if cmd.keystrokes:
            await session.send_keys(cmd.keystrokes, block=False, min_timeout_sec=0.0)
        await session.send_keys(f"echo '{marker}'\n", block=False, min_timeout_sec=0.0)

    hard_timeout = min(max(total_dur, 10.0), 120.0)
    await asyncio.sleep(0.3)
    deadline = time.monotonic() + hard_timeout
    while time.monotonic() < deadline:
        pane = await session.capture_pane(capture_entire=True)
        if markers[-1] in pane:
            break
        await asyncio.sleep(0.5)

    return time.monotonic() - t0, _strip_markers(await session.get_incremental_output())


async def exec_smart(session, commands):
    """Smart executor: skip empty commands, poll for markers, early exit.

    Key improvements over hybrid:
    1. Empty keystrokes (duration>0) → just poll for any prior marker, skip the sleep
    2. Per-command early exit when marker found
    3. Pager prevention already set in session
    """
    t0 = time.monotonic()

    # Filter out pure empty-wait commands — they're just "sleep" requests
    # Instead of sleeping, we'll just continue and let marker polling handle timing
    real_commands = []
    total_empty_wait = 0.0
    for cmd in commands:
        if not cmd.keystrokes.strip():
            total_empty_wait += cmd.duration
        else:
            real_commands.append(cmd)

    if not real_commands:
        # All empty — just sleep a small amount and check
        await asyncio.sleep(min(total_empty_wait, 2.0))
        return time.monotonic() - t0, await session.get_incremental_output()

    total_dur = sum(c.duration for c in real_commands)
    max_dur = max(c.duration for c in real_commands)

    # Fast path
    if max_dur <= 0.5:
        for cmd in real_commands:
            await session.send_keys(cmd.keystrokes, block=False, min_timeout_sec=0.0)
        await asyncio.sleep(max(total_dur, 0.5))
        return time.monotonic() - t0, await session.get_incremental_output()

    # Pipelined markers (only for real commands)
    markers = []
    for cmd in real_commands:
        marker = _next_marker()
        markers.append(marker)
        await session.send_keys(cmd.keystrokes, block=False, min_timeout_sec=0.0)
        await session.send_keys(f"echo '{marker}'\n", block=False, min_timeout_sec=0.0)

    # Include empty wait time in timeout but cap it
    hard_timeout = min(max(total_dur + min(total_empty_wait, 5.0), 10.0), 120.0)
    await asyncio.sleep(0.3)
    deadline = time.monotonic() + hard_timeout
    while time.monotonic() < deadline:
        pane = await session.capture_pane(capture_entire=True)
        if markers[-1] in pane:
            break
        await asyncio.sleep(0.5)

    return time.monotonic() - t0, _strip_markers(await session.get_incremental_output())


STRATEGIES = {
    "original": exec_original,
    "hybrid": exec_hybrid,
    "smart": exec_smart,
}


async def create_sandbox():
    trial_dir = Path(tempfile.mkdtemp(prefix="stall-"))
    trial_paths = TrialPaths(trial_dir=trial_dir)
    trial_paths.mkdir()
    env = ModalEnvironment(
        environment_dir=trial_dir, environment_name="stall-bench",
        session_id=f"stall-{int(time.time())}", trial_paths=trial_paths,
        task_env_config=EnvironmentConfig(
            docker_image="ubuntu:22.04", cpus=1, memory_mb=2048,
            storage_mb=10240, gpus=0, allow_internet=True,
        ),
        sandbox_timeout_secs=600,
    )
    print("Starting sandbox...")
    t0 = time.time()
    await env.start(force_build=False)
    print(f"  Ready in {time.time()-t0:.1f}s")
    return env


async def create_session(env):
    s = TmuxSession(
        session_name="stall", environment=env,
        logging_path=PurePosixPath("/tmp/stall.pane"),
        local_asciinema_recording_path=None, remote_asciinema_recording_path=None,
        pane_width=160, pane_height=40,
    )
    await s.start()
    # Prevention
    await s.send_keys("export PAGER=cat GIT_PAGER=cat MANPAGER=cat\n", block=False, min_timeout_sec=0.3)
    await asyncio.sleep(0.5)
    await s.get_incremental_output()
    return s


def check(output, commands):
    fails = []
    for c in commands:
        if c.expect_substr and c.expect_substr not in output:
            fails.append(f"missing '{c.expect_substr}'")
    return not fails, fails


async def main():
    env = None
    try:
        env = await create_sandbox()
        results = []

        for case in CASES:
            agent_time = sum(c.duration for c in case.commands)
            empty_time = sum(c.duration for c in case.commands if not c.keystrokes.strip())
            print(f"\n{'='*70}")
            print(f"  {case.name} — {case.description}")
            print(f"  {len(case.commands)} cmds, agent-duration={agent_time:.0f}s "
                  f"(empty waits: {empty_time:.0f}s), target: <{case.expected_wall_max:.0f}s")
            print(f"{'='*70}")

            for sname, sfn in STRATEGIES.items():
                # Skip original on cases with >60s of empty waits (would timeout sandbox)
                if sname == "original" and empty_time > 60:
                    print(f"  {sname:<12s}    SKIP (would sleep {empty_time:.0f}s of empty waits)")
                    results.append({
                        "case": case.name, "strategy": sname,
                        "wall": agent_time, "correct": False,
                        "within_target": False, "target": case.expected_wall_max,
                        "agent_duration": agent_time, "empty_wait": empty_time,
                    })
                    continue
                session = await create_session(env)
                try:
                    wall, output = await sfn(session, case.commands)
                    ok, fails = check(output, case.commands)
                    within = wall <= case.expected_wall_max
                    status = "PASS" if ok else "FAIL"
                    time_ok = "OK" if within else "SLOW"
                    print(f"  {sname:<12s} {wall:7.1f}s [{status}] [{time_ok}]" +
                          (f" {'; '.join(fails)}" if fails else ""))
                    results.append({
                        "case": case.name, "strategy": sname,
                        "wall": round(wall, 1), "correct": ok,
                        "within_target": within, "target": case.expected_wall_max,
                        "agent_duration": agent_time, "empty_wait": empty_time,
                    })
                except Exception as e:
                    print(f"  {sname:<12s} ERROR: {e}")

        # Summary
        print(f"\n{'='*80}")
        print(f"{'Case':<25s} {'Strat':<12s} {'Wall':>6s} {'Target':>7s} {'OK':>5s} {'Time':>5s} {'Saved':>7s}")
        print("-"*80)
        for r in results:
            ok = "PASS" if r["correct"] else "FAIL"
            time_ok = "OK" if r["within_target"] else "SLOW"
            saved = r["agent_duration"] - r["wall"]
            print(f"{r['case']:<25s} {r['strategy']:<12s} {r['wall']:>5.1f}s {r['target']:>6.0f}s "
                  f"{ok:>5s} {time_ok:>5s} {saved:>+6.0f}s")

        Path(__file__).parent.joinpath("stall_results.json").write_text(
            json.dumps(results, indent=2))

    finally:
        if env:
            print("\nTearing down...")
            await env.stop(delete=True)


if __name__ == "__main__":
    asyncio.run(main())
