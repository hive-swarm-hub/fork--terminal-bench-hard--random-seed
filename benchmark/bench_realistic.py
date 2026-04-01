"""
Realistic command execution benchmark based on actual agent failure patterns.

Tests an improved executor that:
1. Prevents pagers by setting PAGER=cat at session start
2. Detects stalls and fails over to pool windows
3. Keeps stalled windows alive (model decides to kill)
4. Reports stall info in output so model knows what happened

Usage:
    python benchmark/bench_realistic.py
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


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Cmd:
    keystrokes: str
    duration: float = 1.0
    expect_substr: str | None = None


@dataclass
class BenchCase:
    name: str
    commands: list[Cmd]
    description: str = ""


# ---------------------------------------------------------------------------
# Realistic test cases from actual agent failures
# ---------------------------------------------------------------------------

CASES: list[BenchCase] = [
    # === NORMAL CASES (should be fast and correct) ===

    BenchCase(
        name="explore_workspace",
        description="Agent's first action: explore /app (5 fast reads)",
        commands=[
            Cmd("ls -la /app/ 2>/dev/null || echo 'empty'\n", 0.5),
            Cmd("cat /etc/os-release | head -5\n", 0.5),
            Cmd("python3 --version 2>&1\n", 0.5),
            Cmd("which gcc g++ make 2>/dev/null || echo 'no build tools'\n", 0.5),
            Cmd("df -h / | tail -1\n", 0.5),
        ],
    ),

    BenchCase(
        name="write_compile_run",
        description="gpt2-codegolf pattern: heredoc write + compile + run",
        commands=[
            Cmd("cat << 'EOF' > /tmp/hello.c\n#include <stdio.h>\nint main() { printf(\"RESULT_42\\n\"); return 0; }\nEOF\n", 5.0),
            Cmd("gcc -O2 -o /tmp/hello /tmp/hello.c 2>&1\n", 2.0),
            Cmd("/tmp/hello\n", 1.0, "RESULT_42"),
            Cmd("rm -f /tmp/hello /tmp/hello.c\n", 0.1),
        ],
    ),

    BenchCase(
        name="apt_install_and_use",
        description="Install package then use it (real agent pattern)",
        commands=[
            Cmd("apt-get update -qq 2>&1 | tail -1\n", 15.0),
            Cmd("apt-get install -y -qq jq 2>&1 | tail -1\n", 10.0),
            Cmd("echo '{\"key\":\"value\"}' | jq -r .key\n", 0.5, "value"),
        ],
    ),

    BenchCase(
        name="python_script_heredoc",
        description="dna-insert pattern: write python script via heredoc, agent overestimates at 30s",
        commands=[
            Cmd("cat << 'PYEOF' > /tmp/analyze.py\nimport sys, os\nprint('analysis_start')\nfor i in range(5):\n    print(f'step_{i}')\nprint('analysis_done')\nPYEOF\n", 30.0),
            Cmd("python3 /tmp/analyze.py\n", 5.0, "analysis_done"),
            Cmd("rm /tmp/analyze.py\n", 0.1),
        ],
    ),

    # === STALL CASES (executor must recover) ===

    BenchCase(
        name="git_pager_real",
        description="Real git pager trap: git log in a repo with 60 commits (exact fix-git failure)",
        commands=[
            Cmd("apt-get install -y -qq git 2>&1 | tail -1\n", 10.0),
            Cmd("git init /tmp/pagertest && cd /tmp/pagertest && for i in $(seq 1 60); do git commit --allow-empty -m \"c$i\" 2>/dev/null; done && echo REPO_READY\n", 15.0, "REPO_READY"),
            # WITHOUT --no-pager: this opens less
            Cmd("cd /tmp/pagertest && git log --oneline --all --graph\n", 5.0),
            # Must still work after the stall
            Cmd("echo POST_GIT_OK\n", 2.0, "POST_GIT_OK"),
            Cmd("rm -rf /tmp/pagertest\n", 0.5),
        ],
    ),

    BenchCase(
        name="stuck_process",
        description="query-optimize pattern: long-running process that can't be C-c'd",
        commands=[
            # Simulate a stuck process (trap SIGINT so C-c doesn't work)
            Cmd("bash -c 'trap \"\" INT; sleep 30' &\n", 0.5),
            # Agent needs to continue working despite background stuck process
            Cmd("echo STILL_WORKING\n", 1.0, "STILL_WORKING"),
            Cmd("kill %1 2>/dev/null; wait 2>/dev/null; echo CLEANED\n", 2.0),
        ],
    ),

    BenchCase(
        name="python_repl",
        description="Accidentally opening python3 REPL (interactive program blocks shell)",
        commands=[
            Cmd("python3\n", 3.0),
            # Shell is blocked by REPL - next command must still work
            Cmd("echo AFTER_REPL\n", 2.0, "AFTER_REPL"),
        ],
    ),

    BenchCase(
        name="stdout_flood",
        description="Command producing massive output that floods terminal buffer",
        commands=[
            Cmd("seq 1 100000\n", 5.0),
            Cmd("echo FLOOD_SURVIVED\n", 2.0, "FLOOD_SURVIVED"),
        ],
    ),

    BenchCase(
        name="empty_wait_pattern",
        description="Agent sends empty keystrokes with 30s duration as async wait",
        commands=[
            Cmd("(sleep 2 && echo BACKGROUND_DONE > /tmp/bg_result.txt) &\n", 0.5),
            Cmd("", 30.0),
            Cmd("cat /tmp/bg_result.txt 2>/dev/null\n", 0.5, "BACKGROUND_DONE"),
            Cmd("rm -f /tmp/bg_result.txt\n", 0.1),
        ],
    ),
]


# ---------------------------------------------------------------------------
# Executor strategies
# ---------------------------------------------------------------------------

_marker_seq = 0
_MARKER_PREFIX = "__BENCH__"


def _next_marker() -> str:
    global _marker_seq
    _marker_seq += 1
    return f"{_MARKER_PREFIX}{_marker_seq}__"


def _strip_markers(text: str) -> str:
    return "\n".join(l for l in text.split("\n") if _MARKER_PREFIX not in l)


class WindowPool:
    """Pre-allocated tmux windows for stall failover."""

    def __init__(self, env, sess_name: str, size: int = 3):
        self._env = env
        self._sess = sess_name
        self._size = size
        self._ready: list[str] = []
        self._seq = 0

    async def start(self):
        for _ in range(self._size):
            name = await self._create()
            self._ready.append(name)

    async def _create(self) -> str:
        self._seq += 1
        name = f"w{self._seq}"
        await self._env.exec(command=f"tmux new-window -t {self._sess} -n {name} -d")
        # Set PAGER=cat in the new window too
        await self._env.exec(
            command=f"tmux send-keys -t {self._sess}:{name} 'export PAGER=cat GIT_PAGER=cat MANPAGER=cat' Enter"
        )
        await asyncio.sleep(0.2)
        return name

    async def acquire(self) -> str:
        if self._ready:
            return self._ready.pop(0)
        return await self._create()

    async def release(self, name: str):
        self._ready.append(name)


async def exec_baseline(session: TmuxSession, commands: list[Cmd]) -> tuple[float, str]:
    """Baseline: sequential sleep (what Terminus2 parent does)."""
    t0 = time.monotonic()
    for cmd in commands:
        if cmd.keystrokes:
            await session.send_keys(cmd.keystrokes, block=False, min_timeout_sec=0.0)
        await asyncio.sleep(cmd.duration)
    output = await session.get_incremental_output()
    return time.monotonic() - t0, output


async def exec_hybrid(session: TmuxSession, commands: list[Cmd]) -> tuple[float, str]:
    """Current agent hybrid: fast-path sleep or pipelined markers."""
    t0 = time.monotonic()
    total_dur = sum(c.duration for c in commands)
    max_dur = max((c.duration for c in commands), default=0)

    if max_dur <= 0.5:
        for cmd in commands:
            if cmd.keystrokes:
                await session.send_keys(cmd.keystrokes, block=False, min_timeout_sec=0.0)
        await asyncio.sleep(max(total_dur, 0.5))
        output = await session.get_incremental_output()
        return time.monotonic() - t0, output

    markers = []
    for cmd in commands:
        marker = _next_marker()
        markers.append(marker)
        if cmd.keystrokes:
            await session.send_keys(cmd.keystrokes, block=False, min_timeout_sec=0.0)
        await session.send_keys(f"echo '{marker}'\n", block=False, min_timeout_sec=0.0)

    hard_timeout = min(max(total_dur, 10.0), 120.0)
    await asyncio.sleep(min(0.3, total_dur))
    deadline = time.monotonic() + hard_timeout
    while time.monotonic() < deadline:
        pane = await session.capture_pane(capture_entire=True)
        if markers[-1] in pane:
            break
        await asyncio.sleep(0.5)

    output = _strip_markers(await session.get_incremental_output())
    return time.monotonic() - t0, output


async def exec_resilient(session: TmuxSession, commands: list[Cmd]) -> tuple[float, str]:
    """Resilient executor: hybrid + pager prevention + stall failover to pool windows.

    Design:
    1. PAGER=cat set at session start (prevention)
    2. Run commands in main window using hybrid approach
    3. Per-command stall detection: if marker not found after cmd.duration + 3s,
       capture current output, switch to a pool window, continue
    4. Stalled window stays alive, stall info included in output
    """
    t0 = time.monotonic()
    env = session.environment
    sess_name = session._session_name

    pool = WindowPool(env, sess_name, size=2)
    await pool.start()

    current_target = f"{sess_name}:0"
    outputs = []
    stall_count = 0

    for i, cmd in enumerate(commands):
        marker = _next_marker()

        # Send command + marker to current window
        if cmd.keystrokes:
            await env.exec(command=f"tmux send-keys -t {current_target} {shlex.quote(cmd.keystrokes)}")
        await env.exec(command=f"tmux send-keys -t {current_target} {shlex.quote(f'echo {marker}' + chr(10))}")

        # Poll for marker with per-command timeout
        per_cmd_timeout = max(cmd.duration + 3.0, 5.0)
        poll_start = time.monotonic()
        await asyncio.sleep(min(0.3, cmd.duration))

        found = False
        prev_pane = ""
        unchanged_polls = 0

        while time.monotonic() - poll_start < per_cmd_timeout:
            result = await env.exec(command=f"tmux capture-pane -p -S - -t {current_target}")
            pane = result.stdout or ""

            if marker in pane:
                found = True
                break

            # Stall detection: if pane unchanged for 3 polls, likely stuck
            if pane == prev_pane:
                unchanged_polls += 1
            else:
                unchanged_polls = 0
            prev_pane = pane

            # Early stall detection: 3 unchanged polls = ~1.5s of no change
            if unchanged_polls >= 3 and time.monotonic() - poll_start > 2.0:
                break

            await asyncio.sleep(0.5)

        # Capture output from current window
        result = await env.exec(command=f"tmux capture-pane -p -S - -t {current_target}")
        pane_out = result.stdout or ""
        outputs.append(pane_out)

        if not found:
            stall_count += 1
            # Stall detected — switch to a pool window, leave old one alive
            stall_info = (
                f"\n[EXECUTOR: Command {i} appears stalled in window "
                f"{current_target.split(':')[1]}. Switching to fresh window. "
                f"Stalled command: {cmd.keystrokes.strip()[:60]}]\n"
            )
            outputs.append(stall_info)

            new_win = await pool.acquire()
            current_target = f"{sess_name}:{new_win}"

    combined = _strip_markers("\n".join(outputs))
    elapsed = time.monotonic() - t0
    return elapsed, combined


STRATEGIES = {
    "baseline":   exec_baseline,
    "hybrid":     exec_hybrid,
    "resilient":  exec_resilient,
}


# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------

async def create_sandbox() -> ModalEnvironment:
    trial_dir = Path(tempfile.mkdtemp(prefix="bench-"))
    trial_paths = TrialPaths(trial_dir=trial_dir)
    trial_paths.mkdir()
    env_config = EnvironmentConfig(
        docker_image="ubuntu:22.04", cpus=1, memory_mb=2048,
        storage_mb=10240, gpus=0, allow_internet=True,
    )
    env = ModalEnvironment(
        environment_dir=trial_dir, environment_name="benchmark",
        session_id=f"bench-{int(time.time())}", trial_paths=trial_paths,
        task_env_config=env_config, sandbox_timeout_secs=600,
    )
    print("Starting Modal sandbox...")
    t0 = time.time()
    await env.start(force_build=False)
    print(f"  Sandbox ready in {time.time() - t0:.1f}s")
    return env


async def create_session(env: ModalEnvironment, set_pager_cat: bool = False) -> TmuxSession:
    session = TmuxSession(
        session_name="bench", environment=env,
        logging_path=PurePosixPath("/tmp/bench.pane"),
        local_asciinema_recording_path=None,
        remote_asciinema_recording_path=None,
        pane_width=160, pane_height=40,
    )
    t0 = time.time()
    await session.start()

    if set_pager_cat:
        # Prevention: disable all pagers
        await session.send_keys(
            "export PAGER=cat GIT_PAGER=cat MANPAGER=cat LESS='-F -X'\n",
            block=False, min_timeout_sec=0.3,
        )

    await asyncio.sleep(0.5)
    await session.get_incremental_output()  # drain
    return session


def check_correctness(output: str, commands: list[Cmd]) -> tuple[bool, list[str]]:
    failures = []
    for cmd in commands:
        if cmd.expect_substr and cmd.expect_substr not in output:
            failures.append(f"missing '{cmd.expect_substr}' from: {cmd.keystrokes.strip()[:50]}")
    return len(failures) == 0, failures


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main(filter_cases=None, filter_strats=None):
    env = None
    try:
        env = await create_sandbox()
        results = []

        cases = CASES if not filter_cases else [c for c in CASES if c.name in filter_cases]
        strats = STRATEGIES if not filter_strats else {k: v for k, v in STRATEGIES.items() if k in filter_strats}

        for case in cases:
            total_dur = sum(c.duration for c in case.commands)
            print(f"\n{'='*70}")
            print(f"  {case.name} — {case.description}")
            print(f"  {len(case.commands)} cmds, agent-duration={total_dur:.1f}s")
            print(f"{'='*70}")

            for sname, sfn in strats.items():
                # resilient strategy gets PAGER=cat prevention
                use_pager_cat = (sname == "resilient")
                session = await create_session(env, set_pager_cat=use_pager_cat)

                try:
                    wall, output = await sfn(session, case.commands)
                    ok, fails = check_correctness(output, case.commands)
                    status = "PASS" if ok else "FAIL"
                    detail = "; ".join(fails) if fails else ""
                    print(f"  {sname:<15s} {wall:7.2f}s [{status}]" +
                          (f"  {detail}" if detail else ""))
                    results.append({
                        "case": case.name, "strategy": sname,
                        "wall_sec": round(wall, 3), "correct": ok, "detail": detail,
                    })
                except Exception as e:
                    print(f"  {sname:<15s} ERROR: {e}")
                    results.append({
                        "case": case.name, "strategy": sname,
                        "wall_sec": -1, "correct": False, "detail": str(e),
                    })

        # Summary
        print(f"\n{'='*80}")
        print(f"{'Case':<25s} {'Strategy':<15s} {'Wall':>7s} {'OK':>5s}")
        print("-" * 80)
        for r in results:
            ok = "PASS" if r["correct"] else "FAIL"
            w = f"{r['wall_sec']:.1f}s" if r["wall_sec"] > 0 else "ERR"
            print(f"{r['case']:<25s} {r['strategy']:<15s} {w:>7s} {ok:>5s}")

        out_path = Path(__file__).parent / "realistic_results.json"
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nSaved to {out_path}")

    finally:
        if env:
            print("\nTearing down...")
            await env.stop(delete=True)


if __name__ == "__main__":
    import sys
    fc = fs = None
    for a in sys.argv[1:]:
        if a.startswith("--case="): fc = a.split("=",1)[1].split(",")
        if a.startswith("--strategy="): fs = a.split("=",1)[1].split(",")
    asyncio.run(main(fc, fs))
