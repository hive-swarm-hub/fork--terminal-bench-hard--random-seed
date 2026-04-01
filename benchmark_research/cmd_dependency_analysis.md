# Multi-Command Batch Dependency Analysis

Analysis of agent trajectory files to determine whether commands sent together
in a single `execute_commands` / tool call are sequential (dependent) or
parallel-safe (independent).

## Data sources

| # | Task | Trajectory | Status |
|---|------|-----------|--------|
| 1 | build-pmars | `agent/jobs/2026-03-31__15-40-05/build-pmars__TA2HHBh/` | Failed during environment setup (no trajectory) |
| 2 | pytorch-model-recovery | `agent/jobs/2026-03-31__15-40-05/pytorch-model-recovery__M4taVfT/` | Failed during environment setup (no trajectory) |
| 3 | fix-git | `agent/jobs/2026-03-31__19-09-41/fix-git__FXy2g8X/agent/trajectory.json` | Complete (16 steps) |
| 4 | gpt2-codegolf | `agent/jobs/2026-03-31__15-49-46/gpt2-codegolf__E7aYnRw/` | Failed during environment setup (no trajectory) |
| 5 | dna-insert | `agent/jobs/2026-03-31__19-56-07/dna-insert__nX5scS3/agent/trajectory.json` | Complete (33 steps) |

Three of the five trials (build-pmars, pytorch-model-recovery, gpt2-codegolf) failed
before any agent actions due to Runloop environment provisioning errors. Analysis is
based on the two trajectories that contain agent actions: fix-git and dna-insert.

---

## Trajectory 1: fix-git (16 steps, 7 multi-command batches)

### Batch 1 -- Step 2 (4 commands) -- MIXED

```
cmd1: cd /app/personal-site && git status
cmd2: git branch -a
cmd3: git stash list
cmd4: git reflog
```

**Classification: MIXED**
- cmd1 uses `cd` to change the working directory, then `git status`. The `cd` sets up
  the working directory that cmd2-cmd4 implicitly rely on (they assume cwd is already
  the repo). So cmd1 must run first.
- cmd2, cmd3, cmd4 are all read-only git queries that are independent of each other
  and could run in parallel once the cwd is established.

### Batch 2 -- Step 3 (2 commands) -- PARALLEL-SAFE

```
cmd1: git log --oneline 650dba4 -3
cmd2: git diff master 650dba4 --stat
```

**Classification: PARALLEL-SAFE**
- Both are read-only git queries examining existing commits. Neither modifies state.
  They could run in separate terminals simultaneously.

### Batch 3 -- Step 6 (3 commands) -- PARALLEL-SAFE

```
cmd1: cat _includes/about.md
cmd2: git diff c4e38a1 d7d3e4b -- _includes/about.md
cmd3: git diff c4e38a1 650dba4 -- _includes/about.md
```

**Classification: PARALLEL-SAFE**
- cmd1 reads the current file contents. cmd2 and cmd3 compute diffs between specific
  commits. All three are read-only operations with no side effects. Fully independent.

### Batch 4 -- Step 8 (3 commands) -- PARALLEL-SAFE

```
cmd1: cat _includes/about.md
cmd2: git show 650dba4:_includes/about.md | xxd | tail -5
cmd3: xxd _includes/about.md | tail -5
```

**Classification: PARALLEL-SAFE**
- All three read file/git contents. No writes. cmd2 and cmd3 both failed (xxd not
  installed) but that does not change the dependency analysis -- they are independent
  read operations.

### Batch 5 -- Step 10 (2 commands) -- SEQUENTIAL

```
cmd1: git add _includes/about.md
cmd2: git commit -m "Merge 'Move to Stanford' changes into master"
```

**Classification: SEQUENTIAL**
- cmd2 (`git commit`) depends on cmd1 (`git add`) having staged the file first. If
  these ran in parallel, the commit could execute before the file was staged, producing
  an incorrect merge commit. Classic write-then-use dependency.

### Batch 6 -- Step 11 (2 commands) -- PARALLEL-SAFE

```
cmd1: git log --oneline --graph -5
cmd2: git status
```

**Classification: PARALLEL-SAFE**
- Both are read-only git queries. No side effects. Fully independent.

### Batch 7 -- Step 14 (4 commands) -- PARALLEL-SAFE

```
cmd1: git log --oneline --graph -6
cmd2: git status
cmd3: cat _includes/about.md
cmd4: git diff 650dba4 HEAD -- _layouts/default.html
```

