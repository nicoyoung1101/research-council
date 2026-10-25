# Research Council macOS client

The client is a Swift/AppKit window containing the existing WKWebView UI. It keeps the existing loopback Host/Origin/token protections. It probes application identity and the resolved data directory before loading a service; another application's occupied port is an explicit error. It does not change CLI auth or permissions.

On this Mac:

- App: `~/Applications/Research Council.app`
- Desktop shortcut: `~/Desktop/Research Council.app` (Finder hides the shortcut's `.app` extension; the actual application bundle keeps it. Apply Finder metadata to the desktop symlink only, since FinderInfo on the signed app invalidates strict signature verification)
- Persistent data: `~/Library/Application Support/Research Council/`
- Service: `local.research-council.app` on `127.0.0.1:8765`
- Original data entry: the project's `.research-council` symlink.
- Original backup: ignored `work/pre-macos-app-data/`.

Double-click the icon to start or reopen the application. There is no Terminal dependency in the user flow. Closing the app window keeps its view in memory for reopening; quitting flushes pending saves. The local discussion service continues after either, preserving automatic discussion behavior. Cmd+R refreshes; the Window menu reconnects or opens the browser; the app menu reveals data and logs. Native open/save panels handle source/backup import and blob downloads. External links go to the default browser.

## Build

Requires macOS 12+, Xcode command-line tools and Python 3.11+. The current artifact targets this Mac's Apple Silicon architecture. The app uses the installed Python interpreter and official Claude/Codex/Gemini CLIs; neither Python nor credentials are copied into the bundle.

```sh
python3 desktop/build_app.py --output 'work/Research Council.app'
```

The builder refuses an existing destination, packages an explicit allowlist, creates the existing Council-style icon, compiles Swift, ad-hoc signs and verifies the app. Builds contain no state, tests, API keys or auth files. Copy the generated bundle to `~/Applications/Research Council.app`. It is a local development build, without Developer ID notarization for distribution to other machines.

The native launcher uses launchd, logs to the data folder and disables Python bytecode writes so the signed bundle stays unchanged. It does not register a login item or expose the service beyond loopback. Existing jobs keep their persisted records and native session IDs.

## Migrate an existing checkout

First finish or cancel active research and stop its old service. The migration refuses active saved jobs and any existing destination/backup. It hashes and verifies a separate copy, moves the original to the backup, then creates a compatibility symlink. Workspace symlinks are preserved rather than followed. An interrupted copy leaves the original untouched.

```sh
python3 desktop/migrate_data.py .research-council \
  "$HOME/Library/Application Support/Research Council" \
  work/pre-macos-app-data
```

Do not rerun against another data set or overwrite an existing app/data directory. For a future app update, preserve the old bundle and data, wait for jobs to finish, stop `local.research-council.app`, install the new build, then reopen. No background updater is configured.

## Validation

`python3 -m unittest discover -s tests -q` includes exact migration/backup preservation, destination collision, active-job refusal, symlink handling and resource allowlist checks. The installed bundle's real startup was tested from a stopped service and restored both existing discussions without changing their records. After startup, verify the installed signature with:

```sh
codesign --verify --deep --strict "$HOME/Applications/Research Council.app"
```

The App icon uses a white rounded background with only the original orbital mark in dark green, without lettering. The icon generator renders exact pixel sizes independently of Retina scaling. Build 32 retains the `CouncilSymbolWhite.icns` resource so macOS can distinguish it from the earlier dark icon.

## Feedback release setup

The header feedback form is packaged in Build 28. Pass `--feedback-email` to prefill an email to the developer, or `--feedback-endpoint` for a deployed HTTPS JSON receiver (see the main README for the contract). The public source defaults to local-only feedback; configure your own recipient or HTTPS receiver when building. Feedback is saved on-device and can be copied/exported; opening the email draft never marks it as delivered. Email mode opens a draft for the user to send, with ZIP export for screenshots/long text. Direct submission needs no email application or login. Do not put mail credentials or private receiver secrets in the bundle.

Build 29 adds **Send question** beside the peer-review control, usable during a running review, and one-click copying for completed research and side-chat answers. Both controls preserve all three interface languages and themes.

Build 30 shows real per-model CLI activity beside focused questions and the active research call, makes pause reasons visible near the composer, and queues consecutive questions across reloads.

Build 31 makes Pause cancel active discussion/question CLI calls and hold queued questions across reload. Continue retries only members without committed answers. Interrupted experiments retain file changes and require a new review/approval before another execution; Continue never replays them.

Build 32 prioritizes the latest shared question, stops an obsolete review, and binds answers and plan reviews to their task. Question references, grouped replies and a current-question header prevent interleaved answers from appearing to continue an older request. Existing research text, prior plans and native sessions are retained.

Build 33 completes the current peer-review round before pausing on a member’s request for user input. Explicit Next speaker and individual questions remain available. It also prevents inherited agreement from skipping a reviewer in a new round. Execution still requires separate approval.

Build 34 keeps pending reviews beneath their actual question and labels their source while the model is working. Legacy frontend-only questions return to their chronological positions; their text remains intact.

Build 35 advances Next speaker after the last published reviewer across round boundaries, avoiding consecutive calls to the same member. Cancelled calls do not advance the sequence. The button tooltip previews the next member in all three languages.

Build 36 lets Next speaker submit the current text, quotations and images to the scheduled member. Drafts clear only after acceptance, and failed submissions can be retried. Empty Send continues an existing discussion; a blank new discussion still requires input.

Build 37 separates unpausing from starting a call. Continue only unlocks the controls and keeps the queue held across reload. Next speaker then calls the original unfinished member once; explicit Send can release queued questions. Returned peer answers are retained, and experiments are never replayed by unpausing.

Build 38 adds a recipient selector to peer review. Selecting one member makes a single public native review; Next speaker calls the other member with the full published question and answer. All-member review retains one-round/automatic scheduling. Selecting one reviewer never changes an ordinary targeted question into a public message.

Build 39 adds on-demand main-discussion and local-source access to side chats, full-discussion opt-in, editable read-only source scope, progress/read receipts, bounded model calls and accumulated token usage. The application read layer is bundled in side_context.py; the restricted CLI permissions remain unchanged. A real Gemini check used only generated temporary source text.

Build 40 preserves unexecuted plan candidates across follow-up questions, invalidates old approvals, and recovers legacy candidates without replaying attempted tasks. The composer offers plan preparation and an editable final execution confirmation with required decisions for every objection or missing review. Human-confirmed tasks retain peer objections and the exact approved plan/decisions for both executor and verifier. Preparation and opening confirmation do not start experiments.

Build 41 removes application duration limits from native execution and verification, records experiment time separately from the discussion budget, and adds durable live tool/output activity to experiment cards. Output updates from actual CLI events; Pause and restart recovery retain their existing behavior. The execution_progress.py helper is included in the bundle.

Build 42 adds explicit continuation of the latest failed/interrupted approved experiment. It preserves the frozen plan, human decisions and original executor/verifier, inspects saved progress and records a linked new attempt. Short continue instructions in execution mode dispatch this recovery rather than a preparation review. Unpause remains a separate action and does not restart work.

Build 43 adds persisted incremental public-context delivery for Claude/Codex, per-member filtered local reference records, one-time historical image attachment, and clean checkpoints for legacy/large native contexts. It preserves old CLI session IDs and research audits, makes no summarization calls, and retains exact execution authority. The context_sync.py helper is included in the bundle.

Build 44 gives the composer one primary action, hides discussion advancement in experiment mode and replaces active experiment action buttons with plain member/phase status. Permanent and hover descriptions clarify preparation versus execution. This is a UI-only update and can be applied without restarting the service or active native calls.

Build 45 removes the redundant secondary Send question button from peer review. The selected composer action determines the single send button’s behavior, with a persistent explanation in all discussion modes. Switching to an ordinary question preserves the draft and works during a review. This remains a UI-only update.


Build 47 displays experiment decision pauses as localized requests for a host decision, with the full detail retained in the task card. Real CLI and connection errors keep their error messages. Existing saved controller error codes remain supported; this build does not migrate the backend status protocol.


Build 48 lists experiment tasks in creation order, opens the experiment view at the newest task, and enables View latest through the shared conversation scroll controller. This changes presentation only; it does not resume experiments or call models.
