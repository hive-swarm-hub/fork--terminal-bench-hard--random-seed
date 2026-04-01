# Trial Log Analysis - Batch 1

Analysis of 5 trajectory files from agent runs on 2026-03-31. Covers tasks:
gpt2-codegolf, fix-git (3 runs), dna-insert.

## Source Files

| Trial | Task | Model | Steps | Total Commands |
|-------|------|-------|-------|----------------|
| `gpt2-codegolf__WN2a8Nw` | GPT-2 C code-golf | claude-haiku-4-5 | 72 | ~95 |
| `fix-git__zs879ar` | Git merge recovery | claude-opus-4-6 | 32 | ~100 |
| `fix-git__WCvvvRc` | Git merge recovery | claude-opus-4-6 | 20 | ~90 |
| `fix-git__FXy2g8X` | Git merge recovery | claude-opus-4-6 | 16 | ~28 |
| `dna-insert__nX5scS3` | DNA primer design | claude-opus-4-6 | 22 | ~30 |

---

## Table of All Unique Commands

### File/Directory Inspection Commands (FAST: 0.5-1.0s)

| Command Pattern | Duration | Category | Output Size Range | Notes |
|----------------|----------|----------|-------------------|-------|
| `ls -lh /app/` | 0.5s | fast | 150-300 chars | Basic listing |
| `ls -la /app/` | 0.5-1.0s | fast | 250-500 chars | Detailed listing |
| `cat <file>` | 0.5-1.0s | fast | 150-7400 chars | Depends on file size; fasta=7357 chars |
| `head -c 1000 <file> \| od -c \| head -20` | 0.5s | fast | ~1800 chars | Binary inspection |
| `hexdump -C <file> \| head -30` | 0.5s | fast | ~300 chars | Binary header |
| `tail -20 <file>` | 0.5s | fast | ~300 chars | File tail |
| `wc -c <file>` | 0.5s | fast | ~150 chars | Byte count |
| `file <file>` | 0.5s | fast | ~150 chars | File type check |
| `head -5 <file> && echo '...' && tail -5 <file>` | 0.5s | fast | ~700 chars | File bookends |
| `xxd <file> \| tail -5` | 0.5s | fast | ~200 chars | Hex dump tail |
| `echo 'string' \| wc -c` | 1.0s | fast | ~100 chars | String length |

### File Write Commands (FAST: 0.5s)

| Command Pattern | Duration | Category | Output Size Range | Notes |
|----------------|----------|----------|-------------------|-------|
| `cat > <file> << 'CEOF' ...` | 0.5s | fast | 960-3100 chars | Heredoc write; output is echo of content |
| `printf '...' > <file>` | 0.5s | fast | ~450 chars | Direct write |
| `echo '...'` | 0.5s | fast | ~600 chars | Status messages |

### Compilation Commands (MEDIUM: 1.0-2.0s)

| Command Pattern | Duration | Category | Output Size Range | Notes |
|----------------|----------|----------|-------------------|-------|
| `gcc -O3 <file> -lm -o <out> 2>&1` | 2.0s | medium | 250-1200 chars | C compilation |
| `gcc -O3 <file> -lm -o <out> 2>&1 \| grep error` | 2.0s | medium | 250-600 chars | Filtered compile |
| `wc -c <file> && gcc -O3 <file> -lm -o <out> 2>&1` | 2.0s | medium | 300-600 chars | Size + compile |
| `gcc <file> -o <out> && ./<out>` | 1.0s | medium | 800-2200 chars | Compile + run test |

### Program Execution Commands (MEDIUM-SLOW: 1.0-5.0s)

| Command Pattern | Duration | Category | Output Size Range | Notes |
|----------------|----------|----------|-------------------|-------|
| `/app/a.out <ckpt> <vocab> "input" 2>&1` | 5.0s | slow | 130-600 chars | GPT-2 inference; actual ~1.7s |
| `python3 << 'EOF' ... EOF` | 1.0-2.0s | medium | 400-15000 chars | Python heredoc scripts |
| `python3 -c "..."` | 2.0-3.0s | medium | 370-700 chars | One-liner Python |
| `oligotm -tp 1 -sc 1 ... <seq>` | 1.0s | fast | ~140 chars | Melting temp calc |

