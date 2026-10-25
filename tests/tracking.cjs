const fs=require('fs'),path=require('path'),os=require('os'),{spawn}=require('child_process'),assert=require('assert/strict');
let playwright;try{playwright=require('playwright')}catch{playwright=require(path.join(process.env.RC_NODE_MODULES||path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'),'playwright'))}
const root=path.resolve(__dirname,'..'),data=fs.mkdtempSync(path.join(os.tmpdir(),'council-tracking-')),checks=[];
const check=(v,name)=>{assert.ok(v,name);checks.push(name)};
(async()=>{
 const child=spawn(process.env.PYTHON||'python3',[path.join(__dirname,'ui_fixture.py'),data],{cwd:root});child.stderr.pipe(process.stderr);let browser;
 try{
  const url=await new Promise((resolve,reject)=>{child.stdout.once('data',chunk=>resolve(JSON.parse(chunk.toString()).url));child.once('exit',code=>reject(Error('Fixture exited '+code)))});
  browser=await playwright.chromium.launch({headless:true,executablePath:process.env.RC_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const context=await browser.newContext({viewport:{width:1500,height:1080}}),page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(url);await page.waitForFunction(()=>!!window.RC_DEBUG);await page.locator('#focusToggle').click();await page.locator('#langSelect').selectOption('en');
  await page.locator('#addAgentRail').click();await page.locator('#nativeSettings > summary').click();await page.locator('#discussionProtocol').selectOption('fixed');await page.locator('#engineSelect').selectOption('live');await page.locator('#registrySave').click();
  await page.locator('#consensusBtn').click();check(await page.locator('#runTracking').isDisabled(),'tracking waits for published independent answers');await page.locator('#trackingClose').click();
  await page.locator('#runModeSelect').selectOption('semi');check(await page.locator('#nextSpeaker').isEnabled(),'single speaker is available in semi-automatic mode');
  await page.locator('#nextSpeaker').click();await page.waitForFunction(()=>RC_DEBUG.getState().session.independentCount===1&&!RC_DEBUG.getState().session.live.pending);
  check(true,'single speaker invokes exactly one independent agent');
  await page.locator('#advance').click();await page.waitForFunction(()=>RC_DEBUG.getState().session.independentCount===2&&!RC_DEBUG.getState().session.live.pending);
  const original=await page.evaluate(()=>JSON.stringify(RC_DEBUG.getState().session.live.independent));
  await page.locator('#consensusBtn').click();await page.locator('#runTracking').click();await page.waitForFunction(()=>!!RC_DEBUG.getState().session.live.pending);
  await page.evaluate(()=>CouncilBridge.flush());await page.reload();await page.waitForFunction(()=>!!window.RC_DEBUG);
  await page.waitForFunction(()=>!!RC_DEBUG.getState().session.live.tracking&&!RC_DEBUG.getState().session.live.pending);
  check(true,'tracking job recovers after page reload');await page.locator('#consensusBtn').click();
  check(await page.locator('.tracking-claim').count()===3,'real tracking result renders per-claim cards');
  check((await page.locator('.tracking-counts strong').allTextContents()).join(',')==='1,1,1','counts distinguish alignment, disagreement and missing positions');
  check(!(await page.locator('#trackingPanel').textContent()).includes('%'),'no synthetic percentage appears');
  await page.locator('.tracking-evidence summary').first().click();check((await page.locator('.tracking-evidence blockquote').first().textContent()).includes('fixture answer'),'each explicit stance has a real source quotation');
  await page.locator('[data-tracking-source]').first().click();check(await page.locator('.tracking-target').count()===1,'quote navigation highlights its original published answer');
  const first=await page.evaluate(()=>structuredClone(RC_DEBUG.getState().session.live.tracking.snapshots[0]));
  check(await page.locator('#nextSpeaker').isEnabled(),'single speaker can cross the independent-to-debate boundary');
  await page.locator('#nextSpeaker').click();await page.waitForFunction(()=>RC_DEBUG.getState().session.stage==='debate'&&RC_DEBUG.getState().session.turnIndex===1&&!RC_DEBUG.getState().session.live.pending);
  check(true,'one click crosses the phase boundary and calls one debate agent');
  await page.locator('#nextSpeaker').click();await page.waitForFunction(()=>RC_DEBUG.getState().session.turnIndex===2&&!RC_DEBUG.getState().session.live.pending);
  check((await page.locator('#consensusDelta').textContent()).includes('New round'),'newly completed rounds mark tracking as stale');
  await page.locator('#consensusBtn').click();await page.locator('#trackingAnalyst').selectOption('codex');await page.locator('#runTracking').click();await page.waitForFunction(()=>RC_DEBUG.getState().session.live.tracking?.snapshots.length===2&&!RC_DEBUG.getState().session.live.pending);
  check(await page.evaluate(()=>RC_DEBUG.getState().session.live.tracking.analyst.id)==='codex','a different analyst can be selected without changing Scribe or debate answers');
  check(JSON.stringify(await page.evaluate(()=>RC_DEBUG.getState().session.live.tracking.snapshots[0]))===JSON.stringify(first),'updating tracking preserves the earlier snapshot exactly');
  check((await page.locator('.tracking-counts strong').allTextContents()).join(',')==='2,0,2','updated counts reflect the new positions and added claim');
  check((await page.locator('[data-claim-id=c4]').textContent()).includes('New claim'),'new propositions are identified explicitly');
  check((await page.locator('[data-claim-id=c2]').textContent()).includes('Position changed'),'stance changes are shown');
  await page.locator('[data-tracking-point="0"]').click();check((await page.locator('.tracking-counts strong').allTextContents()).join(',')==='1,1,1','round history retains the original baseline');
  await page.locator('#trackingClose').click();
  for(const [locale,title] of [['zh','观点与分歧追踪'],['ja','見解と相違点の追跡'],['en','Claims and disagreements']]){await page.locator('#langSelect').selectOption(locale);await page.locator('#consensusBtn').click();check((await page.locator('#modalTitle').textContent())===title,'tracking labels localized in '+locale);await page.locator('#trackingClose').click()}
  await page.locator('#langSelect').selectOption('zh');await page.locator('#consensusBtn').click();await page.locator('.tracking-evidence summary').first().click();
  await page.locator('#modalBody').evaluate(el=>{el.scrollTop=0});
  check(await page.locator('#modalTitle').evaluate(el=>{const r=el.getBoundingClientRect();return r.top>=0&&r.bottom<innerHeight}),'long tracking results keep the dialog title and close controls visible');
  fs.mkdirSync(path.join(root,'test-results'),{recursive:true});await page.screenshot({path:path.join(root,'test-results','claim-tracking.png')});
  await page.locator('#trackingClose').click();await page.evaluate(()=>CouncilBridge.flush());await page.reload();await page.waitForFunction(()=>!!window.RC_DEBUG);
  check((await page.evaluate(()=>RC_DEBUG.getState().session.live.tracking.snapshots.length))===2,'claim history persists to disk');
  check(await page.evaluate(()=>JSON.stringify(RC_DEBUG.getState().session.live.independent))===original,'analysis does not rewrite agent answers');
  const jobs=fs.readdirSync(path.join(data,'jobs')).map(f=>JSON.parse(fs.readFileSync(path.join(data,'jobs',f)))).filter(j=>j.request.kind==='tracking');
  check(jobs.length===2&&jobs.every(j=>j.request.agents.length===1&&Object.values(j.request.agents[0].tools).every(v=>!v)&&j.request.transcript.length===0),'tracking uses one tool-free analyst and only the published source packet');
  // One-speaker control also crosses later round boundaries and ends with
  // exactly one synthesis invocation, without an implicit Scribe call.
  await page.locator('#runModeSelect').selectOption('semi');
  for(let round=2;round<=3;round++)for(let turn=1;turn<=2;turn++){
   await page.locator('#nextSpeaker').click();await page.waitForFunction(({round,turn})=>RC_DEBUG.getState().session.debateRound===round&&RC_DEBUG.getState().session.turnIndex===turn&&!RC_DEBUG.getState().session.live.pending,{round,turn});
  }
  check(true,'single speaker crosses later round boundaries in semi-automatic mode');
  await page.locator('#nextSpeaker').click();await page.waitForFunction(()=>RC_DEBUG.getState().session.stage==='synthesis'&&!RC_DEBUG.getState().session.live.pending);
  check(!await page.evaluate(()=>!!RC_DEBUG.getState().session.live.scribeProposal),'single speaker ends with one synthesis call without an implicit Scribe call');
  check(errors.length===0,'no JavaScript errors');console.log(JSON.stringify({checks,errors},null,2));
 }finally{if(browser)await browser.close();child.kill('SIGINT');await new Promise(r=>child.once('exit',r));fs.rmSync(data,{recursive:true,force:true})}
})().catch(e=>{console.error(e);process.exitCode=1});
