import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import ScenarioConfig, AttackType, ShardingStrategy
from algorithms.sharding_bft import run_sharding_bft


class TestShardingBFT(unittest.TestCase):
    def test_sharding_honest_random_consensus(self):
        scenario = ScenarioConfig(
            name="test_sharding_honest_random",
            num_nodes=8,
            num_traitors=0,
            num_shards=2,
            sharding_strategy=ShardingStrategy.RANDOM,
            num_transactions=10,
            num_trials=1,
        )
        metrics = run_sharding_bft(scenario, seed=42)
        self.assertTrue(metrics.consensus_success)
        self.assertEqual(metrics.agreement_rate, 1.0)
        self.assertIsNotNone(metrics.agreed_value)

    def test_sharding_honest_geographic_consensus(self):
        scenario = ScenarioConfig(
            name="test_sharding_honest_geo",
            num_nodes=8,
            num_traitors=0,
            num_shards=2,
            sharding_strategy=ShardingStrategy.GEOGRAPHIC,
            num_transactions=10,
            num_trials=1,
        )
        metrics = run_sharding_bft(scenario, seed=42)
        self.assertTrue(metrics.consensus_success)
        self.assertEqual(metrics.agreement_rate, 1.0)

    def test_sharding_failure_with_compromised_shard(self):
        # With n=8 nodes and 2 shards (4 nodes each).
        # If we have 2 traitors, a shard could end up with 2 traitors.
        # Since 4 nodes with 2 traitors violates n >= 3f+1 (4 < 3*2+1 = 7),
        # that shard should fail, and overall consensus fails.
        scenario = ScenarioConfig(
            name="test_sharding_compromised",
            num_nodes=8,
            num_traitors=2,
            num_shards=2,
            sharding_strategy=ShardingStrategy.RANDOM,
            attack_type=AttackType.CONFLICTING_BROADCAST,
            num_transactions=10,
            num_trials=1,
        )
        metrics = run_sharding_bft(scenario, seed=42)
        # Because at least one shard will violate f_shard <= (n_shard - 1)//3,
        # it should fail.
        self.assertFalse(metrics.consensus_success)


if __name__ == "__main__":
    unittest.main()
