# How I built this with AI: process notes

*Written after the work, as a guide for reviewers. This is a summary, not a transcript. The raw transcript of the deployment session is `claude_code_session.jsonl` in this folder, and the commit history shows the order of work.*

**Manas Gupta · 23JE0547**

---

## 0. Starting point: understanding the pain before the code

Before writing any code, I mapped each pain in the brief to the part of the system that removes it. This decided what to build first and where each rule had to live.

| Pain in the brief | Root cause | What the tool does | Where it lives |
|---|---|---|---|
| ₹1,20,000 typed as ₹12,000; totals never checked | Humans retype numbers | Read the PDF, then check line maths and PO maths on the server | `extraction.py`, `validation.py` |
| The same PO entered twice | The sheet has no memory of PO numbers | `UNIQUE(po_number)` in the database, not just a UI check | `db/schema.sql` |
| Creator types "Approved" on their own PO | Anyone can edit the sheet | Role and own-PO checks on every request, plus a conditional `UPDATE` | `permissions.py`, `workflow.py` |
| "Who approved this?" lost in WhatsApp | No audit trail | Append-only `po_actions`, with timestamps from the DB clock | `workflow.py`, DB triggers |
| Script on one laptop; PDFs in inboxes | Nothing is hosted | Render + Supabase Postgres + a private storage bucket, plus `/health` | `storage.py`, `health.py` |

The guiding rule: **the UI only decides what to show; the server decides what is allowed.** Every rule had to hold for a raw `curl` call.

---

## 1. How I broke the problem down

I followed the brief's own priority: the parts that protect money come first, and PDF reading comes after them.

| Order | Piece | Why in this order | Commit |
|---|---|---|---|
| 1 | Scaffold: env config, schema with `UNIQUE(po_number)`, `/health`, request-id logs | Deployment problems are configuration problems, so set up config and health first | `64a3c2c` |
| 2 | Core A: bcrypt login, one function per permission rule, atomic state machine, append-only history | The "untrusted approvals" pain is the audit gap, so it gets the most marks and the most care | `4ed3482` |
| 3 | Part 1: text layer → garbled detection → optional OCR → the same checks | Reading is useless unless the checks catch its mistakes | `90d8c33` |
| 4 | UI, seed script, Docker / Render blueprint | The UI only shows things; the server decides | `6aa51bb` |
| 5 | 76 tests + real-Postgres checks of UNIQUE, concurrent approve and append-only | Prove the rules instead of trusting them | `bd68c2e` |
| 6 | UI fix from a browser walkthrough | Found by actually clicking through the app | `63f2f74` |
| 7 | README, runbook, project brief | Explain every decision | `c10c038`, `42ef5df` |
| 8 | Deploy, test live, rotate secrets, fix bugs, improve the UI, submit | Session 2 (Claude Code), sections 4–6 below | `31a7911` onward |

Each commit is one coherent step, so the history reads as the plan.

---

## 2. Key design decisions and trade-offs

These are the choices I would defend in an interview, and why I made each one rather than the alternative.

**404, not 403, for another creator's PO.** A 403 confirms "this PO exists but isn't yours", which lets someone probe IDs. A 404 gives the same answer as "no such PO". The duplicate-number message follows the same thinking: it says the number exists, never whose PO it is.

**Rules in one file, called before any data changes.** `permissions.py` has one small function per rule (`require_approver`, `require_not_own_po`, `require_owner`, `require_editable`, `load_visible_po`). The routes and workflow call them first. That makes it easy to answer "where is rule X enforced?" with a line number, and easy to test.

**Defence in depth for "nobody approves their own PO".** The rule is checked twice: once in Python (`require_not_own_po`) and again inside the SQL itself (`AND created_by <> %s` in the `UPDATE`). Even if a future code path forgot the Python check, the database update would match zero rows.

**Atomic approve.** `UPDATE purchase_orders SET status='APPROVED' WHERE id=? AND status='SUBMITTED' … RETURNING id`, plus the history `INSERT`, in one transaction. With two clicks at once, Postgres row locking lets the first win; the second updates 0 rows and gets **409**. No separate "read status, then write" step that could race.

**History is append-only in three layers.** No API route edits or deletes it, no UI control does, and database triggers reject `UPDATE`, `DELETE` and `TRUNCATE` on `po_actions`. Timestamps come from the database clock (`now()`), not the browser.

**Money as integer paise via `Decimal`, never floats.** `₹1,24,500.00`, `Rs. 124500`, `INR 1,24,500` and `124,500` all become `12450000`. Floats can't store 0.1 exactly, so rupee maths would drift. The tolerance of ₹1 is exactly 100 paise.

