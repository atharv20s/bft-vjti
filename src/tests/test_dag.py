import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import ScenarioConfig, AttackType
from algorithms.dag_bft import run_dag_bft, HashgraphProtocol, Event
from network import setup_network


class TestDagBFT(unittest.TestCase):
    def test_dag_honest_consensus(self):
        scenario = ScenarioConfig(
            name="test_dag_honest",
            num_nodes=4,
            num_traitors=0,
            num_transactions=10,
            num_trials=1,
        )
        metrics = run_dag_bft(scenario, seed=42)
        self.assertTrue(metrics.consensus_success)
        self.assertEqual(metrics.agreement_rate, 1.0)
        self.assertIsNotNone(metrics.agreed_value)

    def test_dag_with_traitor(self):
        # n = 4, f = 1
        scenario = ScenarioConfig(
            name="test_dag_traitor",
            num_nodes=4,
            num_traitors=1,
            attack_type=AttackType.CONFLICTING_BROADCAST,
            num_transactions=10,
            num_trials=1,
        )
        metrics = run_dag_bft(scenario, seed=42)
        self.assertTrue(metrics.consensus_success)
        self.assertEqual(metrics.agreement_rate, 1.0)

    def test_event_hashing(self):
        e1 = Event(creator=1, self_parent="h1", other_parent="h2", payload="data", timestamp=10.0)
        e2 = Event(creator=1, self_parent="h1", other_parent="h2", payload="data", timestamp=10.0)
        self.assertEqual(e1.hash, e2.hash)
        
        e3 = Event(creator=1, self_parent="h1", other_parent="h2", payload="different_data", timestamp=10.0)
        self.assertNotEqual(e1.hash, e3.hash)


if __name__ == "__main__":
    unittest.main()
