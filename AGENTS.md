# Repository instructions

## Scope

- Production scripts process only direct child images of `sorting/` and stop after moving them into `梗图`、`表情`、`史` or `其他`.
- Final archive folders are human-managed. Leave their media files and directory structure unchanged unless the user explicitly names exact files to change.
- Treat `等待手动分类,ai勿动/` as protected user content: leave it unread and unchanged.

## Changes

- Keep `scripts/main.py` as a thin entry point. Put model inference in `marker.py`, format conversion in `converter.py`, orchestration and moves in `sorter.py`, and shared file primitives in `utils.py`.
- Preserve the one-request contract: one image request returns both `mark` and `category` as JSON.
- Keep processing stateless. Failed images remain at the input root; completed images are skipped naturally because scanning is non-recursive.
- Store secrets only in environment variables. Logs, tests, commits, and documentation contain no API Key values.

## Verification

- Run `python -m unittest discover -s tests -v` after Python changes.
- Automated tests use temporary directories and fake model clients. A real API run requires an explicit user request.
- Live validation uses copied images in `sorting/.validation`, verifies the exact resolved cleanup path, and removes only that directory after collecting results.
