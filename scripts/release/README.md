# Scheduled Release Queue

This folder contains automation used to release specific commits on planned dates.

## Files

- `release-queue.json`: date-to-commit mapping.
- `push-queued-commit.ps1`: pushes the commit scheduled for the current date to `origin/master`.

## Behavior

On each run day:

1. Reads today's date (`yyyy-MM-dd`).
2. Looks up the matching commit in `release-queue.json`.
3. Fast-forwards remote `master` to that commit with:
   - `git push origin <commit>:master`

If no entry matches today, the script exits without changes.
