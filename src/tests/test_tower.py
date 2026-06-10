import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import ScenarioConfig, AttackType
from algorithms.tower_bft import run_tower_bft, TowerBFTProtocol
from network import setup_network


class TestTowerBFT(unittest.TestCase):
    def test_tower_honest_consensus(self):
        scenario = ScenarioConfig(
            name="test_tower_honest",
            num_nodes=4,
            num_traitors=0,
            num_transactions=10,
            num_trials=1,
        )
        metrics = run_tower_bft(scenario, seed=42)
        self.assertTrue(metrics.consensus_success)
        self.assertEqual(metrics.agreement_rate, 1.0)
        self.assertIsNotNone(metrics.agreed_value)

    def test_tower_with_traitor(self):
        # n = 4, f = 1
        scenario = ScenarioConfig(
            name="test_tower_traitor",
            num_nodes=4,
            num_traitors=1,
            attack_type=AttackType.CONFLICTING_BROADCAST,
            num_transactions=10,
            num_trials=1,
        )
        metrics = run_tower_bft(scenario, seed=42)
        self.assertTrue(metrics.consensus_success)
        self.assertEqual(metrics.agreement_rate, 1.0)

    def test_poh_chain_generation(self):
        net = setup_network(num_nodes=4, num_traitors=0, seed=42)
        tower = TowerBFTProtocol(net, ticks_per_slot=4, num_slots=3)
        # Check that Poh chain has 3 slots * 4 ticks = 12 ticks
        tower._generate_poh_slots("test_value")
        self.assertEqual(len(tower.poh_chain), 12)
        # Check sequential hashing property
        for i in range(1, 12):
            self.assertEqual(tower.poh_chain[i].previous_hash, tower.poh_chain[i-1].hash)


if __name__ == "__main__":
    unittest.main()
