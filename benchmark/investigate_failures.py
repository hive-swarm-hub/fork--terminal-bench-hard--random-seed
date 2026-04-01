"""
Dispatch agents to investigate all baseline eval task failures in parallel.
Each agent reads the trajectory, extracts command patterns and failure modes,
then a synthesizer agent combines findings into benchmark improvements.

Usage:
    python benchmark/investigate_failures.py
"""

import asyncio
import json
from pathlib import Path
from orchestrate import Agent

JOBS_DIR = Path("/home/tianhao/terminal-bench-hard/jobs/2026-03-31__19-50-00")
OUTPUT_DIR = Path("/home/tianhao/terminal-bench-hard/benchmark_research/task_analysis")

TASKS = [
    "adaptive-rejection-sampler__yge4HMd",
    "caffe-cifar-10__R4rX5vf",
    "db-wal-recovery__wWJcwhb",
    "dna-insert__uqU9Bf6",
    "filter-js-from-html__iyD2qbp",
    "gpt2-codegolf__LkmPQri",
    "install-windows-3.11__m6ZQQDg",  # PASSED — investigate why it worked
    "make-doom-for-mips__XojnVBs",
    "make-mips-interpreter__LizdkMB",
    "model-extraction-relu-logits__k93J9YZ",
    "mteb-leaderboard__h8VXxWu",
    "mteb-retrieve__Be2sUsS",
    "raman-fitting__RwzQy4H",
    "sam-cell-seg__w9ppdGd",
    "schemelike-metacircular-eval__jEELHHz",
    "train-fasttext__Cv64rJC",
    "video-processing__dmyX8n7",
]

# Already analyzed by earlier agents — skip these
ALREADY_ANALYZED = {
    "dna-insert__uqU9Bf6",
    "make-mips-interpreter__LizdkMB",
    "model-extraction-relu-logits__k93J9YZ",
    "query-optimize__f2r52UP",
    "extract-moves-from-video__v486Lop",
    "video-processing__dmyX8n7",
    "schemelike-metacircular-eval__jEELHHz",
    "configure-git-webserver__tPaj3iL",
}

INVESTIGATOR_PROMPT = """You are a senior engineer analyzing agent execution traces to find failure patterns.
You focus on extracting: what commands were run, what failed, what stalled, what was wasted time,
and what the agent should have done differently. Be precise and concise."""

SYNTHESIZER_PROMPT = """You are a benchmark engineer. You read failure analyses from agent traces
and extract patterns that should be tested in a command execution benchmark.
Focus on: stall patterns, timeout issues, parallel opportunities, wasted time patterns."""


async def investigate_task(task_dir: str) -> dict:
    """Dispatch an agent to investigate one task's trajectory."""
    task_name = task_dir.split("__")[0]
    task_path = JOBS_DIR / task_dir
    passed = "install-windows" in task_dir

    agent = Agent("investigator", prompt=INVESTIGATOR_PROMPT, model="sonnet")
    try:
        result = await agent.arun(
            f"""Analyze the agent trajectory for task '{task_name}' at {task_path}/

This task {'PASSED' if passed else 'FAILED'}. {'Investigate why it succeeded — what did the agent do right?' if passed else 'Investigate why it failed.'}

Read trajectory.json (or trial.log if no trajectory). Extract:

1. TASK: One-line description of what the task required
2. TOTAL_STEPS: How many episodes the agent used
3. TOTAL_TIME: Approximate wall time
4. COMMANDS: List every unique command pattern (not exact args), its typical duration, and category:
   - FAST (<1s): ls, cat, echo, cd, pwd
   - MEDIUM (1-10s): gcc, find, grep, python script
   - SLOW (10-60s): apt-get, make, wget, training
   - VERY_SLOW (>60s): compilation, model training
   - STALL: commands that hung/blocked (pager, interactive prompt, stuck process)
5. FAILURE_MODE: One of:
   - STALL: agent got stuck on a blocked command
   - TIMEOUT: ran out of time before completing
   - WRONG_APPROACH: tried the wrong strategy
   - MISSING_TOOL: needed a tool/package that wasn't available
   - API_BLOCK: external service blocked (e.g., YouTube bot detection)
   - CONTEXT_OVERFLOW: ran out of context window
   - BUG: agent made a coding/logic error
   - INFRA: infrastructure/environment issue
6. WASTED_TIME: Estimate seconds wasted on unproductive actions (retrying failed approaches, stuck in pagers, waiting for slow commands unnecessarily)
7. PARALLEL_OPPORTUNITIES: Commands that were run sequentially but could have been parallel
8. KEY_INSIGHT: The single most important thing to fix to make this task pass

Output as JSON with these exact keys.""",
            schema={
                "task": "str",
                "total_steps": "int",
                "total_time_sec": "int",
                "commands": "list",
                "failure_mode": "str",
                "wasted_time_sec": "int",
                "parallel_opportunities": "list",
                "key_insight": "str",
            },
        )

        finding = {
            "task_dir": task_dir,
            "task_name": task_name,
            "passed": passed,
            **{k: result[k] for k in result if k != "text"},
        }

        # Save individual analysis
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_file = OUTPUT_DIR / f"{task_name}.json"
        with open(out_file, "w") as f:
            json.dump(finding, f, indent=2)

        print(f"  {'PASS' if passed else 'FAIL'} {task_name}: {result.get('failure_mode', 'N/A')} — {result.get('key_insight', '')[:80]}")
        return finding

    except Exception as e:
        print(f"  ERROR {task_name}: {e}")
        return {"task_dir": task_dir, "task_name": task_name, "error": str(e)}
    finally:
        await agent.aclose()


