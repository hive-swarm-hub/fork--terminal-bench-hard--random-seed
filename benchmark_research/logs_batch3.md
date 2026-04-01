# Trial Log Analysis - Batch 3

Analysis of 5 terminal agent trial runs from 2026-03-31. Data extracted from
trajectory.json files and trial.log pipeline/polling timing lines.

## Trials Analyzed

| Trial | Task | Model | Steps | Total Cost | Outcome |
|-------|------|-------|-------|------------|---------|
| dna-insert (nX5scS3) | Design Q5 mutagenesis primers | claude-opus-4-6 | 22 | $0.96 | Completed (mark_task_complete x2) |
| fix-git-FXy (FXy2g8X) | Merge lost git changes | claude-opus-4-6 | 16 | $0.26 | Completed cleanly |
| fix-git-zs8 (zs879ar) | Merge lost git changes | claude-opus-4-6 | 32 | $0.72 | Completed (after pager struggle) |
| fix-git-WCv (WCvvvRc) | Merge lost git changes | claude-opus-4-6 | 20 | $0.39 | Stuck in pager; never completed task |
| gpt2-codegolf (WN2a8Nw) | Minimize GPT-2 C implementation | claude-haiku-4-5 | 72 | $0.68 | Completed (iterative code golf) |

---

## Command Table: All Unique Commands Observed

### File Inspection Commands (fast)

| Command Pattern | Requested Duration | Actual Duration | Category |
|----------------|-------------------|-----------------|----------|
| `cat <file>` | 0.5-1s | ~0.5s | fast |
| `ls -la <dir>` | 0.5-1s | ~0.5s | fast |
| `ls -lh <dir>` | 0.5s | ~0.5s | fast |
| `wc -c <file>` | 0.5s | ~0.5s | fast |
| `head -c N <file> \| od -c \| head -N` | 0.5s | ~0.5s | fast |
| `tail -N <file>` | 0.5s | ~0.5s | fast |
| `file <path>` | 0.5s | ~0.5s | fast |
| `xxd <file> \| tail -N` | 0.5s | ~0.5s | fast |
| `diff <(cat A) <(git show B:A)` | 0.5s | ~0.5s | fast |

### Git Commands (fast)

| Command Pattern | Requested Duration | Actual Duration | Category |
|----------------|-------------------|-----------------|----------|
| `git status` | 0.5-1s | ~0.5s | fast |
| `git branch -a` | 1s | ~0.5s | fast |
| `git log --oneline -N` | 0.5-1s | ~0.5s | fast |
| `git log --oneline --graph -N` | 0.5-1s | ~0.5s | fast |
| `git reflog` | 1s | ~0.5s | fast (but triggered pager!) |
| `git stash list` | 1s | ~0.5s | fast |
| `git diff <ref1> <ref2> --stat` | 0.5-1s | ~0.5s | fast |
| `git diff <ref1> <ref2> -- <file>` | 0.5-1s | ~0.5s | fast |
| `git show <ref>:<file>` | 1s | ~0.5s | fast |
| `git --no-pager log ...` | 1s | ~0.5s | fast (pager-safe) |
| `git --no-pager reflog` | 1s | ~0.5s | fast (pager-safe) |
| `git --no-pager fsck --dangling` | 2s | ~1s | fast-medium |
| `git merge <ref> --no-edit` | 2s | ~1s | fast |
| `git add <file>` | 0.5-1s | ~0.5s | fast |
| `git commit -m "..."` | 1s | ~0.5s | fast |
| `git checkout --theirs <file>` | 1s | ~0.5s | fast |
| `GIT_PAGER=cat git reflog ...` | 2s | unknown | fast (pager-safe) |

### Python Script Execution (medium)

