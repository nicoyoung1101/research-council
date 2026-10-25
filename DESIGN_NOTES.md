# Research Council v0.6 — Architecture decisions

## Three separate identities

An **Agent Instance** is `{id, name, provider, role, model, effort, enabled, tools}`. The `provider` identifies the CLI or API adapter; a `model` is an exact provider-specific identifier; a `role` describes what the agent should do. More than one Agent Instance can point to the same provider and model.

## Default roles

- `Debater` appears in the independent cards and cross-examination timeline.
- `Context` reads/searches explicitly authorized local material and prepares a shared context packet. It is **not** an extra debater. V0.6 uses deterministic keyword matching, not an LLM.
- `Scribe` is reserved for updating a curated `research-notes.md`, which is currently a user-reviewed notes UI, not an automated LLM.
- `Executor` and `Reviewer` are roles in the simulated Work stage, designed for future verified CLI execution.

## Research fairness and permissions

Independent debaters should receive the **same initial evidence packet** (with original source references) but never see each other's unpublished independent opinions. Later retrieval must be reflected visibly in the discussion. Files selected by the user are untrusted content, not system instructions. Enforcing permissions requires a backend: checkbox states in this HTML demo are only future configuration metadata, except that the typed local-file search checks for an enabled Context instance with read permission.

## Runtime provider capability handshake (not yet implemented)

1. Locate installed CLI binary and read version/login state without exfiltrating tokens.
2. Discover model availability using a documented CLI command/API if provided. Otherwise retain an explicitly **unverified** status and validate through a safe dry-run or initial call after consent.
3. Select valid reasoning effort choices for that exact model and provider integration. API capability references are **not** evidence of subscription CLI entitlement.
4. Save both requested and effective model/effort, and report any rejection or fallback.
5. Log agent tool requests, approval decisions and actual results.

## Separation of interface and backend

V0.6 is a static local Web GUI. In a later stage, a loopback backend (Node/Python) will own adapter processes, file tools, permission enforcement, per-agent contexts and round scheduling. Do not let the web page itself issue unrestricted commands.


### v0.7 说明提示约束

仅复杂控件提供延时 hover/focus 提示，单一职能按钮不提供“?”或说明。

## v0.8 — 研究问题固定头部

- 把“场次编号／研究问题标题／参与模型与讨论模式”从正文滚动区域提升到固定头部，放在三阶段控制条上方。
- 页面结构：顶栏 → 固定的当前研究头部 → 固定的讨论阶段控制 → 唯一可滚动的讨论内容 → 底部主持人输入与控制。
- 正文滚动超过约 90 px 时，头部缩成单行，保留标题和模型摘要；返回顶部恢复大标题。压缩与展开采用不同阈值，避免临界点来回跳动。
- Work 页面依然显示紧凑研究标题，不再显示 Debate 阶段导航。
- 未接通 AI 账号和执行环境，保留原来标识的模拟功能。


## v0.9 — Editorial Night

- Dark theme uses `html[data-theme="dark"]` and a separate `themes.css` for explicit surface overrides, allowing v0.8 Light to remain untouched.
- The compact header and stage controller are still outside `#scroll`; only debate content scrolls.
- `theme.js` holds only theme preference/OS appearance and translation of the theme selector; it never touches debate or work data.
- Theme is independent from interface language and session state. Default `dark`, options `light`, `dark`, `auto`. Saved under `rc-theme-v09`.
- macOS start command launches the static files on `127.0.0.1` with Python; no CLI execution, external network requests or file reading occurs until a user chooses files.
- Chromium visual tests cover Independent, Debate, Work, agent registry, scroll compaction and language labels. Browser automation tests use an injected test-only storage shim when a local URL is blocked in the test sandbox.


## v0.10 — Local CLI runtime

The v0.9 HTML structure and palettes remain authoritative. `council-runtime.js` supplies live output through the existing stage renderer, while `bridge-client.js` owns same-origin requests and serialized durable saves. Demo data remains available only in Demo sessions. Live stage navigation changes the viewed stage without rewinding the execution cursor.

`bridge.py` owns CLI discovery/auth checks, bounded jobs, subprocess lifecycle and atomic JSON persistence. No API-key client or shell-command endpoint is introduced. Each invocation uses a fresh temporary working directory and explicit published history, with a frozen roster/rules/evidence/language snapshot. Context output is reused for later independent answers and subsequent debate. Targeted moderator messages are filtered per recipient. Partial model failures preserve completed results and retry only missing members.

Source text explicitly selected by the user is the common evidence packet. The research adapter does not expose arbitrary filesystem or shell tools. Web research is available per agent. Research rules, actual CLI restrictions, and retained Work permission metadata are distinct: enabling runCode does not turn this research adapter into an executor. Claude uses restricted research tools and Codex uses read-only execution with shell tools disabled. Work remains the original labelled simulation.

Scribe proposes append-only changes with manual acceptance and restoreable Markdown history. Session archives and complete backup export preserve prior runs when a user restarts or switches runtime. Imported backups create copies and never resume a process from another installation. Persistent job IDs and request IDs allow recovery after refresh without duplicate quota spending; service restarts mark active work interrupted and require an explicit retry.

Model/effort candidate tables remain unverified. Exact requested IDs are passed through; unavailable models are errors. Effective model identifiers are recorded only when emitted by the CLI. Live mode does not reuse demo agreement percentages.
