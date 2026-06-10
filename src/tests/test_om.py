import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import ScenarioConfig, AttackType
from algorithms.oral_message import run_oral_message, OralMessageAlgorithm
from network import setup_network


class TestOralMessage(unittest.TestCase):
    def test_om_honest_consensus(self):
        # n = 4, f = 0, m = 0
        scenario = ScenarioConfig(
            name="test_om_honest",
            num_nodes=4,
            num_traitors=0,
            num_transactions=10,
            num_trials=1,
        )
        
        metrics = run_oral_message(scenario, seed=42)
        self.assertTrue(metrics.consensus_success)
        self.assertEqual(metrics.agreement_rate, 1.0)
        self.assertIsNotNone(metrics.agreed_value)

    def test_om_traitor_ev(self):
        # n = 4, f = 1 (1 traitor EV, commander DN is honest). Tolerable since 4 >= 3(1)+1.
        scenario = ScenarioConfig(
            name="test_om_traitor_ev",
            num_nodes=4,
            num_traitors=1,
            attack_type=AttackType.CONFLICTING_BROADCAST,
            num_transactions=10,
            num_trials=1,
        )
        
        metrics = run_oral_message(scenario, seed=42)
        self.assertTrue(metrics.consensus_success)
        # 3 honest nodes (1 DN, 2 honest EVs). All 2 honest EVs should agree on DN's value.
        self.assertEqual(metrics.agreement_rate, 1.0)

    def test_om_traitor_commander(self):
        # n = 4, f = 1, where the commander (DN) is the traitor.
        # We manually configure this to test the recursion.
        net = setup_network(
            num_nodes=4,
            num_traitors=1,
            attack_type=AttackType.CONFLICTING_BROADCAST,
            seed=42
        )
        # Force the commander (node 0) to be a traitor
        net.nodes[0].is_traitor = True
        
        om = OralMessageAlgorithm(net, commander_id=0)
        # Commander proposes "demand=150", but is a traitor
        decisions = om.run("demand=150", m=1)
        
        # All honest lieutenants (nodes 1, 2, 3) must agree on the same value (even if it's the default "RETREAT")
        # due to OM(1)'s properties.
        traitor_ids = {0}
        from metrics import compute_agreement_rate
        agreement = compute_agreement_rate(decisions, traitor_ids)
        self.assertEqual(agreement, 1.0)


if __name__ == "__main__":
    unittest.main()