| Command Pattern | Requested Duration | Actual Duration | Category |
|----------------|-------------------|-----------------|----------|
| `python3 -c "short script"` | 1s | ~0.5s | fast |
| `python3 << 'EOF' ... EOF` (simple) | 1-2s | ~0.5s | fast |
| `python3 << 'EOF' ... EOF` (with subprocess) | 5-30s | ~0.5s | fast (grossly overestimated) |
| `python3 -c "from transformers ..."` | 3s | ~1.8s | medium |

### Compilation (medium)

| Command Pattern | Requested Duration | Actual Duration | Category |
|----------------|-------------------|-----------------|----------|
| `gcc -O3 <file> -lm -o <out>` | 2s | ~1.7-1.8s | medium |
| `wc -c && gcc ... \| grep error` | 2s | ~1.7-1.8s | medium |

### Binary Execution (medium)

| Command Pattern | Requested Duration | Actual Duration | Category |
|----------------|-------------------|-----------------|----------|
| `/app/a.out <ckpt> <vocab> "prompt"` | 5s | ~1.7s | medium (overestimated) |

### Package Installation (slow)

| Command Pattern | Requested Duration | Actual Duration | Category |
|----------------|-------------------|-----------------|----------|
| `apt-get update && apt-get install -y <pkg>` | 30s | unknown (no polling data) | slow |

### File Writing (fast)

| Command Pattern | Requested Duration | Actual Duration | Category |
|----------------|-------------------|-----------------|----------|
| `cat > <file> << 'EOF' ... EOF` | 0.5-60s | ~0.5s | fast (wildly overestimated) |
| `printf '...' > <file>` | 0.5s | ~0.5s | fast |

### Tool Invocation (fast)

| Command Pattern | Requested Duration | Actual Duration | Category |
|----------------|-------------------|-----------------|----------|
| `oligotm <flags> <sequence>` | 1s | ~0.5s | fast |
| `which <tool> && <tool> --help` | 2s | ~0.5s | fast |

### Interactive/Escape Keystrokes (interactive)

| Command Pattern | Requested Duration | Actual Duration | Category |
|----------------|-------------------|-----------------|----------|
| `q` (bare, to exit pager) | 0.3-1s | N/A | interactive |
| `q\n` | 0.5-1s | N/A | interactive |
| `:q\n` | 1s | N/A | interactive |
| `C-c` | 0.3-2s | N/A | interactive |
| `C-\\` | 1s | N/A | interactive |
| `C-b` (tmux prefix) | 0.3s | N/A | interactive |
| `\n` (Enter) | 0.3-0.5s | N/A | interactive |
| `\r` (Return) | 0.3-0.5s | N/A | interactive |
| `G` (less: go to end) | 0.5s | N/A | interactive |
| `ZZ` (vi: save-quit) | 1s | N/A | interactive |

### Process Management (medium)

| Command Pattern | Requested Duration | Actual Duration | Category |
|----------------|-------------------|-----------------|----------|
| `killall less 2>/dev/null; reset` | 2s | unknown | medium |
| `!killall -9 less` (from less shell) | 2s | ineffective | medium |
| `!kill -9 $$` (from less shell) | 2s | ineffective | medium |
| `kill -9 $(pgrep less)` | 2s | unknown | medium |
| `!bash -c 'kill -9 $(pgrep -f less)'` | 2s | ineffective | medium |
| `:respawn-pane -k` (tmux) | 2s | ineffective | medium |

---

## Stalling and Failure Patterns

### Pattern 1: The `less` Pager Trap (Critical)

The most severe failure pattern across all trials. When `git reflog` or
`git log --oneline --all --graph` was invoked without `--no-pager`, the output
triggered the `less` pager. The agent then spent many steps trying to escape.

