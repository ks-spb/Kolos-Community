"""Live scan catalogs are not long-term memory; unknown windows do not learn."""
import json
import tempfile
import unittest
from pathlib import Path
from test_object_concepts import learned, waiting
from kolos_states.storage import Store
from kolos_states import object_concepts as oc

class PersistenceScopeTests(unittest.TestCase):
    def test_live_catalogs_are_omitted_but_prototypes_are_persisted(self):
        e,w,a,q=learned()
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d));store.save(e);raw=json.loads((Path(d)/'memory.json').read_text(encoding='utf-8'));store.close()
        def keys(value):
            if isinstance(value,dict):
                for key,sub in value.items():yield key;yield from keys(sub)
            elif isinstance(value,list):
                for sub in value:yield from keys(sub)
        self.assertNotIn('object_registry',set(keys(raw)));self.assertNotIn('object_instances',set(keys(raw)))
        self.assertTrue(all(len(n['prototype'])==64 for n in raw['memory']['nodes'] if n['kind']=='object_view'))
    def test_unknown_window_identity_cannot_confirm(self):
        e,w,a=waiting();obs=w.observe();obs['window_context']=''
        self.assertFalse(oc.fresh(obs))
        with self.assertRaises(ValueError):oc.answer(e,e.model['objectQuestion']['id'],'yes',obs)
    def test_unanswered_question_is_not_replayed_after_load(self):
        e,w,a=waiting();q=e.model['objectQuestion']
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d));store.save(e);loaded=store.load();store.close()
        self.assertNotIn('objectQuestion',loaded.model)
        with self.assertRaises(ValueError):oc.answer(loaded,q['id'],'yes',w.observe())

if __name__=='__main__':unittest.main()
