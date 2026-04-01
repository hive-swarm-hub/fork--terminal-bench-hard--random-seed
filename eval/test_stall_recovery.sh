#!/bin/bash
# Stall Recovery Benchmark
# Runs the 4 tasks most affected by terminal stalls to test reset_terminal effectiveness.
#
# Tasks selected based on eval trace analysis:
#   - sam-cell-seg:      tail -f blocking terminal (170+ stuck steps in V3)
#   - query-optimize:    slow SQL query that can't be killed (18 stuck episodes)
#   - adaptive-rejection-sampler: heredoc stuck in R REPL (33 stuck episodes in V2)
#   - configure-git-webserver: SSH/process management issues
#
# Usage: bash eval/test_stall_recovery.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

cd "$REPO_DIR/agent"

echo "=== Stall Recovery Benchmark ==="
echo "Testing reset_terminal on 4 stall-prone tasks..."
echo ""

harbor run \
  --agent-import-path agent:AgentHarness \
  -d terminal-bench@2.0 \
  -m anthropic/claude-opus-4-6 \
  -e daytona \
  -n 4 \
  --n-attempts 1 \
  -o "$REPO_DIR/jobs" \
  -i sam-cell-seg \
  -i query-optimize \
  -i adaptive-rejection-sampler \
  -i configure-git-webserver \
  --env-file "$REPO_DIR/.env"

# Find the most recent job result
LATEST_JOB=$(ls -td "$REPO_DIR/jobs/"*/ 2>/dev/null | head -1)
RESULT_FILE="${LATEST_JOB}result.json"

if [ ! -f "$RESULT_FILE" ]; then
  echo "ERROR: No result.json found"
  exit 1
fi

echo ""
echo "=== Results ==="

# Parse results
python3 -c "
import json, sys, os

with open('$RESULT_FILE') as f:
    data = json.load(f)

evals = data['stats']['evals']
key = list(evals.keys())[0]
mean = evals[key]['metrics'][0]['mean']
reward_stats = evals[key].get('reward_stats', {}).get('reward', {})
correct = len(reward_stats.get('1.0', []))
total = evals[key]['n_trials']

print(f'mean_pass_rate:   {mean:.3f}')
print(f'correct:          {correct}')
print(f'total:            {total}')
print()

# Check for reset_terminal usage in trial logs
job_dir = '$LATEST_JOB'
for task_dir in sorted(os.listdir(job_dir)):
    task_path = os.path.join(job_dir, task_dir)
    if not os.path.isdir(task_path):
        continue
    trial_log = os.path.join(task_path, 'trial.log')
    if not os.path.exists(trial_log):
        continue

    with open(trial_log) as f:
        content = f.read()

    reset_count = content.count('reset_terminal')
    stall_count = content.count('[stall]')
    critical_count = content.count('[CRITICAL:')

    task_name = task_dir.split('__')[0]
    passed = '1.0' in str(reward_stats.get('1.0', []))  # crude check

    print(f'{task_name}:')
    print(f'  stalls: {stall_count}, critical_warnings: {critical_count}, reset_terminal_calls: {reset_count}')
"