**Classification: PARALLEL-SAFE**
- All four commands are read-only verification checks after the merge was already
  committed. No command modifies state. All independent.

---

## Trajectory 2: dna-insert (33 steps, 5 multi-command batches)

### Batch 8 -- Step 10 (3 commands) -- PARALLEL-SAFE

```
cmd1: oligotm -tp 1 -sc 1 -mv 50 -dv 2 -n 0.8 -d 500 CTCATATGTATATCTCCTTCTTAAAGTTAAACAAAATTATTTCTA
cmd2: oligotm -tp 1 -sc 1 -mv 50 -dv 2 -n 0.8 -d 500 CTCATATGTATATCTCCTTCTTAAAGTTAAACAAAATT
cmd3: echo 'CTCATATGTATATCTCCTTCTTAAAGTTAAACAAAATTATTTCTA' | wc -c
```

**Classification: PARALLEL-SAFE**
- Three independent computations: two melting-temperature calculations on different
  DNA sequences, and a character count. No shared state or dependencies.

### Batch 9 -- Step 15 (3 commands) -- PARALLEL-SAFE

```
cmd1: cat primers.fasta
cmd2: echo '---'
      oligotm -tp 1 -sc 1 -mv 50 -dv 2 -n 0.8 -d 500 CAAGGGCGAGGAGCTGTT
cmd3: oligotm -tp 1 -sc 1 -mv 50 -dv 2 -n 0.8 -d 500 CTCATATGTATATCTCCTTCTTAAAGTTAAACAAAATTATTTCTA
```

**Classification: PARALLEL-SAFE**
- cmd1 reads a file. cmd2 prints a separator then computes a Tm. cmd3 computes another
  Tm. All are read-only with no shared state. The echo in cmd2 is cosmetic output, not
  a state mutation that others depend on.

### Batch 10 -- Step 16 (2 commands) -- SEQUENTIAL

```
cmd1: rm design_primers.py design_primers2.py
cmd2: ls -la /app/
```

**Classification: SEQUENTIAL**
- cmd1 deletes temporary script files. cmd2 lists the directory to verify they are
  gone. The `ls` is checking the side-effect of `rm`. If run in parallel, `ls` might
  execute before `rm` completes, showing stale results.

### Batch 11 -- Step 23 (2 commands) -- PARALLEL-SAFE

```
cmd1: cat primers.fasta
cmd2: ls -la /app/
```

**Classification: PARALLEL-SAFE**
- Both are read-only. `cat` displays file contents, `ls` lists directory. Neither
  modifies state. Independent.

### Batch 12 -- Step 30 (2 commands) -- PARALLEL-SAFE

```
cmd1: cat primers.fasta
cmd2: ls -la /app/
```

**Classification: PARALLEL-SAFE**
- Identical pattern to Batch 11. Both read-only, fully independent.

---

## Summary statistics

| Classification | Count | Percentage |
|----------------|-------|------------|
| PARALLEL-SAFE  |     9 |      75.0% |
| SEQUENTIAL     |     2 |      16.7% |
| MIXED          |     1 |       8.3% |
| **Total**      |**12** | **100.0%** |

## Key findings

1. **75% of multi-command batches are parallel-safe.** The model overwhelmingly batches
   together read-only, information-gathering commands (git log, git status, cat, diff,
   oligotm calculations). These have zero inter-dependencies and could safely execute
   in separate terminals.

2. **Only 2 out of 12 batches are strictly sequential.** Both are classic
   write-then-verify patterns:
   - `git add` then `git commit` (must stage before committing)
   - `rm` then `ls` (delete files then verify deletion)

3. **One batch is mixed.** Step 2 of fix-git chains `cd && git status` as a single
   command (sequential within that command string), followed by three independent git
   queries that rely on the working directory being set by cmd1.

4. **The model uses multi-command batches primarily for parallel information gathering.**
   When the model needs to understand a situation, it fires off multiple read-only
   queries simultaneously. When it needs to perform a mutation (write, delete, commit),
   it typically either issues a single command per step, or chains the mutation with
   its verification in a sequential pair.

5. **The sequential batches represent a potential correctness risk** in an execution
   engine that runs commands in parallel. If the harness were to parallelize all
   commands in a batch, the `git add` + `git commit` pair (Batch 5) would be the most
   dangerous, potentially producing an empty or incorrect commit.
