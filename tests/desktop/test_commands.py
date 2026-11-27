"""Typing generalization with varied hover positions and previously saved paths."""
import json
import unittest
from unittest.mock import Mock, patch

from kolos_states.commands import AmbiguousCommand
from kolos_states.core import StateEngine
from kolos_states.cli import Terminal
from kolos_states.memory import validate_graph
from kolos_states.protocol import clone, compact, observation_key, persistent_graph
from kolos_states.simulator import apply, default_world, demonstrate, icon_actions, observe


class CommandTests(unittest.TestCase):
    def lessons(self, *, legacy: bool = False, separator: str = '',
                other_target: bool = False, other_field: bool = False) -> tuple[StateEngine, dict]:
        """Demonstrate the same command with independently observed hover positions."""
        engine=StateEngine();engine.configure(plasticity=0);world=default_world()
        first=separator.join('12345')
        engine.learn(demonstrate('впиши '+first,world,
            icon_actions(world,'CALC')+[dict(kind='key',value=c) for c in first]))
        second_world=clone(world);second_world['surfaces']['desk']['icons'][2]['y']+=9
        target='OTHER' if other_target else 'CALC'
        second_world['surfaces']['desk']['icons'][2]['id']=target
        if other_field:second_world['surfaces']['calculator']['field']='OTHER-FIELD'
        previous=clone(engine.model['commands']) if legacy else []
        if legacy:engine.model['commands']=[]
        second=separator.join('6789')
        engine.learn(demonstrate('впиши '+second,second_world,
            icon_actions(second_world,target)+[dict(kind='key',value=c) for c in second]))
        if legacy:
            engine.model['commands']=previous+engine.model['commands']
            for command,record in zip(engine.model['commands'],engine.model['lessons']):
                setup=[r for r in record['receipts'] if r['action']['kind']!='key']
                command['signature']=compact([command['context'],True,
                    [[r['action'],observation_key(r['before']),observation_key(r['after'])] for r in setup]])
        return engine,world

    def execute(self, engine: StateEngine, world: dict, target: str) -> None:
        """Execute an unseen order and require its actual receipt-confirmed output."""
        before=persistent_graph(engine.model['memory'])
        engine.start('впиши '+target,observe(world))
        for _ in range(400):
            if engine.model['status']=='complete':break
            engine.tick()
            if engine.model['pending']:engine.accept_receipt(apply(world,engine.model['pending']))
        self.assertEqual(engine.model['status'],'complete',engine.model['message'])
        self.assertEqual(world['output'],target);self.assertEqual(len(engine.model['lessons']),2)
        self.assertEqual(persistent_graph(engine.model['memory']),before)

    def test_varied_hover_teaches_one_command_and_types_digits_from_both_lessons(self):
        for separator in ('',' '):
            with self.subTest(separator=separator):
                engine,world=self.lessons(separator=separator)
                self.assertEqual(len(engine.model['commands']),1)
                self.execute(engine,world,separator.join('1346'))

    def test_saved_coordinate_sensitive_commands_work_after_reload_without_relearning(self):
        engine,world=self.lessons(legacy=True)
        self.assertEqual(len(engine.model['commands']),2)
        self.assertNotEqual(*[c['signature'] for c in engine.model['commands']])
        raw=json.loads(json.dumps(engine.model));validate_graph(raw['memory'],raw['commands'])
        restored=StateEngine();restored.model.update(raw)
        self.execute(restored,world,'1346')
        self.assertEqual(len(restored.model['commands']),2)

    def test_different_targets_or_fields_still_refuse_to_choose(self):
        for difference in ('other_target','other_field'):
            with self.subTest(difference=difference):
                engine,_=self.lessons(**{difference:True})
                self.assertEqual(len(engine.model['commands']),2)
                with self.assertRaises(AmbiguousCommand):engine.inspect('впиши 1346')
                self.assertIsNone(engine.model['pending'])

    def test_unanchored_absolute_moves_remain_different_commands(self):
        engine=StateEngine();world=default_world();world.update(surface='calculator',focus='FIELD')
        for y,value in ((190,'12345'),(199,'6789')):
            engine.learn(demonstrate('впиши '+value,world,
                [dict(kind='move',x=200,y=y)]+[dict(kind='key',value=c) for c in value]))
        with self.assertRaises(AmbiguousCommand):engine.inspect('впиши 1346')

    def test_key_only_lessons_in_different_fields_are_not_merged(self):
        engine=StateEngine();world=default_world();world['surface']='calculator'
        for focus,value in (('FIELD','12345'),('OTHER','6789')):
            world['focus']=focus
            engine.learn(demonstrate('впиши '+value,world,[dict(kind='key',value=c) for c in value]))
        with self.assertRaises(AmbiguousCommand):engine.inspect('впиши 1346')

    def test_ambiguity_does_not_redirect_to_language_training_or_arm_input(self):
        engine,_=self.lessons(other_field=True);engine.model['languageMemory']={'lessons':[{}]}
        terminal=Terminal.__new__(Terminal);terminal.engine=engine;terminal._arm=Mock()
        with patch('builtins.print') as output:terminal.command('впиши 1346')
        terminal._arm.assert_not_called()
        self.assertIn('Ввод не запущен',output.call_args.args[0])
        self.assertNotIn('Для обучения действиям нажмите 3',output.call_args.args[0])


if __name__=='__main__':unittest.main()
