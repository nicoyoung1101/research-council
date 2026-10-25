# Detailed development notes

These implementation notes describe the local v0.11 / Build 48 development snapshot. For a short introduction and portable setup, see the [project README](../README.md).

# Research Council — Local CLI Preview v0.11

**Existing v0.9 GUI with a local Python orchestration service. Light/Dark/System and 中文 / 日本語 / English retained. Demo mode remains available; Live CLI mode calls the official Claude Code, Codex and Google Antigravity CLI executables (Gemini).**

## macOS app

On the development Mac, double-click **Research Council** on the Desktop, or open `~/Applications/Research Council.app`. It opens a native window and starts/reuses the loopback service automatically; no Terminal window is needed. The desktop shortcut points to the installed app. The original GUI, membership login and saved discussions are retained.

Data is stored outside the app in `~/Library/Application Support/Research Council/`. The original project's `.research-council` is a compatibility symlink, and the pre-migration copy is preserved under ignored `work/pre-macos-app-data/`. Updating/removing the app bundle does not remove discussions. The app menu can reveal data/logs and open the normal browser UI. Closing the window or quitting the app leaves the already-started local service running, so background discussions can finish.

This local build uses the existing Python 3.11+ and installed membership CLIs on this Mac. It does not bundle credentials or Python, and is not a notarized distribution for other computers. Swift/Cocoa/WebKit build and migration instructions are in [desktop/README.md](../desktop/README.md).

## v0.11: running locally

1. Double-click `start_mac.command`, or run `python3 bridge.py` in this directory. Python 3.11+ is sufficient; no production npm packages are required.
2. Open `http://127.0.0.1:8765/index.html`. Keep the Terminal window open. A busy port reports an error; it does not silently change the storage origin. For a different port, use `python3 bridge.py --port 8766`.
3. Open **Agents & Models**, check CLI status, and choose **Live CLI** under Execution source. Save the configuration. Existing sessions remain in Demo until explicitly switched.
4. Each enabled debater and Context Agent must use an installed, subscription-authenticated Claude/Codex/Gemini client. Sign in with `claude auth login --claudeai` and `codex login` as needed. API-key billing is not used by this bridge. The service never copies auth files.
5. Pick **Use CLI default** or an exact model you know your account can access. Existing candidate model IDs are retained as unverified references, not a discovered entitlement list. Invalid models/efforts fail visibly; no fallback model is configured.
6. New discussions default to **Native CLI** and **Dynamic discussion**. Choose Live CLI to call real agents. Existing discussions retain their frozen configuration; changing profile/protocol archives the previous run. Manual **Next speaker** calls exactly one debater. The main control runs the remaining independent answers or one sequential review round; Automatic continues until unanimous approval, a blocker needing the user, stagnation, cancellation or a budget limit. Generate a current summary explicitly when needed; optional automatic Scribe still follows that summary.

The installed CLI paths are found via PATH, common macOS locations and ChatGPT.app's bundled Codex CLI. Override discovery with `RC_CLAUDE_PATH` / `RC_CODEX_PATH` / `RC_GEMINI_PATH` if necessary. Overrides name executables, not shell command strings.


## Choose an action when sending

The composer offers **Independent answers / Peer review / Ask a question**, with a separate **Experiment task** entry. The selection is saved per discussion. A new dynamic discussion defaults to Independent answers; existing conversations keep ordinary focused questions as their initial choice. Legacy fixed discussions retain their existing controls until an action is explicitly selected. Unsent message drafts are saved separately and survive reloads. Choose **Ask a question** to ask the selected members without starting a review round. Switching between it and **Peer review** preserves the unsent draft. Questions to one member remain private to that member; questions to all members become the shared focus. **Start review / Send and review** retain the sequential review control. Consecutive focused questions enter a visible, cancellable local queue. Each sends automatically after the preceding question finishes, including after reload. Imported copies never auto-send the original queue; they require explicit retry. Failed sends remain visible with retry controls.

- **Independent answers** ends after the selected members answer. Later independent requests use a fresh native session identity, attached originals and user input, excluding prior agent transcripts. Earlier published answers remain in the record. Native CLI filesystem access still follows local policy; this is prompt/session separation, not OS filesystem isolation.
- **Peer review** reads the published record and current input. Choose **All models** for **One round / Continue automatically**, or select a member for exactly one native review call, even if automatic scheduling was previously selected. The targeted question and reply remain public to every debater. **Next speaker** then calls the other member and can carry a fresh follow-up, quotes or images; the recipient selector does not override this turn order. Empty targeted Send reviews the current question once. Repeated follow-ups to the same selected member are supported. A single review cannot establish unanimous approval. Review can start directly without forcing an initial independent round.
- **Experiment task** opens plan confirmation, running progress or an explicit continuation. Experiment actions live outside the question composer; an existing plan does not need another preparation round.
- **Ask a question** preserves the restricted explanatory lane and selected recipients, including questions during an active experiment.

## Copying and quoted references

Drag to select answer text and press **⌘C**, or use **Copy** in the selection toolbar. Reading selections are retained while background job polling updates the interface. **Add to main chat**, reply quotes, and side-chat quotes create removable reference cards above the composer instead of inserting Markdown into the editable question. Expand a card to inspect the exact excerpt. Up to eight 16,000-character references are saved with the draft, sent separately with the question, and retained in message history; removing a draft reference does not send it.

Selecting **Side chat** now defaults to the source member's exact provider, requested model, reasoning effort and custom rules, with the selected excerpt and original answer attached. The interface identifies the source and allows switching models or returning to **Use source agent**. Existing side chats with a uniquely matching source answer can recover their source metadata without replacing their chosen model or deleting messages. Very long original answers are explicitly marked when clipped to 60,000 characters. **Text selection also works inside side-chat replies**: Copy, Add to main chat, Ask here, or New side chat. Ask here attaches a removable reference without changing the typed question, preserves the answer author’s model/effort/rules when available, and sends the selected passage plus its source answer with the follow-up. Draft references survive reload and transport failure; sent references remain attached to their messages. A new branch retains its parent chat and source answer. Source text longer than 24,000 characters is explicitly marked when clipped for an in-place follow-up. Side chats have web search enabled by default, with no per-chat checkbox; agents decide whether a question needs a search. Side chats remain separate, restricted explanatory sessions; they do not resume the main native CLI session or gain access to its hidden reasoning. Their history remains scrollable and resizable.

Side chats can now search the entire host-visible main discussion and read project/attached text sources **on demand**. The initial input contains the original excerpt, a brief catalog and recent background, not the full transcript. **Load full main discussion** explicitly includes its text (up to 180,000 characters; larger discussions require on-demand search). **Source scope** shows the default discussion workspace, controls local-source access, and accepts up to four extra absolute directory paths. Only documents attached to this discussion enter the source library; unrelated discussions and other side chats do not. Host-visible targeted questions can be retrieved as part of that chosen main discussion, separately from the debaters' recipient-filtered prompts.

Source access is implemented by an application-mediated read loop, not extra shell or native CLI privileges. Claude, Codex and Gemini use the same bounded protocol to request discussion searches, message line ranges, file searches or file line ranges. Directory-descriptor traversal rejects symlink escapes. Text/code files are supported; hidden files, known credential paths and dependency folders are excluded, while PDF/Word/image content needs imported extracted text. Searches are bounded and explicitly non-exhaustive; reads retain source IDs, exact returned text, line numbers, timestamps and content hashes. The discussion snapshot is refreshed on each side question; files are read at lookup time. This neither resumes nor changes the main research controller.

Each side answer has a **Discussion and local source read log**, including unsuccessful reads, lookup excerpts and the model-call count. The same records remain inspectable during a call and after cancellation, and persist across reload. The model is instructed to cite source IDs/lines and distinguish peer claims, file evidence and interpretation; a read receipt alone is not proof of independent verification. Up to four lookup rounds plus a final response (five model calls maximum), a 180-second total CLI budget, bounded search/read sizes and an input-character cap contain the overhead. Token usage is accumulated across these calls while the context indicator remains the latest CLI sample. A disposable real Gemini smoke check read an unknown generated sentinel from a temporary Markdown file and returned the exact line with a source citation in two model calls. No user research files were used in that check.

## Live experiment activity and duration

Native experiment execution and independent verification have **no application time limit**. The former 10-minute native-call deadline and discussion wall-time cancellation do not apply to these two operations. Discussion, question and side-chat limits remain unchanged. A completed, failed or manually interrupted experiment records its own elapsed duration without using later discussion time. The app does not override a tool, remote service or training script's own timeout/failure policy.

