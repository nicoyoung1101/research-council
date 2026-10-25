/* End-to-end thinking pause, partial answer preservation and explicit resume. Fixture calls only. */
const fs=require('fs'),path=require('path'),os=require('os'),{spawn}=require('child_process'),assert=require('assert/strict');
const {chromium}=require(path.join(process.env.RC_NODE_MODULES||path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'),'playwright'));
const root=path.resolve(__dirname,'..'),data=fs.mkdtempSync(path.join(os.tmpdir(),'council-pause-')),checks=[];
const check=(v,n)=>{assert.ok(v,n);checks.push(n)};
(async()=>{const child=spawn('python3',[path.join(__dirname,'ui_fixture.py'),data],{cwd:root});child.stderr.pipe(process.stderr);let browser;
try{
 const url=await new Promise((r,j)=>{child.stdout.once('data',b=>r(JSON.parse(b.toString()).url));child.once('exit',c=>j(Error('Fixture '+c)))});
 browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const context=await browser.newContext({viewport:{width:1500,height:1000},permissions:['clipboard-read','clipboard-write']}),page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(url);await page.waitForFunction(()=>!!window.RC_DEBUG);await page.locator('#langSelect').selectOption('en');await page.locator('#focusToggle').click();await page.locator('#newSession').click();
 await page.locator('#addAgentRail').click();await page.locator('#engineSelect').selectOption('live');await page.locator('.registry-card').first().locator('[data-field=rules]').fill('ACTIVITY_TEST');await page.locator('#registrySave').click();
 await page.locator('#intervention').fill('Review question test');await page.locator('#sendIntervention').click();await page.waitForFunction(()=>RC_DEBUG.getState().session.independentCount===2&&RC_DEBUG.getState().session.live.controller.status==='idle');
 await page.locator('#messageAction').selectOption('question');await page.locator('#intervention').fill('PAUSE_FIRST');await page.locator('#sendIntervention').click();
 await page.locator('[data-activity-agent=claude][data-activity-phase=searching]').waitFor();
 await page.waitForFunction(()=>RC_DEBUG.getState().session.live.controller.turns.some(t=>t.kind==='question'&&t.id==='codex'));
 await page.locator('#intervention').fill('PAUSE_QUEUED');await page.locator('#sendIntervention').click();await page.locator('[data-queued-question]').waitFor();
 await page.locator('#pauseBtn').click();
 await page.waitForFunction(()=>{const s=RC_DEBUG.getState().session;return s.paused&&s.live.controller.thinkingPaused&&s.live.controller.questions[0].status==='paused'});
 let state=await page.evaluate(()=>RC_DEBUG.getState().session),r=state.live.controller;
 check(r.questions.length===1&&r.questions[0].completedAgents.join(',')==='codex','pause retains the completed peer answer');
 const oldJob=r.questions[0].jobId;const job=await page.evaluate(id=>CouncilBridge.request('jobs/'+id),oldJob);check(job.status==='cancelled','pause stops the active backend job');
 await page.waitForTimeout(1000);check((await page.evaluate(()=>RC_DEBUG.getState().session.live.controller.questions.length))===1,'pause holds queued questions without calling models');
 check(await page.locator('.research-stop').textContent().then(x=>x.includes('Thinking paused')),'paused state is explicit beside the composer');
 await page.evaluate(()=>CouncilBridge.flush());await page.reload();await page.waitForFunction(()=>!!window.RC_DEBUG&&RC_DEBUG.getState().session.live.controller?.thinkingPaused);
 check(await page.locator('[data-queued-question]').textContent().then(x=>x.includes('Queue paused')),'queue remains paused across reload');
 const dataFile=path.join(data,'discussions',r.id+'.json');check(JSON.parse(fs.readFileSync(dataFile)).thinkingPaused,'pause is durable on disk');
 const pausedCalls=r.calls;await page.locator('#pauseBtn').click();
 await page.waitForFunction(()=>!RC_DEBUG.getState().session.live.controller.thinkingPaused);
 await page.waitForTimeout(900);r=await page.evaluate(()=>RC_DEBUG.getState().session.live.controller);
 check(r.calls===pausedCalls&&r.questions[0].status==='paused','Continue unlocks without restarting the model');
 check(r.questions.length===1,'Continue does not release queued questions');
 check(await page.locator('#nextSpeaker').isEnabled(),'Next speaker becomes available after Continue');
 await page.evaluate(()=>CouncilBridge.flush());await page.reload();await page.waitForFunction(()=>!!window.RC_DEBUG&&RC_DEBUG.getState().session.live.controller?.dispatchHeld);
 check((await page.evaluate(()=>RC_DEBUG.getState().session.live.controller.calls))===pausedCalls,'unlocked waiting state survives reload without a model call');
 await page.locator('#nextSpeaker').click();await page.waitForFunction(()=>RC_DEBUG.getState().session.live.controller.questions[0].status==='complete');
 r=await page.evaluate(()=>RC_DEBUG.getState().session.live.controller);
 check(r.calls===pausedCalls+1&&r.questions[0].completedAgents.includes('claude'),'Next speaker restarts only the original unfinished member');
 await page.waitForTimeout(700);check((await page.evaluate(()=>RC_DEBUG.getState().session.live.controller.questions.length))===1,'one-member continuation still holds queued questions');
 await page.locator('#sendIntervention').click();
 await page.waitForFunction(()=>{const r=RC_DEBUG.getState().session.live.controller;return r.questions.length===2&&r.questions.every(q=>q.status==='complete')});
 r=await page.evaluate(()=>RC_DEBUG.getState().session.live.controller);
 check(r.questions[0].previousJobs.includes(oldJob)&&r.calls===7,'explicit empty Send releases the queued question');
 check(r.turns.filter(t=>t.kind==='question'&&t.id==='codex').length===2,'continue never duplicates the already completed peer answer');
 check(r.turns.filter(t=>t.type==='user'&&t.text==='PAUSE_FIRST').length===1,'continue retains one original question');
 for(const [locale,label] of [['zh','已暂停思考'],['ja','一時停止'],['en','Thinking paused']]){await page.locator('#langSelect').selectOption(locale);await page.locator('#pauseBtn').click();await page.waitForFunction(()=>RC_DEBUG.getState().session.live.controller.thinkingPaused);check((await page.locator('.research-stop').textContent()).includes(label),'pause localized in '+locale);await page.locator('#pauseBtn').click();await page.waitForFunction(()=>!RC_DEBUG.getState().session.live.controller.thinkingPaused)}
 for(const theme of ['light','dark']){await page.locator('#themeSelect').selectOption(theme);check(await page.locator('html').getAttribute('data-theme')===theme,'pause preserves '+theme+' theme')}
 check(errors.length===0,'no JavaScript errors');console.log(JSON.stringify({checks,errors},null,2));
}finally{if(browser)await browser.close();child.kill('SIGINT');await new Promise(r=>child.once('exit',r));fs.rmSync(data,{recursive:true,force:true})}})().catch(e=>{console.error(e);process.exitCode=1});