async def synthesize(findings: list[dict]):
    """Synthesize all findings into benchmark recommendations."""
    agent = Agent("synthesizer", prompt=SYNTHESIZER_PROMPT, model="sonnet")
    try:
        # Build context summary
        summary_lines = []
        for f in findings:
            if "error" in f:
                summary_lines.append(f"- {f['task_name']}: ANALYSIS ERROR")
                continue
            summary_lines.append(
                f"- {f['task_name']}: mode={f.get('failure_mode','?')}, "
                f"wasted={f.get('wasted_time_sec',0)}s, "
                f"insight={f.get('key_insight','?')[:100]}"
            )

        summary = "\n".join(summary_lines)

        result = await agent.arun(
            f"""Here are failure analyses from 17 agent task runs (1 passed, 16 failed):

{summary}

Full findings are saved as JSON in {OUTPUT_DIR}/

Based on these patterns, write a report covering:

1. FAILURE MODE DISTRIBUTION: Count how many tasks hit each failure mode
2. TOP COMMAND STALL PATTERNS: What specific commands/situations cause stalls?
3. TOP TIME WASTERS: What activities waste the most agent time across tasks?
4. PARALLEL OPPORTUNITIES: Common patterns where sequential execution hurts
5. BENCHMARK TEST CASES: Propose 5-10 NEW benchmark test cases for the command
   executor that would catch these real failure patterns. Each should have:
   - name
   - description (what it tests)
   - commands (realistic sequence)
   - expected behavior (what a good executor should do)

Save the full report to {OUTPUT_DIR}/synthesis.md""",
        )

        print(f"\nSynthesis complete: {result.summary}")
        return result

    finally:
        await agent.aclose()


async def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Filter to tasks not already analyzed
    tasks_to_analyze = [t for t in TASKS if t not in ALREADY_ANALYZED]
    print(f"Investigating {len(tasks_to_analyze)} tasks in parallel...\n")

    # Phase 1: Fan out investigators (all parallel)
    findings = await asyncio.gather(
        *[investigate_task(t) for t in tasks_to_analyze],
        return_exceptions=True,
    )

    # Handle exceptions from gather
    clean_findings = []
    for i, f in enumerate(findings):
        if isinstance(f, Exception):
            name = tasks_to_analyze[i].split("__")[0]
            print(f"  EXCEPTION {name}: {f}")
            clean_findings.append({"task_name": name, "error": str(f)})
        else:
            clean_findings.append(f)

    # Save all findings
    with open(OUTPUT_DIR / "all_findings.json", "w") as f:
        json.dump(clean_findings, f, indent=2)
    print(f"\n{len(clean_findings)} task analyses saved to {OUTPUT_DIR}/all_findings.json")

    # Phase 2: Synthesize
    print("\nSynthesizing findings...")
    await synthesize(clean_findings)

    print(f"\nDone. Reports in {OUTPUT_DIR}/")


if __name__ == "__main__":
    asyncio.run(main())
