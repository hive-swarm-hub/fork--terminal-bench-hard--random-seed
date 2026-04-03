#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

cd "$REPO_DIR/agent"

harbor run \
  --agent-import-path agent:AgentHarness \
  -d terminal-bench@2.0 \
  -m anthropic/claude-opus-4-6 \
  -e daytona \
  -n 17 \
  --n-attempts 1 \
  -o "$REPO_DIR/jobs" \
  -i adaptive-rejection-sampler \
  -i caffe-cifar-10 \
  -i db-wal-recovery \
  -i gpt2-codegolf \
  -i install-windows-3.11 \
  -i make-doom-for-mips \
  -i mteb-retrieve \
  -i query-optimize \
  -i raman-fitting \
  -i configure-git-webserver \
  -i mteb-leaderboard \
  -i schemelike-metacircular-eval \
  -i video-processing \
  -i dna-insert \
  -i extract-moves-from-video \
  -i make-mips-interpreter \
  -i model-extraction-relu-logits \
  --env-file "$REPO_DIR/.env"

# Find the most recent job result
LATEST_JOB=$(ls -td "$REPO_DIR/jobs/"*/ 2>/dev/null | head -1)
RESULT_FILE="${LATEST_JOB}result.json"

if [ ! -f "$RESULT_FILE" ]; then
  echo "ERROR: No result.json found"
  exit 1
fi

# Parse results from harbor's result.json
MEAN=$(python3 -c "
import json, sys
with open('$RESULT_FILE') as f:
    data = json.load(f)
evals = data['stats']['evals']
key = list(evals.keys())[0]
mean = evals[key]['metrics'][0]['mean']
reward_stats = evals[key]['reward_stats'].get('reward', {})
correct = len(reward_stats.get('1.0', []))
total = evals[key]['n_trials']
print(f'{mean:.3f} {correct} {total}')
")

MEAN_VAL=$(echo "$MEAN" | awk '{print $1}')
CORRECT=$(echo "$MEAN" | awk '{print $2}')
TOTAL=$(echo "$MEAN" | awk '{print $3}')

echo "---"
echo "mean_pass_rate:   $MEAN_VAL"
echo "correct:          $CORRECT"
echo "total:            $TOTAL"
