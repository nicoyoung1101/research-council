/* Research execution lives beside the existing renderer; demo behavior is retained. */
window.createCouncilRuntime=function(api){
 const {S,render,save,esc,icon,packet,notes,modal,close,toast,markdown:md}=api;
 const bridge=window.CouncilBridge;
 const strings={
  zh:{engine:'运行来源',demo:'演示',live:'真实 CLI',check:'检查 CLI',rules:'Agent Rules · Markdown（空白使用默认职责规则）',ruleHint:'规则在每次真实调用时保存快照；来源资料不作为指令。原生模式使用本机 CLI 工具与授权策略；正式执行需确认当前方案。',busy:'正在运行',cancel:'取消当前调用',retry:'重试',reset:'重新独立回答',backup:'导出完整备份',importBackup:'导入备份副本',history:'笔记历史',restore:'恢复此版本',audit:'调用记录',autoScribe:'总结后自动生成笔记建议',status:'状态',unverified:'模型可用性待实际调用验证',connected:'已登录',notLogged:'未登录',missing:'未安装',offline:'本地服务未连接，请用 start_mac.command 启动',saved:'磁盘保存失败；请保留此页面并重试',conflict:'另一个窗口保存了更新内容；请点击「保留当前讨论并恢复连接」',proposal:'Scribe 笔记建议',accept:'追加到笔记',dismiss:'忽略',scribe:'运行 Scribe',context:'共同资料摘要',snapshot:'本轮使用已冻结的成员、规则和资料；配置修改在重新独立回答后生效。',paused:'已暂停；继续时处理未完成的回答。',resume:'刷新后发现未完成的调用，正在恢复状态。',login_required:'CLI 尚未通过会员登录',cli_missing:'找不到 CLI',unsupported_provider:'目前真实模式支持 Claude Code、Codex 与 Gemini (Antigravity CLI)',cli_failed:'CLI 调用失败',timeout:'调用超时',cancelled:'调用已取消',interrupted:'服务重启中断调用，请重试',empty_output:'CLI 没有返回答案',context_too_large:'资料过大，请减少挂载内容',busy_error:'此讨论已有运行中的调用',invalid_request:'运行配置无效',internal_error:'本地服务错误',save_failed:'无法保存本地数据',bridge_offline:'本地服务未连接',state_conflict:'另一个窗口保存了更新内容；请保留讨论并恢复连接',failed:'失败',pending:'等待独立回答',work:'Work 仍为演示预览',read:'附加原文会直接提供给双方，无需资料准备员。Claude/Codex 原生模式可按问题自行读本地文件和联网核查；资料准备员仅在启用时先整理资料。'},
  ja:{engine:'実行元',demo:'デモ',live:'実 CLI',check:'CLI を確認',rules:'Agent Rules · Markdown（空欄は役割の既定ルール）',ruleHint:'実行ごとにルールを保存。資料は命令として扱いません。ネイティブモードはローカル CLI のツールと承認方針を利用します。実行には計画の確認が必要です。',busy:'実行中',cancel:'呼び出しを中止',retry:'再試行',reset:'独立回答をやり直す',backup:'全データを出力',importBackup:'バックアップを複製して読込',history:'ノート履歴',restore:'この版を復元',audit:'実行記録',autoScribe:'まとめ後にノートを自動提案',status:'状態',unverified:'モデル利用可否は実行時に確認',connected:'ログイン済み',notLogged:'未ログイン',missing:'未インストール',offline:'start_mac.command でローカルサービスを起動してください',saved:'保存に失敗しました。このページを保持してください',conflict:'別のウィンドウで更新されました。「議論を保持して再接続」を選んでください',proposal:'Scribe のノート提案',accept:'ノートに追記',dismiss:'無視',scribe:'Scribe を実行',context:'共通資料の要約',snapshot:'固定済みの構成・ルール・資料を使用。変更は独立回答をやり直すと反映されます。',paused:'一時停止中。再開時に未完了の回答を処理します。',resume:'未完了の呼び出しを復元しています。',login_required:'CLI の会員ログインが必要です',cli_missing:'CLI が見つかりません',unsupported_provider:'実モードは Claude Code と Codex に対応',cli_failed:'CLI 呼び出しに失敗',timeout:'タイムアウト',cancelled:'中止しました',interrupted:'サービス再起動で中断。再試行してください',empty_output:'CLI の回答が空です',context_too_large:'添付資料が大きすぎます',busy_error:'この議論は実行中です',invalid_request:'設定が無効です',internal_error:'ローカルサービスエラー',save_failed:'ローカル保存に失敗',bridge_offline:'サービス未接続',state_conflict:'別のウィンドウで更新されました。議論を保持して再接続してください',failed:'失敗',pending:'独立回答待ち',work:'Work はデモです',read:'添付原文は討論者へ直接共有します。ネイティブ Claude/Codex は必要に応じてローカル資料と Web を独自に確認します。Context Agent による事前整理は任意です。'},
  en:{engine:'Execution source',demo:'Demo',live:'Live CLI',check:'Check CLIs',rules:'Agent Rules · Markdown (blank uses role defaults)',ruleHint:'Rules are snapshotted per call. Sources are data, never instructions. Native mode uses local CLI tools and approval policy; executing a plan requires explicit confirmation.',busy:'Running',cancel:'Cancel call',retry:'Retry',reset:'Restart independent answers',backup:'Export full backup',importBackup:'Import backup copies',history:'Note history',restore:'Restore this version',audit:'Run record',autoScribe:'Propose notes automatically after synthesis',status:'Status',unverified:'Model availability is verified on actual invocation',connected:'Signed in',notLogged:'Not signed in',missing:'Not installed',offline:'Start the local service with start_mac.command',saved:'Disk save failed; keep this page open and retry',conflict:'Another window saved newer data; use Keep discussion and reconnect',proposal:'Scribe note proposal',accept:'Append to notes',dismiss:'Dismiss',scribe:'Run Scribe',context:'Shared evidence summary',snapshot:'This run uses frozen agents, rules and sources. Restart independent answers to apply edits.',paused:'Paused; continue to process unfinished answers.',resume:'Recovering an unfinished call after reload.',login_required:'Subscription CLI login required',cli_missing:'CLI not found',unsupported_provider:'Live mode currently supports Claude Code and Codex',cli_failed:'CLI call failed',timeout:'Call timed out',cancelled:'Call cancelled',interrupted:'Interrupted by service restart; retry explicitly',empty_output:'CLI returned no answer',context_too_large:'Too much evidence; attach fewer sources',busy_error:'This discussion already has a running call',invalid_request:'Invalid run configuration',internal_error:'Local service error',save_failed:'Could not save local data',bridge_offline:'Local service not connected',state_conflict:'Another window saved newer data; keep discussion and reconnect',failed:'Failed',pending:'Awaiting independent answer',work:'Work is still a demo preview',read:'Attached originals go directly to debaters. Native Claude/Codex can inspect local paths and research web sources independently. Context preparation runs only when enabled.'}
 };
 Object.assign(strings.zh,{returned:'已返回',calling:'调用中',preparing:'正在准备共同资料',starting:'正在检查登录并启动调用…',ready:'发送问题即可开始独立回答；后续轮次可点击「继续研究」。',manualReady:'手动模式：发送只保存补充；点击「下一位发言」或「执行本轮」调用模型。',messageQueued:'补充已保存，将在下一次适用的调用中送给模型。',messageStarting:'问题已发送，正在调用模型。',reconnect:'保留当前讨论并恢复连接',reconnecting:'正在恢复连接并保存讨论…',initialMessages:'开始前的补充',queuedMessages:'待送入讨论的补充',finishedMessage:'补充已保存；本次讨论已总结，可新建讨论或重新开始。'});
 Object.assign(strings.ja,{returned:'回答済み',calling:'呼び出し中',preparing:'共通資料を準備中',starting:'ログインを確認して起動しています…',ready:'質問を送信すると独立回答を開始します。次のラウンドは「研究を続ける」で進めます。',manualReady:'手動モード：送信は補足を保存します。「次の発言者」または実行ボタンで呼び出します。',messageQueued:'補足を保存しました。次の該当する呼び出しで渡します。',messageStarting:'質問を送信しました。モデルを呼び出しています。',reconnect:'議論を保持して再接続',reconnecting:'再接続し、議論を保存しています…',initialMessages:'開始前の補足',queuedMessages:'次の議論への補足',finishedMessage:'補足を保存しました。まとめは完了しています。新しい議論か再開始を選んでください。'});
 Object.assign(strings.en,{returned:'answered',calling:'call in progress',preparing:'preparing shared evidence',starting:'Checking sign-in and starting the call…',ready:'Send a question to start independent answers; use Continue research for later rounds.',manualReady:'Manual mode: Send saves your addition. Use Next speaker or Run this round to call agents.',messageQueued:'Addition saved for the next applicable call.',messageStarting:'Question sent; starting the response.',reconnect:'Keep discussion and reconnect',reconnecting:'Reconnecting and saving your discussion…',initialMessages:'Initial additions',queuedMessages:'Additions queued for discussion',finishedMessage:'Addition saved. This discussion is summarized; start a new discussion or restart.'});
 Object.assign(strings.zh,{thinking:'正在思考…',searching:'正在检索资料…',waitingStart:'等待开始',waitingContext:'等待共同资料…',completed:'已完成',agentError:'出错',agentStarting:'正在启动…'});
 Object.assign(strings.ja,{thinking:'考えています…',searching:'資料を検索中…',waitingStart:'開始待ち',waitingContext:'共通資料を待っています…',completed:'完了',agentError:'エラー',agentStarting:'起動中…'});
 Object.assign(strings.en,{thinking:'Thinking…',searching:'Searching sources…',waitingStart:'Waiting to start',waitingContext:'Waiting for shared evidence…',completed:'Completed',agentError:'Error',agentStarting:'Starting…'});
 Object.assign(strings.zh,{invalid_tracking_output:'分析结果未通过原文核对，请重试'});
 Object.assign(strings.ja,{invalid_tracking_output:'分析結果の原文照合に失敗しました。再試行してください'});
 Object.assign(strings.en,{invalid_tracking_output:'Analysis failed source verification; please retry'});
 Object.assign(strings.zh,{cachedAuth:'发现 Google 登录缓存，实际调用待验证',accountModels:'账号可见模型',cliModels:'本机 CLI 模型目录'});
 Object.assign(strings.ja,{accountModels:'アカウントで利用可能なモデル',cliModels:'ローカル CLI モデル一覧',cachedAuth:'Google ログイン情報あり・呼び出し未検証',unsupported_provider:'Claude Code、Codex、Gemini (Antigravity CLI) に対応'});
 Object.assign(strings.en,{accountModels:'Account-visible models',cliModels:'Installed CLI model catalog',cachedAuth:'Google login cached; call not yet verified',unsupported_provider:'Claude Code, Codex and Gemini (Antigravity CLI) are connected'});
 Object.assign(strings.zh,{unsafe_cli_config:'CLI 工具范围超出研究权限，已停止调用'});
 Object.assign(strings.ja,{unsafe_cli_config:'CLI ツールが研究権限を超えたため停止しました'});
 Object.assign(strings.en,{unsafe_cli_config:'CLI exposed tools outside research permissions; call stopped'});
 Object.assign(strings.zh,{account_verification_required:'Google 要求完成账号验证；请在浏览器完成验证后重试',unsupported_client:'Google 已停用此客户端，请使用 Antigravity CLI（agy）'});
 Object.assign(strings.ja,{account_verification_required:'Google アカウントの確認をブラウザで完了して再試行してください',unsupported_client:'対応する Antigravity CLI（agy）を使用してください'});
 Object.assign(strings.en,{account_verification_required:'Complete Google account verification in your browser, then retry',unsupported_client:'Use the supported Antigravity CLI (agy)'});
 Object.assign(strings.zh,{geminiHelp:'Gemini 使用 Google 官方 Antigravity CLI（agy）。首次运行 login_gemini_mac.command 登录会员；若 Google 要求账号验证，请在浏览器完成后重试。'});
 Object.assign(strings.ja,{geminiHelp:'Gemini は公式 Antigravity CLI（agy）を利用します。login_gemini_mac.command でログインし、Google の確認が必要ならブラウザで完了してください。'});
 Object.assign(strings.en,{geminiHelp:'Gemini uses Google’s official Antigravity CLI (agy). Run login_gemini_mac.command to sign in; complete any Google account verification in your browser before retrying.'});
 Object.assign(strings.zh,{auto_approval_unavailable:'Claude 当前无法进入自动审批，请检查模型、账号或本机设置；也可在高级设置中选择手动审批'});Object.assign(strings.ja,{auto_approval_unavailable:'Claude の自動承認が利用できません。モデル・アカウント・設定を確認するか、手動承認を選んでください'});Object.assign(strings.en,{auto_approval_unavailable:'Claude Auto is unavailable; check model, account or local settings, or choose Manual approval in advanced settings'});
 const L=key=>(strings[api.lang()]||strings.en)[key]||key;
 Object.assign(strings.zh,{images_unsupported:'当前 Gemini / Antigravity 通道不支持图片，请选择 Claude 或 Codex',invalid_image:'图片无效或已丢失，请重新添加'});
 Object.assign(strings.ja,{images_unsupported:'現在の Gemini / Antigravity は画像非対応です。Claude または Codex を選んでください',invalid_image:'画像が無効か見つかりません。再追加してください'});
 Object.assign(strings.en,{images_unsupported:'Gemini / Antigravity image input is unsupported; choose Claude or Codex',invalid_image:'Invalid or missing image; attach it again'});
 const errorText=e=>L(e?.code==='busy'?'busy_error':e?.code||'internal_error')+(e?.detail?' · '+e.detail:'');
 Object.assign(strings.zh,{decision_needed:'等待你的决定 · 详情见下方任务卡片'});Object.assign(strings.ja,{decision_needed:'判断待ち · 詳細は下のタスクカード'});Object.assign(strings.en,{decision_needed:'Your decision needed · see the task card below'});
 // A paused experiment waiting for the host is not a failed call; keep it out of the error path.
 const decisionCodes=new Set(['execution_needs_decision','experiment_needs_decision']);
 const needsDecision=(live,e)=>!!e&&(decisionCodes.has(e.code)||(live.controller?.experiments||[]).some(t=>t.status==='needs_decision'&&t.error?.code===e.code));
 let running=false,auto=false,reconnecting=false,lastSaveError=0;
 Object.assign(strings.zh,{codex_permission_unavailable:'Codex 未采用所选权限，请检查本机或组织策略'});Object.assign(strings.ja,{codex_permission_unavailable:'Codex に選択した権限が適用されませんでした'});Object.assign(strings.en,{codex_permission_unavailable:'Codex did not apply the selected permissions; check local or managed policy'});
 const isLive=()=>S()?.engine==='live';
 const state=s=>s.live||(s.live={independent:{},pending:null,error:null,notesHistory:[],scribeProposal:null});
 function agentStatus(v,id,result){
  if(result)return {phase:'complete',label:L('completed')};
  const requested=v.callAgents?.some(a=>a.id===id),progress=v.agentProgress?.[id];
  if(requested&&(v.pending||v.starting)){
   if(v.approvals?.some(a=>a.status==='pending'&&a.agentId===id))return {phase:'approval',label:dynamic.T('waitingPermission')};
   if(progress?.phase==='error')return {phase:'error',label:errorText(progress.error)};
   if(!v.pending)return {phase:'starting',label:L('agentStarting'),active:true};
   if(v.pendingTask==='independent'&&!v.context&&v.roster?.some(a=>a.enabled&&a.role==='context'))return {phase:'waiting-context',label:L('waitingContext'),active:true};
   return {phase:progress?.phase||'thinking',label:(['tool','responding'].includes(progress?.phase)?dynamic.T(progress.phase):L(progress?.phase==='searching'?'searching':'thinking'))+(progress?.seconds!==undefined?' · '+dynamic.T('elapsed')+' '+Math.floor(progress.seconds/60)+':'+String(progress.seconds%60).padStart(2,'0'):''),active:true};
  }
  return progress?.phase==='error'?{phase:'error',label:errorText(progress.error)}:{phase:'waiting',label:L('waitingStart')};
 }
 function progressHTML(status){return `<span class="agent-progress" data-agent-state="${status.phase}" role="status">${status.active?'<span class="agent-spinner" aria-hidden="true"></span>':''}${esc(status.label)}</span>`}
 function statusHTML(s){const live=state(s),error=bridge.error||live.error,decision=!bridge.error&&needsDecision(live,live.error),active=live.pending||live.starting||live.controller?.status==='running';
  const message=live.reconnecting?dynamic.T('reconnecting'):decision?L('decision_needed'):error?errorText(error):active?(live.starting&&!live.pending?L('starting'):L('busy')+(live.activity?' · '+live.activity:'')):s.paused?L('paused'):live.feedback||(!live.roster?L(s.runMode==='manual'&&!dynamic.is(s)?'manualReady':'ready'):L('snapshot'));
  return `<div class="live-banner"${decision?' data-banner-state="needs-decision"':''} role="status"><strong>${esc(L('live'))}</strong><small>${esc(message)}${active?`<span class="call-progress">${(live.callAgents||[]).map(a=>`<span>${esc(a.name)} · ${progressHTML(agentStatus(live,a.id,live.agentProgress?.[a.id]?.phase==='complete'))}</span>`).join('')}</span>`:''}</small>${error?.code==='state_conflict'?`<button class="btn" data-live-action="reconnect" ${running||live.pending||reconnecting?'disabled':''}>${esc(L(reconnecting?'reconnecting':'reconnect'))}</button>`:''}${live.lastJob?`<button class="btn" data-live-action="audit">${esc(L('audit'))}</button>`:''}${live.pending?`<button class="btn" data-live-action="cancel">${esc(L('cancel'))}</button>`:active?'':`<button class="btn" data-live-action="reset">${esc(L('reset'))}</button>`}</div>`;
 }
 function queuedHTML(s){const v=state(s),initial=v.initialInstructions||[],queued=(s.queued||[]).filter(x=>x.intent!=='question'&&!initial.some(i=>i.id&&i.id===x.id||i.text===x.text&&i.to===x.to));return [initial.length?`<details class="flow-context flow-instructions" data-flow-detail="initial-instructions"><summary>${esc(L('initialMessages'))} · ${initial.length}</summary><div class="instruction-text">${esc(initial.map(x=>x.text).join('\n'))}</div>${initial.map(x=>(window.CouncilImages?.html(x.images)||'')+(window.CouncilUX?.quotesHTML(x.quotes)||'')).join('')}</details>`:'',queued.length?`<div class="live-banner"><b>${esc(L('queuedMessages'))}</b><small>${esc(queued.map(x=>x.text).join('\n'))}</small>${queued.map(x=>window.CouncilImages?.html(x.images)||'').join('')}</div>`:''].join('')}

 function independentHTML(standalone=true){const s=S(),v=state(s);return (standalone?statusHTML(s)+queuedHTML(s):'')+`<div class="stage-head"><div class="stage-name">${esc(api.t('independent'))}</div><div class="stage-counter">${Object.keys(v.independent).length}/${s.selected.length}</div></div><div class="cards" style="--cols:${s.selected.length}">${s.selected.map(id=>{const a=(v.roster||s.agentRoster).find(a=>a.id===id),r=v.independent[id],status=agentStatus(v,id,r);return `<article class="opinion ${r?'':'empty'}" aria-busy="${!!status.active}" data-agent-id="${esc(id)}" data-flow-item="independent-${esc(id)}"><div class="op-head"><div class="op-id">${icon(id)}<div><div class="op-name">${esc(a?.name||id)}</div><div class="op-sub">${esc(r?.effectiveModel||r?.requestedModel||a?.model||'default')}</div>${progressHTML(status)}</div></div></div><div class="live-answer prose">${r?md(r.text):esc(status.label)}</div>${r?.text?`<div class="answer-tools">${window.CouncilUX?.copyButton('independent',id)||''}</div>`:''}</article>`}).join('')}</div>`}
 function timelineHTML(standalone=true){const s=S(),v=state(s);let round=0;
  const waiting=(v.pendingTask==='debate'&&(v.pending||v.starting)?v.callAgents||[]:[]).filter(a=>!s.shownTurns.some(t=>t.type==='agent'&&t.id===a.id&&t.round===s.debateRound));
  const pending=waiting.map(a=>({type:'pending',id:a.id,name:a.name,round:s.debateRound,replyTo:v.controller?.activeQuestion?.id}));
  const turns=dynamic.orderedTurns(s,pending).map(({turn,i})=>{if(turn.type==='pending')return `<div class="turn" data-flow-item="pending-${esc(turn.id)}" aria-busy="true">${icon(turn.id)}<div><div class="turn-top"><span class="turn-who">${esc(turn.name)}</span><span>${esc(api.t('round',{n:turn.round}))}</span></div>${dynamic.replyHTML(s,turn)}<div class="turn-box">${progressHTML(agentStatus(v,turn.id))}</div></div></div>`;if(turn.type==='experiment'){const task=v.controller?.experiments?.find(x=>x.id===turn.taskId);return task?dynamic.taskCard(s,task):''}const heading=turn.kind!=='question'&&turn.round&&turn.round!==round?(round=turn.round,`<div class="flow-round">${esc(api.t('cross'))} · ${esc(api.t('round',{n:round}))}</div>`):'';
   return heading+`<div data-agent-id="${esc(turn.id||'')}" data-turn-index="${i}" class="turn ${turn.type==='user'?'user-turn':''}" data-flow-item="turn-${i}">${icon(turn.type==='user'?'user':turn.id)}<div><div class="turn-top"><span class="turn-who">${esc(turn.type==='user'?api.t('moderator'):(v.roster||[]).find(a=>a.id===turn.id)?.name||turn.id)}</span><span>${esc(turn.action?window.CouncilComposer?.label(turn.action)+(turn.action==='review'&&turn.reviewerId?' · '+((v.roster||[]).find(a=>a.id===turn.reviewerId)?.name||turn.reviewerId):''):turn.kind==='question'?dynamic.T('question'):api.t('round',{n:turn.round||s.debateRound}))}</span></div>${turn.type==='agent'?dynamic.replyHTML(s,turn):''}<div class="turn-box live-answer prose">${md(turn.text||'')}${window.CouncilImages?.html(turn.images)||''}${window.CouncilUX?.quotesHTML(turn.quotes)||''}</div>${turn.type==='user'?dynamic.activityHTML(s,turn.id):''}<div class="turn-actions">${turn.type==='agent'&&turn.text?window.CouncilUX?.copyButton('turn',i)||'':''}<button class="link-btn" data-quote="${i}">${esc(api.t('quote'))}</button>${turn.type==='agent'?`<button class="link-btn" data-note="${i}">${esc(api.t('note'))}</button>`:''}</div></div></div>`;
  }).join('');
  return (standalone?statusHTML(s):'')+`<div class="timeline">${turns}</div>`;
 }
 function synthesisHTML(standalone=true){const s=S(),v=state(s);return (standalone?statusHTML(s):'')+`<article class="synthesis" data-agent-id="${esc(v.synthesis?.agentId||'')}" data-flow-item="synthesis"><div class="stage-name">${esc(api.t('synthTitle'))}</div><div class="live-answer prose">${v.synthesis?md(v.synthesis.text):progressHTML(agentStatus(v,v.callAgents?.[0]?.id))}</div>${v.synthesis?`<div class="answer-tools">${window.CouncilUX?.copyButton('synthesis','')||''}</div><p>${esc(dynamic.T('taskHint'))}</p><button class="btn" id="toWork">${esc(dynamic.T('tasks'))}</button>`:''}</article>`}
 function flowHTML(){const s=S();if(s.view==='work')return '';const v=state(s),hasDebate=s.stage!=='independent'||s.shownTurns.length||v.pendingTask==='debate',hasSummary=!v.councilId&&(s.stage==='synthesis'||v.synthesis||v.pendingTask==='synthesis');
  return statusHTML(s)+dynamic.focusHTML(s)+dynamic.panel(s)+queuedHTML(s)+(v.context?`<details class="flow-context" data-flow-detail="context"><summary>${esc(L('context'))}</summary><div class="live-answer prose">${md(v.context.text)}</div></details>`:'')+
   `<div class="discussion-feed"><section class="flow-section" data-flow-stage="independent">${dynamic.openingHTML(s,independentHTML(false))}</section>`+
   (hasDebate?`<section class="flow-section" data-flow-stage="debate"><p class="flow-sharing">${esc(dynamic.is(s)?dynamic.T('sharing'):api.sharing())}</p>${timelineHTML(false)}</section>`:'')+
   (hasSummary?`<section class="flow-section" data-flow-stage="synthesis">${synthesisHTML(false)}</section>`:'')+'</div>'+dynamic.activeHTML(s);
 }
 async function check(){const el=document.getElementById('cliStatus');if(!el)return;el.textContent=L('busy');try{const data=await bridge.request('capabilities');window.dispatchEvent(new CustomEvent('council-model-catalog',{detail:data}));el.textContent=data.providers.map(p=>`${p.provider}${p.client?' · '+p.client:''}: ${p.installed?p.version+' · '+L(p.loggedIn?(p.authVerified===false?'cachedAuth':'connected'):'notLogged'):L('missing')}${p.models?.length?'\n'+L(p.modelCatalogSource==='installed_cli'?'cliModels':'accountModels')+': '+p.models.map(m=>m.id).join(', '):''}`).join('\n')+'\n'+L('unverified')}catch(e){el.textContent=errorText(e)}}
 function settings(){const s=S();return dynamic.settings()+`<div class="runtime-settings"><label>${esc(L('engine'))} <select id="engineSelect"><option value="demo" ${isLive()?'':'selected'}>${esc(L('demo'))}</option><option value="live" ${isLive()?'selected':''}>${esc(L('live'))}</option></select></label><label><input type="checkbox" id="autoScribe" ${s.autoScribe!==false?'checked':''}> ${esc(L('autoScribe'))}</label><button class="btn" id="checkCLIs">${esc(L('check'))}</button></div><div class="runtime-settings"><button class="btn" id="exportBackup">${esc(L('backup'))}</button><button class="btn" id="importBackup">${esc(L('importBackup'))}</button><input id="backupFile" type="file" accept=".json" hidden></div><div id="cliStatus" class="runtime-status">${esc(bridge.connected?L('unverified'):L('offline'))}</div><p class="runtime-status">${esc(L('read'))}</p><p class="runtime-status">${esc(L('geminiHelp'))}</p>`}
 function bindSettings(){document.getElementById('checkCLIs').onclick=check;dynamic.bind();
  document.getElementById('exportBackup').onclick=async()=>{try{const backup=await window.CouncilImages.exportBackup(api.exportData());const url=URL.createObjectURL(new Blob([JSON.stringify(backup,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='research-council-backup.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}catch(e){toast(errorText(e))}};
  document.getElementById('importBackup').onclick=()=>document.getElementById('backupFile').click();
  document.getElementById('backupFile').onchange=async e=>{try{const file=e.target.files[0];if(!file)return;if(file.size>100000000)throw {code:'context_too_large'};await api.importData(JSON.parse(await file.text()))}catch(error){toast(errorText(error))}};check()}

 const rulesHTML=a=>`<label class="registry-rules">${esc(L('rules'))}<textarea data-agen="${esc(a.id)}" data-field="rules" maxlength="24000">${esc(a.rules||'')}</textarea><small>${esc(L('ruleHint'))}</small></label>`;
 function snapshot(s){const v=state(s);if(!v.roster){v.roster=structuredClone(s.agentRoster);v.packet=structuredClone(packet());v.question=s.question;v.mode=s.discussionStyle||'adaptive';v.lang=api.lang();v.created=Date.now();v.runId=crypto.randomUUID();v.profile=s.cliProfile||'restricted';v.workspace=s.workspace||'';v.initialInstructions=structuredClone(s.interventions.filter(x=>x.to==='all'))}return v}
 function transcript(s){const v=state(s);return [...Object.values(v.independent).map(a=>({type:'independent',id:a.agentId,name:a.name,text:a.text})),...s.shownTurns]}
 async function poll(s,id){
  let job;
  do{job=await bridge.request('jobs/'+id);const v=state(s);v.approvals=job.approvals||[];
   if(v.pendingTask==='independent'){
    v.independent={...v.independent,...Object.fromEntries(job.results.map(r=>[r.agentId,r]))};
    if(job.context)v.context=job.context;
    s.independentCount=Object.keys(v.independent).length;
   }else if(v.pendingTask==='debate'){
    for(const r of job.results)if(!s.shownTurns.some(t=>t.type==='agent'&&t.id===r.agentId&&t.round===s.debateRound))s.shownTurns.push({type:'agent',id:r.agentId,round:s.debateRound,text:r.text,result:r});
    s.turnIndex=s.shownTurns.filter(t=>t.type==='agent'&&t.round===s.debateRound).length;
   }
   const terminal=['complete','failed','cancelled','interrupted'].includes(job.status);
   v.agentProgress=Object.fromEntries((v.callAgents||[]).map(a=>{
    if(job.results.some(r=>r.agentId===a.id))return [a.id,{phase:'complete'}];
    const failure=job.failures?.find(f=>f.agentId===a.id);
    if(failure||terminal&&job.status!=='complete')return [a.id,{phase:'error',error:failure||job.error||{code:job.status}}];
    const searches=new Set();
    for(const event of job.events||[]){if(event.agentId!==a.id||!event.tool)continue;const t=event.tool;
     if(t.type==='web_search'){if(t.status==='completed'||t.status==='failed')searches.delete(t.id);else searches.add(t.id)}
     if(t.type==='tool_use'&&['WebSearch','WebFetch','search_web','read_url_content'].includes(t.name))searches.add(t.id);
     if(t.type==='tool_result')searches.delete(t.tool_use_id);
    }
    return [a.id,{phase:searches.size?'searching':'thinking'}];
   }));
   const expected=v.callAgents||(v.roster||[]).filter(a=>a.enabled&&a.role==='debater');
   const answered=job.results.map(r=>r.name),waiting=expected.filter(a=>!job.results.some(r=>r.agentId===a.id)).map(a=>a.name);
   const context=(v.roster||[]).find(a=>a.enabled&&a.role==='context');
   v.activity=v.pendingTask==='independent'&&!v.context&&context?context.name+' · '+L('preparing'):[answered.length?answered.join(', ')+' · '+L('returned'):'',waiting.length?waiting.join(', ')+' · '+L('calling'):''].filter(Boolean).join(' / ');
   if(S()===s)render();if(!['complete','failed','cancelled','interrupted'].includes(job.status))await new Promise(r=>setTimeout(r,600))}while(!['complete','failed','cancelled','interrupted'].includes(job.status));
  const v=state(s),task=v.pendingTask;
  if(job.status==='complete'||job.status==='failed'&&job.results?.length){
   if(task==='independent'){v.independent={...v.independent,...Object.fromEntries(job.results.map(r=>[r.agentId,r]))};v.context=job.context||v.context||null;s.independentCount=Object.keys(v.independent).length}
   else if(task==='debate'){for(const r of job.results)if(!s.shownTurns.some(t=>t.type==='agent'&&t.id===r.agentId&&t.round===s.debateRound))s.shownTurns.push({type:'agent',id:r.agentId,round:s.debateRound,text:r.text,result:r});s.turnIndex=s.shownTurns.filter(t=>t.type==='agent'&&t.round===s.debateRound).length}
   else if(task==='synthesis'){v.synthesis=job.results[0];s.stage='synthesis'}
   else if(task==='scribe')v.scribeProposal=job.results[0];
   else if(task==='tracking'){v.tracking=job.results[0].tracking;v.tracking.analyst={id:job.results[0].agentId,name:job.results[0].name,provider:job.results[0].provider,model:job.results[0].requestedModel,jobId:id};v.trackingSignature=v.pendingTrackingSignature;v.trackingError=null}
   v.error=job.status==='failed'?job.error:null;
  }else v.error=job.error||{code:job.status};
  if(task==='tracking'&&job.status!=='complete')v.trackingError=job.error||{code:job.status};
  v.lastJob=id;v.pending=null;v.pendingTask=null;v.activity=null;delete v.starting;
  save();if(S()===s)render();
  return job.status==='complete';
 }
 async function task(s,kind,agents,extra={}){
  if(running||state(s).pending||dynamic.busy(s))return false;
  if(!bridge.connected){state(s).error={code:'bridge_offline'};render();return false}
  running=true;
  const v=snapshot(s),request=v.pendingRequest||{requestId:crypto.randomUUID(),sessionId:s.id,kind,agents,profile:v.profile||'restricted',claudePermissionMode:s.claudePermissionMode||'auto',codexPermissionMode:s.codexPermissionMode||'read-only',runId:v.runId,workspace:v.workspace,question:v.question,mode:s.discussionStyle||'adaptive',lang:v.lang,packet:v.packet,initialInstructions:v.initialInstructions||[],sharedContext:v.context?.text||'',transcript:transcript(s),notes:kind==='scribe'?notes():'',moderator:s.interventions.filter(x=>x.to==='all'||x.to==='context'||agents.some(a=>a.id===x.to)),...extra};
  if(request.kind==='tracking'){v.pendingTrackingSignature=request.trackingSignature;v.trackingError=null}
  v.agentProgress={};v.callAgents=request.agents.map(a=>({id:a.id,name:a.name}));v.pendingRequest=request;v.pendingTask=request.kind;v.error=null;v.feedback=null;v.starting=true;
  if(request.kind==='independent'&&!v.context&&!request.contextAgent)request.contextAgent=v.roster.find(a=>a.enabled&&a.role==='context')||null;
  try{render();save();await bridge.flush();const job=await bridge.request('jobs',request);v.pending=job.id;v.pendingRequest=null;save();render();return await poll(s,job.id)}
  catch(e){v.error=e;if(request.kind==='tracking')v.trackingError=e;v.agentProgress=Object.fromEntries(v.callAgents.map(a=>[a.id,{phase:'error',error:e}]));if(e.code&&!v.pending)v.pendingRequest=null;save();if(S()===s)render();return false}
  finally{delete v.starting;running=false;if(S()===s)render()}
 }
 async function step(all=false){
  const s=S(),v=snapshot(s);if(s.paused||running||v.pending)return false;delete v.displayStage;
  if(v.pendingRequest)return task(s,v.pendingRequest.kind,v.pendingRequest.agents);
  const debaters=v.roster.filter(a=>a.enabled&&a.role==='debater');
  if(s.stage==='independent'){
   if(Object.keys(v.independent).length<debaters.length){const missing=debaters.filter(a=>!v.independent[a.id]);return task(s,'independent',all?missing:[missing[0]])}
   s.stage='debate';s.shownTurns.push(...s.queued);s.queued=[];save();render();return true;
  }
  if(s.stage==='debate'){
   const remaining=debaters.filter(a=>!s.shownTurns.some(t=>t.type==='agent'&&t.id===a.id&&t.round===s.debateRound));if(remaining.length)return task(s,'debate',all?remaining:[remaining[0]]);
   if(s.debateRound<3){s.debateRound++;s.turnIndex=0;save();render();return true}
   const ok=await task(s,'synthesis',[debaters[0]]);if(ok&&s.autoScribe!==false){const a=v.roster.find(a=>a.enabled&&a.role==='scribe'&&a.tools?.writeNotes);if(a)await task(s,'scribe',[a])}return ok;
  }
  return false;
 }
 async function next(){
  if(S().stage==='synthesis'&&!state(S()).pending)dynamic.adopt(S());
  if(dynamic.is(S()))return dynamic.action(S(),'next');
  const s=S(),v=state(s);if(running||auto||v.pending||s.paused||s.stage==='synthesis')return;
  // A single-speaker action may cross an empty phase boundary, but stops
  // immediately after exactly one debater invocation.
  for(let i=0;i<3;i++){
   if(s.stage==='debate'&&s.debateRound>=3&&s.turnIndex>=s.selected.length)return task(s,'synthesis',[(v.roster||s.agentRoster).find(a=>a.enabled&&a.role==='debater')]);
   const previous=v.lastJob;
   if(!await step(false)||v.lastJob!==previous||v.error||s.stage==='synthesis')return;
  }
 }
 async function advance(){if(S().stage==='synthesis'&&!state(S()).pending)dynamic.adopt(S());if(dynamic.is(S()))return dynamic.action(S(),S().runMode==='auto'?'auto':'round');if(running||auto)return;const s=S();auto=true;try{
   if(s.runMode==='manual'){await step(true);return}
   if(s.runMode==='semi'){if(s.stage==='independent'&&s.independentCount>=s.selected.length||s.stage==='debate'&&s.turnIndex>=s.selected.length)await step(true);if(!s.paused&&S()===s)await step(true);return}
   while(S()===s&&!s.paused&&s.stage!=='synthesis'){if(!await step(true))break}
  }finally{auto=false;if(S()===s)render()}}
 const dynamic=window.createDynamicCouncil({S,render,save,esc,md,snapshot,state,packet,notes,bridge,toast,modal,close,lang:api.lang,errorText,roundLabel:n=>api.t('round',{n})});
 const tracker=window.createClaimTracker({S,esc,modal,close,lang:api.lang,run:task,busy:()=>running||auto||!!S().live?.pending||dynamic.busy(S()),errorText,save});
 function decorate(){if(!isLive())return;const s=S(),v=state(s);document.querySelector('.rail-foot span:first-child').textContent=L('live');tracker.decorate();
  document.getElementById('nextSpeaker').disabled=!!v.pending||running||s.paused||auto;
  document.getElementById('advance').disabled=!!v.pending||running||auto||s.paused;
  document.querySelectorAll('[data-live-action]').forEach(b=>b.onclick=async()=>{const action=b.dataset.liveAction;if(action==='reconnect'){if(running||v.pending||reconnecting)return;if(api.editing()){toast(api.t('saveEdits'));return}reconnecting=true;render();try{await bridge.recover(api.exportData().state)}catch(error){v.error=error;toast(errorText(error))}finally{reconnecting=false;render()}return}if(action==='audit'){const job=await bridge.request('jobs/'+v.lastJob);modal(L('audit'),'',`<pre class="live-answer">${esc(JSON.stringify(job,null,2))}</pre>`,`<button class="btn" id="auditDone">OK</button>`);document.getElementById('auditDone').onclick=close;return}if(action==='cancel'){await bridge.request('jobs/'+v.pending+'/cancel',{});return}if(running||dynamic.busy(s))return;archiveRun(s);v.notesHistory=v.notesHistory||[];const history=v.notesHistory;s.live={independent:{},notesHistory:history};s.stage='independent';s.independentCount=0;s.turnIndex=0;s.debateRound=1;s.shownTurns=[];s.queued=[];s.paused=false;save();render()});dynamic.bind();if(s.paused&&(running||auto))document.getElementById('pauseBtn').disabled=true;
 }
 function renderNotes(){if(!isLive())return false;const s=S(),v=state(s),el=document.getElementById('proposalArea');el.innerHTML=`<div class="live-scribe"><button class="btn" id="runScribe" ${running||v.pending||dynamic.busy(s)?'disabled':''}>${esc(L('scribe'))}</button>${v.notesHistory?.length?`<button class="btn" id="noteHistory">${esc(L('history'))}</button>`:''}${v.scribeProposal?`<h4>${esc(L('proposal'))}</h4><div class="prose">${md(v.scribeProposal.text)}</div><button class="btn" id="acceptLiveNote">${esc(L('accept'))}</button> <button class="btn" id="dismissLiveNote">${esc(L('dismiss'))}</button>`:''}</div>`;
  document.getElementById('runScribe').onclick=async()=>{const a=(v.roster||s.agentRoster).find(a=>a.enabled&&a.role==='scribe'&&a.tools?.writeNotes);if(!a){toast(L('invalid_request'));return}await task(s,'scribe',[a])};
  if(v.notesHistory?.length)document.getElementById('noteHistory').onclick=()=>{modal(L('history'),'',v.notesHistory.map((entry,i)=>`<div class="live-scribe"><small>${esc(new Date(entry.at).toLocaleString())}</small><div class="prose">${md(entry.markdown)}</div><button class="btn" data-restore-note="${i}">${esc(L('restore'))}</button></div>`).join(''),'<button class="btn" id="historyDone">OK</button>');document.getElementById('historyDone').onclick=close;document.querySelectorAll('[data-restore-note]').forEach(b=>b.onclick=()=>{if(api.editing()){toast(api.t('saveEdits'));return}const md=v.notesHistory[Number(b.dataset.restoreNote)].markdown;v.notesHistory.push({at:Date.now(),markdown:notes()});s.editedMarkdown=md;close();save();render()})};
  if(v.scribeProposal){document.getElementById('acceptLiveNote').onclick=()=>{if(api.editing()){toast(api.t('saveEdits'));return}const previous=notes();v.notesHistory.push({at:Date.now(),markdown:previous});s.editedMarkdown=previous+'\n\n'+v.scribeProposal.text;v.scribeProposal=null;save();render()};document.getElementById('dismissLiveNote').onclick=()=>{v.scribeProposal=null;save();render()}}
  return true;
 }
 function quoteText(i){return S().shownTurns[i]?.text||''}
 function onSaveError(event){if(Date.now()-lastSaveError<5000)return;lastSaveError=Date.now();toast(event.detail?.code==='state_conflict'?L('conflict'):L('saved'));if(isLive())render()}
 window.addEventListener('council-save-error',onSaveError);
 async function recover(){const s=S(),v=s.live;if(dynamic.is(s)&&v?.councilId){dynamic.watch(s);return}if(s.engine==='live'&&v?.pendingRequest&&!v.pending&&!running){await task(s,v.pendingRequest.kind,v.pendingRequest.agents);return}if(s.engine==='live'&&v?.pending&&!running){running=true;try{await poll(s,v.pending)}catch(e){v.error=e;render()}finally{delete v.starting;running=false;render()}}}
 function archiveRun(s){if(s.live?.roster||s.shownTurns.length)(s.runArchive||=[]).push({at:Date.now(),engine:s.engine||'demo',live:structuredClone(s.live||null),shownTurns:structuredClone(s.shownTurns),stage:s.stage,debateRound:s.debateRound})}
 async function onMessage(message){const s=S(),v=state(s);
  if(!dynamic.is(s)&&!v.pending&&(s.stage!=='independent'||s.independentCount))dynamic.adopt(s);
  if(message.action&&!dynamic.is(s)&&!v.pending)dynamic.adopt(s);
  if(message.action&&dynamic.is(s)&&message.to!=='context'){
   if(message.action==='independent'&&!v.councilId&&!s.independentCount&&message.to==='all')return dynamic.action(s,'round');
   if(message.action==='review')return dynamic.action(s,message.reviewerId?'review_one':s.runMode==='auto'?'review_auto':'review',{message,...(message.reviewerId?{reviewerId:message.reviewerId}:{})});
   message.intent='question';return dynamic.action(s,message.action==='independent'?'independent':'question',{message});
  }
  if(dynamic.is(s)){
   if(message.to==='context'){
    if(v.councilId)await dynamic.action(s,'moderator',{moderator:s.interventions.filter(x=>x.intent!=='question')});
    v.feedback=L('messageQueued');save();render();return;
   }
   if(message.to!=='all'||v.councilId||s.stage!=='independent'||s.independentCount){message.intent='question';await dynamic.action(s,'question',{message});return}
   v.feedback=L('messageQueued');save();render();if(!running&&!auto&&!v.pending&&!dynamic.busy(s)){const wasPaused=s.paused;s.paused=false;await dynamic.action(s,!wasPaused&&s.runMode==='auto'?'auto':'round')}return;
  }
  v.feedback=L(s.runMode==='manual'?'manualReady':'messageQueued');save();render();
  if(!s.paused&&!running&&!auto&&!v.pending&&s.runMode!=='manual')await advance();
 }

 return {composerAction:(action,extra={})=>{if(!dynamic.is(S()))dynamic.adopt(S());return dynamic.action(S(),action,extra)},focusLabel:()=>dynamic.focusLabel(S()),tasksHTML:()=>dynamic.tasksHTML(S()),detach:dynamic.detach,pause:async()=>{const s=S(),id=state(s).pending;if(dynamic.is(s)&&(s.live?.councilId||s.live?.starting))await dynamic.action(s,'pause');if(id)await bridge.request('jobs/'+id+'/cancel',{})},resume:()=>{if(dynamic.is(S())&&S().live?.councilId){dynamic.action(S(),'resume');return true}if(isLive())return true;return false},dynamicSettings:()=>({codexPermission:document.getElementById('codexPermissionMode')?.value||window.CouncilActivity.codexAccess(S()),permission:document.getElementById('claudePermissionMode')?.value||'auto',profile:document.getElementById('cliProfile')?.value,protocol:document.getElementById('discussionProtocol')?.value,style:document.getElementById('discussionStyle')?.value||'adaptive',workspace:document.getElementById('nativeWorkspace')?.value.trim(),budgets:{calls:0,seconds:0,unlimited:true}}),showTracking:tracker.show,onMessage,flowHTML,archiveRun,isLive,L,errorText,settings,bindSettings,rulesHTML,independentHTML,timelineHTML,synthesisHTML,decorate,renderNotes,advance,next,quoteText,recover,busy:()=>running||!!S().live?.pending||dynamic.busy(S())};
};
