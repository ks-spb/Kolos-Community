import json
from pathlib import Path
import random
import tempfile
import unittest
from kolos_states.core import StateEngine
from kolos_states.episodes import SCHEMA, observe, values
from kolos_states.episode_experiment import FormWorld, demonstration, run, memory_signature, report
from kolos_states.protocol import clone, compact, persistent_graph
from kolos_states.simulator import default_world, demonstrate, icon_actions
from kolos_states.storage import Store


class EpisodeTests(unittest.TestCase):
    def trained(self, sources=('alpha',), query='Copy the observed fields and save'):
        engine = StateEngine()
        engine.learn_episode(demonstration(FormWorld(sources), query))
        return engine

    def pending(self, engine, world):
        for _ in range(30):
            event = engine.tick()
            if event['kind'] == 'dispatch':
                return clone(engine.model['pending'])
        self.fail(engine.model['message'])

    def test_unknown_values_and_layouts_without_relearning(self):
        e = self.trained()
        for value in ('6143', '  different text  ', 'Привет Ω 🙂', '', 'a\nb\tc', '0'*20000):
            for layout in (0, 1, 2):
                with self.subTest(value=value[:30], layout=layout):
                    e.reset()
                    result = run(e, FormWorld((value,), layout=layout))
                    self.assertTrue(result['passed'], result)
        self.assertEqual(len(e.model['learningLog']), 1)

    def test_multiple_sources_and_internal_input_blocks(self):
        e = self.trained(('first sample', 'second sample'))
        r = run(e, FormWorld(('new one', 'new two'), layout=1))
        self.assertTrue(r['passed'], r)
        self.assertEqual([a['kind'] for a in r['actions']], ['read', 'write', 'read', 'write', 'activate'])

    def test_request_does_not_contain_the_unknown_value(self):
        query = 'An arbitrary taught phrase'
        e = self.trained(query=query)
        r = run(e, FormWorld(('never in the phrase or training',)), query=query)
        self.assertTrue(r['passed'])
        self.assertNotIn('never in the phrase or training', memory_signature(e))

    def test_no_hidden_route_without_demonstration(self):
        e = StateEngine()
        with self.assertRaises(ValueError):
            e.start_episode('Copy the observed fields and save', FormWorld().observe())
        self.assertEqual(e.model['memory']['edges'], [])

    def test_teaching_rollback_and_no_half_graph(self):
        e = StateEngine()
        record = demonstration()
        record['receipts'][1]['after']['objects'][0]['value'] = 'unexplained mutation'
        before = clone(e.model)
        with self.assertRaises(ValueError):
            e.learn_episode(record)
        self.assertEqual(e.model, before)

    def test_disconnected_observations_are_not_a_demonstration(self):
        for field, value in [('session', 'foreign'), ('version', 0)]:
            e = StateEngine()
            record = demonstration()
            record['receipts'][1]['before'][field] = value
            with self.assertRaises(ValueError):
                e.learn_episode(record)
            self.assertEqual(len(e.model['memory']['nodes']), 1)

    def test_explicit_read_to_write_dataflow_required(self):
        e = StateEngine()
        record = demonstration()
        record['receipts'][1]['action']['source'] = 'never read'
        with self.assertRaises(ValueError):
            e.learn_episode(record)

    def test_identical_value_sources_are_not_arbitrarily_disambiguated(self):
        e = StateEngine()
        with self.assertRaises(ValueError):
            e.learn_episode(demonstration(FormWorld(('same', 'same'))))
        self.assertEqual(len(e.model['memory']['nodes']), 1)

    def test_failed_save_cannot_release_goal(self):
        e = self.trained()
        w = FormWorld(('new',))
        w.fail_save = True
        r = run(e, w)
        self.assertFalse(r['passed'])
        self.assertFalse(r['checks']['savedExact'])
        self.assertTrue(e.model['heldGoal'])
        self.assertIsNotNone(e.model['pending'])
        self.assertEqual(len([a for a in w.actions if a['kind'] == 'activate']), 1)

    def test_source_mutation_rejected_before_any_save(self):
        e = self.trained()
        w = FormWorld(('new',))
        w.corrupt_source = True
        r = run(e, w)
        self.assertFalse(r['passed'])
        self.assertFalse(any(a['kind'] == 'activate' for a in w.actions))
        self.assertTrue(e.model['heldGoal'])

    def test_missing_ambiguous_unreadable_disabled_sources_fail_closed(self):
        for attribute, value in [('hidden', {'Source 1'}), ('duplicate', 'Source 1'),
                                 ('unreadable', {'Source 1'}), ('disabled', {'Source 1'})]:
            with self.subTest(attribute=attribute):
                e, w = self.trained(), FormWorld()
                setattr(w, attribute, value)
                with self.assertRaises(ValueError):
                    e.start_episode('Copy the observed fields and save', w.observe())
                self.assertFalse(w.actions)

    def test_runtime_ids_never_win_against_a_wrong_descriptor(self):
        e, w = self.trained(), FormWorld()
        obs = w.observe()
        next(o for o in obs['objects'] if o['descriptor']['name'] == 'Source 1')['descriptor']['name'] = 'Different meaning'
        with self.assertRaises(ValueError):
            e.start_episode('Copy the observed fields and save', obs)

    def test_loss_of_role_after_read_blocks_without_write(self):
        e, w = self.trained(), FormWorld()
        e.start_episode('Copy the observed fields and save', w.observe())
        p = self.pending(e, w)
        e.accept_receipt(w.execute(p))
        w.hidden.add('Target 1')
        e.observe(w.observe())
        self.assertEqual(e.tick()['kind'], 'episode-blocked')
        self.assertEqual(len(w.actions), 1)

    def test_stale_foreign_wrong_action_and_duplicate_receipts(self):
        e, w = self.trained(), FormWorld()
        e.start_episode('Copy the observed fields and save', w.observe())
        p = self.pending(e, w)
        r = w.execute(p)
        for target, value in [('version', r['before']['version']), ('session', 'foreign')]:
            invalid = clone(r)
            invalid['after'][target] = value
            pending_before = clone(e.model['pending'])
            with self.assertRaises(ValueError):
                e.accept_receipt(invalid)
            self.assertEqual(e.model['pending'], pending_before)
            self.assertFalse(e.model['episode']['working'])
        wrong = clone(r)
        wrong['action']['object'] = 'wrong'
        self.assertEqual(e.accept_receipt(wrong)['kind'], 'ignored')
        self.assertEqual(e.accept_receipt(r)['kind'], 'episode-ack')
        previous = e.model['episode']['previous']
        self.assertEqual(e.accept_receipt(r)['kind'], 'duplicate')
        self.assertEqual(e.model['episode']['previous'], previous)

    def test_timeout_holds_pending_and_does_not_repeat(self):
        e, w = self.trained(), FormWorld()
        e.start_episode('Copy the observed fields and save', w.observe())
        p = self.pending(e, w)
        for _ in range(100):
            self.assertNotEqual(e.tick()['kind'], 'dispatch')
        self.assertEqual(e.model['status'], 'timeout')
        self.assertEqual(e.model['pending'], p)
        self.assertTrue(e.model['heldGoal'])
        with self.assertRaises(ValueError):
            e.start_episode('Copy the observed fields and save', w.observe())

    def test_reset_discards_values_and_does_not_resume_effects(self):
        e, w = self.trained(), FormWorld(('old attempt',))
        e.start_episode('Copy the observed fields and save', w.observe())
        e.accept_receipt(w.execute(self.pending(e, w)))
        self.assertTrue(e.model['episode']['working'])
        e.reset()
        self.assertNotIn('episode', e.model)
        self.assertTrue(run(e, FormWorld(('new attempt',)))['passed'])

    def test_learning_is_frozen_during_execution(self):
        e, w = self.trained(), FormWorld()
        e.start_episode('Copy the observed fields and save', w.observe())
        before = memory_signature(e)
        with self.assertRaises(ValueError):
            e.learn_episode(demonstration(query='Another episode'))
        self.assertEqual(memory_signature(e), before)

    def test_ablation_of_next_value_binding_and_result_links_blocks(self):
        for kind in ('episode_next', 'episode_value', 'episode_binds', 'episode_produces', 'episode_effect'):
            with self.subTest(kind=kind):
                e = self.trained()
                edge = next(x for x in e.model['memory']['edges'] if x['kind'] == kind)
                e.set_weight(edge['id'], 0)
                r = run(e, FormWorld(('new',)))
                self.assertFalse(r['passed'])
                self.assertTrue(e.model['heldGoal'])

    def test_persistence_rebuilds_graph_but_not_live_working_memory(self):
        e, w = self.trained(), FormWorld(('transient',))
        frozen = memory_signature(e)
        e.start_episode('Copy the observed fields and save', w.observe())
        e.accept_receipt(w.execute(self.pending(e, w)))
        self.pending(e, w)
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            store.save(e)
            loaded = store.load()
            store.close()
        self.assertEqual(memory_signature(loaded), frozen)
        self.assertIsNone(loaded.model['pending'])
        self.assertNotIn('episode', loaded.model)
        self.assertTrue(run(loaded, FormWorld(('after restart',), layout=1))['passed'])

    def test_snapshot_keeps_episode_weights_and_ordinary_command_memory(self):
        e = self.trained()
        world = default_world()
        e.learn(demonstrate('open the window', world, icon_actions(world, 'A')))
        link = next(edge for edge in e.model['memory']['edges'] if edge['kind'] == 'episode_next')
        e.set_weight(link['id'], .73)
        before = persistent_graph(e.model['memory'])
        folder = self.enterContext(tempfile.TemporaryDirectory())
        store = Store(Path(folder))
        self.addCleanup(store.close)
        store.save(e)
        loaded = store.load()
        self.assertEqual(loaded.model['memory'], before)
        self.assertEqual(loaded.model['commands'], e.model['commands'])
        self.assertEqual(loaded.model['episodeCommands'], e.model['episodeCommands'])
        self.assertEqual(loaded.model['learningLog'], e.model['learningLog'])
        self.assertTrue(run(loaded, FormWorld(('new live value',), layout=1))['passed'])

    def test_snapshot_rejects_episode_source_with_wrong_node_kind(self):
        e = self.trained()
        folder = self.enterContext(tempfile.TemporaryDirectory())
        store = Store(Path(folder))
        self.addCleanup(store.close)
        store.save(e)
        path = Path(folder) / 'memory.json'
        raw = json.loads(path.read_text(encoding='utf-8'))
        step = next(n for n in raw['memory']['nodes'] if n['kind'] == 'episode_step' and n['operation'] == 'write')
        step['source'] = raw['memory']['root']
        path.write_text(json.dumps(raw), encoding='utf-8')
        damaged = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'ячейки'):
            store.load()
        self.assertEqual(path.read_bytes(), damaged)

    def test_shared_1_to_12_before_after_and_reload(self):
        result = report()
        self.assertTrue(result['passed'], result)
        from kolos_states.shared_experiment import SharedSession
        s = SharedSession()
        s.engine.learn_episode(demonstration())
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            store.save(s.engine)
            loaded = store.load()
            store.close()
        self.assertEqual(memory_signature(loaded), memory_signature(s.engine))
        order = list(range(1, 13))
        random.Random(17).shuffle(order)
        self.assertTrue(all(r['pass'] for r in SharedSession(engine=loaded).run_all(order)))

    def test_invalid_protected_or_oversized_observations_rejected(self):
        for mutate in ('protected', 'value'):
            obs = FormWorld().observe()
            field = next(o for o in obs['objects'] if o['descriptor']['name'] == 'Source 1')
            field[mutate] = True if mutate == 'protected' else 'x'*20001
            with self.assertRaises(ValueError):
                observe(obs)


if __name__ == '__main__':
    unittest.main()