### Git Commands (FAST: 0.5-1.0s)

| Command Pattern | Duration | Category | Output Size Range | Notes |
|----------------|----------|----------|-------------------|-------|
| `git status` | 0.5-1.0s | fast | 200-400 chars | Working tree status |
| `git branch -a` | 0.5-1.0s | fast | 100-200 chars | Branch listing |
| `git log --oneline --all --graph` | 1.0s | **INTERACTIVE** | Triggers `less` pager! | DANGER: causes stall |
| `git log --oneline <ref> -N` | 0.5-1.0s | fast | 200-400 chars | Short log; safe |
| `git --no-pager log --oneline --graph -N` | 1.0s | fast | 200-500 chars | Safe: no pager |
| `git reflog` | 1.0s | **INTERACTIVE** | Triggers `less` pager! | DANGER: causes stall |
| `git --no-pager reflog` | 1.0s | fast | 300-500 chars | Safe: no pager |
| `git stash list` | 0.5-1.0s | fast | ~50 chars | Usually empty |
| `git --no-pager show --stat <ref>` | 1.0s | fast | 300-500 chars | Commit stats |
| `git --no-pager diff <ref1> <ref2> -- <file>` | 0.5-1.0s | fast | 300-3800 chars | Diff output |
| `git --no-pager fsck --dangling --no-reflogs 2>&1 \| head -30` | 2.0s | medium | 200-400 chars | Find dangling objects |
| `git merge <ref> --no-edit` | 2.0s | medium | 200-400 chars | May produce conflicts |
| `git checkout --theirs <file>` | 1.0s | fast | ~200 chars | Conflict resolution |
| `git add <file>` | 0.5-1.0s | fast | ~100 chars | Stage file |
| `git commit --no-edit` | 1.0s | fast | ~200 chars | Commit |
| `GIT_PAGER=cat git reflog --no-color > /tmp/reflog.txt 2>&1` | 2.0s | medium | N/A (redirect) | Workaround for pager |

### Package Installation Commands (SLOW: 30s)

| Command Pattern | Duration | Category | Output Size Range | Notes |
|----------------|----------|----------|-------------------|-------|
| `apt-get update && apt-get install -y primer3 2>&1 \| tail -5` | 30s | slow | 375-4100 chars | Package install |

### Cleanup Commands (FAST: 0.5-1.0s)

| Command Pattern | Duration | Category | Output Size Range | Notes |
|----------------|----------|----------|-------------------|-------|
| `rm <files>` | 0.5-1.0s | fast | ~100 chars | File deletion |
| `rm <file> 2>/dev/null; ls -la <dir>` | 0.5s | fast | ~400 chars | Clean + verify |
| `ps aux \| grep <process>` | 0.5s | fast | ~200 chars | Process check |

### Interactive Escape Keystrokes (STALLING RECOVERY)

