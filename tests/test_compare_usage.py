import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('compare_usage',Path(__file__).resolve().parents[1]/'scripts/compare_usage.py')
bench=importlib.util.module_from_spec(spec);spec.loader.exec_module(bench)


class ComparisonTests(unittest.TestCase):
    def settings(self):return bench.config(Path(__file__).resolve().parents[1]/'scripts/comparison.example.json')
    def test_default_dry_run_never_instantiates_cli_or_council(self):
        with tempfile.TemporaryDirectory() as root,patch.object(bench,'run',side_effect=AssertionError('Must not spend usage')),patch.object(bench,'Council',side_effect=AssertionError('Must not start service')):
            bench.main(['--config',str(Path(__file__).resolve().parents[1]/'scripts/comparison.example.json'),'--output',root])
            m=json.loads((Path(root)/'manifest.json').read_text())
            self.assertEqual(m['mode'],'dry-run');self.assertEqual(len(m['runs']),18)
            self.assertEqual(m['plannedModelInvocations'],48)
    def test_models_effort_repetitions_and_pair_order_match(self):
        settings=self.settings();manifest=bench.plan(settings)
        groups={}
        for run in manifest['runs']:
            key=(run['arm'],tuple(a['id'] for a in run['agents']));groups[key]=groups.get(key,0)+1
            for agent in run['agents']:self.assertEqual(agent,next(a for a in settings['models'] if a['id']==agent['id']))
        self.assertTrue(all(n==3 for n in groups.values()))
        self.assertEqual([r['arm'] for r in manifest['runs'] if r['pair']=='single-claude-1'],['native_single','rc_single'])
        self.assertEqual([r['arm'] for r in manifest['runs'] if r['pair']=='single-claude-2'],['rc_single','native_single'])
    def test_quality_is_measured_separately_from_tokens(self):
        task=bench.plan(self.settings())['task']
        good=json.dumps(dict(meanB3=.8,meanK3=.83,meanDifference=.03,limitations='Single seed, validation folds only.'))
        self.assertTrue(bench.quality(good,task)['passed'])
        self.assertFalse(bench.quality(good.replace('.03','.30'),task)['passed'])
        self.assertFalse(bench.quality('No answer',task)['passed'])
    def test_full_harness_with_fake_clients_preserves_settings_and_saves_tokens(self):
        settings=self.settings();manifest=bench.plan(settings);seen=[];waits=[]
        def fake(c,agent,request,job,text,context):
            seen.append((copy.deepcopy(agent),request['kind'],request['transcript'],text))
            job['usageCalls']=[dict(id=job['id'],agentId=agent['id'],toolCalls=0,tokens={k:10 for k in bench.FIELDS})]
            return dict(text=json.dumps(dict(manifest['task']['expected'],limitations='Three folds, one seed; no clinical claims.')),effectiveModel=agent['model'])
        with tempfile.TemporaryDirectory() as root:
            report=bench.run(manifest,root,clients=dict(native=fake,council=fake),sleeper=waits.append)
            self.assertEqual(len(seen),48);self.assertEqual(waits,[10]*18)
            self.assertTrue(all(g['qualityEligible'] for g in report['summary'].values()))
            self.assertEqual(report['summary']['rc_single:claude']['meanTokens']['outputTokens'],20)
            self.assertTrue((Path(root)/'report.json').is_file())
            self.assertTrue(all(not public for a,kind,public,text in seen if kind=='independent'))
            for a,kind,public,text in seen:
                if kind=='debate' and 'Published peer answers:' in text:
                    peers=json.loads(text.split('Published peer answers:\n',1)[1])
                    self.assertTrue(all(t['id']!=a['id'] for t in peers))
    def test_unknown_tokens_and_incorrect_quality_prevent_unqualified_savings(self):
        agent=self.settings()['models'][0]
        rows=[dict(arm='rc_single',agents=[agent],elapsedSeconds=1,usageCalls=[],quality={agent['id']:dict(passed=False)},responses=[])]
        summary=bench.summarize(rows)['rc_single:claude']
        self.assertIsNone(summary['meanTokens']['inputTokens']);self.assertFalse(summary['qualityEligible'])
    def test_configuration_does_not_silently_accept_default_models_or_small_sample(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'config.json'
            for change in ('model','repetitions'):
                value=self.settings()
                if change=='model':value['models'][0]['model']='default'
                else:value['repetitions']=2
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):bench.config(path)
