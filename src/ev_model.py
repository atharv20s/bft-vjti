"""
EV-DN Energy Trading Model.

Implements the IEEE 33-bus test feeder energy trading scenario from:
"Secured Energy Trading Using Byzantine-Based Blockchain Consensus"
(Sheikh et al., IEEE Access, 2020)

Core equations modeled:
- SOC_init, SOC_reach, C_rem, E_i
- Demand/supply matching
- EV participation filtering (SOC >= 75%)
- Revenue calculation for discharged power
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import random
import math


@dataclass
class EVNode:
    """
    Represents an Electric Vehicle in the parking lot.

    Attributes:
        ev_id:              Unique identifier
        battery_capacity:   Total battery capacity (kWh)
        soc_init:           Initial State of Charge (0.0 to 1.0)
        max_discharge_rate: Maximum discharge rate (kW)
        parking_lot_id:     Geographic cluster / parking lot assignment
        is_participating:   Whether EV qualifies for trading (SOC >= 75%)
    """
    ev_id: int
    battery_capacity: float     # kWh
    soc_init: float             # 0.0 to 1.0
    max_discharge_rate: float   # kW
    parking_lot_id: int = 0     # For geographic sharding

    # Computed fields
    is_participating: bool = field(init=False)
    soc_reach: float = field(init=False)        # Target SOC after trading
    c_rem: float = field(init=False)            # Remaining capacity for discharge (kWh)
    energy_available: float = field(init=False) # E_i: energy this EV can contribute

    def __post_init__(self):
        """Compute derived parameters from paper equations."""
        # Only EVs with SOC >= 75% participate (Section IV of the paper)
        self.is_participating = self.soc_init >= 0.75

        if self.is_participating:
            # SOC_reach: target SOC after discharging (keep at least 30% for return trip)
            self.soc_reach = 0.30

            # C_rem = battery_capacity * (SOC_init - SOC_reach)
            # This is the energy available for trading
            self.c_rem = self.battery_capacity * (self.soc_init - self.soc_reach)

            # E_i = min(C_rem, max_discharge_rate * trading_hours)
            # Assume 2-hour trading window during peak hours
            trading_hours = 2.0
            self.energy_available = min(self.c_rem, self.max_discharge_rate * trading_hours)
        else:
            self.soc_reach = self.soc_init
            self.c_rem = 0.0
            self.energy_available = 0.0

    @property
    def soc_after_trading(self) -> float:
        """SOC after discharging energy_available."""
        if not self.is_participating:
            return self.soc_init
        discharged_soc = self.energy_available / self.battery_capacity
        return max(self.soc_reach, self.soc_init - discharged_soc)


@dataclass
class DNNode:
    """
    Distribution Network node (the commander in BGP terms).

    Attributes:
        demand_kwh:     Total peak demand requirement (kWh)
        system_load_kw: IEEE 33-bus system peak load (kW)
    """
    demand_kwh: float = 150.0       # From paper: 150 kWh peak demand
    system_load_kw: float = 3715.0  # IEEE 33-bus peak load
    reactive_kvar: float = 2300.0   # Reactive power


@dataclass
class EnergyTransaction:
    """
    A single energy trading transaction between EV and DN.

    This is the payload that consensus algorithms must agree upon.
    """
    tx_id: int
    sender_ev_id: int           # EV providing energy
    receiver_dn_id: int         # DN receiving energy (always 0 in single-DN scenario)
    energy_kwh: float           # Amount of energy traded
    price_per_kwh: float        # Price per kWh
    timestamp: float            # Simulated timestamp
    sender_soc_before: float    # EV's SOC before this transaction
    sender_soc_after: float     # EV's SOC after this transaction

    @property
    def total_reward(self) -> float:
        """Revenue earned by EV for this transaction."""
        return self.energy_kwh * self.price_per_kwh

    def to_dict(self) -> dict:
        return {
            "tx_id": self.tx_id,
            "sender_ev_id": self.sender_ev_id,
            "receiver_dn_id": self.receiver_dn_id,
            "energy_kwh": round(self.energy_kwh, 4),
            "price_per_kwh": self.price_per_kwh,
            "total_reward": round(self.total_reward, 4),
            "timestamp": self.timestamp,
            "soc_before": round(self.sender_soc_before, 4),
            "soc_after": round(self.sender_soc_after, 4),
        }


@dataclass
class TradingRound:
    """
    A complete energy trading round between DN and EV fleet.

    Models the scenario from the paper:
    1. DN broadcasts demand
    2. Qualifying EVs respond with available energy
    3. Transactions are formed
    4. Consensus must be reached on the transaction set
    """
    dn: DNNode
    evs: List[EVNode]
    transactions: List[EnergyTransaction] = field(default_factory=list)

    # Computed supply/demand metrics
    total_supply: float = field(init=False)
    supply_deficit: float = field(init=False)
    participating_evs: List[EVNode] = field(init=False)
    num_participating: int = field(init=False)

    def __post_init__(self):
        self.participating_evs = [ev for ev in self.evs if ev.is_participating]
        self.num_participating = len(self.participating_evs)
        self.total_supply = sum(ev.energy_available for ev in self.participating_evs)
        self.supply_deficit = max(0, self.dn.demand_kwh - self.total_supply)

    def generate_transactions(self, price_per_kwh: float = 0.15) -> List[EnergyTransaction]:
        """
        Generate energy trading transactions based on demand-supply matching.

        If total supply < demand:
            All participating EVs contribute their full available energy.
            Remaining deficit is noted (would be arranged by SCADA in real system).
        If total supply >= demand:
            EVs contribute proportionally until demand is met.

        Returns:
            List of EnergyTransaction objects to be validated by consensus.
        """
        self.transactions = []
        remaining_demand = self.dn.demand_kwh
        tx_id = 0

        for ev in self.participating_evs:
            if remaining_demand <= 0:
                break

            # Each EV contributes min(available, remaining_demand)
            energy_contribution = min(ev.energy_available, remaining_demand)
            remaining_demand -= energy_contribution

            tx = EnergyTransaction(
                tx_id=tx_id,
                sender_ev_id=ev.ev_id,
                receiver_dn_id=0,
                energy_kwh=energy_contribution,
                price_per_kwh=price_per_kwh,
                timestamp=tx_id * 0.1,  # Simulated timestamps
                sender_soc_before=ev.soc_init,
                sender_soc_after=ev.soc_init - (energy_contribution / ev.battery_capacity),
            )
            self.transactions.append(tx)
            tx_id += 1

        return self.transactions

    def summary(self) -> dict:
        """Summary of the trading round for reporting."""
        return {
            "total_evs": len(self.evs),
            "participating_evs": self.num_participating,
            "dn_demand_kwh": self.dn.demand_kwh,
            "total_supply_kwh": round(self.total_supply, 2),
            "supply_deficit_kwh": round(self.supply_deficit, 2),
            "num_transactions": len(self.transactions),
            "total_energy_traded_kwh": round(
                sum(tx.energy_kwh for tx in self.transactions), 2
            ),
            "total_revenue": round(
                sum(tx.total_reward for tx in self.transactions), 2
            ),
        }


def create_ev_fleet(
    num_evs: int,
    battery_capacity: float = 60.0,
    soc_mean: float = 0.85,
    soc_std: float = 0.05,
    max_discharge_rate: float = 7.0,
    num_parking_lots: int = 4,
    seed: Optional[int] = None,
) -> List[EVNode]:
    """
    Create a fleet of EVs with realistic parameter distributions.

    Args:
        num_evs:            Number of EVs in the fleet
        battery_capacity:   Battery capacity per EV (kWh)
        soc_mean:           Mean initial SOC
        soc_std:            Standard deviation of SOC distribution
        max_discharge_rate: Max discharge rate per EV (kW)
        num_parking_lots:   Number of geographic clusters (for sharding)
        seed:               Random seed for reproducibility

    Returns:
        List of EVNode objects
    """
    if seed is not None:
        random.seed(seed)

    evs = []
    for i in range(num_evs):
        # SOC follows normal distribution, clipped to [0.5, 1.0]
        soc = max(0.5, min(1.0, random.gauss(soc_mean, soc_std)))

        # Assign to parking lot (geographic cluster)
        lot_id = i % num_parking_lots

        evs.append(EVNode(
            ev_id=i + 1,  # 1-indexed (DN is node 0)
            battery_capacity=battery_capacity,
            soc_init=round(soc, 4),
            max_discharge_rate=max_discharge_rate,
            parking_lot_id=lot_id,
        ))

    return evs


def create_trading_scenario(
    num_evs: int = 50,
    demand_kwh: float = 150.0,
    seed: Optional[int] = 42,
    num_parking_lots: int = 4,
) -> TradingRound:
    """
    Create a complete EV-DN trading scenario matching the paper.

    Args:
        num_evs:          Number of EVs (default 50, matching paper)
        demand_kwh:       DN demand in kWh (default 150, matching paper)
        seed:             Random seed
        num_parking_lots: Number of geographic clusters

    Returns:
        TradingRound with generated transactions
    """
    evs = create_ev_fleet(num_evs, seed=seed, num_parking_lots=num_parking_lots)
    dn = DNNode(demand_kwh=demand_kwh)
    trading_round = TradingRound(dn=dn, evs=evs)
    trading_round.generate_transactions()
    return trading_round
