# Terminal-Bench 2.0 Hard

Improve an agent scaffold to maximize pass rate on the 20 hardest Terminal-Bench 2.0 tasks.

## Quickstart

```bash
bash prepare.sh
bash eval/eval.sh
```

## Structure

- `agent/` — the agent scaffold (artifact to evolve)
- `eval/eval.sh` — evaluation script (do not modify)
- `prepare.sh` — dependency installer (do not modify)
- `program.md` — full task instructions
- `tasks.md` — the 20 hard tasks and their baseline pass rates
