/* Current-question handoff and reply attribution. Fixture calls only. */
const fs=require('fs'),path=require('path'),os=require('os'),{spawn}=require('child_process'),assert=require('assert/strict');
const {chromium}=require(path.join(process.env.RC_NODE_MODULES||path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'),'playwright'));
const root=path.resolve(__dirname,'..'),data=fs.mkdtempSync(path.join(os.tmpdir(),'council-focus-')),checks=[];
const check=(v,n)=>{assert.ok(v,n);checks.push(n)};
(async()=>{const child=spawn('python3',[path.join(__dirname,'ui_fixture.py'),data],{cwd:root});child.stderr.pipe(process.stderr);let browser;
try{
 const url=await new Promise((r,j)=>{child.stdout.once('data',b=>r(JSON.parse(b.toString()).url));child.once('exit',c=>j(Error('Fixture '+c)))});
 browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const context=await browser.newContext({viewport:{width:1500,height:1000},permissions:['clipboard-read','clipboard-write']}),page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(url);await page.waitForFunction(()=>!!window.RC_DEBUG);await page.locator('#langSelect').selectOption('en');await page.locator('#focusToggle').click();await page.locator('#newSession').click();
 await page.locator('#addAgentRail').click();await page.locator('#engineSelect').selectOption('live');await page.locator('.registry-card').first().locator('[data-field=rules]').fill('SLOW_TEST');await page.locator('#registrySave').click();
 await page.locator('#intervention').fill('Review question test');await page.locator('#sendIntervention').click();await page.waitForFunction(()=>RC_DEBUG.getState().session.independentCount===2&&RC_DEBUG.getState().session.live.controller.status==='idle');
 await page.locator('#messageAction').selectOption('review');await page.locator('#reviewRunMode').selectOption('auto');await page.locator('#intervention').fill('OLD_TASK prepare presentation');await page.locator('#sendIntervention').click();
 await page.waitForFunction(()=>RC_DEBUG.getState().session.live.controller?.status==='running'&&RC_DEBUG.getState().session.live.controller.pendingJob);
 const old=await page.evaluate(()=>RC_DEBUG.getState().session.live.controller.pendingJob);
 await page.locator('#intervention').fill('NEW_TASK quick AutoDL experiment, no presentation');await page.locator('#messageAction').selectOption('question');await page.locator('#sendIntervention').click();
 await page.waitForFunction(()=>{const r=RC_DEBUG.getState().session.live.controller;return r.questions?.[0]?.status==='complete'&&r.status==='idle'});
 let s=await page.evaluate(()=>RC_DEBUG.getState().session),r=s.live.controller;
 check(JSON.parse(fs.readFileSync(path.join(data,'jobs',old+'.json'))).status==='cancelled','new shared question cancels the previous automatic review');
 check(r.reason==='new_question'&&r.plan===null&&!Object.keys(r.reviews).length,'old approvals cannot mark the new question ready');
 check((await page.locator('.current-question').textContent()).includes('NEW_TASK')&&(await page.locator('#title').textContent()).includes('NEW_TASK'),'current question is visible in the header and research record');
 check(await page.locator('[data-flow-detail=opening-history]').count()===1&&await page.locator('[data-flow-detail=opening-history]').getAttribute('open')===null,'initial answers remain available as collapsed history rather than answers to the new question');const qid=r.questions[0].id;check(r.turns.filter(t=>t.kind==='question').every(t=>t.replyTo===qid),'every new answer identifies its exact question');
 check(await page.locator(`[data-reply-to="${qid}"]`).count()===2,'both answers show a clickable reference to the same question');
 await page.locator('#messageAction').selectOption('review');await page.locator('#intervention').fill('REVIEW_CURRENT_TASK focus on one GPU and two baselines');await page.locator('#sendIntervention').click();await page.locator('[data-controller-status=ready]').waitFor();
 r=await page.evaluate(()=>RC_DEBUG.getState().session.live.controller);const reviews=r.jobs.map(id=>JSON.parse(fs.readFileSync(path.join(data,'jobs',id+'.json')))).filter(j=>j.request.kind==='debate'&&j.request.focusMessageId===r.activeQuestion.id);
 check(reviews.length===2&&reviews.every(j=>j.request.question==='REVIEW_CURRENT_TASK focus on one GPU and two baselines'),'both peer reviews use the latest message as their main task');
 check(reviews.every(j=>j.request.researchQuestion==='Review question test'),'original research topic remains reference context');
 check(reviews.every(j=>j.request.focusRevision===r.focusRevision),'approvals are bound to the current task revision');
 await page.locator('#messageAction').selectOption('question');await page.locator('#intervention').fill('THIRD_TASK');await page.locator('#sendIntervention').click();await page.waitForFunction(()=>RC_DEBUG.getState().session.live.controller.questions.length===2);
 await page.locator('#intervention').fill('FOURTH_TASK');await page.locator('#sendIntervention').click();await page.locator('[data-queued-question]').waitFor();
 await page.waitForFunction(()=>{const r=RC_DEBUG.getState().session.live.controller;return r.questions.length===3&&r.questions.every(q=>q.status==='complete')});
 s=await page.evaluate(()=>RC_DEBUG.getState().session);r=s.live.controller;const third=r.questions[1].id,fourth=r.questions[2].id;
 const order=await page.locator('.timeline [data-turn-index]').evaluateAll(els=>els.map(e=>Number(e.dataset.turnIndex)));const index=id=>s.shownTurns.findIndex(t=>t.type==='user'&&t.id===id),thirdReplies=s.shownTurns.flatMap((t,i)=>t.replyTo===third?[i]:[]);
 check(thirdReplies.every(i=>order.indexOf(i)>order.indexOf(index(third))&&order.indexOf(i)<order.indexOf(index(fourth))),'queued questions keep their own answers grouped before the following question');
 check(s.shownTurns.filter(t=>t.kind==='question').every(t=>t.replyTo),'no question reply is left without attribution');
 await page.locator(`[data-reply-to="${fourth}"]`).first().click();check(await page.locator(`[data-turn-index="${index(fourth)}"]`).isVisible(),'answer reference returns to its source question');
 const count=r.calls;await page.evaluate(()=>CouncilBridge.flush());await page.reload();await page.waitForFunction(id=>!!window.RC_DEBUG&&RC_DEBUG.getState().session.live.controller?.activeQuestion?.id===id,fourth);
 check((await page.locator('.current-question').textContent()).includes('FOURTH_TASK'),'latest task survives reload');
 check((await page.evaluate(()=>RC_DEBUG.getState().session.live.controller.calls))===count,'reload does not rerun an old task');
 for(const [locale,label] of [['zh','当前问题'],['ja','現在の質問'],['en','Current question']]){await page.locator('#langSelect').selectOption(locale);check((await page.locator('.current-question').textContent()).includes(label),'current-question label localized in '+locale)}
 for(const theme of ['light','dark']){await page.locator('#themeSelect').selectOption(theme);check(await page.locator('html').getAttribute('data-theme')===theme,'question handoff preserves '+theme+' theme')}
 check(errors.length===0,'no JavaScript errors');console.log(JSON.stringify({checks,errors},null,2));
}finally{if(browser)await browser.close();child.kill('SIGINT');await new Promise(r=>child.once('exit',r));fs.rmSync(data,{recursive:true,force:true})}})().catch(e=>{console.error(e);process.exitCode=1});
