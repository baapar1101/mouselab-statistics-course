# Notebook CI and safe deployment

Source: `baapar1101/mouselab-statistics-course`, branch `main`, notebook
`MouseLab_Complete_81_Colab.ipynb`.

1. A push changing that notebook, `ci/**` or the workflow triggers GitHub Actions.
   Pull requests also execute and validate, but cannot publish. Manual Run workflow
   is available. No notebook execution runs on the web server.
2. A disposable Python 3.12 runner with pinned packages clears all saved outputs
   and executes every code cell top-to-bottom, stopping at the first error.
   It checks the two existing reference-assertion cells, sequential execution,
   81 lesson IDs/order, 81 exercises, per-lesson figure coverage, current-result
   interpretations, stderr/errors, and PNG decoding, dimensions and nonblankness.
   Source code and Markdown must remain identical to the submitted notebook.
   Eight negative tests exercise rejection of broken results.
3. A separate runner rechecks the execution artifact WITHOUT running Python from
   the notebook. Only this job has repository-write permission. A newer `main`
   supersedes older jobs. The job writes the executed notebook, validation report
   and release manifest to `published`, using non-forced Git ref updates.
4. A restricted `mouselab-release` system account checks that public branch every
   60 seconds (plus up to 5 seconds jitter and network/download time). It confirms
   the GitHub workflow completed successfully on `main`, checks provenance,
   checksum and coverage, then stores an immutable release directory. The final
   `notebook-live/release.json` pointer is replaced atomically. Prior releases stay
   available. Failed checks/downloads leave the active pointer unchanged.
5. Both website and viewer read that pointer, load its exact immutable GitHub
   notebook, require its SHA-256, and bind Colab/download links to that same release.
   If GitHub cannot be reached, the byte-identical local immutable file is used.
   An absent/invalid release manifest fails closed; raw `main` is never displayed.

The pipeline uses no server SSH key, GitHub PAT, or inbound webhook. No additional
port is exposed. Only temporary GitHub job tokens are used for promotion. Notebook
execution gets no write token, persisted checkout credentials or deployment secret.
Workflow actions are pinned to reviewed commit SHAs. The pull service cannot write
the website's application scripts or execute the submitted notebook.

Operations:

```text
systemctl status mouselab-notebook-release.timer
journalctl -u mouselab-notebook-release.service -n 30 --no-pager
systemctl start mouselab-notebook-release.service
```

Failures appear in GitHub Actions, with a failed-notebook artifact when execution
started. Server transfer failures appear in the journal and retry on the next tick.
To drill the gate, run the workflow manually with `exercise_failure_gate=true`:
it injects an intentional error into the runner copy only and must NOT publish.
Then run normally to restore a green latest workflow status.

Editing a private Drive/Colab copy does not trigger CI. Save to this GitHub `main`
path. Colab opens the immutable last verified release; edit a Drive copy and commit
back to `main` to publish changes. Already-open visible website/viewer tabs poll
only the small active manifest every 30 seconds; the full notebook downloads only
when its verified release identity changes. No navigation or page reload occurs.
The DOM swap captures the visible content anchor, expanded code, horizontal code
scrolling, focus and sidebar position. Search text/caret and progress are retained.
The current lesson stays pinned if it would disappear from an active search;
that update waits until the query changes. Presentation, print and text selection
defer application; after finishing, the manifest is rechecked before the newest
candidate is applied. Hidden/offline tabs pause network checks and recheck on
return. Failures retain the current page and retry with bounded backoff. Offline
downloaded HTML and archived notebooks remain explicitly static.

Limits: automated checks are not a human scientific review of arbitrary new claims
or a guarantee of plot label layout. Reference assertions are intentionally pinned
in `ci/contract.json`; intentional dataset/lesson-order changes need a deliberate
contract/site review. Existing text/examples are not regenerated or removed by CI.
The standalone downloadable HTML remains a clearly labelled offline snapshot.

## Verified publication history

The pull agent also maintains `notebook-live/history.json`, newest first. It walks
the reachable `published` commit history (including intermediate releases skipped
between timer ticks), checks each successful workflow and notebook contract, and
stores the exact notebook, validation report, `release.json` and `changes.json`
in its immutable per-commit directory. No notebook code runs on the server.
Backfill saves progress atomically after each complete version and resumes after
a network error. A file lock serializes manual and timer runs. A failed backfill
never changes the active release pointer; no-op ticks do not redownload notebooks.

Changelogs compare stable lesson IDs, code, narrative/exercises, displayed text /
tables and PNG bytes. Execution counters/timing/output metadata are ignored and
adjacent stdout chunks are normalized. Shared setup, datasets and validation
code are tracked separately. A PNG byte difference is not a scientific claim.

Both pages have an isolated history dialog with an independent lesson selector,
previous-version preview, side-by-side saved outputs and bounded line diff.
Old versions use the same immutable-URL and SHA-256 checks as the live course.
Download / Colab links inside the dialog open the selected version only; the
underlying page links, query/caret, lesson, progress and code state remain intact.
Live updates are queued while history or presentation is open and rechecked on
close. History selections are frozen until explicit refresh. Archived standalone
notebooks and the offline HTML do not acquire a live history dependency.

To roll back, stop the timer and atomically restore the saved previous
`notebook-live/release.json` after verifying its immutable directory. Re-enable the
timer only when the upstream `published` branch points to the desired release;
otherwise the next check will install the newer successful release again.
