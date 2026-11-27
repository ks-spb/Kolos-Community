"""Partial labels, real detector proposals, persistence and presentation contracts."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import ImageDraw
from Glaz.image_processor import ImageProcessor, LineBasedDetector
from Glaz.cursor_target import pointed_bbox_index
from Glaz.perception.retina import lesson, collect
from kolos_states.core import StateEngine
from kolos_states.storage import Store
from kolos_states.ipc import atomic_json, read_json
from kolos_states.protocol import clone, persistent_graph
from kolos_states.memory import validate_graph
from kolos_states.neuron_projection import project_neurons
from kolos_states.perception.learning import teach, bind
from kolos_states.perception.matching import binding
from kolos_states.perception.types import views
from kolos_states.perception.observer import VisualAccessibility
from tests.perception.fixtures import scene, learned, observation, font
from tests.perception.test_integration import motor_lesson, terminal_case


class ImageBoundaryTests(unittest.TestCase):
    def test_real_glaz_detector_and_cyrillic_labels_survive_relocation(self) -> None:
        engine = StateEngine(); names = ('Договоры', 'Документы', 'Отчёты')
        frame, boxes, labels = scene(names)
        def detect(image):
            return [list(o.bbox) for o in LineBasedDetector().detect(ImageProcessor.detect_color_peaks(image,40,False))]
        found = detect(frame); index = pointed_bbox_index(found,(45,50))
        self.assertIsNotNone(index)
        target = teach(engine,dict(lesson(frame,found[index],labels[0],40),name='Цель'))
        frame, boxes, _ = scene(names,order=(2,0,1)); proposed = detect(frame)
        obs = observation(engine,target,frame,proposed)
        result = binding(engine.model['memory'],target,obs,engine.model['config'])
        self.assertIsNotNone(result)
        l,t,r,b = result['bbox']
        self.assertTrue(l <= 425 <= r and t <= 50 <= b)

    def test_shown_prefix_distinguishes_objects_but_shared_prefix_does_not(self) -> None:
        engine=StateEngine();target,_=learned(engine)
        frame,boxes,labels=scene(('Contr...', 'Docum...', 'Repor...'))
        teach(engine,dict(lesson(frame,boxes[0],labels[0],40),name='Prefix',target=target,clipped='right'))
        obs=observation(engine,target,frame,boxes)
        self.assertEqual(binding(engine.model['memory'],target,obs,engine.model['config'])['bbox'],boxes[0])
        frame,boxes,_=scene(('Contr...',)*3)
        self.assertIsNone(binding(engine.model['memory'],target,observation(engine,target,frame,boxes),engine.model['config']))

    def test_unknown_crop_or_blank_label_is_not_an_invisible_suffix(self) -> None:
        engine=StateEngine();target,_=learned(engine)
        for names in [('Contr...', 'Docum...', 'Repor...'), ('', '', '')]:
            frame,boxes,_=scene(names)
            self.assertIsNone(binding(engine.model['memory'],target,observation(engine,target,frame,boxes),engine.model['config']))

    def test_label_belongs_to_its_own_icon_and_does_not_cross_into_glaz(self) -> None:
        engine=StateEngine();target,_=learned(engine);frame,boxes,_=scene()
        req=views(engine.model['memory'],target,fine_only=True)
        samples=collect(frame,boxes,req,40,dict(left=0,top=0),own_rect=[15,70,180,110])
        obs=observation(engine,target,frame,boxes);obs['perception_samples']=samples
        self.assertIsNone(binding(engine.model['memory'],target,obs,engine.model['config']))

    def test_separate_own_windows_do_not_mask_the_gap_between_them(self) -> None:
        engine=StateEngine();target,_=learned(engine);frame,boxes,_=scene(order=(1,0,2))
        req=views(engine.model['memory'],target,fine_only=True)
        samples=collect(frame,boxes,req,40,dict(left=0,top=0),own_rects=[[0,0,180,150],[400,0,600,150]])
        obs=observation(engine,target,frame,boxes);obs['perception_samples']=samples
        self.assertEqual(binding(engine.model['memory'],target,obs,engine.model['config'])['bbox'],boxes[0])

    def test_incomplete_or_excessive_candidate_set_cannot_authorize_a_click(self) -> None:
        engine=StateEngine();target,_=learned(engine);frame,boxes,_=scene()
        req=views(engine.model['memory'],target,fine_only=True)
        samples=collect(frame,[[i,35,i+30,65] for i in range(201)],req,40,dict(left=0,top=0))
        self.assertFalse(samples['complete'])
        obs=observation(engine,target,frame,boxes);obs['perception_samples']=samples
        self.assertIsNone(binding(engine.model['memory'],target,obs,engine.model['config']))

    def test_deleting_fragment_link_does_not_create_a_shorter_label(self) -> None:
        engine=StateEngine();target,_=learned(engine);memory=engine.model['memory']
        part=next(n for n in memory['nodes'] if n.get('role')=='label')
        edge=next(e for e in memory['edges'] if e['kind']=='visual_contains' and e['to']==part['id'])
        memory['edges'].remove(edge)
        with self.assertRaises(ValueError):validate_graph(memory,[])
        frame,boxes,_=scene()
        self.assertIsNone(binding(memory,target,observation(engine,target,frame,boxes),engine.model['config']))

    def test_projection_contains_actual_visual_currents_and_does_not_mutate(self) -> None:
        terminal,screen,target=terminal_case()
        from tests.perception.test_integration import VisualIntegrationTests
        VisualIntegrationTests().run_attempt(terminal)
        before=clone(terminal.engine.model)
        frame=project_neurons(before,terminal.engine.events[-1])
        self.assertEqual(terminal.engine.model,before)
        self.assertTrue(any(n['group']=='visual' and n['S'] is not None for n in frame['nodes']))
        self.assertTrue(any(e['provenance']=='recorded' and e['kind']=='visual-sensory' for e in frame['edges']))

    def test_visual_mode_has_no_accessibility_import_or_dependency(self) -> None:
        with patch('kolos_states.perception.observer.sys.platform','linux'):
            observer=VisualAccessibility(0);observer.ensure_available()
            self.assertFalse(observer.read()['readable'])
        source=Path('kolos_states/perception/observer.py').read_text(encoding='utf-8')
        self.assertNotIn('import uiautomation',source)


class PersistenceTests(unittest.TestCase):
    def test_oversized_memory_is_rejected_before_replacing_the_old_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory))
            try:
                engine=StateEngine();store.save(engine);path=Path(directory)/'memory.json'
                before=path.read_bytes();learned(engine)
                with patch('kolos_states.storage.MAX_BYTES',len(before)+10):
                    with self.assertRaises(ValueError):store.save(engine)
                self.assertEqual(path.read_bytes(),before)
            finally:store.close()

    def test_new_experience_copies_grounding_without_corrupting_state_reference(self) -> None:
        from kolos_states.experience import remember, actions
        engine=StateEngine();engine.learn(motor_lesson());target,_=learned(engine);bind(engine,'o1','A',target)
        step=next(n for n in engine.model['memory']['nodes'] if n.get('action',{}).get('kind')=='enter')
        receipt=clone(motor_lesson()['receipts'][-1]);receipt.update(step=step['id'],action=clone(step['action']))
        receipt['after']['features']=['visible:NEW_WINDOW']
        transition,created=remember(engine.model,[receipt])
        self.assertTrue(created);self.assertEqual(engine.node(transition['from'])['kind'],'state')
        self.assertEqual(actions(engine.model,transition)[0]['visual'],target)
        self.assertTrue(any(e['kind']=='visual_ground' and e['from']==transition['first'] for e in engine.model['memory']['edges']))
        validate_graph(engine.model['memory'],engine.model['commands'])

    def test_missing_executed_grounding_does_not_partially_learn(self) -> None:
        from kolos_states.experience import remember
        engine=StateEngine();target,_=learned(engine);receipt=clone(motor_lesson()['receipts'][-1])
        receipt['action'].update(visual=target,visual_object='A');receipt['step']='unknown'
        before=clone(engine.model['memory'])
        self.assertEqual(remember(engine.model,[receipt]),(None,False))
        self.assertEqual(engine.model['memory'],before)

    def test_v2_migration_preserves_graph_pending_audit_and_creates_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);store=Store(folder)
            try:
                engine=StateEngine();engine.learn(motor_lesson());store.save(engine)
                raw=read_json(folder/'memory.json');raw['schema']='kolos-desktop-states/2'
                atomic_json(folder/'memory.json',raw)
                atomic_json(folder/'last-attempt.json',dict(pending={'id':'unsure'}))
                restored=store.load()
                self.assertEqual(persistent_graph(restored.model['memory']),persistent_graph(engine.model['memory']))
                self.assertIsNone(restored.model['pending'])
                self.assertEqual(read_json(folder/'last-attempt.json')['pending']['id'],'unsure')
                backups=list(folder.glob('memory-v2-*.json'))
                self.assertEqual(len(backups),1);self.assertEqual(read_json(backups[0]),raw)
                self.assertEqual(read_json(folder/'memory.json')['schema'],'kolos-desktop-states/4')
            finally:store.close()

    def test_visual_graph_and_command_binding_survive_without_live_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory))
            try:
                engine=StateEngine();engine.learn(motor_lesson());target,_=learned(engine);bind(engine,'o1','A',target)
                engine.model['perception']=dict(target=target,I=1,requests=[{'unsafe':'old'}])
                store.save(engine);restored=store.load()
                self.assertEqual(persistent_graph(restored.model['memory']),persistent_graph(engine.model['memory']))
                self.assertNotIn('perception',restored.model)
                self.assertEqual(restored.inspect('o1')['command']['label'],'o1')
                frame,boxes,_=scene(order=(2,1,0))
                self.assertEqual(binding(restored.model['memory'],target,observation(restored,target,frame,boxes),restored.model['config'])['bbox'],boxes[0])
            finally:store.close()

    def test_corrupted_visual_memory_is_not_overwritten_or_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);store=Store(folder)
            try:
                engine=StateEngine();learned(engine);store.save(engine)
                raw=read_json(folder/'memory.json')
                next(n for n in raw['memory']['nodes'] if n['kind']=='visual_fragment')['data']='invalid'
                atomic_json(folder/'memory.json',raw);before=(folder/'memory.json').read_bytes()
                with self.assertRaises(ValueError):store.load()
                self.assertEqual((folder/'memory.json').read_bytes(),before)
            finally:store.close()


if __name__ == '__main__':unittest.main()
