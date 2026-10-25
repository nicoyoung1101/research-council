"""Extractive public-only handoffs. No model calls or reads of research files."""
import copy
import re

FILE = re.compile(r'(?<![\w])((?:/|\.?[\w\u4e00-\u9fff-]+/)[^\s`\"<>]*?\.(?:py|md|json|csv|txt|ya?ml|toml|log|pt|pth))(?:[:：]\d+)?')


def build(record, request):
    independent = request.get('kind') == 'independent'
    turns = [] if independent else record.get('transcript', [])
    findings, files, questions = [], {}, []
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        text = turn.get('text', '')
        source = dict(author=turn.get('id'), kind=turn.get('kind', turn.get('type')), sourceId=turn.get('jobId') or turn.get('id'))
        if turn.get('type') in ('agent', 'independent'):
            excerpts = [line.strip() for line in text.splitlines() if line.strip()][:3]
            findings.append(dict(source, excerpt='\n'.join(excerpts)[:500], status='public_report_not_independently_verified'))
        if turn.get('type') == 'user':
            questions.append(dict(source, excerpt=text[:400]))
        for match in FILE.finditer(text):
            path = match[1]
            start, end = max(0, match.start()-80), min(len(text), match.end()+180)
            files[path] = dict(path=path, point=text[start:end], source=source,
                               status='mentioned_in_public_record_not_a_read_receipt')
    plan = record.get('approvedPlan') or record.get('currentPlan')
    blockers = [] if independent else copy.deepcopy((request.get('control') or {}).get('blockers', {}))
    return dict(version=1, currentQuestion=record.get('question'),
                confirmedPlan={k:copy.deepcopy(plan[k]) for k in ('hash','version','title') if k in plan} if isinstance(plan,dict) else None, reportedFindings=findings[-5:],
                fileNotes=list(files.values())[-12:], unresolved=blockers,
                latestUserQuestions=questions[-2:],
                experimentState=experiment_state(record),
                instruction='This is an extractive index of visible public records, not new evidence or peer private memory. Attribution and uncertainty are preserved. File mentions do not prove a file was read or is unchanged. Read originals selectively when verification is necessary.')


def experiment_state(record):
    result = {}
    for key in ('resumeExperiment', 'managedExperiment'):
        value = record.get(key)
        if isinstance(value, dict):
            result[key] = {k:copy.deepcopy(value[k]) for k in ('sourceTaskId','pid','logPath','status','command','cwd','completionMarker','failurePatterns','expectedSeconds','exitCode','outputDirectory') if k in value}
    # Resume records retain observable program metadata separately from verbose logs.
    # Carry the latest published PID/output locations without replaying those logs.
    processes = []
    for activity in (record.get('resumeExperiment') or {}).get('previousActivity', []):
        for monitor in (activity.get('managedExperiments') or {}).values():
            processes.append({k:copy.deepcopy(monitor[k]) for k in
                ('monitorId','pid','runnerPid','status','logPath','exitCode','elapsedSeconds') if k in monitor})
    if processes:
        result['publishedProcesses'] = processes[-8:]
    execution = record.get('executionResult')
    if isinstance(execution, dict):
        result['publicExecutionReport'] = str(execution.get('text',''))[:1000]
    return result
