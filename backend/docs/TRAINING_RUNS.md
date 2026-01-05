Training Runs API
=================

Endpoints (MVP):

- POST /api/training-runs?definition_id=<id>&participants[]=... -> create a new run
- GET  /api/training-runs/{run_id} -> get run state
- POST /api/training-runs/{run_id}/levels/{level_idx}/submit -> submit answer for a task
- POST /api/training-runs/{run_id}/levels/{level_idx}/hint -> take a hint (simple penalty)

Implementation notes:
- Runs are persisted as JSON under `WORK_DIR/training_runs/`.
- Evaluation for `quiz` tasks compares provided answer to `task.answer` (case-insensitive equality).
- On correct submission, run advances to the next level; when last level is completed, run.state -> `completed`.