**Parse errors vs. check failures.** A value that can't be read at all (e.g. "twelve lakh") is refused with 422 and not saved. A value that can be read but fails a business check (totals don't match) can be saved as a draft, but blocks submit. That lets a creator save work in progress without ever letting a wrong PO reach an approver.

**Checks re-run on submit, on stored data.** `workflow.submit` runs the checks against what is in the database, not what the browser claims, so a crafted request can't skip validation.

**Private bucket + 5-minute signed links.** The storage key never reaches the browser. Opening a PDF re-checks that the user may see that PO, then redirects to a short-lived signed URL.

**Plain Flask + vanilla JS, no framework.** Small enough to read end to end and explain line by line. The brief says the UI isn't scored, so the effort went into server rules.

---

## 3. How PDF reading decides what to trust

The brief warns that some "digital" PDFs have garbage text layers. I check whether the text **makes sense**, not only how much there is:

1. **Fewer than 40 characters** → treated as a scan / image-only PDF.
2. **Junk ratio above 3 %** (`(cid:NN)` placeholders and symbols like `¤§¶†`) → broken font encoding.
3. **Fewer than 3 PO words** (purchase, order, total, qty, vendor, date…) → gibberish, such as letters shifted by a bad character map.
4. **No PO number and no total found** → also treated as unreadable.

An unreadable PDF **never** fills the form. The user gets a clear message and a blank form.

**OCR fallback (optional challenge).** Pages are rendered at 300 dpi and read with Tesseract `--psm 4`. The OCR text goes through the **same** parser and **all** the checks. OCR output is accepted only if it finds both a PO number and a total, and it's labelled `ocr` with a "check every value" warning. Digits are never "auto-corrected": a misread digit must fail the line-maths or PO-maths check, which is exactly how the checks protect against OCR mistakes.

---

## 4. Deployment timeline (session 2, 27–28 Nov 2026)

| Step | What happened | Problem hit | How it was solved |
|---|---|---|---|
| Supabase | Enabled Row Level Security on all 4 tables; confirmed the private `po-pdfs` bucket | The first query result didn't show whether the `ALTER`s ran | Checked `pg_class.relrowsecurity`: all `true` |
| GitHub | Created the public repo and pushed the existing history | The push from the tool had no way to prompt for login | Pushed from my own PowerShell, with browser sign-in through Git Credential Manager |
| Render | Docker web service, Singapore, free plan, `/health` as the health check | `DATABASE_URL` set to just the password, then with `[ ]` left in, and the password had `@`/`#` | Built the full Session-pooler URI with an alphanumeric password |
| First deploy | Live in under a minute; `/health` → database ok | Free plan sleeps after 15 idle minutes (~45 s wake-up) | Documented in the README; suggested a keep-alive ping |
| Secrets | Keys and the password were visible in my screenshots | The chat transcript would be public | Rotated all three secrets and re-checked `/health?deep=1` |
| Live tests | Every rule checked with direct API calls (section 6) | lead1's test PO reused an existing PO number, so submit was blocked | That was the duplicate guard working; gave it a new number and retested |
| Bug fix | The double-click bug, found while using the live app | Second click hit an already-locked PO | Buttons ignore repeat clicks while a request is in flight |
| Demo data | 3 new demo PDFs, tested on the live server and then cleaned up | Windows git warned it would convert PDF line endings | `.gitattributes` `*.pdf binary`; checked the bytes are identical |

---

## 5. AI mistakes caught and fixed

The AI wrote most of the code. These are real mistakes from the two sessions, and how each was caught (by me while testing, or by a review/check step before anything went live):

| What the AI got wrong | How it was caught | Fix |
|---|---|---|
| OCR with `--psm 6` dropped the labels in sample 4's boxed header grid | Ran OCR on the sample and compared the output | Switched to `--psm 4` (one column, variable sizes) |
| CSS `display:flex` overrode the HTML `hidden` attribute, so **locked POs showed edit buttons** | Browser walkthrough | `[hidden]{display:none!important}`. The server already refused those clicks, which showed why rules must live on the server |
| `query_one` used for multi-row `DELETE`s | Review and tests | Replaced with `execute` |
| Quantity sent to Postgres as text | Review and tests | Converted to `Decimal` |
| `DATABASE_URL` first set to only the password, then with `[ ]` left in, and with `@`/`#` in the password breaking the URL | Reviewing the Render settings before deploying | Full pooler URI and an alphanumeric password |
| **Double-click on Submit** showed a scary "SUBMITTED and locked" error even though the submit worked | I saw it while testing the live app | Buttons ignore repeat clicks while a request runs (`89b39d5`) |
| A PowerShell edit garbled `✓ ₹ —` characters in `po.js` | Read the diff before committing | Restored the file and re-applied the change with a safe editor |
| A new variable `once` clashed with an existing `const once` | Read the surrounding code before the change went live | Renamed it to `guarded` |
| Submission PDF heading turned the password into **PEPDEMO@2026**, which would break every reviewer login | Read the generated PDF | Moved the password out of the uppercase heading |
| README said "share link is listed" and "no code changes" after both stopped being true | Checked the README against the brief and the repo | Corrected both statements |
| Demo PDFs at risk of Windows line-ending conversion, which corrupts PDF offsets | Noticed a git CRLF warning | `.gitattributes`: `*.pdf binary`, then checked the files are byte-identical |

