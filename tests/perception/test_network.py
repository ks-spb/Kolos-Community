"""Causal checks: pixels and learned links must determine the motor target."""
from __future__ import annotations

import unittest
from itertools import permutations
from kolos_states.core import StateEngine
from kolos_states.perception.learning import teach
from kolos_states.perception.matching import binding, evaluate
from kolos_states.perception.dynamics import advance, attention, runtime
from kolos_states.perception.types import views
from kolos_states.protocol import clone, guard
from kolos_states.memory import validate_graph
from tests.perception.fixtures import scene, learned, observation, arranged_scene
from Glaz.perception.retina import lesson


class VisualNetworkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = StateEngine(); self.target, self.lesson = learned(self.engine)

    def test_moved_icon_is_resolved_by_label_for_every_permutation(self) -> None:
        for order in permutations(range(3)):
            with self.subTest(order=order):
                frame, boxes, _ = scene(order=order)
                observed = observation(self.engine, self.target, frame, boxes, cursor=tuple(boxes[1][:2]))
                result = binding(self.engine.model['memory'], self.target, observed, self.engine.model['config'])
                self.assertIsNotNone(result)
                self.assertEqual(result['bbox'], boxes[0])

    def test_same_label_and_unknown_label_do_not_guess(self) -> None:
        for names in [('Contracts',)*3, ('Letters', 'Documents', 'Reports')]:
            frame, boxes, _ = scene(names)
            observed = observation(self.engine, self.target, frame, boxes)
            self.assertIsNone(binding(self.engine.model['memory'], self.target, observed, self.engine.model['config']))

    def test_zero_label_or_spatial_synapses_remove_recognition(self) -> None:
        frame, boxes, _ = scene(); observed = observation(self.engine, self.target, frame, boxes)
        for role in ('label', 'relation'):
            memory = clone(self.engine.model['memory'])
            node = next(n for n in memory['nodes'] if n.get('role') == role or
                        role == 'relation' and n['kind'] == 'visual_relation')
            for edge in memory['edges']:
                if edge['from'] == node['id']:
                    edge['weight'] = 0
            self.assertIsNone(binding(memory, self.target, observed, self.engine.model['config']))

    def test_attention_weights_change_the_actual_request(self) -> None:
        model = self.engine.model; current = runtime(model, self.target); current['I'] = 1
        first = attention(model, self.target, current)
        self.assertEqual([v['detail'] for v in first], [0])
        for edge in model['memory']['edges']:
            if edge['from'] == self.target and edge['kind'] == 'visual_attention':
                edge['weight'] = 1 if self.engine.node(edge['to'])['detail'] else 0
        self.assertEqual([v['detail'] for v in attention(model, self.target, current)], [1])

    def test_top_down_current_without_pixels_cannot_authorize_action(self) -> None:
        model = self.engine.model; state = self.engine.state(dict(features=[], icons=[], cursor=dict(x=0,y=0), selected='',focus='',output=''), True)
        step = self.engine._node(kind='step', label='check', action=dict(kind='check', object='A', visual=self.target, visual_object='A'), pre=state['id'], post=state['id'])
        self.engine._edge(step['id'], self.target, 'visual_ground', 1)
        model.update(heldGoal=True, observed=dict(perception_samples={}))
        for _ in range(12):
            self.assertFalse(advance(model, step)['ready'])
        self.assertGreater(model['perception']['I'], .9)
        self.assertFalse(model['perception']['winner'])

    def test_right_label_and_another_scale_are_shown_variants(self) -> None:
        frame, boxes, labels = scene(right=True, factor=2)
        teach(self.engine, dict(lesson(frame, boxes[0], labels[0], 40), name='Same', target=self.target))
        observed = observation(self.engine, self.target, frame, boxes)
        self.assertEqual(binding(self.engine.model['memory'], self.target, observed, self.engine.model['config'])['bbox'], boxes[0])

    def test_shown_left_above_and_multiline_labels_survive_relocation(self) -> None:
        for position in ('left','above','multiline'):
            with self.subTest(position=position):
                frame,boxes,labels=arranged_scene(position)
                teach(self.engine,dict(lesson(frame,boxes[0],labels[0],40),name='Layout',target=self.target))
                frame,boxes,_=arranged_scene(position,order=(2,0,1))
                observed=observation(self.engine,self.target,frame,boxes)
                proof=binding(self.engine.model['memory'],self.target,observed,self.engine.model['config'])
                self.assertIsNotNone(proof);self.assertEqual(proof['bbox'],boxes[0])

    def test_repeated_supervision_strengthens_links_without_new_variant(self) -> None:
        count = len(self.engine.model['memory']['nodes'])
        before = [e['weight'] for e in self.engine.model['memory']['edges']]
        teach(self.engine, dict(self.lesson, target=self.target))
        self.assertEqual(len(self.engine.model['memory']['nodes']), count)
        self.assertGreater(sum(e['weight'] for e in self.engine.model['memory']['edges']), sum(before))

    def test_repeat_strengthens_only_the_shown_variant(self) -> None:
        frame, boxes, labels = scene(right=True)
        teach(self.engine, dict(lesson(frame, boxes[0], labels[0], 40), name='Side', target=self.target))
        other = self.engine.model['visualLessons'][-1]['variant']
        edges = self.engine.model['memory']['edges']
        before = {e['id']: e['weight'] for e in edges if e['to'] == other or e['from'] == other}
        teach(self.engine, dict(self.lesson, target=self.target))
        self.assertEqual({e['id']: e['weight'] for e in edges if e['id'] in before}, before)

    def test_node_ids_and_storage_order_do_not_choose_an_instance(self) -> None:
        memory = self.engine.model['memory']
        ids = {n['id']: 'renamed-'+str(9999-i) for i,n in enumerate(memory['nodes'])}
        for node in memory['nodes']:
            node['id'] = ids[node['id']]
            if 'variant' in node: node['variant'] = ids[node['variant']]
        for edge in memory['edges']:
            edge['from'],edge['to'] = ids[edge['from']],ids[edge['to']]
        memory['nodes'].reverse(); memory['edges'].reverse()
        target = ids[self.target]; frame,boxes,_ = scene(order=(2,0,1))
        proof = binding(memory,target,observation(self.engine,target,frame,boxes),self.engine.model['config'])
        self.assertEqual(proof['bbox'],boxes[0])

    def test_saved_graph_is_valid_and_empty_first_image_is_rejected(self) -> None:
        validate_graph(self.engine.model['memory'], [])
        before = clone(self.engine.model)
        bad = dict(self.lesson, label=dict(width=1, height=24, data='00'*24))
        with self.assertRaises(ValueError):
            teach(self.engine, bad)
        self.assertEqual(self.engine.model, before)

    def test_fresh_proof_does_not_survive_another_frame(self) -> None:
        frame, boxes, _ = scene(); obs = observation(self.engine, self.target, frame, boxes, cursor=(40,40))
        proof = binding(self.engine.model['memory'], self.target, obs, self.engine.model['config'])
        obs['visual_bindings'] = {self.target: proof}; action = dict(kind='click', object='A', visual=self.target)
        self.assertFalse(guard(obs, action)); obs['version'] += 1
        self.assertTrue(guard(obs, action))


if __name__ == '__main__':
    unittest.main()
