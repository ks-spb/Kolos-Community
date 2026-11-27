import copy
import json
import re
import tempfile
import unittest
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from urllib.parse import urljoin
from kolos_states.neuron_trace import NeuronTraceWriter
from kolos_states.neuron_server import NeuronServer
from kolos_states.ipc import atomic_json
from kolos_states.simulator import prepare_case,observe
ROOT=Path(__file__).resolve().parents[2]

class NeuronViewTests(unittest.TestCase):
    def test_live_viewer_module_imports_are_served(self):
        with tempfile.TemporaryDirectory() as d:
            server=NeuronServer(ROOT,Path(d),'s')
            try:
                address=f'http://127.0.0.1:{server.server.server_port}'
                pending=[address+'/web/neurons/app.mjs'];seen=set()
                while pending:
                    url=pending.pop()
                    if url in seen:continue
                    seen.add(url)
                    with self.subTest(module=url):
                        with urlopen(url) as reply:source=reply.read().decode('utf-8')
                        for dependency in re.findall(r'''\bfrom\s+['"]([^'"]+)['"]''',source):
                            pending.append(urljoin(url,dependency))
                self.assertIn(address+'/web/states/core.mjs',seen)
            finally:server.close()

    def test_disabled_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            writer=NeuronTraceWriter(Path(d),'s');engine,_,_=prepare_case(1)
            self.assertFalse(writer.capture(engine));self.assertFalse((Path(d)/'neuron-frames').exists())
    def test_capture_does_not_mutate_any_engine_value(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);atomic_json(p/'neuron-watch.json',dict(session='s',enabled=True))
            engine,world,query=prepare_case(1);engine.start(query,observe(world));before=copy.deepcopy(engine.model)
            writer=NeuronTraceWriter(p,'s');self.assertTrue(writer.capture(engine));self.assertFalse(writer.capture(engine))
            self.assertEqual(engine.model,before)
            raw=json.loads(next((p/'neuron-frames').glob('*.json')).read_text(encoding='utf-8'))
            self.assertEqual(raw['model']['memory'],before['memory']);self.assertEqual(raw['event'],engine.events[-1]);self.assertNotIn('world',raw['model'])
    def test_ring_buffer_is_bounded(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);atomic_json(p/'neuron-watch.json',dict(session='s',enabled=True));writer=NeuronTraceWriter(p,'s',capacity=3);engine,_,_=prepare_case(1)
            for _ in range(8):engine.tick();writer.capture(engine)
            self.assertEqual(len(list((p/'neuron-frames').glob('*.json'))),3)
    def test_restart_keeps_increasing_sequence(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);atomic_json(p/'neuron-watch.json',dict(session='s',enabled=True));engine,_,_=prepare_case(1)
            first=NeuronTraceWriter(p,'s');first.capture(engine);engine.tick();first.capture(engine)
            second=NeuronTraceWriter(p,'s');second.capture(engine)
            self.assertEqual(second.sequence,3);self.assertTrue((p/'neuron-frames'/'000000003.json').exists())
    def test_wrong_session_does_not_start_recording(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);atomic_json(p/'neuron-watch.json',dict(session='another',enabled=True));engine,_,_=prepare_case(1)
            self.assertFalse(NeuronTraceWriter(p,'s').capture(engine))
    def test_server_is_loopback_token_protected_readonly_and_allowlisted(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);server=NeuronServer(ROOT,p,'s')
            try:
                address=f'http://127.0.0.1:{server.server.server_port}';self.assertEqual(server.server.server_address[0],'127.0.0.1')
                engine,_,_=prepare_case(1);NeuronTraceWriter(p,'s').capture(engine)
                with self.assertRaises(HTTPError) as no_token:urlopen(address+'/api/frames')
                self.assertEqual(no_token.exception.code,403)
                with urlopen(Request(address+'/api/frames',headers={'X-Kolos-View':server.token})) as r:
                    raw=json.loads(r.read());self.assertEqual(len(raw['frames']),1);self.assertEqual(r.headers.get('Cache-Control'),'no-store');self.assertIsNone(r.headers.get('Access-Control-Allow-Origin'))
                for path in ['/main.py','/../../kolos_states/storage.py','/web/neurons/../../../main.py']:
                    with self.assertRaises(HTTPError) as fail:urlopen(address+path)
                    self.assertEqual(fail.exception.code,404)
                with self.assertRaises(HTTPError) as write:urlopen(Request(address+'/api/frames',data=b'/image-act',method='POST'))
                self.assertEqual(write.exception.code,405)
                with self.assertRaises(HTTPError) as host:urlopen(Request(address+'/api/frames',headers={'Host':'evil.example','X-Kolos-View':server.token}))
                self.assertEqual(host.exception.code,403)
                with self.assertRaises(HTTPError) as origin:urlopen(Request(address+'/api/frames',headers={'Origin':'https://evil.example','X-Kolos-View':server.token}))
                self.assertEqual(origin.exception.code,403)
                with urlopen(address+'/web/neurons/index.html') as r:self.assertIn('neuron-app',r.read().decode())
            finally:server.close()
            self.assertFalse(json.loads((p/'neuron-watch.json').read_text())['enabled'])
    def test_reader_reports_gap_instead_of_inventing_missing_ticks(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);server=NeuronServer(ROOT,p,'s')
            try:
                writer=NeuronTraceWriter(p,'s',capacity=2);engine,_,_=prepare_case(1)
                for _ in range(7):engine.tick();writer.capture(engine)
                url=f'http://127.0.0.1:{server.server.server_port}/api/frames?after=1'
                with urlopen(Request(url,headers={'X-Kolos-View':server.token})) as r:raw=json.loads(r.read())
                self.assertTrue(raw['gap']);self.assertEqual([f['seq'] for f in raw['frames']],[6,7])
            finally:server.close()

if __name__=='__main__':unittest.main()