| Keystroke | Duration | Category | Context |
|-----------|----------|----------|---------|
| `q` | 0.3-1.0s | escape | Less pager quit |
| `\n` (Enter) | 0.3-0.5s | escape | Dismiss prompt |
| `\r` (CR) | 0.3-0.5s | escape | Dismiss prompt |
| `C-c` | 0.3-1.0s | escape | Interrupt signal |
| `C-\` | 1.0s | escape | SIGQUIT |
| `C-b` | 0.3-0.5s | escape | Tmux prefix |
| `G` | 0.5s | escape | Less: go to end |
| `ZZ` | 1.0s | escape | Vi/less save-quit |
| `:q\n` | 1.0s | escape | Vi/less quit |
| `!killall less\n` | 2.0s | escape | Less shell command |
| `!killall -9 less\n` | 2.0s | escape | Force kill less |
| `!kill -9 $$\n` | 2.0s | escape | Kill current shell |
| `:respawn-pane -k\n` | 2.0s | escape | Tmux pane respawn |
| `!bash -c 'kill -9 $(pgrep -f less) 2>/dev/null; true'\n` | 2.0s | escape | Kill less via pgrep |
| `killall less 2>/dev/null; reset\n` | 2.0s | escape | Kill + reset terminal |
| `\n:q\n` x20 (bulk) | 10.0s | escape | Desperation escape |

---

## Stalling and Failure Patterns

### Pattern 1: Git Pager Trap (CRITICAL - observed in 3/3 fix-git runs)

**Trigger:** Running `git log`, `git reflog`, or `git log --oneline --all --graph` without `--no-pager` flag.

**Mechanism:** Git opens `less` as its pager. The agent sees the LESS help screen instead of git output. The agent's keystrokes are sent via tmux `send-keys` which get interpreted as shell commands rather than pager input.

**Observed in:**
- `fix-git__zs879ar` (steps 3-18): Spent **16 steps** (dozens of keystrokes) trying to escape `less`. Tried: `q`, `C-c`, `!killall less`, `!kill -9 $$`, `C-b :respawn-pane -k`, `C-\`, `:q`, and finally a burst of 20x `:q\n` sequences.
- `fix-git__WCvvvRc` (steps 3-20): Spent **17 steps** trying to escape `less`. Tried: `q`, `C-c`, `q\n`, `killall less; reset`, `ZZ`, `:q`, `!killall -9 less`, `C-b c` (tmux new window). Never successfully escaped -- the run used up its budget stuck in `less`.
- `fix-git__FXy2g8X`: Avoided the trap entirely by using short `-N` flags with git log commands.

**Resolution that worked (zs879ar):** Sending `\n:q\n` 20 times with duration=10s eventually exited all nested less instances. After escaping, agent switched to `git --no-pager` prefix for all subsequent commands.

**Resolution that failed (WCvvvRc):** Nothing worked. The agent exhausted its entire step budget stuck in the pager. Even `C-b c` (tmux new window) didn't help because the terminal context still showed the less help screen.

**Waste quantification:**
- zs879ar: ~40+ keystrokes over 16 steps wasted on escape attempts
- WCvvvRc: ~80+ keystrokes over 17 steps -- ENTIRE RUN WASTED

### Pattern 2: Empty Keystrokes / No-op Commands

Commands with `""` (empty string) keystrokes were sent as "task_complete" signals or appear when the agent has no more commands to issue. Observed durations: 30s and 60s (likely timeout-padded waits for prior async operations).

Examples from dna-insert:
- Step 6: `keystrokes=""`, `duration=30` -- waiting after apt-get install
- Step 14: `keystrokes=""`, `duration=60` -- waiting after large heredoc write
- Step 20, 22: `keystrokes=""` -- task_complete signals

### Pattern 3: Polling Optimization (logged in trial.log)

The agent framework implements "polling" optimization that detects early command completion:
- `[polling] saved 3.3s (duration=5.0s)` -- inference commands finish in ~1.7s but duration set to 5.0s
- `[polling] saved 0.3s (duration=2.0s)` -- compilation finishes in ~1.7s but duration set to 2.0s
- `[polling] saved 1.0s (duration=2.0s)` -- git commands finish in ~1.0s

### Pattern 4: Repeated Compile-Test Cycles

In gpt2-codegolf, the agent repeatedly executed the same compile+run sequence:
1. `cat > /app/gpt2.c << 'CEOF' ...` (0.5s)
2. `gcc -O3 /app/gpt2.c -lm -o /app/a.out 2>&1` (2.0s)
3. `/app/a.out <args> "input" 2>&1` (5.0s)

This 3-step cycle was repeated ~15 times (steps 9-54), totaling ~112.5s of wall time just for compilation+inference.

### Pattern 5: Pipeline Optimization (dna-insert trial.log)

The dna-insert run used a "pipeline" optimization:
```
[pipeline] saved 29.5s (total_duration=30.0s, actual=0.5s, cmds=1)
[pipeline] saved 59.5s (total_duration=60.0s, actual=0.5s, cmds=1)
```
Some commands with 30-60s budgets completed in 0.5s -- the pipeline framework saved significant time by detecting early completion.

---

## Command Sequences That Could Be Parallelized

### 1. Initial Exploration (all tasks)

These commands are routinely sent in parallel already (batched in a single step):
```
ls -lh /app/                          # 0.5s
file /app/gpt2-124M.ckpt              # 0.5s
head -c 1000 /app/vocab.bpe | od -c   # 0.5s
```

### 2. Git State Assessment (fix-git)

Already parallelized in run FXy2g8X (the successful run):
```
git status                  # 1.0s
git branch -a               # 1.0s
git stash list              # 1.0s
git reflog                  # 1.0s  (but must use --no-pager!)
```

### 3. Compile + File Size Check (gpt2-codegolf)

These are already combined but could be split for parallelism:
```
wc -c /app/gpt2.c           # 0.5s  (independent)
gcc -O3 /app/gpt2.c -lm ... # 2.0s  (independent)
```

### 4. Git Conflict Analysis (fix-git)

Sent in parallel in step 22 of zs879ar (5 commands at once):
```
cat _includes/about.md                              # 1.0s
git --no-pager diff HEAD 650dba4 -- _includes/about.md  # 1.0s
git --no-pager show d7d3e4b:_includes/about.md      # 1.0s
git --no-pager show 650dba4:_includes/about.md      # 1.0s
git --no-pager show c4e38a1:_includes/about.md      # 1.0s
```

### 5. Verification Steps (gpt2-codegolf)

Final verification commands that are independent:
```
ls -lh /app/gpt2.c /app/a.out    # 0.5s
file /app/gpt2.c                  # 0.5s
wc -c /app/gpt2.c                # 0.5s
```

### 6. NOT Parallelizable (sequential dependencies)

These sequences must remain sequential:
```
cat > /app/gpt2.c << 'CEOF' ...  # Must complete before compile
gcc -O3 /app/gpt2.c -lm ...      # Must complete before run
/app/a.out <args>                  # Depends on compilation
```

```
git merge 650dba4                 # Must complete before conflict check
cat _includes/about.md            # Check merge result
git add _includes/about.md        # Must come after resolution
git commit                        # Must come after add
```

---

## Output Size Ranges Observed

| Category | Min (chars) | Max (chars) | Typical (chars) | Examples |
|----------|------------|------------|-----------------|----------|
| Directory listing | 100 | 500 | 250 | `ls -la /app/` |
| File content (small) | 50 | 1000 | 400 | `cat _includes/about.md` |
| File content (large) | 1000 | 7400 | 3000 | `cat sequences.fasta` (7357 chars) |
| Heredoc write echo | 960 | 3100 | 2000 | `cat > file.c << 'EOF'` |
| Python script output | 370 | 15000 | 1500 | `python3 << 'EOF'` (fasta comparison: 14976 chars) |
| Compilation output | 250 | 1200 | 500 | `gcc -O3 ...` |
| Program execution | 130 | 730 | 300 | `/app/a.out ...` |
| Git short output | 50 | 500 | 300 | `git status`, `git log --oneline -5` |
| Git diff output | 200 | 3800 | 1000 | `git diff ...` |
| **Pager trap output** | **3000** | **8000** | **5000** | LESS help screen (repeated) |
| Empty/minimal | 50 | 100 | 70 | task_complete signals |
| Package install | 375 | 4100 | 2000 | `apt-get install` |

---

## Key Takeaways

1. **Pager trap is the #1 failure mode.** Two of three fix-git runs wasted massive step budgets fighting `less`. The fix is simple: always use `--no-pager` or `GIT_PAGER=cat` with git commands, or set `PAGER=cat` globally at session start.

2. **Duration over-provisioning is common but mitigated by polling.** Commands assigned 5.0s typically complete in 1.7s. The polling/pipeline framework recovers 60-80% of the provisioned wait time.

3. **Compilation + inference cycles dominate gpt2-codegolf.** 15 iterations of write-compile-run consumed most of the agent's time budget. Each cycle costs ~7.5s of wall time (0.5 + 2.0 + 5.0).

4. **Batch parallelism is already used effectively** for independent read-only operations (ls, cat, git log), but sequential write-compile-run chains cannot be parallelized.

5. **Duration choices cluster around:** 0.5s (file reads), 1.0s (git/python), 2.0s (compile/kill), 5.0s (inference/long scripts), 10.0s (desperation escape), 30s (package install), 60s (large writes + apt).

6. **The successful fix-git run (FXy2g8X)** avoided all stalling by using short `git log -N` forms and `0.5s` durations from the start, completing the task in ~16 steps vs 32+ for the stalled runs.
