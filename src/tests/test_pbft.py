import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import ScenarioConfig, AttackType
from algorithms.pbft import run_pbft


class TestPBFT(unittest.TestCase):
    def test_pbft_honest_consensus(self):
        scenario = ScenarioConfig(
            name="test_pbft_honest",
            num_nodes=4,
            num_traitors=0,
            num_transactions=10,
            num_trials=1,
        )
        metrics = run_pbft(scenario, seed=42)
        self.assertTrue(metrics.consensus_success)
        self.assertEqual(metrics.agreement_rate, 1.0)
        self.assertIsNotNone(metrics.agreed_value)

    def test_pbft_with_traitor(self):
        # n = 4, f = 1. Tolerable since n >= 3f+1.
        scenario = ScenarioConfig(
            name="test_pbft_traitor",
            num_nodes=4,
            num_traitors=1,
            attack_type=AttackType.CONFLICTING_BROADCAST,
            num_transactions=10,
            num_trials=1,
        )
        metrics = run_pbft(scenario, seed=42)
        self.assertTrue(metrics.consensus_success)
        self.assertEqual(metrics.agreement_rate, 1.0)

    def test_pbft_failures_above_threshold(self):
        # n = 4, f = 2. Fails BFT requirement (n >= 3f+1 is false: 4 < 7)
        scenario = ScenarioConfig(
            name="test_pbft_unstable",
            num_nodes=4,
            num_traitors=2,
            attack_type=AttackType.CONFLICTING_BROADCAST,
            num_transactions=10,
            num_trials=1,
        )
        metrics = run_pbft(scenario, seed=42)
        self.assertFalse(metrics.consensus_success)


if __name__ == "__main__":
    unittest.main()
