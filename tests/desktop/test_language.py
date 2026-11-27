import json
import io
from contextlib import redirect_stdout
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock
from kolos_states.core import StateEngine
from kolos_states.protocol import clone
from kolos_states.storage import Store
from kolos_states.language_experiment import prepare_language,run_language
from kolos_states.simulator import observe
ROOT=Path(__file__).resolve().parents[2]


def decode(e,w,text,config=None):
    e.start_language(text,observe(w),config)
    for _ in range(3200):
        if e.model['phase']!='language' or e.model['status']!='running':break
        e.tick()
    return e


class LanguageTests(unittest.TestCase):
    def test_twelve_end_to_end(self):
        r,e,w=run_language();self.assertTrue(r['passed'],r);self.assertEqual(r['output'],'1354')
        self.assertFalse(any('1354' in l['phrase'] for l in e.model['languageMemory']['lessons']))
        self.assertEqual(e.model['imagery']['confirmations'][0]['source'],'external')
    def test_per_tick_js_parity(self):
        if not shutil.which('node'):self.skipTest('Node only for parity')
        raw=json.loads(subprocess.check_output(['node',str(ROOT/'tests/desktop/language_reference.mjs')],cwd=ROOT,text=True,encoding='utf-8'))
        e=StateEngine()
        for op in raw['learning']:e.learn(op['record'],exposure=op['kind']=='expose')
        for l in raw['languageLessons']:e.teach_language(l['phrase'],l['goal'])
        e.start_language(raw['phrase'],raw['observed'])
        for expected in raw['trace']:
            ev=e.tick();self.assertEqual(ev['kind'],expected['kind'])
            self.assertEqual(e.model['language'],expected['language'])
            self.assertEqual(e.model['imagery'],expected['imagery'])
    def test_no_language_experience_means_no_image(self):
        e,w,_=prepare_language();del e.model['languageMemory'];decode(e,w,'я хочу увидеть 1354 в поле')
        self.assertEqual(e.model['status'],'unknown');self.assertIsNone(e.model['imagery'])
    def test_no_image_for_unlearned_negation_or_unknown_symbols(self):
        for text in ['не хочу увидеть 1354 в поле','я хочу увидеть 1354 в другом поле','я хочу увидеть 8345 в поле','я хочу увидеть 1354 в поле потом']:
            e,w,_=prepare_language();decode(e,w,text);self.assertEqual(e.model['status'],'unknown');self.assertIsNone(e.model['imagery'])
    def test_language_lesions(self):
        for kind in ('literal','readout','support','ground'):
            e,w,_=prepare_language()
            for edge in e.model['languageMemory']['edges']:
                if edge['kind']==kind:e.set_language_weight(edge['id'],0)
            decode(e,w,'я хочу увидеть 1354 в поле');self.assertEqual(e.model['status'],'unknown')
    def test_language_memory_rebuild_and_weight_restore(self):
        with tempfile.TemporaryDirectory() as d:
            e,w,text=prepare_language();edge=next(e for e in e.model['languageMemory']['edges'] if e['kind']=='readout');e.set_language_weight(edge['id'],.95)
            lex=clone(e.model['languageMemory']);store=Store(Path(d));store.save(e);other=store.load();store.close()
            self.assertEqual(lex,other.model['languageMemory']);self.assertIsNone(other.model.get('language'))
            decode(other,w,text);self.assertEqual(other.model['language']['goal']['value'],'1354')
    def test_teaching_failure_transactional(self):
        e,w,_=prepare_language();before=clone(e.model)
        with self.assertRaises(ValueError):e.teach_language('1700 и 1700',dict(kind='field',focus='FIELD',value='1700'))
        self.assertEqual(e.model,before)
    def test_cli_say_no_permission_no_act(self):
        from kolos_states.cli import Terminal
        import threading,types
        e,w,_=prepare_language();t=Terminal.__new__(Terminal);t.engine=e;t.running=False;t.recording=False;t.schedule=None;t.pending_phrase='';t.language_auto=False;t.abort=threading.Event();t.pause=threading.Event();t._arm=Mock(side_effect=PermissionError('disabled'))
        # This unit invokes command() without main()'s UTF-8 console setup.
        # Capture the message instead of relying on the CI host code page.
        output=io.StringIO()
        with redirect_stdout(output):
            t.command('/say я хочу увидеть 1354 в поле');t._arm.assert_not_called();self.assertFalse(t.language_auto);self.assertEqual(t.schedule[0],'language')
            with self.assertRaises(PermissionError):t.command('/say-run я хочу увидеть 1354 в поле')
            self.assertFalse(t.language_auto)
            t.command('/pause');self.assertIsNone(t.schedule)
        self.assertIn('языковые связи',output.getvalue())
    def test_grounding_is_not_ignorable_annotation(self):
        e,w,text=prepare_language();g=next(n for n in e.model['languageMemory']['nodes'] if n['kind']=='glyph' and n['char']=='3')
        edge=next(e for e in e.model['languageMemory']['edges'] if e['kind']=='ground' and e['from']==g['id'])
        edge['to']=next(n['id'] for n in e.model['memory']['nodes'] if n['kind']=='symbol' and n['value']=='4')
        decode(e,w,text);self.assertEqual(e.model['language']['goal']['value'],'1454')
if __name__=='__main__':unittest.main()
