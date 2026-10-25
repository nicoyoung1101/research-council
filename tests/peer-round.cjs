/* Entire review round before a need_user pause; test fixture only. */
const fs=require('fs'),path=require('path'),os=require('os'),{spawn}=require('child_process'),assert=require('assert/strict');
const {chromium}=require(path.join(process.env.RC_NODE_MODULES||path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'),'playwright'));
const root=path.resolve(__dirname,'..'),data=fs.mkdtempSync(path.join(os.tmpdir(),'council-peer-round-')),checks=[];
const check=(v,n)=>{assert.ok(v,n);checks.push(n)};
(async()=>{const child=spawn('python3',[path.join(__dirname,'ui_fixture.py'),data],{cwd:root});child.stderr.pipe(process.stderr);let browser;
try{
 const url=await new Promise((r,j)=>{child.stdout.once('data',b=>r(JSON.parse(b.toString()).url));child.once('exit',c=>j(Error('Fixture '+c)))});
 browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const page=await browser.newPage({viewport:{width:1500,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto(url);await page.waitForFunction(()=>!!window.RC_DEBUG);await page.locator('#focusToggle').click();
 await page.locator('#newSession').click();await page.locator('#addAgentRail').click();await page.locator('#engineSelect').selectOption('live');await page.locator('#registrySave').click();
 await page.locator('#intervention').fill('A reproducible question');await page.locator('#sendIntervention').click();await page.waitForFunction(()=>RC_DEBUG.getState().session.independentCount===2&&RC_DEBUG.getState().session.live.controller.status==='idle');
 check(true,'normal initial Send returns both independent answers');
 await page.locator('#messageAction').selectOption('review');
 for(const mode of ['manual','auto']){
  await page.locator('#reviewRunMode').selectOption(mode);await page.locator('#intervention').fill('NEED_USER_ROUND_TEST '+mode);await page.locator('#sendIntervention').click();
  await page.waitForFunction(mode=>{const r=RC_DEBUG.getState().session.live.controller;return r.activeQuestion?.text==='NEED_USER_ROUND_TEST '+mode&&r.status==='paused'&&r.reason==='need_user'},mode);
  const s=await page.evaluate(()=>RC_DEBUG.getState().session),r=s.live.controller;
  const turns=r.turns.filter(t=>t.kind==='debate'&&t.round===r.round);
  check(turns.length===2&&new Set(turns.map(t=>t.id)).size===2,mode+' review finishes every member before need_user pause');
  const jobs=turns.map(t=>JSON.parse(fs.readFileSync(path.join(data,'jobs',t.jobId+'.json'))));
  check(jobs[1].request.transcript.some(t=>t.text===turns[0].text),'second reviewer sees the first answer in '+mode+' mode');
  check((await page.locator('#roundStatus').textContent()).includes('2/2'),'visible progress reaches 2/2 in '+mode+' mode');
  check(!r.experiments.length&&!r.pendingJob,'need_user pause starts no experiment or extra round');
 }
 const before=await page.evaluate(()=>RC_DEBUG.getState().session.live.controller.calls);
 await page.locator('#pauseBtn').click();await page.waitForFunction(()=>!RC_DEBUG.getState().session.paused);
 await page.locator('#nextSpeaker').click();await page.waitForFunction(n=>RC_DEBUG.getState().session.live.controller.calls===n+1&&RC_DEBUG.getState().session.live.controller.status!=='running',before);
 check((await page.evaluate(()=>RC_DEBUG.getState().session.live.controller.calls))===before+1,'explicit Next speaker still invokes only one member');
 check(errors.length===0,'no JavaScript errors');console.log(JSON.stringify({checks,errors},null,2));
}finally{if(browser)await browser.close();child.kill('SIGINT');await new Promise(r=>child.once('exit',r));fs.rmSync(data,{recursive:true,force:true})}})().catch(e=>{console.error(e);process.exitCode=1});