**fix-git-zs8**: 56% of steps (15 of 27 agent steps) wasted on pager escape.
63 escape tool calls vs 35 productive calls. The agent tried:
1. `q` (multiple times) -- did not work because pager was in help mode
2. `q\n` -- sent to shell, not to less
3. `C-c` (multiple times) -- does not exit less
4. `G` then `q` -- navigated help but did not exit
5. `!killall less` from less shell -- ineffective
6. `!kill -9 $$` from less shell -- ineffective
7. `!killall -9 less` -- ineffective
8. `C-b` + `:respawn-pane -k` (tmux approach) -- ineffective
9. `C-\\` (SIGQUIT) -- ineffective
10. `:q\n` repeated 20 times (vim syntax, not less) -- this accidentally worked
    because spam exited to bash which then ran `:q` as an unknown command

**fix-git-WCv**: 89% of steps (17 of 19 agent steps) wasted on pager escape.
87 escape tool calls vs 6 productive calls. The agent NEVER successfully
escaped the pager. It tried all the same techniques as fix-git-zs8 but the
trial ended with the pager still active. The task was never completed.

**fix-git-FXy**: Successful -- used `git reflog` without `--no-pager` but the
output was short enough to not trigger the pager. No escape needed.

**Root cause**: The `git reflog` command outputs long history that fills the
terminal. Without `--no-pager` or `| head -N`, this opens `less`. The agent
lacks a reliable mental model for how to escape interactive pagers.

**Recommended fix**: Always use `git --no-pager <cmd>` or pipe through `head`.
After fix-git-zs8 discovered `--no-pager`, the remaining commands all used it
successfully.

### Pattern 2: Duration Overestimation on File Writes

The dna-insert trial requested `duration=60s` for `cat << 'EOF' > file.py ...`,
which is a heredoc file write. These always complete in ~0.5s. The pipeline
efficiency was 1% for those steps (60s requested, 0.5s actual).

Similarly, `duration=30s` was requested for Python scripts that completed in
~0.5s. The pipeline data shows:
- 4 commands at duration=30s with actual=0.5s (2% efficiency)
- 2 commands at duration=60s with actual=0.5s (1% efficiency)
- Only 4 of 19 pipeline steps had efficiency >= 50%

### Pattern 3: Binary Execution Duration Mismatch

In gpt2-codegolf, the GPT-2 inference binary (`/app/a.out`) was consistently
given `duration=5.0s` but actually completed in ~1.7s. Over 18 executions,
this wasted approximately 3.3s * 18 = 59.4s. A `duration=2s` would have been
sufficient and saved ~54s total.

### Pattern 4: Repeated Compilation + Execution Cycles

The gpt2-codegolf trial ran the same `gcc` + `/app/a.out` cycle at least 15
times, each time with the same duration parameters. No adaptation of the
duration values was observed despite consistent ~1.7s actual times.

---

## Parallelization Patterns

### Successfully Parallelized Command Groups

**Information gathering** (commonly seen in fix-git trials):
```
git status          |  concurrent  |  git branch -a
git stash list      |  concurrent  |  git reflog
git log --oneline   |  concurrent  |  git diff --stat
```
These are all read-only, independent git queries. Typical batch size: 3-5 commands.

**Verify + inspect** (dna-insert):
```
cat primers.fasta           |  concurrent  |  oligotm <seq1>
oligotm <seq2>              |  concurrent  |  echo <seq> | wc -c
```
Independent read operations run in parallel.

**Compile + test** (gpt2-codegolf):
```
gcc -O3 file.c -lm -o a.out  |  concurrent  |  /app/a.out <args>
```
NOTE: This is a dependency violation -- the binary must be compiled before it
can be executed. The agent parallelized compile and execute, which only works
if a previous compiled binary still exists. Risky pattern.

**File create + compile** (gpt2-codegolf):
```
cat > test.c << 'EOF' ...  |  concurrent  |  gcc test.c -o test && ./test
```
Another dependency violation -- the file must be written before compilation.

**Cleanup + verify** (dna-insert, fix-git):
```
rm <files>  |  concurrent  |  ls -la <dir>
git add .   |  concurrent  |  git commit -m "..."
```
The `git add` + `git commit` pair is a dependency violation (add must precede commit).

