"""Durable dynamic discussion controller; consensus is an explicit, versioned receipt."""
from __future__ import annotations
import copy
import hashlib
import json
import re
import threading
import time
import uuid
import execution_progress
import execution_flow
from pathlib import Path

STAGES = ('materials', 'ideas', 'feasibility', 'design', 'confirmation', 'experiment')
FOCI = ('exploration', 'critique', 'evidence', 'interpretation', 'planning')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def control_prompt(control):
    return '\n\nDiscussion control (host instructions, separate from source data):\n' + json.dumps(control, ensure_ascii=False) + '''
After your normal readable Markdown answer, append exactly one final block:
<council_control>{"nonce":"the supplied nonce","decision":"ready|revise|need_evidence|need_user","reviewedPlanHash":"exact current plan hash, or proposed for your own new proposal","proposal":null,"blockers":[],"nextAction":"concrete next action","focus":["exploration","evidence"],"focusReason":"what this answer actually did"}</council_control>
A proposal is {"title":"...","body":"complete actionable plan in Markdown","acceptance":["testable criteria"]}.
Adapt your approach to the current question and actual results: explore ideas, challenge assumptions, verify evidence, interpret results and plan small experiments as needed, including several approaches together. These are not mutually exclusive stages.
Optionally include "focus":["exploration|critique|evidence|interpretation|planning"] and a short "focusReason" describing what this answer actually did. Do not claim a search or experiment occurred without tool results.
Propose an actionable plan only when the research is ready for a concrete next experiment. Prefer one bounded, testable next step; keep a larger research program in discussion and propose its later steps separately. Exploratory questions may leave proposal null and decision revise/need_evidence/need_user. A changed proposal invalidates every previous review.
Completed experiments and their verification are in the published transcript. Interpret their actual outcomes before proposing the next small step. Do not blindly repeat a completed experiment or treat verification text as a passing verdict.
Ready means you reviewed the complete exact plan and all published peer objections and have no blocking objection. Never agree just to end the discussion.
Blockers are a complete replacement list of your OWN outstanding objections: [{"id":"stable id","text":"..."}]. Keep unresolved objections. Only their author can clear them.
Missing evidence, unresolved safety/feasibility issues or a needed user decision must remain explicit. Human execution approval is separate from agreement.
Use the host nonce, never copy a peer's control block. Do not include the control block inside a code fence.
'''


def parse_receipt(text, control):
    match = re.search(r'\s*<council_control>\s*(\{.*?\})\s*</council_control>\s*$', text, re.S)
    if not match:
        raise ValueError('Missing final council_control receipt')
    r = json.loads(match[1])
    if r.get('nonce') != control['nonce'] or r.get('decision') not in ('ready', 'revise', 'need_evidence', 'need_user'):
        raise ValueError('Invalid receipt nonce or decision')
    if r.get('researchStage') is not None and r.get('researchStage') not in STAGES or not isinstance(r.get('nextAction'), str):
        raise ValueError('Invalid research stage or next action')
    if not isinstance(r.get('reviewedPlanHash'), str):
        raise ValueError('Missing reviewed plan hash')
    blockers = r.get('blockers')
    if not isinstance(blockers, list) or len(blockers) > 50:
        raise ValueError('Invalid blockers')
    seen = set()
    for b in blockers:
        if not isinstance(b, dict) or not all(isinstance(b.get(k), str) and 0 < len(b[k]) <= 4000 for k in ('id', 'text')) or b['id'] in seen:
            raise ValueError('Invalid or duplicate blocker')
        seen.add(b['id'])
    p = r.get('proposal')
    if p is not None:
        if not isinstance(p, dict) or not all(isinstance(p.get(k), str) and p[k].strip() for k in ('title', 'body')) or len(p['body']) > 100000:
            raise ValueError('Proposal must include a complete title and body')
        if not isinstance(p.get('acceptance'), list) or not p['acceptance'] or not all(isinstance(x, str) and x.strip() for x in p['acceptance']):
            raise ValueError('Proposal needs testable acceptance criteria')
        r['proposal'] = {k: p[k] for k in ('title', 'body', 'acceptance')}
    if r['decision'] == 'ready' and blockers:
        raise ValueError('Ready receipt still has blockers')
    if 'focus' in r and (not isinstance(r['focus'], list) or not 1 <= len(r['focus']) <= 5 or any(x not in FOCI for x in r['focus'])):
        raise ValueError('Invalid discussion focus')
    if 'focusReason' in r and (not isinstance(r['focusReason'], str) or len(r['focusReason']) > 1000):
        raise ValueError('Invalid focus explanation')
    return text[:match.start()].rstrip(), r


