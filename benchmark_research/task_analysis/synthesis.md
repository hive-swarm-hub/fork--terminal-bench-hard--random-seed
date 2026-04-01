# Command Executor Benchmark — Failure Pattern Synthesis

**Date:** 2026-03-31
**Input:** 17 agent task runs (1 passed, 16 failed); 12 tasks returned ANALYSIS ERROR
**Data sources:** `logs_batch1.md`, `logs_batch2.md`, `logs_batch3.md`, `cmd_dependency_analysis.md`, `all_findings.json`

---

## 1. FAILURE MODE DISTRIBUTION

### Meta-failure: Analysis pipeline timeouts (12/12 ANALYSIS ERRORs)

Every task that the investigator tried to analyze returned `504 Gateway Timeout`
from `http://localhost:7777/agents/investigator/message`. The investigator agent
itself stalled — it was analyzing complex trajectories (likely multi-KB JSON)
via an LLM API call that exceeded the gateway timeout. This is the same
pager/stall pattern appearing at the **analysis layer**, not just the execution
layer: a long-running sub-process (LLM call) blocks indefinitely, and the caller
has no timeout or retry.

Affected tasks: adaptive-rejection-sampler, caffe-cifar-10, db-wal-recovery,
filter-js-from-html, gpt2-codegolf, install-windows-3.11, make-doom-for-mips,
mteb-leaderboard, mteb-retrieve, raman-fitting, sam-cell-seg, train-fasttext.

### Task-level failure modes (from analyzed trajectories)

| Failure Mode | Tasks Affected | Severity |
|---|---|---|
| **Interactive pager trap** (`less` opened by git/man) | fix-git WCvvvRc (total failure), fix-git zs879ar (partial) | CRITICAL |
| **Environment provisioning failure** (sandbox never started) | build-pmars, pytorch-model-recovery, gpt2-codegolf E7aYnRw | HIGH |
| **Duration overestimation** (30-60s for 0.5s ops) | dna-insert (~250s wasted), gpt2-codegolf (~59s wasted) | MEDIUM |
| **False parallelization of dependencies** (compile+run sent together) | gpt2-codegolf | LOW |
| **Context window inflation from pager output** | fix-git zs879ar, fix-git WCvvvRc | MEDIUM |
| **No duration adaptation across repeated cycles** | gpt2-codegolf (15+ compile-run cycles) | LOW |

**Summary counts (task runs with observable data):**
- Pager trap: **2/5** runs severely impacted (1 complete failure, 1 partial)
- Environment failures: **3/5** runs in one batch (no trajectory data)
- Duration overestimation: **2/5** runs with meaningful waste
- Dependency violations in parallel batches: **2/12** batches (from dependency analysis)

---

## 2. TOP COMMAND STALL PATTERNS

### Stall #1: Git pager trap (CRITICAL)

**Trigger commands:**
```
git log --oneline --all --graph
git reflog
git log   # (without -N limit or --no-pager)
```

**Mechanism:** When output exceeds terminal height (40 rows), git opens `less`.
The terminal shows the LESS help screen. Subsequent keystrokes are interpreted
as pager input, not shell commands. Escape sequences tried and their success:

| Escape sequence | Result |
|---|---|
| `q` | Fails — pager in help mode, `q` navigates help |
| `C-c` | Fails — `less` ignores SIGINT |
| `:q\n` (vim syntax) | Accidentally worked after 20x spam |
| `!killall less` (from less shell) | Fails — shell not accessible |
| `C-b :respawn-pane -k` (tmux) | Fails — created junk files, still stuck |
| `C-\` (SIGQUIT) | Fails |
| `GIT_PAGER=cat git reflog > /tmp/r.txt` | Works — correct fix discovered late |

**Quantified waste:**
- fix-git zs879ar: 68/99 commands (69%) wasted on escape attempts, ~40s
- fix-git WCvvvRc: 87/93 commands (94%) wasted, ~47s — run never completed

**Safe forms that prevent the stall:**
```
git --no-pager log --oneline --graph -10
git --no-pager reflog
GIT_PAGER=cat git reflog
git log --oneline -5          # -N flag keeps output short
```

### Stall #2: Interactive REPL / interactive program

Any command that starts an interactive program stalls the pager-marker approach:
- `python3` (no args) → Python REPL
- `man ls` → less pager
- `less <file>` directly
- `vim <file>` → vi editor
- `top` / `htop` → full-screen TUI

The marker `echo __BENCH__` gets queued but never executes because the shell
is suspended waiting for the interactive program.

### Stall #3: Long-running processes with no output

Commands like `apt-get install`, ML training, or large builds produce periodic
output but can go silent for 10-60s. The stall detector (checking for pane
content change) would fire false positives and send escape sequences into
an in-progress install, corrupting it.

### Stall #4: Empty keystroke "wait" commands

From dna-insert: steps with `keystrokes=""` and `duration=30-60s` are the
agent's way of saying "wait for the previous command." These degrade to
pure sleeps. A polling executor would recover 29-59s per occurrence.

---

## 3. TOP TIME WASTERS

| Time Waster | Observed Waste | Root Cause |
|---|---|---|
| Pager escape loops | 40-47s per run, entire step budgets | Missing `--no-pager` |
| Heredoc write overestimation | 29.5-59.5s per write × 4-6 occurrences | Agent assigns 30-60s to 0.5s ops |
| Python script overestimation | 4.5-29.5s per script × 6 occurrences | Agent assigns 5-30s to 0.5s ops |
| GPT-2 inference overestimation | 3.3s × 18 runs = ~59s | Agent assigns 5s to 1.7s ops |
| Repeated identical compile+run cycles | ~7.5s × 15 iterations | No caching, no duration learning |
| Empty wait commands | 29.5-59.5s per occurrence | Polling not used for async waits |
| Context window inflation | ~25K chars of useless `less` help | Pager output floods context |

**Total estimated recoverable time:**
- dna-insert: ~250s (~4 min) from overestimation alone
- gpt2-codegolf: ~59s from binary overestimation
- fix-git (stalled runs): ~87s from pager escape (or full run if escape fails)

---

## 4. PARALLEL OPPORTUNITIES

### Already parallelized correctly (75% of multi-command batches)

From dependency analysis of 12 multi-command batches:
- **9/12 batches (75%)** are fully parallel-safe — all read-only queries
- Typical parallel groups: `git status` + `git branch -a` + `git stash list` + `git reflog`
- Typical parallel groups: `cat <file>` + `oligotm <seq1>` + `oligotm <seq2>`
- Typical parallel groups: `ls -lh` + `file` + `head | od | head`

### Sequential batches that must stay sequential (16.7%)

- `git add <file>` → `git commit` (stage must precede commit)
- `rm <files>` → `ls` (delete must precede verify)
- `cat > file << 'EOF'` → `gcc file.c` → `./a.out` (write → compile → run)

### False parallelizations observed (dependency bugs)

Two problematic patterns found in gpt2-codegolf:
1. `gcc ... -o /tmp/a.out` sent **in parallel with** `/app/a.out <args>` — works
   only because a stale binary exists from the previous cycle. Would race-fail
   on a fresh environment.
2. `cat > file.c << 'EOF'` sent **in parallel with** `gcc file.c` — works
   only because the previous iteration's file still exists.

### Missed parallelization opportunities

- `wc -c /app/gpt2.c` chained with `&&` before `gcc` instead of run in parallel
- Independent Python analysis scripts run sequentially when they could be batched
- Tool capability checks (`which oligotm && oligotm --help`) run before actual
  computation instead of together

---

## 5. BENCHMARK TEST CASES

The following 8 new test cases are not yet covered by the existing benchmark
(`bench_cmd_exec.py`) and directly target the failure patterns above.

---

### TC-1: `git_pager_trap`

**Description:** Tests recovery from the #1 real-world failure mode. Runs
`git log --all --graph` without `--no-pager` in a repo with enough commits to
trigger `less`. A good executor must detect the stall and send escape sequences
before the deadline expires, then verify the shell is usable afterward.

**Commands (realistic agent sequence):**
```python
Cmd("git init /tmp/pgtest && cd /tmp/pgtest\n", 1.0),
# Create enough commits to overflow a 40-row terminal
Cmd("for i in $(seq 1 60); do git commit --allow-empty -m \"commit $i\"; done\n", 15.0),
# This WILL trigger less — the trap
Cmd("cd /tmp/pgtest && git log --oneline --all --graph\n", 5.0),
# If stall recovery works, this must succeed
Cmd("echo SHELL_ALIVE\n", 2.0, expect_substr="SHELL_ALIVE"),
Cmd("rm -rf /tmp/pgtest\n", 0.5),
```

**Expected behavior:** Executor detects pane-content stall after 1-2 polls,
sends `q` to exit `less`, re-injects the marker echo, and reports `SHELL_ALIVE`.
Failure = timeout on `SHELL_ALIVE` or missing `SHELL_ALIVE` in output.

---

### TC-2: `man_page_pager`

**Description:** `man ls` opens `less` via the man pager — a different trigger
than git, and commonly seen in exploration steps. Tests that stall recovery
handles non-git interactive pagers.

**Commands:**
```python
Cmd("man ls\n", 3.0),
# Must recover from man's less instance
Cmd("echo RECOVERED_FROM_MAN\n", 2.0, expect_substr="RECOVERED_FROM_MAN"),
```

**Expected behavior:** Executor detects stall, sends `q`, recovers.

---

### TC-3: `python_repl_trap`

**Description:** `python3` without arguments opens an interactive REPL.
The marker echo sent after it never executes. Tests REPL detection and recovery.

**Commands:**
```python
Cmd("python3\n", 2.0),
# Python REPL is now active — marker won't echo until we exit
Cmd("echo AFTER_PYTHON\n", 2.0, expect_substr="AFTER_PYTHON"),
```

**Expected behavior:** Executor detects stall, sends `C-d` or `exit()\n` to
close REPL, re-injects marker. `AFTER_PYTHON` must appear in output.

---

### TC-4: `iterative_compile_run_5x`

**Description:** Simulates the gpt2-codegolf pattern: 5 iterations of the
write-compile-run cycle with a fixed `duration=5.0s` (agent over-provision).
Tests whether the executor adapts or at minimum uses polling to recover time.
A polling executor should save ~3.3s × 5 = ~16.5s vs naive sleep.

**Commands (5 iterations, ~1.5s actual each):**
```python
for i in range(5):
    Cmd(f"printf '#include<stdio.h>\\nint main(){{printf(\"%d\\\\n\",{i});}}' > /tmp/c{i}.c\n", 5.0),
    Cmd(f"gcc -o /tmp/c{i} /tmp/c{i}.c\n", 5.0),
    Cmd(f"/tmp/c{i}\n", 5.0, expect_substr=str(i)),
