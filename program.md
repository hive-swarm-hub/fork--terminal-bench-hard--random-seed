# Terminal-Bench 2.0 Hard

Improve an agent scaffold to maximize mean pass rate on the 20 hardest Terminal-Bench 2.0 tasks (0-40% baseline with Terminus-KIRA).

## Setup

1. **Read the in-scope files**:
   - `agent/` — the agent scaffold. You modify everything in here.
   - `agent/agent.py` — the main agent implementation (extends Harbor's Terminus2).
   - `agent/anthropic_caching.py` — Anthropic prompt caching utility.
   - `agent/prompt-templates/` — prompt templates used by the agent.
   - `eval/eval.sh` — runs evaluation. Do not modify.
   - `prepare.sh` — installs dependencies. Do not modify.
2. **Run prepare**: `bash prepare.sh` to install the agent package and its dependencies.
3. **Run baseline**: `bash eval/eval.sh` to establish the starting score.

## The benchmark

Terminal-Bench 2.0 is a benchmark of 89 terminal-based coding tasks. This task focuses on the 20 hardest tasks where the baseline Terminus-KIRA agent scores 0-40%. Tasks span systems programming (compile CompCert, build DOOM for MIPS), ML (train FastText, SAM cell segmentation), data recovery (DB WAL recovery), and more. Each task runs in an isolated sandbox environment via Daytona.

The 20 hard tasks (grouped by baseline Terminus-KIRA pass rate):

**0% pass rate (12 tasks):** adaptive-rejection-sampler, caffe-cifar-10, db-wal-recovery, filter-js-from-html, gpt2-codegolf, install-windows-3.11, make-doom-for-mips, mteb-retrieve, query-optimize, raman-fitting, sam-cell-seg, train-fasttext

**20% pass rate (4 tasks):** configure-git-webserver, mteb-leaderboard, schemelike-metacircular-eval, video-processing

**40% pass rate (4 tasks):** dna-insert, extract-moves-from-video, make-mips-interpreter, model-extraction-relu-logits

## Experimentation

**What you CAN do:**
- Modify any file in `agent/` — the agent code, prompt templates, add new files, restructure, etc.
- Change the agent's strategy, tool use, prompting, error handling, environment bootstrapping, retry logic, etc.
- Add new Python dependencies (update `agent/pyproject.toml`).

**What you CANNOT do:**
- Modify `eval/`, `prepare.sh`, or `tasks.md`.
- Change the model — must use `anthropic/claude-opus-4-6`.
- Add external API calls beyond the Anthropic API (which harbor manages).

**The goal: maximize mean_pass_rate.** This is the average score across all 20 tasks, where each task scores 0.0 (fail) or 1.0 (pass) on a single trial. Higher is better.

**Simplicity criterion**: All else being equal, simpler is better.

## Output format

```
---
mean_pass_rate:   <value>
correct:          <N>
total:            20
```