The experiment card shows the executor/verifier, current real tool and command, elapsed time, last update, public model progress statements, recent steps and returned command output. Codex command-output deltas stream before command completion. Claude tool-result text and supported task notifications update when its CLI returns them; its internal tool stdout is not synthesized. Execution prompts ask agents to use unbuffered output and background/poll tools for long work, and to expose measured log tails or checkpoints periodically. No extra monitoring model calls or invented percentages are used. Silence is labelled as waiting for new CLI activity, not proof of failure.

Progress is persisted in the job record with bounded tool history and the most recent 18,000 output characters. The same output is visible in the main record and Experiments view, selectable/copyable and scrollable without forcing a reader back to the end. Completed, interrupted and failed task logs remain available after reload. Old task activity can be reconstructed from its existing tool events without rewriting historical jobs. Output is escaped as text and no hidden reasoning events are displayed.

**Pause** still cancels active native calls and retains received progress and file changes. Unpausing does not replay an interrupted experiment. **Continue this experiment** is a separate explicit action: it starts the original executor and verifier against the same frozen approved plan, checks saved progress and resumes unfinished work. A short “continue” message in experiment mode uses this action instead of preparing another plan. New requirements still use plan confirmation. Each attempt has its own record linked to its predecessor, and idempotent retries cannot start duplicate attempts. Later malformed review receipts remain in the audit and do not invalidate a separately approved frozen experiment. An app/service restart interrupts active native work and requires explicit recovery; removing duration limits does not imply a background task can survive a service restart.

## Remembering Claude tool permissions

Native Claude calls now default to **Auto** (`--permission-mode auto`), using the installed CLI's own tool review rather than bypassing checks. **CLI tools and sessions → Claude tool approval** can switch to Manual; the choice applies on the next call without clearing published answers. Initialization verifies the actual mode before submitting a user turn. If Auto is unavailable, the call stops with an explicit error instead of silently falling back to repeated manual prompts. Explicit confirmation rules and questions can still require a response. See [Claude permission modes](https://code.claude.com/docs/en/permission-modes).

