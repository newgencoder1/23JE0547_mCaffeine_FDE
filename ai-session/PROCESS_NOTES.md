# How I built this with AI: process notes

*Written after the work, as a guide for reviewers. This is a summary, not a transcript. The raw transcript of the deployment session is `claude_code_session.jsonl` in this folder, and the commit history shows the order of work.*

**Manas Gupta · 23JE0547**

## 1. How I broke the problem down

I followed the brief's own priority: the parts that protect money come first, and PDF reading comes after them.

| Order | Piece | Why in this order | Commit |
|---|---|---|---|
| 1 | Scaffold: env config, schema with `UNIQUE(po_number)`, `/health`, request-id logs | Deployment problems are configuration problems, so set up config and health first | `64a3c2c` |
| 2 | Core A: bcrypt login, one function per permission rule, atomic state machine, append-only history | The "untrusted approvals" pain is the audit gap, so it gets the most marks and the most care | `4ed3482` |
| 3 | Part 1: text layer → garbled detection → optional OCR → the same checks | Reading is useless unless the checks catch its mistakes | `90d8c33` |
| 4 | UI, seed script, Docker / Render blueprint | The UI only shows things; the server decides | `6aa51bb` |
| 5 | 76 tests + real-Postgres checks of UNIQUE, concurrent approve and append-only | Prove the rules instead of trusting them | `bd68c2e` |
| 6 | README, runbook, project brief | Explain every decision | `c10c038`, `42ef5df` |
| 7 | Deploy, test live, rotate secrets, fix bugs, improve the UI, submit | Session 2 (Claude Code), below | `31a7911` onward |

## 2. AI mistakes I caught and fixed

The AI wrote most of the code. These are real mistakes from the two sessions, and how each was caught (by me while testing, or by a review/check step before anything went live):

| What the AI got wrong | How it was caught | Fix |
|---|---|---|
| OCR with `--psm 6` dropped the labels in sample 4's boxed header grid | Ran OCR on the sample and compared the output | Switched to `--psm 4` (one column, variable sizes) |
| CSS `display:flex` overrode the HTML `hidden` attribute, so **locked POs showed edit buttons** | Browser walkthrough | `[hidden]{display:none!important}`. The server already refused those clicks, which showed why rules must live on the server |
| `query_one` used for multi-row `DELETE`s | Review and tests | Replaced with `execute` |
| Quantity sent to Postgres as text | Review and tests | Converted to `Decimal` |
| `DATABASE_URL` first set to only the password, then with `[ ]` left in, and with `@`/`#` in the password breaking the URL | `/health` and the Render deploy | Full pooler URI and an alphanumeric password |
| **Double-click on Submit** showed a scary "SUBMITTED and locked" error even though the submit worked | I saw it while testing the live app | Buttons ignore repeat clicks while a request runs (`89b39d5`) |
| A PowerShell edit garbled `✓ ₹ —` characters in `po.js` | Read the diff before committing | Restored the file and re-applied the change with a safe editor |
| A new variable `once` clashed with an existing `const once` | Read the surrounding code before the change went live | Renamed it to `guarded` |
| Submission PDF heading turned the password into **PEPDEMO@2026**, which would break every reviewer login | Read the generated PDF | Moved the password out of the uppercase heading |
| README said "share link is listed" and "no code changes" after both stopped being true | Checked the README against the brief and the repo | Corrected both statements |
| Demo PDFs at risk of Windows line-ending conversion, which corrupts PDF offsets | Noticed a git CRLF warning | `.gitattributes`: `*.pdf binary`, then checked the files are byte-identical |

## 3. What I verified myself, on the live app

"It works on my machine" wasn't enough. In session 2, every rule was checked against the deployed app with direct API calls (curl and PowerShell), not only through the UI:

* No login → **401** · creator approving → **403** · lead1 approving their own PO → **403** · creator2 opening creator1's PO → **404**
* Approver editing → **403** · reject with no reason → **400** · second approve → **409** · editing an approved PO → **409**
* Total mismatch blocked on submit → **422** · duplicate PO number → "already exists", without naming the owner
* Reject → resubmit → approve gives **4 history entries** with server timestamps
* Garbled PDF → **OCR fallback** works on the server · "Open original PDF" → **private signed link**
* `/health` and `/health?deep=1` → database ok, storage ok

## 4. Security decisions I made during deployment

* Turned on **Row Level Security** on all four tables, so the public Supabase API can't read them. The app connects as the owner role.
* Secret keys and the database password appeared in my screenshots, so I **rotated all three secrets** (Supabase key, DB password, `SECRET_KEY`). The ones visible in the transcript no longer work.
* Scanned the git history and the submission ZIP for secrets before submitting. Redacted my email and the dead secrets from the transcript, and said so.

## 5. Why there are two sessions

The build chat (session 1, about 20 minutes on 27-11-2026, commits `64a3c2c`–`42ef5df`) had no access to my machine, GitHub, Render or the live URL. Deployment, live testing and fixes therefore happened in a second session with Claude Code. Its transcript is in this folder. A share link and export for session 1 could not be produced; see `README.md` in this folder.
