# AI session transcripts

The project was built with Claude in two sessions.

## Session 1: build (claude.ai chat)

The app (code, tests, README, project brief) was built in a claude.ai chat session.
A public share link for that chat could not be created from my account, so it is not included here.
The commit history shows the order in which the work was done.

## Session 2: deployment and finishing (Claude Code)

* **Export:** `claude_code_session.jsonl` in this folder: the raw transcript from the Claude desktop app's session export, one JSON message per line.
* **Redactions:** my email address and the old Supabase keys, database passwords and session secret were replaced with `[REDACTED]` everywhere they appear. Nothing else was edited.

A second session was used because the first chat could not reach my machine, GitHub, Render or the live app. In it, Claude Code:

* pushed the existing commits and guided the Supabase and Render setup;
* ran the live checks against the deployed app (401, 403, 404, 409, reject reason, resubmit, history, OCR fallback, signed PDF link);
* fixed a double-click bug on the Submit button and redesigned the three pages (HTML/CSS/JS only, no backend changes);
* added three demo PO PDFs in `samples/demo/` and updated the README with the live URL.

Secrets shown during that session were replaced afterwards and no longer work.
