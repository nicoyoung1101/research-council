"""Durable per-invocation telemetry. Token observations are not quota estimates."""
import copy
import math
import threading
import time
import uuid

FIELDS = ('inputTokens', 'uncachedInputTokens', 'cacheWriteInputTokens',
          'cachedInputTokens', 'outputTokens', 'reasoningOutputTokens')


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None


def normalized(provider, usage):
    u = usage or {}
    if provider == 'claude':
        raw = [number(u.get(k)) for k in ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens')]
        return dict(inputTokens=sum(raw) if all(x is not None for x in raw) else None,
                    uncachedInputTokens=raw[0], cacheWriteInputTokens=raw[1], cachedInputTokens=raw[2],
                    outputTokens=number(u.get('output_tokens')),
                    reasoningOutputTokens=number((u.get('output_tokens_details') or {}).get('thinking_tokens')))
    total, cached = number(u.get('inputTokens', u.get('input_tokens'))), number(u.get('cachedInputTokens', u.get('cached_input_tokens')))
    return dict(inputTokens=total, uncachedInputTokens=max(0, total-cached) if total is not None and cached is not None else None,
                cacheWriteInputTokens=number(u.get('cacheWriteInputTokens')), cachedInputTokens=cached,
                outputTokens=number(u.get('outputTokens', u.get('output_tokens'))),
                reasoningOutputTokens=number(u.get('reasoningOutputTokens')))


class Meter:
    def __init__(self, council, agent, job, session=None):
        self.council, self.job, self.agent = council, job, agent
        self.lock = threading.RLock()
        self.messages, self.tools, self.current_message = {}, set(), None
        self.authoritative, self.latest_total = None, None
        self.baseline = copy.deepcopy((session or {}).get('usageTotal'))
        self.resumed = bool((session or {}).get('id'))
        if self.baseline is None and self.resumed:
            prior = [(j.get('created',0),(r.get('usage') or {}).get('total'))
                     for j in getattr(council,'jobs',{}).values() for r in j.get('results',[])
                     if r.get('nativeSessionId') == (session or {}).get('id') and isinstance((r.get('usage') or {}).get('total'),dict)]
            if prior:
                self.baseline = copy.deepcopy(max(prior,key=lambda item:item[0])[1])
        self.rates, self.end_rates = {}, {}
        self.first_message = None
        q = job.get('request', {})
        prior = [j for j in getattr(council, 'jobs', {}).values() if j.get('id') != job.get('id') and q.get('runId') and
                 j.get('request', {}).get('runId') == q.get('runId') and j.get('request', {}).get('question') == q.get('question') and
                 j.get('request', {}).get('kind') == q.get('kind') and j.get('status') in ('failed', 'cancelled', 'interrupted')]
        retry = max(prior, key=lambda j:j.get('created', 0))['id'] if prior else q.get('retryOf')
        self.data = dict(id=uuid.uuid4().hex, agentId=agent.get('id'), provider=agent.get('provider'),
            model=agent.get('model', 'default'), effort=agent.get('effort', 'default'), kind=q.get('kind'),
            purpose='retry' if retry else 'review' if q.get('kind') == 'debate' else q.get('kind'),
            originalPurpose=q.get('kind'), retryOf=retry, attempt=q.get('attempt', len(prior)+1 if retry else 1),
            startedAt=time.time(), endedAt=None, status='running', partial=True,
            tokens={k:None for k in FIELDS}, toolCalls=0, contextStartTokens=None,
            contextEndTokens=None, contextStartBasis=None, rateLimits={'start': [], 'end': []})
        self.publish()

    def publish(self):
        c = self.council
        if c is None:
            return
        with c.lock:
            calls = self.job.setdefault('usageCalls', [])
            entry = next((x for x in calls if x['id'] == self.data['id']), None)
            if entry is None:
                calls.append(copy.deepcopy(self.data))
            else:
                entry.clear(); entry.update(copy.deepcopy(self.data))
            if hasattr(c, 'persist'):
                c.persist(self.job)

    def merge_message(self, mid, usage):
        if not mid or not isinstance(usage, dict):
            return
        if self.first_message is None:
            self.first_message = mid
        old = self.messages.setdefault(mid, {})
        for k, v in normalized('claude', usage).items():
            if v is not None:
                old[k] = max(old.get(k, 0), v)
        self.data['tokens'] = {k:sum(x[k] for x in self.messages.values() if k in x)
            if any(k in x for x in self.messages.values()) else None for k in FIELDS}
        size = old.get('inputTokens')
        if size is not None:
            if mid == self.first_message:
                self.data.update(contextStartTokens=size, contextStartBasis='first_reported_input')
            self.data['contextEndTokens'] = size

    def tool(self, block):
        if block.get('type') in ('tool_use', 'commandExecution', 'fileChange', 'mcpToolCall', 'dynamicToolCall', 'webSearch', 'imageView', 'collabAgentToolCall', 'command_execution', 'web_search', 'mcp_tool_call', 'file_change') and block.get('id'):
            self.tools.add(block['id'])
            self.data['toolCalls'] = len(self.tools)

    def observe(self, event):
        with self.lock:
            before = copy.deepcopy(self.data)
            kind = event.get('type', event.get('event'))
            if self.agent.get('provider') == 'claude':
                if kind == 'assistant':
                    msg = event.get('message') or {}
                    self.merge_message(msg.get('id'), msg.get('usage'))
                    for block in msg.get('content') or []:
                        self.tool(block)
                elif kind == 'stream_event':
                    raw = event.get('event') or {}
                    if raw.get('type') == 'message_start':
                        msg = raw.get('message') or {}; self.current_message = msg.get('id')
                        self.merge_message(self.current_message, msg.get('usage'))
                    elif raw.get('type') == 'message_delta':
                        self.merge_message(self.current_message, raw.get('usage'))
                    elif raw.get('type') == 'content_block_start':
                        self.tool(raw.get('content_block') or {})
                elif kind == 'rate_limit_event':
                    raw = event.get('rate_limit_info') or {}; typ = raw.get('rateLimitType')
                    if isinstance(typ, str):
                        sample = dict(rateLimitType=typ, utilization=number(raw.get('utilization')),
                                      resetsAt=raw.get('resetsAt'), observedAt=time.time())
                        self.rates.setdefault(typ, sample); self.end_rates[typ] = sample
                        self.data['rateLimits'] = dict(start=list(self.rates.values()), end=list(self.end_rates.values()))
                elif kind == 'result' and isinstance(event.get('usage'), dict):
                    # Result usage already covers the assistant messages; do not add it again.
                    self.authoritative = normalized('claude', event['usage'])
                    for k, v in self.authoritative.items():
                        if v is not None:
                            self.data['tokens'][k] = v
            else:
                method = event.get('method', '')
                p = event.get('params') or {}
                if method == 'thread/tokenUsage/updated':
                    raw = p.get('tokenUsage') or {}; total = raw.get('total') or {}
                    if total:
                        self.latest_total = copy.deepcopy(total)
                        if self.baseline is None and self.resumed:
                            # Without a pre-call baseline, thread totals cannot truthfully
                            # be assigned to this invocation. Preserve the raw cumulative
                            # snapshot and mark the per-call counters unknown.
                            self.data['baselineSource'] = 'unknown'
                        base = self.baseline or {}
                        delta = {k:max(0, v-base.get(k, 0)) for k,v in total.items() if number(v) is not None
                                 and (not self.resumed or k in base)}
                        self.data['tokens'] = normalized('codex', delta)
                        self.data['threadTotal'] = copy.deepcopy(total)
                    last = raw.get('last') or {}
                    size = number(last.get('totalTokens'))
                    if size is not None:
                        if self.data['contextStartTokens'] is None:
                            self.data.update(contextStartTokens=size, contextStartBasis='first_reported_context')
                        self.data['contextEndTokens'] = size
                if method == 'item/started' or kind == 'item.started':
                    self.tool(p.get('item') or event.get('item') or {})
                if kind == 'turn.completed' and event.get('usage'):
                    self.data['tokens'] = normalized('codex', event['usage'])
            if self.data != before:
                self.publish()

    def finish(self, status):
        with self.lock:
            self.data.update(endedAt=time.time(), status=status, partial=status != 'complete')
            self.publish()
            return copy.deepcopy(self.data)


def quota_changes(call):
    starts = {s['rateLimitType']:s for s in call.get('rateLimits', {}).get('start', [])}
    ends = {s['rateLimitType']:s for s in call.get('rateLimits', {}).get('end', [])}
    return [dict(rateLimitType=k, start=starts.get(k), end=ends.get(k),
                 utilizationChange=(ends[k]['utilization']-starts[k]['utilization'])
                 if k in starts and k in ends and starts[k].get('utilization') is not None and ends[k].get('utilization') is not None
                 and starts[k].get('resetsAt') == ends[k].get('resetsAt') and starts[k]['observedAt'] != ends[k]['observedAt'] else None)
            for k in sorted(starts.keys() | ends.keys())] or [dict(rateLimitType=None, start=None, end=None, utilizationChange=None)]


def audit(jobs):
    calls, unknown = [], []
    prior_totals = {}
    for job in sorted(jobs, key=lambda j:j.get('created', 0)):
        observed = list(job.get('usageCalls', []))
        if not observed:
            for result in job.get('results', []):
                u = result.get('usage') or {}; provider = result.get('provider') or ('codex' if 'total' in u else 'claude')
                if not u:
                    continue
                tokens = normalized(provider, u)
                if provider == 'codex' and u.get('total'):
                    key = result.get('nativeSessionId')
                    previous = prior_totals.get(key) if key else None
                    tokens = normalized('codex', {k:max(0,v-previous.get(k,0)) for k,v in u['total'].items() if number(v) is not None}) if previous else {k:None for k in FIELDS}
                    if key:
                        prior_totals[key] = u['total']
                observed.append(dict(id='legacy-'+job['id']+'-'+result['agentId'], agentId=result['agentId'], provider=provider,
                    kind=job.get('request', {}).get('kind'), tokens=tokens, status='complete', partial=False,
                    source='legacy_result', rateLimits={}))
            if not observed:
                unknown.append(dict(jobId=job['id'], status=job['status'], reason='legacy_usage_not_recorded'))
        for call in observed:
            calls.append(dict(call, jobId=job['id'], quotaChanges=quota_changes(call)))
    def total(rows):
        return {k:dict(reported=sum(r.get('tokens', {}).get(k) or 0 for r in rows),
                       unknownCalls=sum(r.get('tokens', {}).get(k) is None for r in rows)) for k in FIELDS}
    failed = [c for c in calls if c['status'] not in ('complete', 'running')]
    return dict(calls=calls, totals=total(calls), cancelledOrFailed=dict(calls=len(failed), tokens=total(failed)),
                legacyUnknown=unknown, notes=['Reasoning tokens are a subset of output, cached tokens a subset of input.',
                'Quota changes use first/last reported events, not exact boundary measurements or causal billing attribution.'])
