/* Manual originals and optional Context, using an isolated fake CLI service. */
const fs=require('fs'),path=require('path'),os=require('os'),{spawn}=require('child_process'),assert=require('assert/strict');
let playwright;try{playwright=require('playwright')}catch{playwright=require(path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'))}
const root=path.resolve(__dirname,'..'),data=fs.mkdtempSync(path.join(os.tmpdir(),'council-sources-')),checks=[];
const check=(v,n)=>{assert.ok(v,n);checks.push(n)};
(async()=>{const child=spawn(process.env.PYTHON||'python3',[path.join(__dirname,'ui_fixture.py'),data],{cwd:root});child.stderr.pipe(process.stderr);let browser;
try{
 const url=await new Promise((resolve,reject)=>{child.stdout.once('data',b=>resolve(JSON.parse(b.toString()).url));child.once('exit',c=>reject(Error('Fixture '+c)))});
 browser=await playwright.chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const page=await browser.newPage({viewport:{width:1600,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(url);await page.waitForFunction(()=>!!window.RC_DEBUG);await page.locator('#langSelect').selectOption('zh');
 const legacy=await page.evaluate(()=>RC_DEBUG.getState().session);
 check(legacy.agentRoster.some(a=>a.role==='context'&&a.enabled),'legacy discussion retains enabled Context');
 if(!await page.locator('#newSession').isVisible())await page.locator('#railToggle').click();await page.locator('#newSession').click();await page.evaluate(question=>Object.assign(RC_DEBUG.getState().session,{question,awaitingFirstMessage:false}),'核对本地资料并独立检索来源');
 let state=await page.evaluate(()=>RC_DEBUG.getState().session);
 check(state.agentRoster.filter(a=>a.role==='context').every(a=>!a.enabled),'fresh discussion defaults Context off even if parent enabled');
 check(state.agentRoster.some(a=>a.role==='scribe'&&a.enabled),'Scribe remains enabled');
 await page.locator('#localFileInput').setInputFiles(path.join(root,'sample-local.md'));
 await page.waitForFunction(()=>RC_DEBUG.getContextPacket().documents.length===1);
 const original=await page.evaluate(()=>RC_DEBUG.getContextPacket().documents[0]);
 check(original.text.length>0,'raw Markdown attaches without a Context Agent');
 for(const [lang,label] of [['zh','手动资料库'],['ja','手動資料ライブラリ'],['en','Manual source library']]){
  await page.locator('#langSelect').selectOption(lang);await page.locator('#toolBtn').click();
  check((await page.locator('#ctxStat').textContent()).includes(label),'manual source library localized in '+lang);
  await page.locator('#doneContext').click();
 }
 await page.locator('#addAgentRail').click();await page.locator('#engineSelect').selectOption('live');await page.locator('#registrySave').click();
 const instruction='请查找本地 /tmp/my-project/source.md，并自行联网检索原始来源，不要依赖对方摘要。';
 await page.locator('#intervention').fill(instruction);await page.locator('#sendIntervention').click();
 check(!await page.locator('#modalOverlay').evaluate(el=>el.classList.contains('open')),'native local path request bypasses manual library');
 state=await page.evaluate(()=>RC_DEBUG.getState().session);
 check(state.interventions.some(x=>x.text===instruction),'complete path and search instruction saved intact');
 check(state.independentCount===0,'manual send retains manual execution control');
 await page.waitForFunction(()=>RC_DEBUG.getState().session.independentCount===2&&!RC_DEBUG.getState().session.live.pending);
 state=await page.evaluate(()=>RC_DEBUG.getState().session);
 const record=JSON.parse(fs.readFileSync(path.join(data,'discussions',state.live.councilId+'.json')));
 check(record.calls===2&&!record.context,'two independent calls run directly without Context cost');
 const jobs=record.jobs.map(id=>JSON.parse(fs.readFileSync(path.join(data,'jobs',id+'.json'))));
 check(jobs.every(j=>j.request.packet.documents[0].text===original.text),'both independent jobs receive attached original text');
 check(jobs.every(j=>j.request.initialInstructions.some(x=>x.text===instruction)),'both independent jobs receive local and web research request');
 check(jobs.every(j=>!j.request.contextAgent&&!j.request.transcript.length),'no mandatory Context and no peer answers in independent prompts');
 // Context edits are pending until a new run; the active native run still accepts paths.
 await page.locator('#addAgentRail').click();await page.locator('.registry-card').filter({has:page.locator('[data-field=role] option:checked[value=context]')}).locator('[data-field=enabled]').check();await page.locator('#registrySave').click();
 await page.locator('#messageAction').selectOption('question');await page.locator('#target').selectOption('claude');await page.locator('#intervention').fill('请搜索本地 /tmp/another.md');await page.locator('#sendIntervention').click();
 check(!await page.locator('#modalOverlay').evaluate(el=>el.classList.contains('open')),'targeted local request still goes to the active native debater after pending Context edits');
 // A new restricted run keeps the existing manual library path, without requiring Context.
 if(!await page.locator('#newSession').isVisible())await page.locator('#railToggle').click();await page.locator('#newSession').click();await page.evaluate(question=>Object.assign(RC_DEBUG.getState().session,{question,awaitingFirstMessage:false}),'Restricted manual sources');
 await page.locator('#addAgentRail').click();await page.locator('#nativeSettings > summary').click();await page.locator('#cliProfile').selectOption('restricted');await page.locator('#registrySave').click();
 await page.locator('#intervention').fill('find local source.md');await page.locator('#sendIntervention').click();
 check(await page.locator('#ctxSearch').isVisible(),'restricted local request still opens manual source library without Context');
 await page.locator('#ctxSearch').fill('');await page.locator('[data-context-id]').filter({hasText:'Attach'}).first().click();await page.locator('#startWithContext').click();
 state=await page.evaluate(()=>RC_DEBUG.getState().session);
 check(state.contextIds.length===1&&state.agentRoster.filter(a=>a.role==='context').every(a=>!a.enabled),'source-created discussion attaches originals with Context off');
 await page.evaluate(()=>CouncilBridge.flush());await page.reload();await page.waitForFunction(()=>!!window.RC_DEBUG);
 const disk=JSON.parse(fs.readFileSync(path.join(data,'state.json')));
 check(disk.sessions.find(s=>s.id===legacy.id).agentRoster.some(a=>a.role==='context'&&a.enabled),'legacy Context preference survives save and reload');
 check(errors.length===0,'no JavaScript errors');console.log(JSON.stringify({checks,errors},null,2));
}finally{if(browser)await browser.close();child.kill('SIGINT');await new Promise(r=>child.once('exit',r));fs.rmSync(data,{recursive:true,force:true})}})().catch(e=>{console.error(e);process.exitCode=1});