### Commands That Should Be Parallelized But Were Not

In gpt2-codegolf, `wc -c /app/gpt2.c` was often chained with `gcc` using `&&`
rather than run as a separate parallel command. Since `wc` is purely read and
`gcc` is independent of the byte count, these could be separate parallel calls.

In dna-insert, sequential Python scripts for sequence analysis could have been
split into parallel invocations when doing independent analyses.

---

## Observation (Output) Size Ranges

| Metric | Value |
|--------|-------|
| Minimum | 86 chars (empty terminal screen) |
| Maximum | 20,367 chars (git reflog output that triggered pager) |
| Average | 1,854 chars |
| Median | 1,289 chars |
| Typical range | 200-5,000 chars |

Large observations (>5000 chars) came from:
- `git reflog` without `--no-pager` (20,367 chars, 20,279 chars)
- `python3` scripts with verbose difflib output (15,158 chars)
- Long heredoc file writes echoed back (7,777 chars, 7,438 chars)
- Python script output with primer design results (4,695-5,809 chars)

---

## Timing Mismatch Summary

### Commands Where Agent Waited Too Long

| Command | Requested | Actual | Wasted | Frequency |
|---------|-----------|--------|--------|-----------|
| `cat << 'EOF' > file.py ...` (heredoc write) | 30-60s | ~0.5s | 29.5-59.5s | 4x in dna-insert |
| `python3 << 'EOF' ...` (simple scripts) | 5-30s | ~0.5s | 4.5-29.5s | 6x in dna-insert |
| `/app/a.out <ckpt> <vocab> "prompt"` | 5s | ~1.7s | ~3.3s | 18x in gpt2-codegolf |
| Empty keystroke (wait for output) | 30-60s | ~0.5s | 29.5-59.5s | 2x in dna-insert |

Total estimated wasted time from overestimation:
- dna-insert: ~250s wasted across 19 pipeline steps
- gpt2-codegolf: ~59s wasted across 18 binary executions

### Commands With Appropriate Durations

| Command | Requested | Actual | Efficiency |
|---------|-----------|--------|------------|
| `gcc -O3 file.c -lm -o out` | 2s | ~1.7-1.8s | 85-90% |
| `cat <file>` | 0.5-1s | ~0.5s | 50-100% |
| `git status` / `git log` | 0.5-1s | ~0.5s | 50-100% |
| `oligotm <seq>` | 1s | ~0.5s | 50% |
| `python3 -c "from transformers ..."` | 3s | ~1.8s | 60% |

---

## Key Findings

1. **Pager escape is the #1 failure mode**: Two of three fix-git trials were
   severely impacted. One never completed the task. The fix is trivial:
   `git --no-pager` or `GIT_PAGER=cat`.

2. **Duration estimation is poor for fast commands**: The agent assigns 30-60s
   durations to heredoc writes and Python scripts that complete in 0.5s. The
   pipeline/polling system recovers quickly, but the overhead adds up.

3. **No duration adaptation**: The agent uses the same `duration=5s` for
   `/app/a.out` on every one of 18+ invocations, despite it consistently
   finishing in 1.7s. A learning mechanism could halve this.

4. **Parallelization has dependency bugs**: The agent parallelizes compile+execute
   and file-write+compile, which are sequential dependencies. This only works
   by accident when a stale binary or file exists.

5. **Interactive escape vocabulary is limited**: The agent tries vim commands
   (`:q`, `ZZ`) in less, shell signals (`C-c`, `C-\`) that less ignores, and
   tmux commands that have no effect. It lacks knowledge of how `less` works
   (just pressing `q` at the prompt, not in help mode, exits it).

6. **Observation sizes are manageable**: Median 1,289 chars. The largest outputs
   (20K chars from reflog) are the ones that cause pager problems. Piping
   through `head -N` would keep output small and avoid pagers.
