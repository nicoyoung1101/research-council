# Architecture

Research Council separates the reading interface, local orchestration, provider execution, and stored evidence.

| Layer | Main files | Responsibility |
| --- | --- | --- |
| Research interface | `app.js`, `council-runtime.js`, `dynamic-runtime.js` | Sessions, published answers, review controls, and task views |
| Reading and composition | `conversation-scroll.js`, `composer-actions.js`, `research-tasks.js`, `council-ux.js` | Latest-position navigation, drafts, quotations, side chats, and plan confirmation |
| Local service | `bridge.py` | Loopback HTTP API, persisted state, jobs, and request validation |
| Discussion controller | `orchestration.py`, `context_sync.py` | Independent answers, sequential review, exact session resumption, and public-context delivery |
| Experiment lifecycle | `execution_flow.py`, `handoff.py`, `execution_progress.py` | Frozen plan identity, stage receipts, handoffs, and acceptance checks |
| Managed processes | `experiment_monitor.py`, `experiment_worker.py` | Observe longer-running work without keeping a model waiting |
| Provider clients | `native_cli.py`, `gemini_adapter.py`, `gemini_guard.py` | Installed CLI protocols, activity, cancellations, and permissions |
| Local research tools | `tracking.py`, `side_context.py`, `image_store.py` | Claim tracking, bounded source lookup, and attachments |
| Desktop shell | `desktop/ResearchCouncil.swift` | Native window, service startup, file dialogs, and application menus |

## Discussion and execution are separate

A discussion can collect independent views, publish sequential reviews, or answer a focused question. None of those actions constitutes permission to run an experiment.

An experiment starts from an explicitly confirmed plan. The controller retains the plan hash, participating members, acceptance criteria, and human decisions. Stage receipts are checked against the expected task and nonce. Missing evidence, invalid receipts, and out-of-scope decisions stop continuation.

A final success claim requires the independent verifier's acceptance checks. Older records that only show two completed calls remain distinguishable from verified completion.

## Local persistence

The browser service stores state and jobs in its selected data directory. The desktop application uses `~/Library/Application Support/Research Council/`, outside the app bundle. Application updates can therefore preserve discussions and native CLI session identities.

The repository contains synthetic fixtures rather than a copy of a user's data directory. Do not add credentials or private workspaces to source control.

## Validation boundaries

Automated scenarios exercise state transitions, permission propagation, restart recovery, UI controls, and fixture-based execution. They do not establish model accuracy, scientific validity, or access to every provider/model configuration.