Claude approval cards offer **Allow once**, **Remember rule for this discussion**, and, when the CLI proposes a local rule, **Save in current working directory**. The exact matching rules are previewed before selection. Only additive suggestions for the requested tool are offered; question forms and requests that suppress persistent approval are not remembered. This follows [Claude's native permission-update protocol](https://code.claude.com/docs/en/agent-sdk/user-input).

Discussion rules are saved with that member's native session and reapplied with `--allowedTools` when the CLI resumes in later rounds. They do not apply to other discussions, members, or imported copies. **CLI tools and sessions → Clear remembered discussion permissions** removes them for subsequent calls; a running CLI keeps its existing rules until its next invocation. Directory rules use Claude's `.claude/settings.local.json` and are managed through normal Claude settings. Other tools and unmatched actions still follow the local CLI's permission policy. An agent blocked on approval shows **Awaiting permission**. Active native calls distinguish local tools, web searches, and answer preparation, with elapsed time. A completed peer answer displays immediately while another agent waits. Transient status-poll failures reconnect automatically with bounded retries and a visible error if recovery fails. These are tool activity indicators, not private reasoning traces.

Codex has a separate **Agents & Models → CLI tools and sessions → Codex permissions** control. **Read-only sandbox · ask as needed** keeps interactive escalation; **Full access · no command approvals** explicitly requests `danger-full-access` plus `never` for native thread start/resume and each turn. The returned effective thread policy is verified before sending the prompt; a rejected selection stops with an actionable error rather than silently continuing in a different mode. Saved answers and native session IDs are retained when switching modes. The selection applies on the next call in that discussion, does not edit global Codex configuration, and is not inherited by a new discussion. It does not expand restricted ordinary-question/side-chat utilities or remove Research Council's experiment-plan confirmation, managed-process launch approval, or questions that need a human answer. Old requests without this field retain their inherited CLI policy. See [official OpenAI sandbox guidance](https://learn.chatgpt.com/docs/sandboxing).

## Native Claude/Codex and dynamic discussion

**Agents & Models** now includes a collapsible **CLI tools and sessions** section for the CLI profile, stopping condition, workspace and call/time budgets. The agent list and rules remain scrollable with the controls pinned. Newly created discussions use a persistent independent workspace under `.research-council/workspaces/<run-id>/`; an existing absolute project directory can be selected before starting. The resolved directory appears in the discussion. This is a working directory, not a filesystem security boundary: actual access follows the installed CLI policy and approvals.

- **Native CLI** uses Codex **App Server over stdio** and Claude Code **stream-json control protocol** with saved membership login. It keeps the clients' configuration, native tools, local rules/skills, MCP configuration and permission policies. It does not add skip-permission flags or force full filesystem access. Shell, file operations and web tools are available according to those policies. A connector still needs its own native authorization. Desktop-only UI features are not emulated.
- Every run/agent/role has its own exact native session ID, saved locally and resumed for later turns. No global `--continue` or `--last` is used. Independent prompts exclude peer messages and instruct agents not to inspect private peer workspaces/session files. Native mode does not enforce cross-agent filesystem isolation; use Restricted mode where tool-level isolation is needed.
- Native command/file/permission requests, Claude tool approvals, user questions and Codex MCP elicitation are shown in the feed. Decisions are bound to one job and request, accepted once, and audited. Native clients can pre-authorize operations through their saved policies. Cancelling or restarting expires unresolved requests. Unknown protocol requests fail explicitly. Waiting for a human pauses the per-call generation timeout; the discussion's overall elapsed-time budget still applies.
- **Restricted research tools** remains available. Legacy sessions keep it. Its Codex/Claude tool limits and ephemeral calls are unchanged. Tool checkboxes apply to this profile and Gemini; Scribe's Update notes checkbox still gates app note proposals. **Gemini retains its existing research-only guard**, even in a discussion whose Claude/Codex instances use Native CLI.

Dynamic discussion uses independent answers followed by **sequential** peer review in continuous member order. Every reviewer sees all previously published replies, including the immediately preceding speaker. Each reply ends with a machine-readable control receipt, removed from the reading view but retained in the audit. The controller validates its per-call nonce, decision, plan reference and blocker list. It never infers approval from phrases such as “I agree”.

Normal Send, one-round review and automatic review complete all participating debaters in the current round before pausing for an agent’s `need_user` receipt or declaring agreement. The next reviewer can assess the first member’s proposed questions and objections. This does not authorize experiment execution. Explicit **Next speaker** continues after the last published reviewer, including across round boundaries; its tooltip identifies the scheduled member. Cancelled calls do not advance the sequence, and pause/reload preserve the next member. With a composer draft, Next speaker sends the text, selected quotations and images to that scheduled member as the current question, including while paused; other members are not called. The draft clears only after acceptance and remains available on failure. With no draft, Next speaker retains its ordinary one-member continuation. Empty Send continues an existing discussion without creating an empty question; a new blank discussion still needs an initial question or source. A new question starts a new sequence. **Next speaker** and a selected individual recipient retain their single-member behavior; user pause, native permission requests, errors and budgets can still interrupt a round.

A proposal contains complete plan text and testable acceptance criteria. New questions retain an unexecuted candidate and its author-owned objections as background, while invalidating prior approvals and identifying the earlier question. Changing the question never inherits agreement. Older records whose candidate was cleared can recover their latest unattempted proposal; completed, failed or interrupted experiment plans are not offered for replay.

**Experiment task** is separate from the shared conversation composer. The composer always uses **Send**; its strategy chooses ordinary questions, independent answers or peer review, with individual recipients and Next speaker retained. Experiment confirmation never consumes unsent questions, quotations or images. An existing candidate goes directly to an editable Markdown preview and acceptance checklist without another planning call. If no candidate exists, **Prepare plan from discussion** explicitly requests a bounded plan without running it. The selected executor and verifier receive one frozen plan. Missing peer reviews go to independent preflight without mandatory user instructions; stale confirmation tokens and incomplete plans block launch. Genuine decisions outside the approved scope remain blocked.

New tasks use durable, nonce-bound stage receipts: executor → checkpoint review → executor continuation → final verification. A required review gate stops the executor before the gated operation; the controller passes it to the chosen independent verifier, then continues the same approved scope. A final verifier receipt must explicitly pass every acceptance criterion with evidence. Missing/malformed receipts, failures, changed assumptions, open user decisions or repeated unchanged checkpoints stop the workflow. Only an explicit human continuation can restart it; scope changes require a new confirmed plan. Long processes remain bridge-owned and their waits do not keep a model inferring.

The task card shows the responsible member, current step, stage observations and next action. Pause/restart recovery merges already committed handoffs exactly once and resumes the unfinished role. A blocked reviewer is re-invoked as reviewer after a user decision; it is not skipped. Older `reviewed` records mean only that two calls returned, so they display **completion unconfirmed** and offer **Verify and continue** with optional context; the original verifier first checks saved artifacts before requesting any remaining execution. An unchanged or unresolved scientific/external-permission issue still stops the task. New candidates take precedence over old resumable work; continuing an older task is a separate explicit choice. Only a fully checked task can show **All acceptance criteria passed**. On completion the composer returns to questions. **Discuss results** prepares a referenced follow-up for the user to send; it makes no automatic discussion call.

Legacy composer **Continue experiment** buttons now open the same **Verify and continue** dialog as the task entry; they never submit the obsolete resume request directly. A resumable task no longer shows a contradictory missing-plan message.

The task confirmation assigns both members automatically; no separate model instructions are required. Missing reviews and unresolved recorded issues go to an independent preflight before execution. The preflight must return evidence for every issue; substantive scientific, acceptance or external-permission decisions remain blocked. The optional **Allow verification helper repairs** setting permits at most two narrow auxiliary-code corrections across a task and its continuations. Only an existing workspace helper can be proposed; its original hash is checked before the next call. The verifier must preserve original scripts and reports, use new evidence files, and cannot change scientific settings, loosen tolerances or rerun training/inference/statistics. The host routes that correction to the same verifier. `verification_paths.report_hash` resolves annotated Markdown hash paths against explicit roots, rejecting missing or ambiguous files rather than silently skipping them. Task approval remains required and native permissions are unchanged.

Active experiment identity and observable progress remain visible above the shared composer in every message mode. The compact status names the current executor/verifier; a persistent strip adds the selected model, actual tool target, public progress, elapsed call time and an explicit no-new-activity state. Independent verification describes its evidence/criteria method and links to the existing task logs. The strip excludes machine handoff blocks, ignores unrelated concurrent question calls and clears when the task stops. This UI does not add model calls or expose private reasoning. Codex progress distinguishes the actual acknowledged call policy from the next-call setting. Native policy acknowledgements persist separately from the bounded event history; missing acknowledgements remain unknown. Legacy sessions without a local permission field preserve the controller setting instead of silently reverting full access to read-only. New discussions keep their existing default.

Completed, cancelled and failed activity cards freeze elapsed time at their recorded end (or the saved final update for historical jobs), including individual members that finish before a peer. Reload retains those timestamps; terminal cards show the end time rather than a growing last-update age.

All-enabled-member **ready** receipts for the exact hash still identify peer unanimity. Human-confirmed execution is a separate, explicit path; it never fabricates those receipts or clears peer objections. Task audit records preserve original reviews/blockers, user resolutions, candidate hash and whether the plan was edited. Both roles receive the same frozen plan and resolutions. Native permissions remain in force; user decisions cannot grant missing external/data rights. Per-claim source tracking remains separate.

The backend persists scheduling, plans, receipts, pending calls and results, so automatic discussion continues after closing/reloading the browser. A service restart pauses it for explicit recovery rather than silently spending quota. Default budgets are 40 agent calls (including Context) and 3,600 active discussion seconds. Native execution and verification have no application duration limit and do not consume the discussion time budget; their duration is recorded separately. Discussion call-count limits still apply to discussion; approved native execution/verification are not stopped by that limit. Native tool policy, explicit Pause and service-restart recovery still apply. Repeated unchanged rounds pause as stagnation; reaching a budget pauses and offers an explicit extension. Neither state counts as consensus. A queued moderator addition is applied after the current call, before another reviewer is scheduled. Imported/recovered copies preserve the record but must restart independently before making calls, so they cannot resume another discussion's native sessions.

## Continuous research, adaptive discussion and experiments

**Research log / Experiments** are two views of one ongoing research, with the main composer always available. Ideas, criticism, evidence checking, result interpretation and planning can alternate or coexist. The default is **Adaptive discussion**; optional criticism/idea/evidence preferences live in the collapsible CLI settings and new-discussion advanced options. They guide emphasis without forcing a stage. Agents may report several focus tags and a short explanation inside their normal review receipt; this adds no classification-model call. Missing tags remain labelled Adaptive, rather than inferred as an actual tool action.

**Confirm execution plan** sends the exact human-confirmed plan to one native Claude/Codex executor, then another native instance independently verifies it. Each experiment has its own durable card, frozen plan/hash, status, returned reports and job links. Native tool approvals still apply. Results return to the chronological research log; the composer stops after verification so you can inspect results before the next discussion. The next experiment always needs a new candidate and explicit human execution confirmation. A returned verification report is not itself a passing verdict.

Normal messages after the initial answers ask the selected agent(s) a focused question. They use a separate **restricted, non-executing question lane**, with published research, current plan and returned experiment results as context. Questions can run while an experiment continues; they do not change its frozen plan or acquire the executing agents' native write permissions. Questions and answers remain in the main log and become context for later reviews. Their agent calls count against the discussion call budget. Pending questions prevent a new execution approval; completed questions invalidate future plan reviews. Targeted questions and answers are filtered from other agents' prompts. Use **Add to future context** for explicit new research conditions: during execution these queue for the next review, while verification still checks the originally approved plan. Side chats remain available for selected result text in either view.

A completed experiment is not a completed research. Continue can reopen an approved plan for review, discuss partial/failed results or plan another experiment in the same discussion. Continuing or asking about a completed legacy fixed-round discussion adopts its published answers as reference history, without rerunning independent answers or treating old text as execution approval. Existing fixed-run records, notes and frozen CLI profile stay preserved. Demo execution remains a labelled simulation; in Live mode the Experiments view shows real task records rather than the old Work simulation.

Reload restores task/question status. Restart interrupts active experiments and returns them to review, preserving partial results without silently rerunning commands. Imported copies retain result cards but detach active calls and approvals; they cannot cancel or resume the source research's tasks.

The original fixed three-round scheduler, Demo flow, themes, languages, rules, Context, Scribe, notes and claim tracking remain available. Changing the profile or protocol archives the previous displayed run; it does not delete old records.

Official protocol references: [Codex App Server](https://learn.chatgpt.com/docs/app-server), [Claude Code headless CLI](https://code.claude.com/docs/en/headless), [Claude control-protocol reference implementation](https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/_internal/query.py). The bridge invokes the installed official CLIs; it does not offer an SDK API-key or subscription-token relay.

## Gemini membership login

On this Mac, Gemini runs through Google's official **Antigravity CLI (`agy` 1.4.2)** with saved Google OAuth login. The older Gemini CLI returned `UNSUPPORTED_CLIENT` for this personal account and directed it to Antigravity. Research Council invokes the supported executable; it never extracts OAuth tokens or calls an undocumented Google backend.

1. Install the official CLI using [Google's installation instructions](https://antigravity.google/docs/install?tab=cli). Research Council first checks `~/.local/bin/agy`; `RC_GEMINI_PATH` can select another official executable.
2. Double-click `login_gemini_mac.command`, complete Google login and any account verification in the browser, then return to Research Council. Login codes belong in the official login flow; no key is entered in this GUI.
3. Open **Agents & Models** using the sidebar or the model icons below the research question. Check CLI status. It shows **Gemini · Antigravity CLI**, login status and account-visible Gemini model IDs from `agy models`.
4. Add an agent or change the provider of Context/Scribe to **Gemini**. Select **Account-available Gemini (prefer Medium)** or an exact listed model, save, and use Live CLI. On this account the tested model is `gemini-3.8-flash-medium`. High/Medium/Low variants are distinct model IDs; the effort selector stays at CLI default. An explicit invalid model fails visibly.

Status checks request account metadata without making a model call. They do not prove generation quota or eligibility; those errors appear on the real call. Inherited API keys and gateway overrides are removed. API-provider settings and optional AI-credit overage are rejected, so these calls use account login rather than an API-key fallback. Membership limits remain subject to the account's plan and Google's quotas.

Each call gets its own immutable research-agent definition and temporary workspace. Only `finish` is permitted by default. Enabling **Web search** additionally permits `search_web`, `read_url_content`, and `view_file` restricted to `content.md` generated by this same conversation’s completed web-tool steps. Other conversations, credential files, transcripts, unrelated local files, private-network URLs, shell commands, interactive browser actions, MCP, scheduling and delegation remain blocked. Public-web cache content (up to 50,000 characters per tool result) is retained in the job audit when available; missing native output is explicitly marked. User-imported text is supplied in the shared evidence packet. Antigravity's `init.tools` event lists the full CLI catalog even when the custom agent restricts the model; the bridge therefore verifies the active execution hook instead of treating the catalog as the effective tool scope. Native tool errors remain visible and are not counted as successful searches. Missing hooks and incomplete terminal results fail explicitly.

Independent answers cannot see peer answers. During dynamic debate, Gemini receives all published replies up to its turn. The preserved fixed-round scheduler uses a frozen transcript for agents called together. Editable rules, notes, cancellation, claim quote validation, three languages and all themes use the existing flow.

Official references: [Google migration guidance](https://antigravity.google/docs/cli/gcli-migration/), [headless CLI](https://antigravity.google/docs/cli/headless/), [custom agents](https://antigravity.google/docs/subagents/), [execution hooks](https://antigravity.google/docs/hooks/), [AI-credit setting](https://antigravity.google/docs/settings?tab=cli).

## Experiment and discussion controls

The composer has one stable **Send** action. Its strategy selector controls ordinary questions, independent answers or peer review, and recipient selection controls who answers. Switching strategies preserves unsent text, selected quotes, images and recipient, and never starts a model call. Questions remain available during review or execution. The header’s **Experiment task** entry handles plan confirmation, progress and continuation separately. The legacy execution-mode adapter remains hidden for old integrations; persisted visible execution mode migrates to ordinary questions. Discussion advance/next-speaker controls never start or resume an experiment.

## Native context delivery

Claude and Codex keep their own persistent native sessions (`--resume` and `thread/resume` + `turn/start`). The bridge sends a filtered public bootstrap once, then only newly published or changed messages and evidence. It strips nested result/usage copies, avoids reinjecting the member’s own published answer, and attaches historical images only once per native session (explicit current images can be attached again). The current task and exact execution plan/human decisions remain present on every execution/verification call.

A complete per-member filtered public reference record is saved in the workspace’s `.council-context/` directory. Long discussion excerpts and old recovery logs link to that record for native on-demand reading; original discussion data and job audits are preserved. Delivery checkpoints advance only after successful native completion, survive service restart, and are serialized per member. Failed/cancelled calls cannot silently skip undelivered context. Independent questions start a fresh native context after peer discussion.

Old sessions that accumulated repeated full histories are preserved by ID and replaced on their next explicit call, with a clean public bootstrap. A completed session at 120,000 context tokens (or 70% of a smaller reported window) is similarly checkpointed before the next call. Native private tool history stays in the archived CLI session; research files, exact execution authority, published messages, permissions, and the complete local public record remain available. This does not make a model call to summarize the old context or change the chosen model/effort.

The job audit records actual delivered prompt size, baseline size and delivery mode. These are input-character measurements, not billed-token or subscription-percentage estimates. Native caching/compaction and provider accounting still apply. UI activity updates consume no extra inference; execution prompts favor quiet background waits and meaningful milestones over repeated unchanged log polling. This adds no automatic restarts, reviews or scheduled calls.

References: [Codex App Server](https://learn.chatgpt.com/docs/app-server), [Claude Code programmatic sessions](https://code.claude.com/docs/en/headless), [Claude Code context/cost guidance](https://code.claude.com/docs/en/costs).

## Model-specific reasoning effort

The Agent settings page reads model metadata from the installed clients: Codex `model/list` and Claude's SDK initialization model list. These metadata requests do not start an inference turn. Results are cached for ten minutes and invalidated when the CLI binary changes; no account or credential fields are returned. The model list describes CLI capabilities, not a guarantee of subscription entitlement. Existing candidate/custom model IDs remain available.

Effort choices come from the selected model's returned metadata, including alias-to-exact-ID matching for Claude. For example, this Mac's Codex reports `low / medium / high / xhigh / max / ultra` for GPT-6.1 Sol, but no `ultra` for Luna. Claude reports `low / medium / high / xhigh / max` for Opus 5.5 and Sonnet 5; Haiku has no separate effort selector. These are observed CLI results, not hardcoded universal ranges. Gemini High/Medium/Low is shown as part of the chosen model slug and sends no separate effort parameter.

**Follow local CLI settings** omits the effort override; it does not force the catalog's suggested default. Select an explicit Codex model to choose its reported levels. Unknown models or unavailable metadata offer only the default, while any saved explicit effort remains visible with a verification warning. Known unsupported saved levels must be corrected before saving an enabled agent; the backend also rejects a known unsupported level before launching an inference. Unknown/custom configurations remain subject to the CLI's actual validation. No level is silently substituted. New metadata preserves unsaved names/rules and their input focus. As with other Agent settings, changing effort affects a frozen discussion only after restarting independent answers.

## Claim and disagreement tracking

In Live CLI mode, **Claim tracking** replaces the disabled agreement placeholder. Open it and choose **Analyze published record** (or **Update tracking** after a completed round). Choose an enabled Claude/Codex/Gemini instance in the analyst picker (the Scribe is the default). Each analysis makes one explicit subscription CLI call; it can be cancelled without changing Scribe settings or debate membership. Successful reports record the analyst and requested model; an unavailable effective model identifier is not guessed. This analyst has no research tools and receives only published debater answers, not private moderator messages, raw source files or editable notes. Analysis does not regenerate or change the discussion.

The analyst extracts atomic propositions and each agent's support, opposition, reservation or missing position. Every explicit position requires a quotation from that same agent's actual published text. The service rejects fabricated quotes, wrong-speaker quotes, future-round sources and malformed reports. Counts are computed from the validated stance entries: unanimous support/opposition is alignment; different explicit positions are disagreement/reservation; missing positions or shared uncertainty remain undetermined. These are AI interpretations for review, not a scientific-validity score.

The first analysis can reconstruct independent answers and all completed debate rounds. Later updates append new snapshots and new propositions without changing previous claims or earlier baselines. New claims and position changes are labelled. Each quote links to its original answer; records persist through reload, backup and the existing run archive. New completed rounds mark tracking as needing an update; analysis is not silently repeated on every render or turn.

**In the preserved fixed-round scheduler**, Next speaker is available in any run mode when idle and not paused. It calls exactly one debater, automatically crossing an empty phase/round boundary. After the third completed round it calls one synthesis agent, without an implicit Scribe call. The main Continue control retains the existing full-stage/automatic scheduler and optional Scribe behavior.

## Reading layout

Live answers, debate turns, synthesis, shared evidence, Scribe proposals and edited notes render Markdown headings, paragraphs, emphasis, nested lists, quotes, fenced code, links and tables. Answer text is 15px, with stronger contrast in both themes. Tables scroll inside their own region instead of widening the discussion. Quoting, note editing and exports retain original Markdown.

Marked 17.0.5 is bundled locally with its license in `THIRD_PARTY_NOTICES.md`; rendering requires no CDN or npm installation. The renderer escapes raw HTML, omits embedded images and restricts generated elements and URL protocols. External citations open only when clicked. The local HTTP service embeds the maintained CSS and JavaScript files, in dependency order into its HTML response so the in-app browser loads them reliably after reload. If the parser is unavailable, escaped plain text keeps the page and controls usable. Direct file previews still use the original local files.

## Continuous discussion view

The three stage tabs are replaced by one dynamic process status and a continuous discussion record. Independent answers, each debate round and synthesis stay in the same record, with every agent output stacked vertically at full width in Live and Demo modes. **Start discussion / Continue discussion** uses the existing manual, round-by-round or automatic scheduler; **View latest** returns to the newest output. Shared evidence is expandable. Completed debate replies appear individually while slower peers are still running. Rendering preserves expanded evidence and the reading position when viewing earlier messages.

Independent prompts exclude peer answers. For debate, both agents receive the published independent answers and earlier discussion turns. In dynamic discussion agents speak sequentially and see the preceding speaker immediately. In the preserved fixed-round scheduler, agents called together use the same frozen transcript and see current parallel answers in the next round. Targeted moderator text is filtered for its recipient. The UI explains this sharing boundary, and backend tests verify both sides receive the published peer history without in-flight answer leakage.

## Compact UI and side chats

The default **Focus chat** view uses the full window for discussion, with the sidebar and notes tucked away. The top **⛶** button restores the panels; the menu and Notes buttons open either panel directly. Focus mode is a local display preference and does not change discussion content or Agent settings.

The question and process share a single 44 px desktop row. Answers use continuous, unboxed typography, with a centered reading column up to 1040 px and 15 px prose. Initial moderator instructions are expandable. The sidebar remains 184 px when opened. Native macOS selects keep flat web styling. The composer starts at 44 px instead of inheriting a previously oversized input; drag the curved top-right grip to resize vertically, use arrow keys on the grip, or double-click it to return to compact size. Focus, sidebar and input-height preferences persist locally. Narrow windows keep the transcript scrollable and all controls accessible.

Right-click a discussion (or use its **⋯** button) to rename, name with Gemini, pin, archive/restore, copy its question or export an importable single-discussion backup. Archive is reversible from **Archived discussions**. The new-discussion plus button opens a blank chat immediately and focuses the composer, with no title/task form and no model call. The first Send keeps the exact message as the research task and starts the selected research action. In Live mode, one separate Gemini call generates a concise title and 1–2 sentence overview in the background; the overview is available in an expandable section above the discussion. Manual names are preserved, including renames before or during generation. Drafts, titles and overviews survive reload. An unavailable Gemini call leaves a readable provisional name and never blocks research; the discussion menu can retry generation. Metadata generation uses the saved Gemini login with no fallback to Claude/Codex. It is a small utility job, not a research-stage Coordinator. An unavailable login or model gives a visible error and leaves manual naming available.

Select text in a live Markdown answer to **Add to chat** or open a **Side chat**. The source agent is selected by default, and you can change provider/model. Availability is checked on actual CLI invocation; candidate IDs are not a promise of account access. Web search is enabled by default. Scoped discussion/local source reads are available through the application read loop described above; shell execution and file edits remain disabled.

The side transcript scrolls independently with the trackpad or mouse wheel, without scrolling the main debate at its boundaries. Drag the panel’s left edge for width, top edge for height, or top-left corner for both. Sizes persist locally across reopen/reload and are constrained to the visible window; the ↺ button restores defaults. Focus a resize handle to use arrow keys, or Home to reset. New answers preserve an earlier reading position; readers already at the bottom continue following new replies.

Long discussions and side chats have a thin reading-position map at the right of their own transcript. Ticks represent messages and Markdown section headings, with the visible range highlighted and a stronger current marker. Hover/focus shows the agent, round and heading; click to jump. Up/Down, Home/End also navigate from a focused tick. Short transcripts hide the map. Each map scrolls only its own transcript and follows layout/resize changes, newly published content, language and theme. Very large outlines are sampled to at most 80 ticks to keep the overview compact. Navigation is local and never starts a model call or edits discussion content.

Only the parent question, selected excerpt and that side chat's own history reach its model. The parent debate is unchanged until you explicitly quote a side answer into the main composer and send it. Side history, model choices and pending job IDs persist across reload; imported/recovered copies detach source utility jobs so they cannot cancel or continue the originals. Each answer shows its requested/effective model when returned by the CLI.

On 2026-10-20, real Gemini membership calls passed title generation and a source-based side explanation using `gemini-3.8-flash-medium`. Custom provider/model routing, follow-up isolation, pending-call reload recovery, archive/restore, imported-copy separation, both themes and three languages are covered by isolated browser tests. The installed macOS app's custom discussion context menu was also checked directly in WebKit.

Completed independent answers, review/question replies, synthesis, experiment execution/verification reports and side-chat answers have a **Copy answer** button. It copies the original Markdown text (including links and code), excluding model names, status text and other interface controls. Copying never starts a model call or changes the research record.

## Current question and reply attribution

A new question sent to all members takes priority over an existing discussion/review call. The old review is cancelled and its committed replies remain reference history. Further reviews use the latest question as their primary task, with the original research topic and earlier turns as background. Existing plan approvals and blockers are archived by task; a changed task requires a fresh plan review. A late receipt from the previous task cannot approve the new one. The header and a compact current-question block show the active task, and answers carry clickable question references. Replies are grouped under their question, including when questions are queued. Existing records recover the latest shared question without a model call. Pending review cards carry the same question reference as completed replies and stay grouped beneath that question. Older frontend-only review messages are restored by their saved timestamps instead of being appended as a new task.

Targeted questions keep their recipient scope. Questions during an experiment do not cancel or rewrite its approved plan; the latest shared question becomes the next focus after execution/verification finishes or fails. Changing task focus never starts another experiment. Separate side chats remain independent.

## Live model activity

**Pause / Continue:** Pause cancels current discussion and focused-question calls and holds queued questions, including after reload. Returned answers stay in the transcript. Continue only unlocks the controls; it makes no model call and keeps queued questions held, including across reload. Click Next speaker afterward to make one new call to the original unfinished member; returned peer answers are not repeated. Explicit Send can resume the remaining answers or release the queued questions. New calls use preserved context rather than restoring hidden in-flight reasoning. Native CLI cancellation terminates its local process group. Already applied file changes are retained. An interrupted experiment is marked interrupted and is never replayed by Continue; inspect its artifacts and review a new plan before executing again.

Each running question shows per-member activity beneath the corresponding message. The current research call also has an activity card near the composer. Status is derived from actual CLI tool events: web searches, source/file reads, commands, edits, generic tools, pending approval and completion/failure. Both Codex event spellings and Claude/Gemini tool events are normalized. The last four tool activities can be expanded; targets are bounded to 180 characters. Raw command output and duplicated full answers are excluded from the saved activity snapshot. This displays observable tool activity rather than hidden reasoning. More than 30 seconds without new CLI events is explicitly labelled as awaiting new activity, not invented progress. Paused research shows its actual stop reason near the composer. Opening or reloading a discussion starts at its latest message. An upward wheel/touch/keyboard gesture immediately stops following, including small movements near the bottom. Updates preserve the paragraph being read; reading-map and question-reference navigation also opt out. Manually returning to the bottom or choosing View latest restores following, including the final answer after a call becomes idle. Browser scroll anchoring is disabled in the main viewport to avoid competing with explicit restoration. These rules are local UI state and never trigger a model call.

## User feedback

The header's **Feedback** button opens a small trilingual form. Users write a message, optionally choose a category/reply email and paste or attach up to two PNG/JPEG/WebP screenshots (3 MB each). It never invokes an AI or automatically collects research conversations, source files, paths, logs, accounts or credentials. The only automatic metadata is app version/build and platform. Draft text is saved separately in localStorage; chosen screenshots remain in memory until saved. Saved records and screenshots live separately under the data directory's `feedback/`, outside research backups.

Delivery has three explicit states: **submitted to receiver** after an HTTPS acknowledgement, **email app requested — not sent** when opening a prefilled mail, and **saved locally — not sent** when no channel is configured or delivery cannot be confirmed. Failed direct submissions remain available in **My feedback** for explicit retry. UUIDs and the `Idempotency-Key` header allow the receiver to deduplicate retries. No automatic background resends occur. Export creates a ZIP with the feedback text/JSON and only chosen screenshots; mail fallback requires the user to attach that ZIP for images or longer messages and press Send in their mail app.

Release configuration is in `feedback-config.json` (`email` and/or `endpoint`). The packaged recipient is `feedback@example.org`; no hosted receiver is configured, so users confirm Send in their email application. An empty configuration supports local-only saving. Override the public recipient or HTTPS receiver while building:

```sh
python3 desktop/build_app.py --output 'work/Research Council Release Feedback.app' --feedback-email 'your-public-feedback@example.org'
```

For direct in-app submission, add `--feedback-endpoint 'https://your-receiver.example/feedback'`. This is a JSON receiver you operate, not an arbitrary email address: it must accept `POST` with `{id, created, category, message, contact, language, images, environment}`, deduplicate by `id`, and return 2xx only after durable acceptance. Images have generated names, MIME types and base64 data. Explicit JSON `success:false` or `ok:false`, redirects, non-2xx responses and transport failures do not count as delivered. No provider API key or SMTP password belongs in the app. The public intake should enforce its own size/rate limits and validation; local app validation does not replace server validation.

For this development Mac only, `<data-directory>/feedback-config.json` can override bundled settings without rebuilding or restarting; settings are read for each feedback operation. This file is not served as a static asset and the normal loopback origin/token checks protect all feedback APIs. The config API exposes only delivery mode, public recipient/host and app version, not the full receiver URL. Saving a record locally or opening an email draft never marks it as delivered.

## Clipboard photos

Paste a screenshot/photo with **⌘V** while the main or side-chat input is focused, or choose an image with the existing attachment button. Thumbnails can be enlarged or removed before sending; image-only messages are supported. Drafts, sent photos and image-bearing side-chat history survive reload. PNG, JPEG, GIF and WebP are accepted, up to four images per message and 5 MB per image. Uploading only stores a private local asset; model calls begin through the existing Send/discussion controls.

Claude receives actual base64 image content; Codex receives local-image input (or its documented `exec --image` input in restricted mode). Every call receives up to the four most recent images visible to that agent, with explicit attachment IDs in the prompt; older references may remain in the text/history. Initial independent calls exclude peer and targeted private images. Title generation, claim tracking and Scribe work from published text rather than raw photos. The current Antigravity stream protocol supports text blocks only, so Gemini image messages fail explicitly before starting a model; the draft remains available for switching to Claude/Codex. The app never silently discards a photo or automatically reroutes it to another provider.

Images are immutable content-addressed files under the application data folder, outside the app bundle. Upload and preview APIs require the same local session token; arbitrary paths and SVG are rejected. Full and single-discussion JSON backups embed referenced image bytes, and imports verify their hashes before restoring discussion state. Removing an attachment detaches the draft; retained message records remain intact. The original text-source import flow is preserved.

On 2026-10-21, real membership calls through Claude Opus 5.5 and Codex GPT-6.1 Sol both identified the four colors in a generated test image correctly. Native input payloads, target isolation, paste previews, reload, image-only Send, side-chat follow-ups, Gemini rejection, backups, both themes and three interface languages are also covered by isolated tests.

## Account quota and context telemetry

The top-bar **Usage** button separates account quota, each agent's latest reported context, and call token statistics. The read-only Codex adapter uses only `initialize` and `account/rateLimits/read`; it never starts a model turn, consumes a reset credit, purchases credits, or sends a quota email. It strips account identifiers and caches account snapshots for 60 seconds. Shared metering buckets remain shared; the UI does not invent a per-model question allowance.

Claude quota is read through the installed Claude Code SDK control request `get_usage` with `skip_behaviors: true`, after `initialize`; this metadata-only process uses `--safe-mode` to skip customizations/hooks, sends no user message and skips local transcript analysis. Debate CLI permissions are unchanged. The experimental reply is reduced to shared five-hour/weekly and any reported model-scoped windows. Gemini quota is read through Antigravity’s built-in `-p "/usage" --output-format json` command; it must report a successful slash-command response with zero agent turns. A version check requires Antigravity 1.1.11 or newer, avoiding older clients that treated slash commands as model prompts. The Gemini card names Antigravity explicitly: these are its subscription buckets, including any third-party model bucket it reports, rather than the Claude/ChatGPT accounts. Antigravity third-party model balances are collapsed by default with an explicit account-scope explanation; cards keep their own height. Each reader fails independently, strips unrelated fields, and uses the same 60-second cache. Login, timeout and version failures have a visible retry/manual-check fallback. Missing/reset-expired snapshots are explicitly shown without inferring a refill. No interactive interface scraping or credential-file extraction is used.

Codex context comes from `thread/tokenUsage/updated.last` and its reported `modelContextWindow`, never cumulative `total`. Claude context uses the latest assistant message's fresh/cache input counts and the result's reported `modelUsage.contextWindow`; aggregated result usage is not treated as current context. Missing capacity stays unknown; Gemini's aggregate usage is displayed only as call statistics. Existing records without telemetry are preserved rather than retroactively estimated. No inference is run just to populate this view.

References: [Codex App Server quota RPC](https://learn.chatgpt.com/docs/app-server), [Claude SDK](https://github.com/anthropics/claude-agent-sdk-typescript), [Claude context/statusline field semantics](https://code.claude.com/docs/en/statusline), [Antigravity quota panel](https://www.antigravity.google/docs/cli/commands/usage), [Antigravity print-mode quota support (v1.1.11)](https://antigravity.google/docs/changelog). On 2026-10-20 the saved Codex login returned real primary and weekly windows through the metadata-only reader. Claude Code 2.1.280 returned real five-hour and weekly utilization through `get_usage`; Antigravity 1.4.3 returned Gemini and third-party quota buckets with `num_turns: 0` and all token counters zero. The installed service and GUI were checked against the normalized responses.

## Manual sources and optional preparation

New discussions (including discussions started from sources) keep the current custom debaters/rules and Scribe, but start with Context disabled. Enable it in **Agents & Models** when a shared preliminary report is useful. Existing discussions and imported backups retain their saved Context configuration; changing a frozen run's agents/sources requires restarting independent answers.

Attach a Markdown/text file using the paperclip or **Open local sources**. The imported original is sent directly to every debater without a preparatory model call. The manual library searches imported text only. Imports support up to 20 text files, 512 KB each; stored text is capped at 120,000 characters and each prompt attachment at 15,000, with truncation marked.

For full local documents, use **Live CLI + Native CLI** with Claude/Codex and send a request such as “Read `/absolute/path/research.md`, independently check original web sources, and compare your findings.” These requests go intact to the selected native debaters instead of being intercepted by the manual library. Each agent uses its own native tools under existing CLI approvals, reports actual filenames/URLs and access failures, then checks published peer claims during debate. This does not guarantee every relevant source is discovered or every requested tool succeeds. Restricted/Gemini-only recipients keep the manual-import flow for local-file search requests.

Interface controls, labels and status text cannot be selected with the pointer. Research answers, user messages, quotes, note contents, source excerpts and editable inputs remain selectable and copyable.

Main and side-chat draft references use an icon-only × button with a localized accessible label. The main composer resizes from the curved top-right grip; drag vertically or use Up/Down when focused, and double-click to restore its compact height. Its height is remembered locally.

## Send and save recovery

For new dynamic Live CLI discussions, Send starts the independent answers even in Manual mode; Manual controls subsequent rounds, rather than requiring a second click to send the initial question. Semi-automatic starts one round and Automatic continues the configured run. A single-agent recipient immediately starts a focused answer, including before any independent round. An explicit “Add to future discussion context” recipient only queues context. Sending a fresh question while paused explicitly starts the independent answers without resuming an automatic loop. Legacy fixed-round Manual discussions retain their explicit execution controls. Later shared additions during the initial call are saved without changing its frozen input. Shared additions sent before the first call are frozen into the same initial instructions for both independent agents; later additions do not change an in-flight independent packet.

Agent cards show waiting, shared-evidence preparation, thinking, native web search, completion and errors in all three languages. Status indicators follow actual call state; returned answers appear immediately while other agents are still running. Reduced-motion settings disable spinner animation.

If another window has saved newer data, the app shows **Keep discussion and reconnect**. Recovery preserves newer remote data and saves any conflicting local edits as separate recovered discussions. It does not overwrite the other window's notes. Unchanged renders no longer produce unnecessary disk writes. The client keeps an immutable saved base separate from editable session objects.

## What now runs

- Native CLI sessions persist per run/agent; Restricted mode uses separate processes/contexts per invocation, with explicit published discussion history. No global `--continue` or `resume --last` is used.
- Frozen research question, agent configuration, rules, language and common evidence packet. Independent prompts never contain unpublished peer answers. Attached originals reach every debater directly. New discussions default to Context disabled; opt-in Context preparation produces a shared report reused by later independent answers. Existing discussions retain their setting.
- Real cross-examination, synthesis, targeted moderator messages, cancellation and 10-minute process timeout. Partial successes are retained; retry fills only missing agents. Reload recovers running jobs. A service restart marks interrupted jobs explicitly, without silently spending more quota.
- Per-instance editable Markdown rules, base research rules and role defaults. Job snapshots retain rules, evidence, prompt hashes, requested model/effort, available usage metadata, CLI events and tool records. The run-record dialog exposes the last task. Earlier task records remain on disk.
- Scribe proposals use the real discussion. Accepting appends to user notes; previous Markdown versions can be restored from Note history. Proposals never overwrite an active edit.
- Live mode shows no synthetic consensus percentage. The original demo metrics and demo Work flow remain available and labelled.

## Data and permissions

The service binds only to `127.0.0.1`, validates Host/Origin and protects APIs with a per-launch token. External links may navigate to the public homepage; iframe/subresource and API requests retain strict source checks. Static routes cannot serve source code, Git metadata, jobs or private state files. It accepts research tasks, not arbitrary shell commands.

Sessions, text sources, theme and language are atomically saved in `.research-council/state.json`; revision checks prevent another window from silently overwriting newer state. Jobs live in `.research-council/jobs/`. These paths and test artifacts are ignored by Git. Keep a backup of this folder for recovery. Restricted calls use temporary directories. Native calls use the selected persistent workspace and can use native file/shell tools subject to CLI policy and user approval.

Attached text is explicitly shared evidence for all debaters. No Context Agent is needed to attach or share raw text. If explicitly enabled, Context needs Read authorized files when processing attachments in Restricted mode. In Restricted mode, the research adapter exposes no arbitrary filesystem or shell tools: Codex uses a read-only sandbox with shell tools disabled, Claude uses a restricted explicit research-tool list, and Gemini uses a restricted custom agent plus an official pre-tool hook that denies every unlisted tool. The Gemini hook is registered under an app-specific name in `~/.gemini/config/hooks.json`; it does nothing outside Research Council calls and preserves other hooks. Each invocation must confirm its own workspace, nonce, conversation and tool scope before its output is accepted. Web search/reading can be enabled per agent. Native tools and their errors are recorded. `runCode` does not grant shell execution in Restricted mode; Native mode follows native tool policy. Scribe needs Update notes enabled; the app applies accepted changes itself.

Use **Export full backup / Import backup copies** in Agents & Models to move data. Import preserves existing sessions and creates separate copies, reconnecting imported sources. Old random-port v0.9 localStorage cannot be read from a different origin: run this service on the old port, with a separate `--data-dir`, to load and export that origin's existing browser data, then import the backup into the normal service. The old server must be stopped before reusing its port. When no server data exists, the app migrates localStorage from its current origin automatically.

## Current boundaries and verified status

- On 2026-10-21, the installed App passed a real Gemini-only metadata call using the saved login and `gemini-3.8-flash-high`: it returned separate Chinese `title` and `summary` JSON fields with no research tools. Blank-chat startup, first-message task preservation, draft recovery, manual-name races and Gemini failure isolation are covered by fixture browser checks.
- On 2026-10-21, the installed Claude Code 2.1.280 initialized with actual permission mode `auto`. Resuming the existing Opus 5.5 research call completed a real answer with native local tools and zero human approval cards; the previously completed Codex answer was preserved. This verifies the integration for that installed account/model, not that every tool action or local policy can run without confirmation.
- On 2026-10-20, native membership acceptance passed with real Claude Opus 5.5 and Codex GPT-6.1 Sol: native local reading, exact per-agent session resumption and memory, public-web tool calls, two independent answers, sequential peer reviews, matching plan-hash approval, explicit Claude Bash approval, file creation and independent Codex byte verification. The test file was exactly `b"RC_EXECUTION_OK\n"` (16 bytes). The verifier explicitly left the wider “no files outside workspace changed” criterion unverified, rather than treating the execution report as proof. These calls used disposable workspaces and did not rerun the user's research.
- Automated coverage currently includes 232 Python tests and the browser suites listed below, including the execution-confirmation scenario. Browser scenarios use an injected fixture runner, including pending native permissions across reload, trilingual plan review, both themes, sequential visibility, imported-copy isolation and execution/verification rendering; they are not substituted for the real CLI checks above.

- On the development Mac, real Codex calls completed Context → two independent instances → cross-examination → synthesis → Scribe using the saved ChatGPT login. This does not verify access to every candidate model.
- On 2026-10-18, after Claude CLI subscription login, live acceptance through the running loopback service passed: Codex Context → Claude Opus 5.5 and Codex independent answers → both cross-comments → Claude synthesis → Claude Scribe. The configured `claude-sonnet-4-6` Scribe model also completed a separate real call. This acceptance exercised one cross-examination round; the three-round scheduler is covered by the browser tests. Existing sessions still require explicitly selecting Live CLI.
- Real claim-tracking acceptance on 2026-10-18 used the saved Codex login to analyze two independent answers and three debate rounds: 11 claims, four snapshots and 78 source-verified quotations, completed in about 127 seconds. A preceding Claude attempt was explicitly cancelled after waiting without a result; it was not recorded as a success. These checks establish quotation provenance, not the correctness of every AI stance interpretation.
- On 2026-10-19, the saved Google login passed real Gemini acceptance with `gemini-3.8-flash-medium`: independent answer, cross-comments in both directions with Codex, Context with native web tools feeding an independent answer, an additive Scribe proposal, and Gemini claim tracking (five claims with six source-validated quotations). A further web-cache check read the actual HTML title and retained the source content in the tool audit. These tests used isolated data, preserving the user’s existing research. Tool invocation/completion does not establish scientific correctness or prove that a full source document was read.
- The six-stage research workflow and a separate Coordinator remain proposed design; Work still simulates experiments. DeepSeek is not connected; Gemini can now serve as a debater, Context, Scribe or tracking analyst. Assigning Gemini does not itself implement a separate research-stage Coordinator.
- Codex exec does not always emit the effective model identifier. Such results store `effectiveModel: null` rather than guessing. The exact requested model/effort is always recorded.
- The GUI can run in the browser or the new native macOS `.app` window. The original Work tab remains a simulation; the new dynamic discussion Execute action uses real native tools and a second verifier. The Grok registry entry and existing demo functionality are retained; Grok live calls are not connected.
- Source import currently supports the existing text formats, not PDF parsing or arbitrary directory crawling. Common evidence is frozen per run; restart independent answers to apply changed sources/rules. Previous runs are retained in session archives and full backups.

## Tests

```sh
python3 -m unittest discover -s tests -v
node tests/ui.cjs
node tests/send.cjs
node tests/reading.cjs
node tests/tracking.cjs
node tests/gemini.cjs
node tests/dynamic.cjs
node tests/peer-round.cjs
node tests/pending-attribution.cjs
node tests/next-speaker.cjs
node tests/next-draft.cjs
node tests/experiment-live.cjs
node tests/execution.cjs
node tests/actions.cjs
node tests/sources.cjs
node tests/ux.cjs
node tests/images.cjs
node tests/effort.cjs
node tests/side-size.cjs
node tests/side-followup.cjs
node tests/feedback.cjs
node tests/reading-map.cjs
```

UI tests require Node.js, Playwright and Chrome. They use a separate temporary data directory and a test-only injected runner; no subscription quota is spent. Set `RC_CHROME` to your browser executable and optionally `RC_NODE_MODULES` to a directory containing Playwright. The test script also discovers the Codex bundled Playwright runtime on this Mac. Screenshots go to ignored `test-results/` and never overwrite the original preview assets. The older `test_theme.py` remains available with Python Playwright installed.

Official integration references: [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode), [Claude Code programmatic mode](https://code.claude.com/docs/en/headless).

---

The sections below document the preserved v0.9 prototype behavior and its original limitations. For current live behavior and startup, use the v0.11 sections above.

## What's new in v0.9 — Dark design

- **Editorial Night:** warm graphite canvas, soft high-contrast text, subtle green accents, neutral Agent cards and clear research notes. Avoids pure black and neon palettes.
- **Switch themes instantly:** upper-right appearance selector (`浅色 / 深色 / 跟随系统`, `ライト / ダーク / システム`, `Light / Dark / System`).
- **Dark by default for new v0.9 installations**; remembers a manually selected preference using `rc-theme-v09` in browser localStorage. `System` reacts to macOS appearance changes when supported.
- **Same product, two palettes:** v0.8 Light theme is retained. The sticky research title, three debate phases, agent/model registry, debate timeline, Work preview, Sources and Scribe Notes are available in either theme.
- UI still uses demo answers. No actual LLM execution or academic search is connected.

## Quick start (macOS)

1. Unzip the distribution.
2. Double-click `start_mac.command` (macOS may require right-click → Open); Python 3 is required.
3. Your browser opens a local server URL such as `http://127.0.0.1:NNNN/index.html`. Keep the Terminal window open.
4. Choose **Agents & Models** in the left sidebar.

The page can also be opened as `index.html`, but using the included local server is preferable for reliable browser storage and file loading.

## What's new in 0.6

- **Independent agent instances.** A provider is not an agent. Add, duplicate, rename, remove, activate, and reassign agent instances. You can create two different Codex agents, or multiple Claude agents. The initial cast has two debate agents and two background agents.
- **Roles:** Debater, Context, Scribe, Executor, Reviewer. Roles can be changed independently of the underlying provider.
- **Background list:** A default **Context Agent** and **Scribe Agent** appear in the left sidebar but do not participate in the debate. Context can be assigned to Claude, Codex, Gemini, or Grok in the UI.
- **Model + effort per instance:** a curated set of candidate model IDs, a custom ID field, and model-specific effort choices read from installed CLI metadata in Live mode. The legacy demo tables are superseded by the implementation described above; subscription entitlements remain subject to actual CLI validation.
- **Permission intentions:** read authorized local files, web search, update notes, execute code. This is stored metadata to prepare a future enforceable tool-permission layer. Web search and code execution are not implemented. Only files explicitly imported in the browser can be read by the local keyword search.
- **Work roles:** If a dedicated Reviewer exists, the Work preview displays that reviewer; if not, it uses other active debate agents. An enabled dedicated Executor is eligible for execution in the Work preview.
- **Trilingual labels:** 中文 / 日本語 / English.
- Maintains manual/semi-automatic/automatic **simulated** debate, fixed stage navigation, editable notes, local text import, and simulated execution/QA.

## Suggested walkthrough

1. Open **Agents & Models**.
2. Use **Add agent**, select `Codex`, name it `Codex — Alternative Hypotheses`, and leave its role as `Debater`.
3. Pick a candidate model such as `gpt-6.1-sol`, then a CLI-reported effort such as `high`. Save.
4. The independent stage now contains three slots. Use **Next speaker** to advance the simulated output.
5. Reopen the registry. Change **Context Agent** to `Gemini`, retain only **Read authorized local files**, save.
6. Import a `.md` file in **Sources**, search its name or content, attach it, then return to the debate. Imported documents do **not** alter the simulated responses.
7. Add an agent with role `Reviewer`, enter **Work**. The simulated Work cast will use the dedicated Reviewer.

## Storage and limitations

- Sessions and agent configurations: browser `localStorage` under the existing `rc-v03` key, to preserve compatibility with v0.5.
- Imported text snippets: browser `localStorage` under `rc-local-files-v1`. Do **not** import confidential documents into this demo. Imported file size capped at 512 KB, at most 20 text files per batch, and large text is truncated.
- Browsers cannot scan arbitrary local directories. The user must choose files or a folder first.
- There is no autonomous Context Agent LLM, no genuine Claude/Codex/Gemini/Grok output, no real CLI/account-capability handshake, no live scientific-search service, and no sandboxed code runner. All agent conversation, consensus metrics, and Work outcomes are examples.
- A published model's API-supported reasoning options do not prove the same model or effort is available to an individual's subscription CLI. The local bridge queries installed CLI capabilities where supported and shows errors rather than silently substituting.

## Source references

- Claude Code subagents: https://code.claude.com/docs/en/sub-agents
- Codex multi-agent: https://developers.openai.com/codex/multi-agent
- OpenAI reasoning levels: https://developers.openai.com/api/docs/guides/reasoning
- Gemini CLI model configuration: https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/generation-settings.md
- Brand artwork and license: see `THIRD_PARTY_NOTICES.md`.

## Automated tests

Requires `playwright` Python package and Chromium installed at `/usr/bin/chromium` in the test environment (edit executable path on a Mac). Run `python test_v06.py` and `python test_regression.py` to exercise the UI.


## v0.8 · 轻量提示（GUI 原型）

- 移除所有可见 `?` 辅助按钮。
- 对讨论模式、运行方式、一致性趋势、模型版本与推理等级等复杂设置，鼠标悬停约 650ms 才出现说明；移开后自动隐藏。
- 不给单一职能的“文献”“笔记”等按钮附加多余解释。
- 仍为模拟 AI/Work GUI；不连接真实 CLI。

*关于后续的位置调整：如需把某个具体元素移至另一位置并固定，需先确认源元素与目标区域。*

## v0.8 · Pinned research-question header

- Session label, full research question, model icons and discussion mode now live **above the scrollable debate body**, alongside the pinned stage controls.
- When reading a long timeline, the heading compresses to a one-line title with model metadata; scrolling back to the top expands it.
- In Work mode the title remains pinned in compact form while the debate stage controls disappear.
- Only the debate body scrolls; the footer controls remain fixed.
- All behavior remains a GUI demonstration; Claude/Codex are not connected.

### Durable invocation accounting

Native Claude/Codex calls now save `usageCalls` independently of the bounded event log,
including cancelled, failed, timed-out and interrupted calls. Claude message IDs and tool
IDs are deduplicated; final result totals replace rather than add to message totals.
Codex thread totals are differenced against the saved invocation baseline. Reasoning is
part of output, and cache reads/writes are parts of total input; do not add them twice.
Missing counters are `null`, not zero. Claude rate-limit samples retain the first and
last reported event for each rate-limit type with observation/reset timestamps. These
are not guaranteed to arrive exactly at call boundaries, and shared-account usage or
window resets prevent causal attribution. No additional model call retrieves telemetry.

Read-only audit (includes partial usage and a separate cancelled/failed subtotal):

```sh
python3 scripts/audit_usage.py --data-dir "$HOME/Library/Application Support/Research Council" --run-id DISCUSSION_ID
```

Old unsuccessful jobs whose usage was never saved remain explicitly unknown. Legacy
Codex thread totals are only differenced when a previous same-thread sample is present.

### Public handoff and delivery state

Fresh native contexts receive an extractive, attributed handoff index from their own
filtered public record: reported findings, mentioned file paths and notes, open issues,
and available experiment metadata. File mentions are not proof of a completed read.
No primary-model or Gemini call prepares this index, and independent answers exclude
peer turns. Prepared handoffs are cached and exact source records remain retrievable.
Delivery transitions through `prepared`, `sent_unconfirmed`, and `confirmed`. Codex
confirms when `turn/start` is accepted; Claude confirms on an assistant response or
message-start event. Confirmation commits the delivery cursor even if generation is
later cancelled. A subsequent call sends only differences. If delivery cannot be
confirmed, the old session is archived and a fresh session receives the cached handoff;
the same bootstrap is never blindly appended again to the uncertain session.

### Bridge-managed long experiments

After existing frozen-plan execution approval, a native executor (or verifier running a
long check) prepares its scripts and returns a final `<council_monitor>` JSON block with
`action: "start"`, a stable `key`, an argv `command`, absolute `cwd` and `logPath`, a
literal `completionMarker`, literal `failurePatterns`, and `expectedSeconds` (or null).
The bridge displays the exact command for approval before launching anything. It owns
the process wrapper, logs and exit receipt, independently of the CLI process lifetime.
The model must not launch detached commands using nohup/setsid, use Monitor, sleep or
poll while waiting. The program updates the activity view and only wakes the same
selected model/effort for completion, an error, or an expected-duration decision.
A duration estimate is a notification threshold, not an execution timeout.

The wake-up contains exit code, the last 30 log lines (bounded to 12KB), matched failure
features, process IDs and marker state. A still-running task can return
`<council_monitor>{"action":"wait","monitorId":"..."}</council_monitor>` without
starting another process. Completion needs a real exit receipt, exit code zero and any
specified marker; PID disappearance alone is not success. Old log content is excluded
from marker checks. A finished receipt cannot create an unbounded wake-up loop.

Records under `managed-experiments/` survive a bridge crash; an explicit retry can adopt
the same approved keyed process without relaunching it. A normal Pause/cancel or service
shutdown terminates owned process groups, preserving logs and output files. Process
birth time and unique wrapper arguments guard against PID reuse. Independent verification
starts only after the executor has processed the completion receipt. It remains its own
model call, separate from the two executor calls in the healthy long-process test.

### Token/quality comparison harness (not run against real models)

See [scripts/USAGE_COMPARISON.md](../scripts/USAGE_COMPARISON.md). The harness defaults to
a dry-run manifest and has only been exercised with fake clients. Real token measurements
require separate user confirmation and the explicit `--execute` flag. It compares both
providers individually and a manual dual-model baseline against the native Council
adapter with exact model/effort settings, counterbalanced pairs, at least three repeats,
recorded follow-up intervals, classified token usage and independent quality checks.