class Controller:
    def __init__(self, council, atomic, error):
        self.c, self.atomic, self.Error = council, atomic, error
        self.runs, self.threads = {}, []
        self.stopping = threading.Event()
        for p in (council.data_dir/'discussions').glob('*.json'):
            r = json.loads(p.read_text())
            r['budgets'] = {'calls': 0, 'seconds': 0, 'unlimited': True}
            if r.get('reason') == 'budget_reached':
                r.update(status='idle', reason=None, error=None)
            atomic(p, r)
            if r.get('synthesis') and not any(t.get('kind') == 'synthesis' for t in r['turns']):
                result = r['synthesis']
                r['turns'].append(dict(type='agent', kind='synthesis', id=result['agentId'], text=result['text'], result=result, round=r['round']))
            if r.get('execution') and not r.get('experiments'):
                plan = next((x for x in r['plans'] if x['hash'] == r.get('executionPlanHash')), r.get('plan'))
                if plan:
                    task = dict(id='legacy-'+r['id'], plan=copy.deepcopy(plan), created=r['created'],
                                status='reviewed' if r.get('verification') else 'interrupted',
                                execution=r['execution'], executor=r['execution']['agentId'],
                                jobs=[j for j in r['jobs'] if self.c.jobs.get(j, {}).get('request', {}).get('kind') in ('execution', 'verification')])
                    if r.get('verification'):
                        task['verification'] = r['verification']; task['reviewer'] = r['verification']['agentId']
                    r['experiments'] = [task]
                    r['turns'].append(dict(type='experiment', id='experiment-'+task['id'], taskId=task['id'], round=r['round']))
            if r['status'] == 'running':
                r.update(status='paused', reason='interrupted', auto=False)
                interrupted_task = False
                for task in r.get('experiments', []):
                    if task['status'] in ('running', 'verifying'):
                        task.update(status='interrupted', finished=time.time())
                        if task.get('workflowVersion'):execution_flow.recover(task,self.c.jobs)
                        interrupted_task = True
                if interrupted_task:
                    r.pop('activeExperiment', None)
                    r.update(reviews={}, phase='debate', round=r['round']+1, cycleSignatures=[])
                atomic(p, r)
            self.recover_questions(r)
            if r.get('deferredFocus') and not r.get('activeExperiment'):
                self.set_focus(r, r.pop('deferredFocus'))
            # Recover the latest shared question in older records without running it again.
            if 'focusRevision' not in r:
                latest = next((q['message'] for q in reversed(r.get('questions', []))
                               if q['message'].get('to', 'all') == 'all'), None)
                if latest and not r.get('activeExperiment'):
                    self.set_focus(r, latest)
                    if r['status'] == 'paused':
                        r['reason'] = 'new_question'
                else:
                    r['focusRevision'] = 0
            atomic(p, r)
            self.runs[r['id']] = r

    def recover_questions(self, r):
        for question in r.get('questions', []):
            if question['status'] == 'running':
                job = self.c.jobs.get(question['jobId'])
                if job:
                    self.merge_question(r, question, job)
                else:
                    question['status'] = 'interrupted'

    def persist(self, r):
        r['updated'] = time.time()
        self.atomic(self.c.data_dir/'discussions'/(r['id']+'.json'), r)

    def public(self, r):
        with self.c.lock:
            result = copy.deepcopy(r)
            questions = {jid: q['id'] for q in r.get('questions', [])
                         for jid in [q['jobId'], *q.get('previousJobs', [])]}
            for turn in result['turns']:
                if turn.get('kind') == 'question' and turn.get('jobId') in questions:
                    turn.setdefault('replyTo', questions[turn['jobId']])
                if turn.get('kind') in ('debate', 'synthesis') and turn.get('jobId'):
                    request = self.c.jobs.get(turn['jobId'], {}).get('request', {})
                    if request.get('focusRevision', 0) != r.get('focusRevision', 0):
                        turn['superseded'] = True
                    if not turn.get('replyTo'):
                        parents = {t['id'] for t in r['turns'] if t['type'] == 'user' and t.get('id')}
                        mentioned = [t for t in [*request.get('transcript', []), *request.get('moderator', [])]
                                     if t.get('type') == 'user' and t.get('id') in parents and t.get('to', 'all') == 'all']
                        if request.get('focusMessageId') in parents:
                            turn['replyTo'] = request['focusMessageId']
                        elif mentioned:
                            turn['replyTo'] = max(mentioned, key=lambda t: t.get('at', 0) if isinstance(t.get('at'), (int, float)) else 0)['id']
            order = self.speaker_order(r)
            remaining = [a for a in order if not any(t.get('kind', 'debate') == 'debate' and
                t.get('id') == a['id'] and t.get('round') == r['round'] and not t.get('superseded')
                for t in r['turns'])]
            if r['phase'] == 'independent':
                remaining = [a for a in self.debaters(r) if a['id'] not in r['independent']] or remaining
            next_agent = (remaining or order)[0] if order else None
            paused_question = next((q for q in r.get('questions', []) if q['status'] == 'paused' and not q.get('superseded')), None)
            if paused_question:
                next_agent = next((a for a in self.question_request(paused_question)['agents']
                                   if a['id'] not in paused_question.get('completedAgents', [])), next_agent)
            result['nextSpeaker'] = {k: next_agent[k] for k in ('id', 'name')} if next_agent else None
            for task in result.get('experiments', []):
                task['activities'] = [execution_progress.activity(self.c.jobs[jid]) for jid in task.get('jobs', []) if jid in self.c.jobs]
            resumable = self.resumable_experiment(r)
            result['resumableExperiment'] = {k: resumable[k] for k in ('id', 'executor', 'reviewer')} | dict(
                planHash=resumable['plan']['hash'], title=resumable['plan']['proposal']['title'], status=resumable['status'], requiresDecision=execution_flow.needs_decision(resumable)) if resumable else None
            result['executionReview'] = self.execution_review(r)
            return result

    def resumable_experiment(self, r):
        task = (r.get('experiments') or [None])[-1]
        if (r['request'].get('profile') == 'native' and not r.get('activeExperiment') and task and
            task['status'] in ('failed', 'interrupted', 'needs_decision', 'reviewed') and task.get('approval')):
            return task
        return None

    def execution_candidate(self, r):
        # Recover proposals lost by older focus changes, never a task already attempted.
        cutoff = max((t.get('created', 0) for t in r.get('experiments', [])), default=0)
        used = {t['plan']['hash'] for t in r.get('experiments', [])}
        for plan in [r.get('plan'), *reversed(r.get('plans', []))]:
            if plan and plan['hash'] not in used and plan.get('created', 0) > cutoff:
                return copy.deepcopy(plan)
        return None

    def execution_review(self, r):
        candidate = self.execution_candidate(r)
        issues = []
        for a in self.debaters(r):
            aid = a['id']
            blockers = r['blockers'].get(aid, [])
            for b in blockers:
                issues.append(dict(key=digest([aid, b['id'], b['text']]), agentId=aid,
                                   name=a['name'], text=b['text'], kind='blocker'))
            review = r['reviews'].get(aid)
            valid = bool(review and candidate and review.get('valid') and
                         review.get('planHash') == candidate['hash'])
            if not blockers and (not valid or review.get('decision') != 'ready'):
                issues.append(dict(key=digest([aid, review]), agentId=aid, name=a['name'],
                                   text=review.get('nextAction', '') if review else '',
                                   kind='review' if valid else 'unreviewed'))
        token = digest(dict(candidate=candidate, issues=issues, generation=r['generation'],
                            focusRevision=r.get('focusRevision'), reviews=r['reviews'],
                            moderator=r['moderator'], turns=r['turns'], independent=r['independent'],
                            questions=r.get('questions', []), experiments=r.get('experiments', [])))
        return dict(candidate=candidate, issues=issues, token=token,
                    recovered=bool(candidate and not r.get('plan')), unanimous=self.ready(r))

    def human_execution(self, r, approval):
        review = self.execution_review(r)
        if not isinstance(approval, dict) or approval.get('token') != review['token'] or not review['candidate']:
            raise self.Error('invalid_request', 'Plan or discussion changed; reopen execution confirmation')
        proposal = approval.get('proposal')
        if (not isinstance(proposal, dict) or set(proposal) != {'title', 'body', 'acceptance'} or
            not all(isinstance(proposal.get(k), str) and proposal[k].strip() and len(proposal[k]) <= 100000 for k in ('title', 'body')) or
            not isinstance(proposal.get('acceptance'), list) or not 1 <= len(proposal['acceptance']) <= 100 or
            not all(isinstance(x, str) and x.strip() and len(x) <= 4000 for x in proposal['acceptance'])):
            raise self.Error('invalid_request', 'Confirm a complete plan and testable acceptance criteria')
        decisions = approval.get('decisions')
        preflight=approval.get('issuePolicy')=='review_first'
        if approval.get('issuePolicy') not in (None,'review_first'):
            raise self.Error('invalid_request','Unknown execution issue policy')
        if not isinstance(decisions, dict) or (not set(decisions).issubset({i['key'] for i in review['issues']}) if preflight else set(decisions) != {i['key'] for i in review['issues']}) or not all(
                isinstance(v, str) and v.strip() and len(v) <= 8000 for v in decisions.values()):
            raise self.Error('invalid_request', 'Provide an explicit decision for every outstanding issue')
        record = dict(kind='human_confirmed', candidateHash=review['candidate']['hash'],
                      reviewToken=review['token'], at=time.time(), peerUnanimous=review['unanimous'],
                      edited=proposal != review['candidate']['proposal'],
                      preflightRequired=preflight and bool(review['issues'] or proposal!=review['candidate']['proposal']),
                      issues=[dict(i, resolution=decisions.get(i['key'],'Independent preflight must resolve this issue before affected operations; preserve the approved scope and stop for a substantive user decision.'), deferredToVerifier=i['key'] not in decisions) for i in review['issues']],
                      peerReviews=copy.deepcopy(r['reviews']), peerBlockers=copy.deepcopy(r['blockers']))
        # Hash the decisions as well as the exact plan. Peer objections remain in the audit.
        plan = dict(version=len(r['plans'])+1, hash=digest(dict(proposal=proposal, approval=record)),
                    proposal=copy.deepcopy(proposal), created=time.time())
        return plan, record

    def set_focus(self, r, message):
        if r.get('activeQuestion', {}).get('id') == message['id']:
            return
        if r.get('plan') or r.get('activeQuestion'):
            r.setdefault('focusHistory', []).append(dict(
                question=copy.deepcopy(r.get('activeQuestion')), planHash=(r.get('plan') or {}).get('hash'),
                reviews=copy.deepcopy(r['reviews']), blockers=copy.deepcopy(r['blockers']), round=r['round']))
        candidate = self.execution_candidate(r)
        origin = copy.deepcopy((candidate or {}).get('retainedFromQuestion') or
                               r.get('activeQuestion') or {'text': r['request']['question']})
        r['activeQuestion'] = copy.deepcopy(message)
        r.pop('speakerStart', None)
        r.pop('reviewTarget', None)
        r['focusRevision'] = r.get('focusRevision', 0)+1
        r['generation'] += 1
        r.update(plan=None, reviews={}, phase='debate', round=r['round']+1, cycleSignatures=[])
        if candidate:
            self.plan(r, candidate['proposal'])
            r['plan']['retainedFromQuestion'] = origin
            r['plans'][-1] = copy.deepcopy(r['plan'])
        r.pop('needUser', None)
        r.pop('reviewError', None)
        r.pop('resumeAction', None)
        for q in r.get('questions', []):
            if q['status'] == 'paused':
                q['superseded'] = True
        if 'queuedModerator' in r:
            r['moderator'] = r.pop('queuedModerator')

    def validate_message(self, message):
        if not isinstance(message, dict) or not isinstance(message.get('id'), str) or not 1 <= len(message['id']) <= 120 or not isinstance(message.get('text'), str) or not message['text'].strip() or len(message['text']) > 100000:
            raise self.Error('invalid_request', 'Question requires an id and text')

    def create(self, body):
        from_request = copy.deepcopy(body)
        from_request.update(kind='independent', agents=[a for a in body.get('roster', []) if a.get('enabled') and a.get('role') == 'debater'])
        self.c.validate(from_request)
        if not isinstance(body.get('sessionId'), str) or not 1 <= len(body['sessionId']) <= 120:
            raise self.Error('invalid_request', 'sessionId required')
        if len(from_request['agents']) < 2:
            raise self.Error('invalid_request', 'Dynamic discussion requires at least two debaters')
        roster = body.get('roster', [])
        self.c.validate({**from_request, 'agents': roster})
        with self.c.lock:
            key = body.get('requestId')
            for r in self.runs.values():
                if key and r['request'].get('requestId') == key:
                    if r['request'] != body:
                        raise self.Error('invalid_request', 'requestId already used')
                    return self.public(r)
            if any(r['sessionId'] == body.get('sessionId') and r['status'] == 'running' for r in self.runs.values()):
                raise self.Error('busy')
            rid = uuid.uuid4().hex
            custom = body.get('workspace', '')
            if custom:
                path = Path(custom).expanduser()
                if not path.is_absolute() or not path.is_dir():
                    raise self.Error('invalid_request', 'Workspace must be an existing absolute directory')
                workspace = path.resolve()
            else:
                workspace = (self.c.data_dir/'workspaces'/rid).resolve()
                workspace.mkdir(parents=True, mode=0o700)
            # Discussion runs have no local time or call-count cap.
            calls, seconds = 0, 0
            r = dict(id=rid, sessionId=body['sessionId'], request=copy.deepcopy(body), workspace=str(workspace),
                     roster=copy.deepcopy(roster), independent={}, turns=[], context=None, phase='independent', round=1,
                     status='idle', reason=None, plan=None, plans=[], reviews={}, blockers={}, jobs=[], calls=0,
                     elapsed=0, budgets={'calls': calls, 'seconds': seconds, 'unlimited': True}, created=time.time(), pendingJob=None,
                     auto=False, generation=0, focusRevision=0, cycleSignatures=[], moderator=copy.deepcopy(body.get('moderator', [])))
            # Published legacy answers are reference data, never execution approvals.
            history = body.get('history', {})
            if not isinstance(history, dict) or len(json.dumps(history)) > 2000000:
                raise self.Error('invalid_request', 'Invalid published history')
            independent, turns = history.get('independent', {}), history.get('turns', [])
            if not isinstance(independent, dict) or not isinstance(turns, list):
                raise self.Error('invalid_request', 'Invalid published history')
            valid_ids = {a['id'] for a in from_request['agents']}
            for aid, result in independent.items():
                if aid not in valid_ids or not isinstance(result, dict) or not isinstance(result.get('text'), str):
                    raise self.Error('invalid_request', 'Invalid independent history')
            for turn in turns:
                if not isinstance(turn, dict) or turn.get('type') not in ('user', 'agent') or not isinstance(turn.get('text'), str) or turn.get('type') == 'agent' and turn.get('id') not in valid_ids:
                    raise self.Error('invalid_request', 'Invalid published turn')
            r['independent'] = copy.deepcopy(independent)
            r['turns'] = copy.deepcopy(turns)
            if len(independent) == len(valid_ids):
                r['phase'] = 'debate'
                r['round'] = max([int(t.get('round', 0)) for t in turns] + [0]) + 1
            r['experiments'], r['questions'] = [], []
            self.runs[rid] = r
            self.persist(r)
            return self.public(r)

    def action(self, rid, body):
        with self.c.lock:
            r = self.runs[rid]
            action = body.get('action')
            resuming = None
            if action == 'resume_experiment':
                key = body.get('requestId')
                if not isinstance(key, str) or not 1 <= len(key) <= 120:
                    raise self.Error('invalid_request', 'Explicit experiment resume request required')
                prior = next((t for t in r.get('experiments', []) if t.get('resumeRequestId') == key), None)
                if prior:
                    if prior.get('resumedFrom') != body.get('taskId') or prior['plan']['hash'] != body.get('planHash'):
                        raise self.Error('invalid_request', 'Resume request does not match the original task')
                    return self.public(r)
                resuming = self.resumable_experiment(r)
                if not resuming or resuming['id'] != body.get('taskId') or resuming['plan']['hash'] != body.get('planHash'):
                    raise self.Error('invalid_request', 'Only the latest failed or interrupted approved experiment can resume')
                if resuming.get('workflowVersion'):
                    execution_flow.recover(resuming,self.c.jobs)
                decision=body.get('decision','')
                continuation=body.get('continuationMode')
                if continuation not in (None,'verify_existing'):
                    raise self.Error('invalid_request','Unknown experiment continuation policy')
                if not isinstance(decision,str) or len(decision)>8000 or execution_flow.needs_decision(resuming) and not decision.strip() and continuation!='verify_existing':
                    raise self.Error('invalid_request','Provide a decision before continuing the same approved scope')
                text = body.get('text', '').strip() if isinstance(body.get('text', ''), str) else ''
                if text and not re.fullmatch(r'(继续|继续执行|继续实验|恢复执行|恢复实验|重试|continue|resume|resume experiment|continue experiment|再開|実験を再開)[。.!！?？\s]*', text, re.I):
                    raise self.Error('invalid_request', 'Review new instructions before changing the approved experiment scope')
                action = 'execute'
            if body.get('preference') in ('adaptive', 'critical', 'innovation', 'evidence'):
                r['request']['mode'] = body['preference']
            if 'codexPermissionMode' in body:
                if body['codexPermissionMode'] not in ('read-only','full'):
                    raise self.Error('invalid_request', 'Unsupported Codex permission mode')
                r['request']['codexPermissionMode'] = body['codexPermissionMode']
            if 'claudePermissionMode' in body:
                if body['claudePermissionMode'] not in ('auto','manual'):
                    raise self.Error('invalid_request', 'Unsupported Claude approval mode')
                r['request']['claudePermissionMode'] = body['claudePermissionMode']
            if action in ('question', 'independent'):
                return self.ask(r, body, independent=action == 'independent')
            if action == 'pause':
                r['auto'] = False
                r['pauseRequested'] = True
                r['focusPause'] = False
                r['thinkingPaused'] = True
                r['dispatchHeld'] = True
                for q in r.get('questions', []):
                    if q['status'] == 'running':
                        q['pauseRequested'] = True
                        self.c.cancel(q['jobId'])
                if r.get('pendingJob'):
                    self.c.cancel(r['pendingJob'])
                if r['status'] != 'running':
                    r.update(status='paused', reason='user')
                self.persist(r)
                return self.public(r)
            if action == 'resume':
                if r['status'] == 'running' or any(q['status'] == 'running' for q in r.get('questions', [])):
                    raise self.Error('busy', 'Wait for current calls to stop before continuing')
                # Unlock the controls only. A subsequent explicit dispatch starts a call.
                r.update(thinkingPaused=False, pauseRequested=False, dispatchHeld=True, error=None,
                         status='ready' if self.ready(r) and not r.get('resumeAction') else 'idle', reason='awaiting_dispatch')
                self.persist(r)
                return self.public(r)
            if action == 'moderator':
                entries = body.get('moderator')
                if not isinstance(entries, list) or len(json.dumps(entries)) > 200000:
                    raise self.Error('invalid_request')
                if r['status'] == 'running':
                    r['queuedModerator'] = copy.deepcopy(entries)
                elif entries != r['moderator']:
                    self.update_moderator(r, entries)
                self.persist(r)
                return self.public(r)
            if action == 'review_one':
                if body.get('reviewerId') not in {a['id'] for a in self.debaters(r)}:
                    raise self.Error('invalid_request', 'Choose an enabled debater for peer review')
                if any(q['status'] == 'running' for q in r.get('questions', [])):
                    raise self.Error('busy', 'Wait for the current answer before reviewing')
                if body.get('message'):
                    self.validate_message(body['message'])
                    if body['message'].get('to', 'all') != 'all':
                        raise self.Error('invalid_request', 'Peer review requires a shared question')
            if action in ('next', 'review_one') and body.get('message'):
                self.validate_message(body['message'])
                if any(t.get('type') == 'user' and t.get('id') == body['message']['id'] for t in r['turns']):
                    return self.public(r)
            if r['status'] == 'running':
                raise self.Error('busy')
            if action == 'release_queue':
                r.update(thinkingPaused=False, pauseRequested=False, dispatchHeld=False, reason=None)
                if r['status'] == 'paused':
                    r['status'] = 'idle'
                self.persist(r)
                return self.public(r)
            if action in ('next', 'round') and not body.get('message'):
                if any(q['status'] == 'running' for q in r.get('questions', [])):
                    raise self.Error('busy', 'Wait for the current answer before continuing')
                paused = [q for q in r.get('questions', []) if q['status'] == 'paused' and not q.get('superseded')]
                question = next((q for q in paused if not body.get('questionId') or q['id'] == body['questionId']), None)
                if body.get('questionId') and not question:
                    raise self.Error('invalid_request', 'No paused answer to continue')
                if question:
                    self.resume_question(r, question, single=action == 'next')
                    r.update(thinkingPaused=False, pauseRequested=False, status='idle', reason=None, auto=False)
                    if action == 'round':
                        r['dispatchHeld'] = False
                    self.persist(r)
                    return self.public(r)
            if action == 'extend':
                r['budgets'] = {'calls': 0, 'seconds': 0, 'unlimited': True}
                r.update(status='idle', reason=None, error=None)
                self.persist(r)
                return self.public(r)
            if action not in ('next', 'round', 'auto', 'summary', 'execute', 'review', 'review_auto', 'review_one'):
                raise self.Error('invalid_request', 'Unknown controller action')
            if action != 'next':
                r['dispatchHeld'] = False
            if action == 'next' and body.get('message'):
                message = copy.deepcopy(body['message'])
                if message.get('to', 'all') != 'all':
                    raise self.Error('invalid_request', 'Next speaker uses the scheduled member')
                chosen = self.public(r)['nextSpeaker']['id']
                message['action'] = 'next'
                self.set_focus(r, message)
                r.update(speakerStart=chosen, status='idle')
                r['turns'].append(dict(message, type='user', round=r['round'], at=time.time()))
            if action in ('review', 'review_auto', 'review_one') and body.get('message'):
                message = copy.deepcopy(body['message'])
                if action == 'review_one':
                    message.update(action='review', reviewerId=body['reviewerId'])
                self.validate_message(message)
                if message.get('to', 'all') != 'all':
                    raise self.Error('invalid_request', 'Peer review requires a shared question')
                self.set_focus(r, message)
                if not any(t['type'] == 'user' and t.get('id') == message['id'] for t in r['turns']):
                    r['turns'].append(dict(copy.deepcopy(message), type='user', round=r['round'], at=time.time()))
            if action == 'execute':
                if isinstance(body.get('approval'),dict) and body['approval'].get('issuePolicy') and body.get('executionFlow')!='staged':
                    raise self.Error('invalid_request','Independent preflight requires the staged workflow')
                if body.get('allowHelperRepair') and body.get('executionFlow')!='staged' and not (resuming and resuming.get('workflowVersion')):
                    raise self.Error('invalid_request','Helper recovery requires the staged workflow')
                # Restart/cancellation may leave a committed result to merge. Do it
                # before checking the confirmation token, never after freezing a task.
                if r.get('pendingJob'):
                    old = self.c.jobs.get(r['pendingJob'])
                    if old and old['status'] not in ('complete', 'failed', 'cancelled', 'interrupted'):
                        raise self.Error('busy')
                    if old:
                        self.merge(r, old)
                    r['pendingJob'] = None
                    self.persist(r)
                if any(q['status'] == 'running' for q in r.get('questions', [])):
                    raise self.Error('busy', 'Wait for the focused answer, then review the current plan')
                approval = body.get('approval')
                if not resuming and approval is None and (r['status'] != 'ready' or body.get('planHash') != (r.get('plan') or {}).get('hash') or not self.ready(r)):
                    raise self.Error('invalid_request', 'Execution requires current unanimous plan approval')
                if r['request'].get('profile') != 'native':
                    raise self.Error('invalid_request', 'Real execution requires the native CLI profile')
                executor, reviewer = self.native_pair(r, resuming['executor'] if resuming else body.get('executorId'), resuming['reviewer'] if resuming else body.get('reviewerId'))
                if resuming:
                    plan, record = copy.deepcopy(resuming['plan']), copy.deepcopy(resuming['approval'])
                    record.update(kind='human_resumed', at=time.time(), sourceTaskId=resuming['id'],
                                  instruction=body.get('text') or 'Resume this previously approved experiment from verified saved progress')
                    record.setdefault('issues', [])
                    # Keep the malformed review in its original audit. It cannot veto
                    # an explicit continuation of a separately approved frozen plan.
                    r.pop('reviewError', None)
                else:
                    plan, record = self.human_execution(r, approval) if approval is not None else (copy.deepcopy(r['plan']), dict(kind='peer_reviewed', at=time.time()))
                if resuming and body.get('decision'):
                    record['continuationDecision']=body['decision'].strip()
                if resuming and body.get('continuationMode')=='verify_existing':
                    record['continuationMode']='verify_existing'
                    record['continuationDecision']=body.get('decision','').strip() or 'Independently inspect saved artifacts and the last review, repair only authorized workspace verification-helper defects, preserve original acceptance criteria and evidence; keep unresolved scientific or external-permission decisions blocked.'
                if 'allowHelperRepair' in body:
                    try:record['helperRecovery']=execution_flow.recovery_policy(body['allowHelperRepair'])
                    except ValueError as exc:raise self.Error('invalid_request',str(exc)) from exc
                if body.get('executionFlow') not in (None,'staged'):
                    raise self.Error('invalid_request','Unknown execution workflow')
                if approval is not None and not resuming:
                    r['plans'].append(copy.deepcopy(plan))
                r['executionApprovedHash'] = plan['hash']
                task = dict(id=uuid.uuid4().hex, plan=plan, approval=record, status='running',
                            executor=executor['id'], reviewer=reviewer['id'], followupReview=body.get('followupReview', True) is not False, created=time.time(), jobs=[])
                if body.get('executionFlow')=='staged' or resuming and resuming.get('workflowVersion'):
                    last_kind=(self.c.jobs.get((resuming.get('jobs') or [''])[-1],{}).get('request',{}).get('kind') if resuming else None)
                    preflight=record.get('preflightRequired',False) if not resuming else resuming.get('preflightPending',False)
                    first_role='verification' if preflight or resuming and (last_kind=='verification' or resuming.get('verification')) else 'execution'
                    task.update(workflowVersion=1,workspace=r['workspace'],preflightPending=preflight,repairAttempts=resuming.get('repairAttempts',0) if resuming else 0,workflowNext=('verification' if body.get('continuationMode')=='verify_existing' and not resuming.get('repairAuthorization') else resuming.get('workflowNext',first_role)) if resuming else first_role,stages=copy.deepcopy(resuming.get('stages',[])) if resuming else [])
                    if resuming and resuming.get('repairAuthorization'):task['repairAuthorization']=copy.deepcopy(resuming['repairAuthorization'])
                    task['followupReview']=False
                if resuming:
                    for key in ('execution','verification'):
                        if resuming.get(key):task[key]=copy.deepcopy(resuming[key])
                    task.update(resumedFrom=resuming['id'], resumeRequestId=body['requestId'],
                                followupReview=False, resumeContext=dict(sourceTaskId=resuming['id'],
                                sourcePlanHash=resuming['plan']['hash'], previousStatus=resuming['status'],
                                previousError=copy.deepcopy(resuming.get('error')),
                                previousJobs=list(resuming.get('jobs', [])),
                                previousActivity=[execution_progress.activity(self.c.jobs[j]) for j in resuming.get('jobs', []) if j in self.c.jobs]))
                    r['turns'].append(dict(type='user', id='resume-'+body['requestId'], action='execute',
                        text=record['instruction'], resumedFrom=resuming['id'], to='all', round=r['round'], at=time.time()))
                r.setdefault('experiments', []).append(task)
                r['activeExperiment'] = task['id']
                r['turns'].append(dict(type='experiment', id='experiment-'+task['id'], taskId=task['id'], round=r['round'], at=time.time()))
            elif r['status'] in ('ready', 'executed', 'complete') and action != 'summary':
                r['reviews'] = {}
                r['phase'] = 'debate'
                r['round'] += 1
                r['cycleSignatures'] = []
            # In interrupted jobs merge committed partial results before making another call.
            if r.get('pendingJob'):
                old = self.c.jobs.get(r['pendingJob'])
                if old and old['status'] not in ('complete', 'failed', 'cancelled', 'interrupted'):
                    raise self.Error('busy')
                if old:
                    self.merge(r, old)
                r['pendingJob'] = None
            if action in ('review', 'review_auto', 'review_one'):
                r['phase'] = 'debate'
            if action == 'review_one':
                target = body['reviewerId']
                if any(t.get('kind', 'debate') == 'debate' and t.get('id') == target and
                       t.get('round') == r['round'] and not t.get('superseded') for t in r['turns']):
                    r.update(round=r['round']+1, reviews={}, cycleSignatures=[])
                r['reviewTarget'] = target
            r.update(status='running', reason=None, auto=action in ('auto', 'review_auto'), pauseRequested=False, focusPause=False, thinkingPaused=False, resumeAction=action, error=None)
            self.persist(r)
            r['workerGeneration'] = r.get('workerGeneration', 0)+1
            t = threading.Thread(target=self.work, args=(r, action, r['workerGeneration']), daemon=True)
            self.threads.append(t); t.start()
            return self.public(r)

    def update_moderator(self, r, entries):
        r['moderator'] = copy.deepcopy(entries)
        r['generation'] += 1
        r['reviews'] = {}
        if r['plan']:
            self.plan(r, r['plan']['proposal'])
        r.update(status='idle', reason=None)

    def debaters(self, r):
        return [a for a in r['roster'] if a.get('enabled') and a['role'] == 'debater']

    def speaker_order(self, r):
        agents = self.debaters(r)
        ids = [a['id'] for a in agents]
        focus = r.get('activeQuestion', {}).get('id')
        last = next((t['id'] for t in reversed(r['turns']) if t.get('type') == 'agent' and
            t.get('kind', 'debate') == 'debate' and not t.get('superseded') and
            t.get('replyTo') == focus and t.get('id') in ids), None)
        start = ids.index(r['reviewTarget']) if r.get('reviewTarget') in ids else (ids.index(last)+1) % len(ids) if last else ids.index(r['speakerStart']) if r.get('speakerStart') in ids else 0
        return agents[start:]+agents[:start]

    def transcript(self, r):
        with self.c.lock:
            independent, turns, experiments = copy.deepcopy((r['independent'], r['turns'], r.get('experiments', [])))
        rows = [dict(type='independent', id=x.get('agentId', aid), name=x.get('name', aid), text=x['text']) for aid, x in independent.items()]
        tasks = {x['id']: x for x in experiments}
        for turn in turns:
            if turn['type'] != 'experiment':
                rows.append(copy.deepcopy(turn)); continue
            task = tasks.get(turn['taskId'], {})
            if task:
                rows.append(dict(type='experiment', id='experiment-'+task['id'], text=json.dumps({
                    'experimentId': task['id'], 'status': task['status'], 'approvedPlan': task['plan'],
                    'error': task.get('error'), 'note': 'Host task status; returned reports alone are not proof of success.'}, ensure_ascii=False)))
            for kind in ('execution', 'verification'):
                result = task.get(kind)
                if result:
                    rows.append(dict(type='agent', kind=kind, id=result['agentId'], name=result['name'], text=result['text'],
                                     experimentId=task['id'], approvedPlan=task['plan']))
        return rows

    def ask(self, r, body, independent=False):
        message = body.get('message')
        self.validate_message(message)
        for q in r.get('questions', []):
            if q['id'] == message['id']:
                if q['message'] != message:
                    raise self.Error('invalid_request', 'Question id already used')
                return self.public(r)
        if any(q['status'] == 'running' for q in r.get('questions', [])):
            raise self.Error('busy', 'A focused question is already running')
        agents = [a for a in self.debaters(r) if message.get('to', 'all') in ('all', a['id'])]
        if not agents:
            raise self.Error('invalid_request', 'Choose a question recipient')
        if not r['budgets'].get('unlimited') and r['calls'] + len(agents) > r['budgets']['calls']:
            raise self.Error('budget_reached', 'Extend the discussion budget before another call')
        agents = copy.deepcopy(agents) if independent else [dict(copy.deepcopy(a), role='reviewer', tools={'webSearch': bool(a.get('tools', {}).get('webSearch'))}) for a in agents]
        request = dict(kind='independent' if independent else 'question', requestId='question-'+r['id']+'-'+message['id'], sessionId='question-'+r['id'],
                       question=message['text'], quotedReferences=copy.deepcopy(message.get('quotes', [])), agents=agents, profile='restricted', lang=r['request'].get('lang', 'en'),
                       mode=r['request'].get('mode', 'adaptive'), packet=r['request'].get('packet', {}),
                       transcript=self.transcript(r), images=message.get('images', []), moderator=copy.deepcopy(r['moderator']),
                       initialInstructions=r['request'].get('initialInstructions', []),
                       researchQuestion=r['request']['question'], currentPlan=copy.deepcopy(r['plan']))
        if independent:
            request.update(profile=r['request'].get('profile', 'restricted'), runId=r['id']+'-independent-'+message['id'],
                           workspace=r['workspace'], claudePermissionMode=r['request'].get('claudePermissionMode','auto'),
                           **({'codexPermissionMode':r['request']['codexPermissionMode']} if 'codexPermissionMode' in r['request'] else {}),
                           transcript=[], moderator=[], currentPlan=None)
        job = self.c.start(request)
        if message.get('to', 'all') == 'all':
            if r.get('activeExperiment'):
                r['deferredFocus'] = copy.deepcopy(message)
            else:
                self.set_focus(r, message)
                if r['status'] == 'running':
                    r.pop('resumeAction', None)
                    r.update(auto=False, pauseRequested=True, focusPause=True)
                    if r.get('pendingJob'):
                        self.c.cancel(r['pendingJob'])
        r['thinkingPaused'] = False
        r['dispatchHeld'] = False
        q = dict(id=message['id'], message=copy.deepcopy(message), jobId=job['id'], status='running', created=time.time())
        r.setdefault('questions', []).append(q)
        r['turns'].append(dict(copy.deepcopy(message), type='user', round=r['round'], at=time.time()))
        r['calls'] += len(agents); r['jobs'].append(job['id'])
        # A question cannot rewrite an active experiment. Future execution needs fresh review.
        if r['status'] != 'running':
            r['reviews'] = {}; r.update(status='idle', reason=None)
        self.persist(r)
        t = threading.Thread(target=self.question_work, args=(r, q), daemon=True)
        self.threads.append(t); t.start()
        return self.public(r)

    def question_request(self, question):
        original = (question.get('previousJobs') or [question['jobId']])[0]
        return self.c.jobs[original]['request']

    def resume_question(self, r, question, single=False):
        # A continuation is a new CLI call, only for members without a committed answer.
        request = copy.deepcopy(self.question_request(question))
        completed = set(question.get('completedAgents', []))
        request['agents'] = [a for a in request['agents'] if a['id'] not in completed]
        if single:
            request['agents'] = request['agents'][:1]
        if not request['agents']:
            question.update(status='complete', pauseRequested=False)
            return
        if not r['budgets'].get('unlimited') and r['calls'] + len(request['agents']) > r['budgets']['calls']:
            raise self.Error('budget_reached', 'Extend the budget before continuing')
        request['requestId'] = 'resume-question-'+r['id']+'-'+uuid.uuid4().hex
        if request['kind'] == 'question':
            request['transcript'] = self.transcript(r)
        job = self.c.start(request)
        question.setdefault('previousJobs', []).append(question['jobId'])
        question.update(jobId=job['id'], status='running', pauseRequested=False)
        question.pop('error', None)
        r['calls'] += len(request['agents']); r['jobs'].append(job['id'])
        self.persist(r)
        t = threading.Thread(target=self.question_work, args=(r, question), daemon=True)
        self.threads.append(t); t.start()

    def merge_question(self, r, question, job):
        for result in job.get('results', []):
            completed = question.setdefault('completedAgents', [])
            if result['agentId'] not in completed:
                completed.append(result['agentId'])
            if any(t.get('jobId') == job['id'] and t.get('id') == result['agentId'] for t in r['turns']):
                continue
            r['turns'].append(dict(type='agent', kind='question', id=result['agentId'], text=result['text'], result=result,
                                   replyTo=question['id'], action=question['message'].get('action', 'question'), to=question['message'].get('to', 'all'), jobId=job['id'], round=r['round'], at=time.time()))
        if job['status'] in ('complete', 'failed', 'cancelled', 'interrupted'):
            question['status'] = 'paused' if question.get('pauseRequested') and job['status'] != 'complete' else job['status']
            if job['status'] == 'complete' and any(a['id'] not in question.get('completedAgents', []) for a in self.question_request(question)['agents']):
                question['status'] = 'paused'
            r['reviews'] = {}
            if r['status'] == 'ready':
                r.update(status='idle', reason=None)
            if job.get('error') and question['status'] != 'paused':
                question['error'] = job['error']

    def question_work(self, r, question):
        while True:
            with self.c.lock:
                job = self.c.jobs[question['jobId']]
                self.merge_question(r, question, job); self.persist(r)
                if question['status'] != 'running':
                    return
            if self.stopping.wait(.2):
                self.c.cancel(question['jobId'])

    def native_pair(self, r, executor_id=None, reviewer_id=None):
        candidates = [a for a in r['roster'] if a.get('enabled') and
                      a['provider'] in ('claude', 'codex') and a['role'] in ('executor', 'debater')]
        if not candidates:
            raise self.Error('invalid_request', 'Choose a native Claude/Codex executor')
        executor = next((a for a in candidates if a['id'] == executor_id), None) if executor_id else next((a for a in candidates if a['role'] == 'executor'), candidates[0])
        if executor is None:
            raise self.Error('invalid_request', 'Invalid native executor')
        reviewers = [a for a in r['roster'] if a.get('enabled') and a['provider'] in ('claude', 'codex') and
                     a['role'] in ('debater', 'reviewer') and a['id'] != executor['id']]
        if not reviewers:
            raise self.Error('invalid_request', 'Real execution needs a second native reviewer')
        reviewer = next((a for a in reviewers if a['id'] == reviewer_id), None) if reviewer_id else next((a for a in reviewers if a['provider'] != executor['provider']), reviewers[0])
        if reviewer is None:
            raise self.Error('invalid_request', 'Choose a different native reviewer')
        return executor, reviewer

    def plan(self, r, proposal):
        h = digest({'proposal': proposal, 'generation': r['generation']})
        if r['plan'] and r['plan']['hash'] == h:
            return
        r['plan'] = {'version': len(r['plans'])+1, 'hash': h, 'proposal': copy.deepcopy(proposal), 'created': time.time()}
        r['plans'].append(copy.deepcopy(r['plan']))
        r['reviews'] = {}

    def ready(self, r):
        h = (r.get('plan') or {}).get('hash')
        return bool(h) and all(r['reviews'].get(a['id'], {}).get('decision') == 'ready' and
                              r['reviews'][a['id']].get('planHash') == h and not r['blockers'].get(a['id'])
                              for a in self.debaters(r))

    def merge(self, r, job):
        request = job['request']
        evidence = set(r.get('evidenceDigests', []))
        for event in job.get('events', []):
            tool = event.get('tool') or {}
            output = tool.get('content') if tool.get('type') == 'tool_result' else tool.get('aggregatedOutput', tool.get('output', tool.get('result')))
            if output is not None:
                evidence.add(digest({'agent': event.get('agentId'), 'output': output}))
        r['evidenceDigests'] = sorted(evidence)
        if job.get('context'):
            r['context'] = job['context']
        for result in job.get('results', []):
            aid, kind = result['agentId'], request['kind']
            if kind == 'independent':
                r['independent'][aid] = result
            elif kind == 'debate':
                if any(t.get('jobId') == job['id'] and t['id'] == aid for t in r['turns']):
                    continue
                stale = request.get('focusRevision', 0) != r.get('focusRevision', 0)
                turn = dict(type='agent', kind='debate', id=aid, round=request['round'], text=result['text'], result=result,
                            jobId=job['id'], replyTo=request.get('focusMessageId'), superseded=stale)
                # A late reply belongs to the previous task, before the new question.
                index = next((i for i, t in enumerate(r['turns']) if stale and t.get('id') == r.get('activeQuestion', {}).get('id')), len(r['turns']))
                r['turns'].insert(index, turn)
                if stale:
                    continue
                if r.get('reviewTarget') == aid:
                    r.pop('reviewTarget', None)
                receipt = result.get('receipt')
                if not receipt:
                    r['reviews'].pop(aid, None)
                    r['reviewError'] = result.get('receiptError', 'Missing review receipt')
                    continue
                oldhash = (r['plan'] or {}).get('hash')
                if receipt.get('proposal'):
                    self.plan(r, receipt['proposal'])
                h = (r['plan'] or {}).get('hash')
                referenced = receipt['reviewedPlanHash']
                valid = referenced == h or bool(receipt.get('proposal')) and referenced == 'proposed'
                r['blockers'][aid] = receipt['blockers']
                r['reviews'][aid] = {'decision': receipt['decision'], 'planHash': h if valid else referenced,
                                      'valid': valid, 'nextAction': receipt['nextAction'], 'researchStage': receipt.get('researchStage'),
                                      'focus': receipt.get('focus', []), 'focusReason': receipt.get('focusReason', ''),
                                      'jobId': job['id'], 'at': time.time()}
                if receipt['decision'] == 'ready' and not valid:
                    r['reviewError'] = 'Ready review refers to a different plan version'
                if receipt['decision'] == 'need_user':
                    r['needUser'] = True
            else:
                if kind == 'execution':
                    r['executionPlanHash'] = request['approvedPlan']['hash']
                r[kind] = result
                if kind in ('execution', 'verification'):
                    task = next((x for x in r.get('experiments', []) if x['id'] == request.get('experimentId')), None)
                    if task:
                        task[kind] = copy.deepcopy(result)
                if kind == 'synthesis' and not any(t.get('jobId') == job['id'] for t in r['turns']):
                    r['turns'].append(dict(type='agent', kind='synthesis', id=aid, text=result['text'], result=result,
                                          round=r['round'], jobId=job['id'], at=time.time()))

    def invoke(self, r, kind, agents, **extra):
        body = r['request']
        request = {k: copy.deepcopy(body[k]) for k in ('question', 'mode', 'lang', 'packet', 'initialInstructions', 'profile', 'claudePermissionMode', 'codexPermissionMode') if k in body}
        request.update(sessionId=r['sessionId'], runId=r['id'], workspace=r['workspace'], kind=kind, agents=agents,
                       transcript=self.transcript(r),
                       moderator=r['moderator'], sharedContext=(r.get('context') or {}).get('text', ''), round=r['round'], **extra)
        request['focusRevision'] = r.get('focusRevision', 0)
        if r.get('activeQuestion') and kind not in ('execution', 'verification'):
            focus = r['activeQuestion']
            request.update(question=focus['text'], researchQuestion=body['question'], focusMessageId=focus['id'],
                           quotedReferences=copy.deepcopy(focus.get('quotes', [])), images=copy.deepcopy(focus.get('images', [])))
        if kind == 'independent' and not r.get('context'):
            request['contextAgent'] = next((a for a in r['roster'] if a.get('enabled') and a['role'] == 'context'), None)
        if kind == 'debate':
            request['control'] = {'nonce': uuid.uuid4().hex, 'plan': r['plan'], 'reviews': r['reviews'], 'blockers': r['blockers'], 'round': r['round']}
        if kind in ('execution', 'verification'):
            task = next(x for x in r['experiments'] if x['id'] == r['activeExperiment'])
            request['approvedPlan'] = copy.deepcopy(task['plan'])
            request['executionApproval'] = copy.deepcopy(task.get('approval'))
            request['resumeExperiment'] = copy.deepcopy(task.get('resumeContext'))
            request['executionResult'] = task.get('execution')
            request['experimentId'] = task['id']
            if task.get('workflowVersion'):
                request['executionControl']=execution_flow.control(task,kind)
        with self.c.lock:
            if r.get('pauseRequested'):
                raise self.Error('paused', 'Paused by user')
            if not execution_progress.unlimited(request) and not r['budgets'].get('unlimited') and r['calls']+len(agents)+(1 if request.get('contextAgent') else 0) > r['budgets']['calls']:
                raise self.Error('budget_reached', 'Call budget reached; review before extending it')
            job = self.c.start(request)
            r['calls'] += len(agents)+(1 if request.get('contextAgent') else 0)
            r['jobs'].append(job['id']); r['pendingJob'] = job['id']; self.persist(r)
            if kind in ('execution', 'verification'):
                task['jobs'].append(job['id']); self.persist(r)
        call_started = time.monotonic()
        remaining_seconds = r['budgets']['seconds'] - r['elapsed'] - (call_started-r.get('_activeStarted', call_started))
        budget_cancelled = False
        while job['status'] not in ('complete', 'failed', 'cancelled', 'interrupted'):
            if self.stopping.wait(.15):
                self.c.cancel(job['id'])
            if not r['budgets'].get('unlimited') and not execution_progress.unlimited(request) and time.monotonic()-call_started >= remaining_seconds:
                budget_cancelled = True
                self.c.cancel(job['id'])
            with self.c.lock:
                actual = self.c.jobs[job['id']]
                # Publish successes as soon as each native client finishes.
                self.merge(r, actual); self.persist(r)
                job = self.c.public(actual)
        with self.c.lock:
            self.merge(r, self.c.jobs[job['id']]); r['pendingJob'] = None; self.persist(r)
        if budget_cancelled:
            raise self.Error('budget_reached', 'Time budget reached during the current call')
        if r.get('pauseRequested'):
            raise self.Error('paused', 'Paused by user')
        if job['status'] != 'complete':
            err = job.get('error') or {'code': job['status']}
            raise self.Error(err['code'], err.get('detail', ''))
        if r.get('reviewError'):
            msg = r.pop('reviewError')
            raise self.Error('invalid_receipt', msg)

    def one(self, r, parallel=False, review_only=False):
        debaters = self.debaters(r)
        missing = [a for a in debaters if a['id'] not in r['independent']]
        if r['phase'] == 'independent' and not missing and not review_only:
            r['phase'] = 'debate'
            return
        if missing and not review_only:
            self.invoke(r, 'independent', missing if parallel else missing[:1])
            if len(r['independent']) == len(debaters):
                r['phase'] = 'debate'
            return
        r['phase'] = 'debate'
        # Advance after the last published speaker, including across round boundaries.
        # Cancelled/failed calls do not publish a turn and therefore cannot move the cursor.
        order = self.speaker_order(r)
        remaining = [a for a in order if not any(t.get('kind', 'debate') == 'debate' and t['id'] == a['id'] and t['round'] == r['round'] and not t.get('superseded') for t in r['turns'])]
        if not remaining:
            signature = digest({'plan': (r['plan'] or {}).get('hash'), 'blockers': r['blockers'],
                                'evidence': r.get('evidenceDigests', []), 'reviews': {k: (v['decision'], v['planHash']) for k, v in r['reviews'].items()}})
            r['cycleSignatures'].append(signature)
            if len(r['cycleSignatures']) >= 3 and len(set(r['cycleSignatures'][-3:])) == 1:
                raise self.Error('stalled', 'No change in plan, positions or blockers across repeated rounds')
            r['round'] += 1
            return self.one(r, review_only=review_only)
        self.invoke(r, 'debate', remaining[:1])

    def work(self, r, action, worker_generation=None):
        if worker_generation is None:
            worker_generation = r.get('workerGeneration', 0)
        started = time.monotonic()
        r['_activeStarted'] = started
        experiment_started, excluded = None, 0
        task = None
        def finish_experiment_clock():
            nonlocal experiment_started, excluded
            if experiment_started is not None:
                excluded = time.monotonic()-experiment_started
                experiment_started = None
                r['experimentElapsed'] = r.get('experimentElapsed', 0)+excluded
                r['_activeStarted'] = started+excluded
                if task is not None:
                    task['elapsed'] = excluded
        review_only = action in ('review', 'review_auto', 'review_one') or action == 'next' and r['phase'] == 'debate'
        action = {'review': 'round', 'review_auto': 'auto', 'review_one': 'next'}.get(action, action)
        try:
            if action == 'summary':
                self.invoke(r, 'synthesis', self.debaters(r)[:1])
                scribe = next((a for a in r['roster'] if a.get('enabled') and a['role'] == 'scribe' and a.get('tools', {}).get('writeNotes')), None)
                if scribe and r['request'].get('autoScribe', True):
                    self.invoke(r, 'scribe', [scribe], notes=r['request'].get('notes', ''))
                r['status'] = 'ready' if self.ready(r) else 'paused'; r['reason'] = 'summary'
                return
            if action == 'execute':
                experiment_started = time.monotonic()
                task = next(x for x in r['experiments'] if x['id'] == r['activeExperiment'])
                executor, reviewer = self.native_pair(r, task['executor'], task['reviewer'])
                if task.get('workflowVersion'):
                    execution_flow.run(self,r,task,executor,reviewer)
                else:
                    self.invoke(r, 'execution', [executor])
                    task['status'] = 'verifying'; self.persist(r)
                    self.invoke(r, 'verification', [reviewer])
                finish_experiment_clock()
                task.update(status='completed' if task.get('workflowVersion') else 'reviewed', finished=time.time(), elapsed=excluded)
                task.pop('currentStage',None)
                r.update(plan=None, reviews={}, phase='debate', round=r['round']+1, cycleSignatures=[])
                r['generation'] += 1
                r.pop('activeExperiment', None)
                if r.get('deferredFocus'):
                    self.set_focus(r, r.pop('deferredFocus'))
                    if any(q['status'] == 'running' for q in r.get('questions', [])):
                        r.update(pauseRequested=True, focusPause=True)
                        r.pop('resumeAction', None)
                if 'queuedModerator' in r:
                    self.update_moderator(r, r.pop('queuedModerator'))
                    r['status'] = 'running'
                # The composer can stop after verification; legacy controls retain their follow-up round.
                if not task.get('followupReview', True):
                    r.update(status='paused' if r.get('pauseRequested') else 'idle', reason='execution_finished')
                    return
                action = 'round'
            initial_phase, initial_round = r['phase'], r['round']
            while True:
                if self.stopping.is_set() or r.get('pauseRequested'):
                    r.update(status='idle' if r.get('focusPause') else 'paused', reason='new_question' if r.get('focusPause') else 'user')
                    if r.get('focusPause'):
                        r['pauseRequested'] = False
                    break
                if not r['budgets'].get('unlimited') and r['elapsed']+time.monotonic()-started-excluded >= r['budgets']['seconds']:
                    raise self.Error('budget_reached', 'Time budget reached')
                r['_remainingSeconds'] = r['budgets']['seconds']-r['elapsed']-(time.monotonic()-started-excluded)
                self.one(r, parallel=action in ('round', 'auto'), review_only=review_only)
                if 'queuedModerator' in r:
                    entries = r.pop('queuedModerator')
                    if entries != r['moderator']:
                        self.update_moderator(r, entries)
                        r['status'] = 'running'
                round_complete = all(any(t.get('kind', 'debate') == 'debate' and t['id'] == a['id'] and
                                         t['round'] == r['round'] and not t.get('superseded')
                                         for t in r['turns']) for a in self.debaters(r))
                if round_complete and self.ready(r):
                    r.update(status='ready', reason='unanimous'); break
                # A request for user input blocks execution, not the other member's review.
                # Inspect persisted receipts too, so continuing an older partial round does
                # not lose the first member's question when the in-memory flag was consumed.
                need_user = r.get('needUser') or any(t.get('kind') == 'debate' and
                    t.get('round') == r['round'] and not t.get('superseded') and
                    (t.get('result', {}).get('receipt') or {}).get('decision') == 'need_user'
                    for t in r['turns'])
                if need_user and (round_complete or action == 'next'):
                    r.pop('needUser', None)
                    r.update(status='paused', reason='need_user'); break
                if action == 'next':
                    r['status'] = 'idle'; break
                if action == 'round':
                    if initial_phase == 'independent' and len(r['independent']) == len(self.debaters(r)):
                        r['phase'] = 'debate'; r['status'] = 'idle'; break
                    if round_complete:
                        r['status'] = 'idle'; break
                if action == 'auto' and not r['auto']:
                    r.update(status='paused', reason='user'); break
                with self.c.lock:
                    self.persist(r)
        except Exception as exc:
            finish_experiment_clock()
            if r.get('activeExperiment'):
                task = next(x for x in r['experiments'] if x['id'] == r['activeExperiment'])
                if task.get('workflowVersion'):execution_flow.recover(task,self.c.jobs)
                task.update(status='interrupted' if r.get('pauseRequested') else 'needs_decision' if task.get('workflowVersion') and getattr(exc,'code','') in ('execution_needs_decision','execution_handoff_invalid','execution_stalled') else 'failed', finished=time.time(), error={'code': getattr(exc, 'code', 'internal_error'),'detail':getattr(exc,'detail',str(exc))[:2000]})
                r.pop('resumeAction', None)
                r.pop('activeExperiment', None)
                r.update(reviews={}, phase='debate', round=r['round']+1, cycleSignatures=[])
                if r.get('deferredFocus'):
                    self.set_focus(r, r.pop('deferredFocus'))
            if r.get('pauseRequested'):
                r.update(status='idle' if r.get('focusPause') else 'paused', reason='new_question' if r.get('focusPause') else 'user', error=None)
                if r.get('focusPause'):
                    r['pauseRequested'] = False
            else:
                r.update(status='paused', reason=getattr(exc, 'code', 'internal_error'),
                         error={'code': getattr(exc, 'code', 'internal_error'), 'detail': getattr(exc, 'detail', str(exc))[:2000]})
        finally:
            with self.c.lock:
                finish_experiment_clock()
                r['elapsed'] += max(0, time.monotonic()-started-excluded)
                # A newly dispatched worker may already own these fields after the
                # previous worker published idle. Stale cleanup must not pause it.
                if r.get('workerGeneration', 0) == worker_generation:
                    r['auto'] = False
                    if not r.get('pauseRequested'):
                        r.pop('resumeAction', None)
                    r.pop('_remainingSeconds', None)
                    r.pop('_activeStarted', None)
                self.persist(r)

    def close(self):
        self.stopping.set()
        for t in self.threads:
            t.join(timeout=5)
