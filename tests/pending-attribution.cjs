/* Legacy local message chronology and pending reply attribution. Fixture only. */
const fs=require('fs'),path=require('path'),os=require('os'),{spawn}=require('child_process'),assert=require('assert/strict');
const {chromium}=require(path.join(process.env.RC_NODE_MODULES||path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'),'playwright'));
const root=path.resolve(__dirname,'..'),data=fs.mkdtempSync(path.join(os.tmpdir(),'council-pending-attribution-')),checks=[];
const check=(v,n)=>{assert.ok(v,n);checks.push(n)};
(async()=>{const child=spawn('python3',[path.join(__dirname,'ui_fixture.py'),data],{cwd:root});child.stderr.pipe(process.stderr);let browser;
try{
 const url=await new Promise((r,j)=>{child.stdout.once('data',b=>r(JSON.parse(b.toString()).url));child.once('exit',c=>j(Error('Fixture '+c)))});
 browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const page=await browser.newPage({viewport:{width:1500,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto(url);await page.waitForFunction(()=>!!window.RC_DEBUG);await page.locator('#focusToggle').click();
 await page.locator('#newSession').click();await page.locator('#addAgentRail').click();await page.locator('#engineSelect').selectOption('live');await page.locator('#registrySave').click();
 await page.locator('#intervention').fill('A reproducible question');await page.locator('#sendIntervention').click();await page.waitForFunction(()=>RC_DEBUG.getState().session.independentCount===2&&RC_DEBUG.getState().session.live.controller.status==='idle');
 await page.evaluate(()=>{const s=RC_DEBUG.getState().session;s.shownTurns.push({id:'legacy-review',type:'user',action:'review',text:'OLD presentation deadline',to:'all',round:1,at:Date.now()/1000-100})});
 await page.locator('#messageAction').selectOption('review');await page.locator('#reviewRunMode').selectOption('manual');await page.locator('#intervention').fill('PENDING_ATTRIBUTION_TEST review each other and decide next steps');await page.locator('#sendIntervention').click();
 await page.waitForFunction(()=>{const v=RC_DEBUG.getState().session.live;return v.callAgents?.some(a=>a.id==='codex')&&v.pending});
 const current=await page.evaluate(()=>RC_DEBUG.getState().session.live.controller.activeQuestion.id);
 let pending=page.locator('[data-flow-item=pending-codex]');await pending.waitFor();
 check((await pending.locator('[data-reply-to]').getAttribute('data-reply-to'))===current,'thinking card explicitly references the current question');
 check((await pending.textContent()).includes('review each other')&&!(await pending.textContent()).includes('presentation'),'pending source label does not show the obsolete request');
 let s=await page.evaluate(()=>RC_DEBUG.getState().session);
 check(s.shownTurns.findIndex(t=>t.id==='legacy-review')<s.shownTurns.findIndex(t=>t.id===current),'local-only historical question is restored before the current question');
 check(s.shownTurns.filter(t=>t.id==='legacy-review').length===1,'historical message remains present exactly once');
 // A newer frontend-only row must not steal the active call either.
 await page.evaluate(()=>{const s=RC_DEBUG.getState().session;s.shownTurns.push({id:'local-later',type:'user',action:'question',text:'Later saved local question',to:'all',round:1,at:Date.now()/1000+100});});
 await page.waitForFunction(()=>document.querySelector('.timeline')?.textContent.includes('Later saved local question'));
 const position=await page.locator('.timeline').evaluate(el=>{const rows=[...el.children],p=el.querySelector('[data-flow-item=pending-codex]'),later=[...el.querySelectorAll('.user-turn')].find(e=>e.textContent.includes('Later saved local question'));return rows.indexOf(p)<rows.indexOf(later)});
 check(position,'pending reply is grouped with its question before a later local row');
 await page.evaluate(()=>CouncilBridge.flush());await page.reload();await page.locator('[data-flow-item=pending-codex]').waitFor();
 check((await page.locator('[data-flow-item=pending-codex] [data-reply-to]').getAttribute('data-reply-to'))===current,'pending question attribution survives reload');
 await page.waitForFunction(()=>RC_DEBUG.getState().session.live.controller.status==='ready');
 s=await page.evaluate(()=>RC_DEBUG.getState().session);
 check(s.shownTurns.filter(t=>t.kind==='debate').every(t=>t.replyTo===current),'completed replies retain the same question as their thinking cards');
 check(await page.locator('[data-flow-item=pending-codex]').count()===0,'thinking placeholder disappears when the answer returns');
 check(s.shownTurns.filter(t=>t.id==='legacy-review').length===1,'repeated sync and reload neither duplicate nor delete the old message');
 const job=JSON.parse(fs.readFileSync(path.join(data,'jobs',s.live.lastJob+'.json')));
 check(job.request.question==='PENDING_ATTRIBUTION_TEST review each other and decide next steps','actual model input remains the exact current question');
 check(errors.length===0,'no JavaScript errors');console.log(JSON.stringify({checks,errors},null,2));
}finally{if(browser)await browser.close();child.kill('SIGINT');await new Promise(r=>child.once('exit',r));fs.rmSync(data,{recursive:true,force:true})}})().catch(e=>{console.error(e);process.exitCode=1});