Cmd("rm -f /tmp/c*.c /tmp/c[0-9]\n", 0.5),
```

**Expected behavior:** Total wall time < 30s (naive: 5×15s = 75s).
Each compile completes in ~1.5s; each run in <0.5s. Polling executor
should complete in ~15s. Test measures speedup factor.

---

### TC-5: `dependency_violation_compile_parallel`

**Description:** Targets the false parallelization bug seen in gpt2-codegolf:
sending a compile and its dependent binary run as if they're independent.
A correct executor must execute these sequentially (write → compile → run),
not in parallel — otherwise the run uses a stale or missing binary.

**Commands (sequential dependency chain that must NOT be parallelized):**
```python
Cmd("rm -f /tmp/deptest /tmp/deptest.c\n", 0.5),  # ensure no stale binary
Cmd("printf '#include<stdio.h>\\nint main(){printf(\"FRESH_BUILD\\\\n\");}' > /tmp/deptest.c\n", 0.5),
# compile and run sent as a batch — executor must preserve order
Cmd("gcc -o /tmp/deptest /tmp/deptest.c\n", 2.0),
Cmd("/tmp/deptest\n", 1.0, expect_substr="FRESH_BUILD"),
Cmd("rm -f /tmp/deptest /tmp/deptest.c\n", 0.5),
```

**Expected behavior:** `FRESH_BUILD` in output. If executor parallelizes
compile+run incorrectly and no stale binary exists, the run fails with
"No such file or directory" — correctness check catches this.

---

### TC-6: `empty_wait_command`

**Description:** Targets the dna-insert pattern of `keystrokes=""` with
`duration=30s`. Tests how the executor handles no-op wait commands
that real agents send to "idle" between async operations.

**Commands:**
```python
Cmd("sleep 1 && echo ASYNC_DONE > /tmp/async_marker.txt &\n", 0.5),
Cmd("", 30.0),  # empty keystroke "wait" — agent pattern
Cmd("cat /tmp/async_marker.txt\n", 0.5, expect_substr="ASYNC_DONE"),
Cmd("rm -f /tmp/async_marker.txt\n", 0.5),
```

**Expected behavior:** Executor does not crash on empty keystrokes. Polling
executor recovers the full 30s by detecting marker when async task completes.
Wall time should be ~2s, not 30s.

---

### TC-7: `partial_stall_in_batch`

**Description:** Tests a batch where the FIRST command stalls in a pager,
but subsequent commands are fast and independent. A window-isolation executor
should run remaining commands in a fresh window while recovering the stalled one.

**Commands:**
```python
# This stalls
Cmd("PAGER=less seq 1 10000 | less\n", 5.0),
# These are independent and should run regardless
Cmd("echo INDEPENDENT_1\n", 0.5, expect_substr="INDEPENDENT_1"),
Cmd("echo INDEPENDENT_2\n", 0.5, expect_substr="INDEPENDENT_2"),
```

**Expected behavior:** Both `INDEPENDENT_1` and `INDEPENDENT_2` appear in
output. Window-pool/hybrid-stall-aware strategies should achieve this;
simple sequential strategy will block on the first stall.

---

### TC-8: `stdout_flood_recovery`

**Description:** A command that produces unbounded output (e.g., a fast loop
or cat of a large file) can freeze the terminal buffer. Tests that the
executor detects the flood, recovers, and does not lose subsequent commands.

**Commands:**
```python
# Flood: produces ~50K lines quickly, may fill terminal buffer
Cmd("yes FLOOD | head -50000\n", 5.0),
# Must be reachable after the flood
Cmd("echo POST_FLOOD_OK\n", 2.0, expect_substr="POST_FLOOD_OK"),
```

**Expected behavior:** `POST_FLOOD_OK` appears after the flood command
completes. Stall-aware executor detects buffer freeze and recovers.
Naive executor may deadlock on full terminal buffer.

---

## Summary of Proposed Cases vs Existing Coverage

| New Case | Failure Mode Covered | Already in Benchmark? |
|---|---|---|
| `git_pager_trap` | Git pager, specific trigger + recovery | `pager_stall` covers generic less, not git-specific |
| `man_page_pager` | Man/less pager (non-git trigger) | No |
| `python_repl_trap` | Interactive REPL stall | No |
| `iterative_compile_run_5x` | Duration overestimation across cycles | `compile_run` covers 1 cycle; not 5x with adaptation |
| `dependency_violation_compile_parallel` | False parallelization correctness | `dependency_chain` covers env vars; not compile→run race |
| `empty_wait_command` | Empty keystroke / async wait pattern | No |
| `partial_stall_in_batch` | Mixed batch with one stall | No |
| `stdout_flood_recovery` | Unbounded output / buffer flood | `large_output` tests large output but not flood+recovery |

---

## Key Recommendations

1. **`--no-pager` is the highest-leverage fix.** It eliminates the #1 failure mode entirely at the agent level. The benchmark should verify that stall recovery works when agents don't use it.

2. **Polling recovers 60-99% of overestimated duration.** The existing `hybrid` strategy is already well-suited. The `heredoc_write` and `iterative_compile_run_5x` cases should demonstrate this most dramatically.

3. **Window isolation is the right architecture for stall recovery.** When a command stalls in `less`, killing or abandoning the window and continuing in a fresh one is the only reliable escape. `q`, `C-c`, and tmux tricks fail too often.

4. **Dependency ordering must be guaranteed.** At least 2/12 multi-command batches in real agent traces had dependency violations. An executor that naively parallelizes all commands in a batch will break ~17% of real agent steps.

5. **The analysis pipeline needs its own timeout.** The 504s on the investigator are the same stall pattern recursively. Any long-running sub-call (LLM API, trajectory analysis) needs a hard deadline and graceful failure, not indefinite blocking.
