import copy
import unittest
from bridge import validate_request, prompt_for, CouncilError

class UtilityTests(unittest.TestCase):
    def body(self,kind='title',provider='gemini'):
        return dict(kind=kind,sessionId='utility',question='Explain this excerpt',profile='restricted',agents=[dict(id='utility',provider=provider,role='reviewer',name='Utility',model='custom-account-model',rules='',tools={})],packet={'documents':[{'name':'quote','text':'Quoted original'}]})
    def test_naming_uses_gemini_without_native_or_tools(self):
        q=self.body();self.assertEqual(validate_request(q)['agents'][0]['model'],'custom-account-model')
        self.assertIn('Return only one concise plain-text title',prompt_for(q['agents'][0],q))
        for change in [dict(profile='native'),dict(agents=[{**q['agents'][0],'provider':'codex'}]),dict(agents=[{**q['agents'][0],'tools':{'webSearch':True}}])]:
            with self.assertRaises(CouncilError):validate_request({**q,**change})
    def test_sidechat_allows_selected_provider_and_web_only(self):
        for provider in ('gemini','claude','codex'):
            q=self.body('sidechat',provider);q['agents'][0]['tools']={'webSearch':True}
            self.assertEqual(validate_request(q)['agents'][0]['provider'],provider)
            for tool in ('readLocal','writeNotes','runCode'):
                bad=copy.deepcopy(q);bad['agents'][0]['tools'][tool]=True
                with self.assertRaises(CouncilError):validate_request(bad)
    def test_sidechat_includes_only_supplied_side_history_and_quote(self):
        q=self.body('sidechat');q['transcript']=[dict(type='user',text='Earlier side question',to='all'),dict(type='agent',text='Earlier side answer')]
        p=prompt_for(q['agents'][0],q)
        self.assertIn('Earlier side answer',p);self.assertIn('Quoted original',p)
        self.assertIn('separate explanatory side chat',p)
        self.assertNotIn('council_control',p)

    def test_metadata_is_separate_from_original_task(self):
        q=self.body();q['titleFormat']='metadata'
        self.assertEqual(validate_request(q)['question'],'Explain this excerpt')
        prompt=prompt_for(q['agents'][0],q)
        self.assertIn('string fields "title" and "summary"',prompt)
        self.assertIn('Do not change or replace the original user task',prompt)
        with self.assertRaises(CouncilError):validate_request({**q,'titleFormat':'unknown'})
