const fs=require('fs'),path=require('path'),os=require('os'),{spawn}=require('child_process'),assert=require('assert/strict');
let pw;try{pw=require('playwright')}catch{pw=require(path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'))}
const root=path.resolve(__dirname,'..'),data=fs.mkdtempSync(path.join(os.tmpdir(),'council-gemini-')),checks=[];
const check=(v,n)=>{assert.ok(v,n);checks.push(n)};
(async()=>{const child=spawn('python3',[path.join(__dirname,'ui_fixture.py'),data],{cwd:root});child.stderr.pipe(process.stderr);let browser;
try{
 const url=await new Promise((resolve,reject)=>{child.stdout.once('data',d=>resolve(JSON.parse(d.toString()).url));child.once('exit',c=>reject(Error('fixture '+c)))});
 browser=await pw.chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const page=await browser.newPage({viewport:{width:1600,height:1080}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(url);await page.waitForFunction(()=>!!window.RC_DEBUG);await page.locator('#focusToggle').click();await page.locator('#langSelect').selectOption('zh');
 await page.locator('#addAgentRail').click();await page.locator('#nativeSettings > summary').click();await page.locator('#discussionProtocol').selectOption('fixed');await page.locator('#cliProfile').selectOption('restricted');await page.locator('#engineSelect').selectOption('live');
 await page.locator('[data-card=claude] [data-field=provider]').selectOption('gemini');
 await page.locator('[data-card=claude] [data-field=name]').fill('Gemini');
 await page.locator('[data-card=claude] [data-field=model]').selectOption('gemini-3.8-flash-medium');
 check(await page.locator('[data-card=claude] [data-field=effort] option').count()===1,'Gemini uses model-specific effort slugs, without unsupported CLI flags');
 for(const card of await page.locator('.registry-card').all()){
  const role=await card.locator('[data-field=role]').inputValue();
  if(['context','scribe'].includes(role)){await card.locator('[data-field=enabled]').check();await card.locator('[data-field=provider]').selectOption('gemini');await card.locator('[data-field=model]').selectOption('default')}
 }
 await page.locator('#checkCLIs').click();await page.waitForFunction(()=>document.querySelector('[data-card=claude] [data-field=model] option[value="gemini-account-visible"]')&&document.getElementById('cliStatus').textContent.includes('Antigravity CLI'));
 check((await page.locator('#cliStatus').textContent()).includes('Antigravity CLI'),'status names the actual Google membership client');
 check((await page.locator('#cliStatus').textContent()).includes('gemini-account-visible'),'available account model metadata is added to the picker without changing selected models');
 await page.locator('[data-card=claude] [data-field=rules]').fill('GEMINI_RULES_FIXTURE');
 fs.mkdirSync(path.join(root,'test-results'),{recursive:true});await page.screenshot({path:path.join(root,'test-results/gemini-settings.png')});
 await page.locator('#registrySave').click();await page.locator('#nextSpeaker').click();await page.waitForFunction(()=>RC_DEBUG.getState().session.independentCount===1&&!RC_DEBUG.getState().session.live.pending);
 check(await page.evaluate(()=>RC_DEBUG.getState().session.live.context.provider)==='gemini','Gemini can prepare shared context before the debater');
 check(await page.evaluate(()=>RC_DEBUG.getState().session.live.independent.claude.provider)==='gemini','single-speaker action invokes the configured Gemini debater');
 await page.locator('#nextSpeaker').click();await page.waitForFunction(()=>RC_DEBUG.getState().session.independentCount===2&&!RC_DEBUG.getState().session.live.pending);
 await page.locator('#consensusBtn').click();
 check((await page.locator('#trackingAnalyst option').allTextContents()).some(s=>s.includes('gemini')),'Gemini is available as a claim-tracking analyst');
 await page.locator('#runTracking').click();await page.waitForFunction(()=>!!RC_DEBUG.getState().session.live.tracking&&!RC_DEBUG.getState().session.live.pending);
 check(await page.evaluate(()=>RC_DEBUG.getState().session.live.tracking.analyst.provider)==='gemini','Gemini tracking uses the same source-validation pipeline');
 await page.locator('#trackingClose').click();await page.locator('#runModeSelect').selectOption('semi');await page.locator('#advance').click();await page.waitForFunction(()=>RC_DEBUG.getState().session.turnIndex===2&&!RC_DEBUG.getState().session.live.pending);
 await page.locator('#runScribe').click();await page.waitForFunction(()=>!!RC_DEBUG.getState().session.live.scribeProposal&&!RC_DEBUG.getState().session.live.pending);
 check(await page.evaluate(()=>RC_DEBUG.getState().session.live.scribeProposal.provider)==='gemini','Gemini can propose Scribe notes without overwriting user notes');
 await page.evaluate(()=>CouncilBridge.flush());
 const jobs=fs.readdirSync(path.join(data,'jobs')).map(f=>JSON.parse(fs.readFileSync(path.join(data,'jobs',f))));
 const debate=jobs.find(j=>j.request.kind==='debate');
 check(debate.request.transcript.some(t=>t.id==='codex')&&debate.request.transcript.some(t=>t.id==='claude'),'Gemini debate receives both published independent answers');
 const independent=jobs.find(j=>j.request.kind==='independent'&&j.request.agents[0].provider==='gemini');
 check(independent.request.agents[0].rules==='GEMINI_RULES_FIXTURE','Gemini rules are frozen in the submitted request');
 await page.evaluate(()=>{RC_DEBUG.getState().session.live.error={code:'account_verification_required'}});
 for(const [locale,phrase] of [['zh','Google 要求完成账号验证'],['ja','Google アカウントの確認'],['en','Complete Google account verification']]){
  await page.locator('#langSelect').selectOption(locale);check((await page.locator('.live-banner').allTextContents()).some(t=>t.includes(phrase)),'account verification failure is actionable in '+locale);
 }
 await page.evaluate(()=>CouncilBridge.flush());await page.reload();await page.waitForFunction(()=>!!window.RC_DEBUG);
 check(await page.evaluate(()=>RC_DEBUG.getState().session.live.independent.claude.provider)==='gemini','Gemini answers and configuration survive reload');
 check(errors.length===0,'no browser JavaScript errors');console.log(JSON.stringify({checks,errors},null,2));
}finally{if(browser)await browser.close();child.kill('SIGINT');await new Promise(r=>child.once('exit',r));fs.rmSync(data,{recursive:true,force:true})}})().catch(e=>{console.error(e);process.exitCode=1});
