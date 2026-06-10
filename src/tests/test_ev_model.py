import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from ev_model import EVNode, DNNode, EnergyTransaction, TradingRound, create_ev_fleet, create_trading_scenario


class TestEVModel(unittest.TestCase):
    def test_ev_node_eligibility(self):
        # EV with SOC >= 75% should participate
        eligible = EVNode(ev_id=1, battery_capacity=60.0, soc_init=0.85, max_discharge_rate=7.0)
        self.assertTrue(eligible.is_participating)
        self.assertEqual(eligible.soc_reach, 0.30)
        # c_rem = 60 * (0.85 - 0.30) = 33 kWh
        self.assertAlmostEqual(eligible.c_rem, 33.0)
        # energy_available = min(33.0, 7.0 * 2.0 = 14.0) = 14.0
        self.assertAlmostEqual(eligible.energy_available, 14.0)
        
        # EV with SOC < 75% should NOT participate
        non_eligible = EVNode(ev_id=2, battery_capacity=60.0, soc_init=0.70, max_discharge_rate=7.0)
        self.assertFalse(non_eligible.is_participating)
        self.assertAlmostEqual(non_eligible.c_rem, 0.0)
        self.assertAlmostEqual(non_eligible.energy_available, 0.0)

    def test_soc_after_trading(self):
        ev = EVNode(ev_id=1, battery_capacity=60.0, soc_init=0.85, max_discharge_rate=7.0)
        # discharge 14 kWh: soc reduces by 14/60 = 0.2333
        self.assertAlmostEqual(ev.soc_after_trading, 0.85 - (14.0/60.0))

    def test_energy_transaction(self):
        tx = EnergyTransaction(
            tx_id=101,
            sender_ev_id=1,
            receiver_dn_id=0,
            energy_kwh=10.5,
            price_per_kwh=0.15,
            timestamp=12.34,
            sender_soc_before=0.85,
            sender_soc_after=0.675
        )
        self.assertAlmostEqual(tx.total_reward, 1.575)
        d = tx.to_dict()
        self.assertEqual(d["tx_id"], 101)
        self.assertEqual(d["total_reward"], 1.575)

    def test_trading_round_generation(self):
        # 3 EVs (2 participating, 1 not)
        ev1 = EVNode(ev_id=1, battery_capacity=60.0, soc_init=0.80, max_discharge_rate=7.0) # E_i = min(30, 14) = 14
        ev2 = EVNode(ev_id=2, battery_capacity=60.0, soc_init=0.90, max_discharge_rate=7.0) # E_i = min(36, 14) = 14
        ev3 = EVNode(ev_id=3, battery_capacity=60.0, soc_init=0.70, max_discharge_rate=7.0) # E_i = 0
        
        dn = DNNode(demand_kwh=20.0) # Demand = 20
        trading_round = TradingRound(dn=dn, evs=[ev1, ev2, ev3])
        
        self.assertEqual(trading_round.num_participating, 2)
        self.assertAlmostEqual(trading_round.total_supply, 28.0)
        self.assertAlmostEqual(trading_round.supply_deficit, 0.0)
        
        txs = trading_round.generate_transactions(price_per_kwh=0.15)
        self.assertEqual(len(txs), 2)
        # ev1 should supply its max (14) since demand is 20 and ev1 is first
        self.assertAlmostEqual(txs[0].energy_kwh, 14.0)
        # ev2 should supply the rest (6.0)
        self.assertAlmostEqual(txs[1].energy_kwh, 6.0)

    def test_create_ev_fleet(self):
        fleet = create_ev_fleet(num_evs=10, seed=42)
        self.assertEqual(len(fleet), 10)
        for i, ev in enumerate(fleet):
            self.assertEqual(ev.ev_id, i + 1)
            self.assertTrue(0.5 <= ev.soc_init <= 1.0)


if __name__ == "__main__":
    unittest.main()