**The lesson I took from this:** AI output is a draft. Every change was checked by running it, reading the diff or testing the live app before it counted as done.

---

## 6. What was verified on the live app

"It works on my machine" wasn't enough. In session 2, every rule was checked against the deployed app with direct API calls (curl and PowerShell), not only through the UI:

| Check | Request | Result |
|---|---|---|
| No login | `GET /api/pos` with no cookie | **401** |
| Creator tries to approve | creator1 → `POST /approve` | **403** "Only Approvers can approve or reject" |
| lead1 approves own PO | lead1 → approve own SUBMITTED PO | **403** "You cannot approve or reject a purchase order you created" |
| Creator opens another's PO | creator2 → `GET /api/pos/1` | **404** "Purchase order not found" |
| Approver edits contents | approver1 → `PUT /api/pos/1` | **403** "Only the creator of this purchase order can change it" |
| Reject without reason | `{"reason":"  "}` | **400** "A reason is required" |
| Full cycle | submit → reject (with reason) → resubmit → approve | **4 history entries**, server timestamps |
| Second approve | approve an APPROVED PO | **409** |
| Edit locked PO | creator1 → `PUT` on an APPROVED PO | **409** "APPROVED and locked" |
| Total mismatch | submit `sample_2_mismatch` | **422** "Line items add up to ₹1,24,500.00, but the PO total says ₹1,42,500.00" |
| Duplicate PO number | upload a PDF with an existing number | "already exists", owner not revealed |
| Garbled text layer | upload `sample_4_garbled` | `extraction_method = ocr`, with a warning |
| Original PDF | `GET /api/pos/1/pdf` | **302** to a private signed link |
| Health | `/health`, `/health?deep=1` | database ok, storage ok, live commit shown |

---

## 7. Security decisions during deployment

* Turned on **Row Level Security** on all four tables, so the public Supabase API can't read them. The app connects as the owner role.
* Secret keys and the database password appeared in my screenshots, so I **rotated all three secrets** (Supabase key, DB password, `SECRET_KEY`). The ones visible in the transcript no longer work.
* Scanned the git history and the submission ZIP for secrets before submitting. Redacted my email and the dead secrets from the transcript, and said so.
* Kept `.env` out of git (checked `git status` before every push); `.env.example` lists names only.

---

## 8. UI iterations

The brief says the UI isn't scored, but it must be "clear enough to use without instructions". I went through three rounds:

1. **Original:** plain functional pages; all rules on the server.
2. **First restyle (CSS only):** shadows, coloured status pills, a history timeline. Still looked basic to me, so I asked for more.
3. **Redesign (HTML/CSS/JS only, no backend changes):** split-screen login with demo-account buttons; a dashboard with status tiles, search, tab counts and drag-and-drop upload; a two-column PO page with a progress tracker (Draft → Submitted → Approved/Rejected), a sticky actions panel, and a coloured history timeline. Every element id and API call was kept, so no rule could break. It was previewed locally with mocked data before it went live.

---

## 9. Known limitations and what I would do next

* **Real sample PDFs:** the parser was tested on look-alikes generated from the brief's descriptions, plus my own demo PDFs. The official samples drop into `samples/` and the tests prefer them.
* **Free plan:** Render sleeps after 15 idle minutes, and Supabase pauses after ~7 idle days. A keep-alive ping on `/health` solves both during review.
* **OCR** runs inside the request. Next: a background job queue, deskewing for tilted scans, and per-digit confidence to highlight doubtful numbers.
* **Not built yet:** pagination, password reset, user admin, login rate-limiting, email notifications for approvers, approval limits per approver, CSV audit export.

---

## 10. Why there are two sessions

The build chat (session 1, about 20 minutes on 27-11-2026, commits `64a3c2c`–`42ef5df`) had no access to my machine, GitHub, Render or the live URL. Deployment, live testing and fixes therefore happened in a second session with Claude Code. Its transcript is in this folder. A share link and export for session 1 could not be produced; see `README.md` in this folder.
