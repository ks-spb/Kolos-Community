"""The twelve earlier abilities and E13 coexist with a learned common object."""
import unittest
from kolos_states.shared_experiment import SharedSession
from kolos_states.episode_experiment import demonstration, FormWorld, run as run_episode
from kolos_states.desktop import DesktopAdapter
from kolos_states import object_concepts
from test_object_concepts import World, lesson, run

class SharedRegressionTests(unittest.TestCase):
    def test_previous_abilities_before_and_after_concept_and_episode_learning(self):
        session=SharedSession()
        self.assertTrue(all(r['pass'] for r in session.run_all()))
        engine=session.engine;engine.reset();engine.learn(lesson())
        world=World('glaz.50');world.model_provider=lambda:engine.model
        adapter=DesktopAdapter(world,world,allow=lambda:True,timeout=.1)
        engine.start('O1',world.observe());self.assertEqual(run(engine,world,adapter),'needs-help')
        object_concepts.answer(engine,engine.model['objectQuestion']['id'],'yes',world.observe())
        self.assertEqual(run(engine,world,adapter),'complete')
        engine.reset();engine.learn_episode(demonstration())
        episode=run_episode(engine,FormWorld(('new common-object regression value',),layout=1))
        self.assertTrue(episode['passed'],episode)
        engine.reset()
        results=SharedSession(engine=engine).run_all(range(12,0,-1))
        self.assertTrue(all(r['pass'] for r in results),results)

if __name__=='__main__':unittest.main()
