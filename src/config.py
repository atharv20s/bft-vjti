"""
Configuration module for BFT Consensus Comparison Framework.

Defines simulation parameters, scenario presets, and constants
for the EV-to-DN energy trading consensus research.
"""

from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum


class AttackType(Enum):
    """
    Byzantine attack types modeled from the IEEE paper scenarios.

    - FALSE_DEMAND:         DN (commander) sends inflated/deflated demand values
    - FALSE_SUPPLY:         Traitor EV reports false C_rem / SOC values
    - CONFLICTING_BROADCAST: Traitor sends different values to different peers
    - MESSAGE_DROP:         Traitor silently drops messages (omission fault)
    """
    FALSE_DEMAND = "false_demand"
    FALSE_SUPPLY = "false_supply"
    CONFLICTING_BROADCAST = "conflicting_broadcast"
    MESSAGE_DROP = "message_drop"


class ShardingStrategy(Enum):
    """Sharding node assignment strategy."""
    RANDOM = "random"
    GEOGRAPHIC = "geographic"  # Parking lot clusters


@dataclass
class NetworkConfig:
    """Network simulation parameters."""
    # Latency model (milliseconds)
    latency_mean: float = 50.0       # Mean network delay (ms)
    latency_std: float = 15.0        # Std dev for gaussian model
    latency_min: float = 5.0         # Minimum latency floor

    # Realistic network impairments
    packet_loss_probability: float = 0.02   # 2% packet loss
    jitter_probability: float = 0.1         # 10% chance of jitter event
    jitter_multiplier: float = 3.0          # Jitter adds up to 3x normal latency
    burst_delay_probability: float = 0.01   # 1% chance of burst delay
    burst_delay_ms: float = 500.0           # Burst delay magnitude (ms)


@dataclass
class EVConfig:
    """EV fleet configuration matching IEEE 33-bus test feeder."""
    # Battery parameters
    battery_capacity_kwh: float = 60.0      # Typical EV battery (kWh)
    soc_min_participation: float = 0.75     # Min SOC to participate (75%)
    soc_init_mean: float = 0.85             # Mean initial SOC
    soc_init_std: float = 0.05              # SOC variation across fleet
    max_discharge_rate_kw: float = 7.0      # Max discharge rate (kW)

    # DN demand parameters (IEEE 33-bus)
    dn_demand_kwh: float = 150.0            # Peak demand from DN (kWh)
    price_per_kwh: float = 0.15             # Reward per kWh discharged ($)

    # IEEE 33-bus system parameters
    system_peak_load_kw: float = 3715.0     # Peak load (kW)
    system_reactive_kvar: float = 2300.0    # Reactive power (kVAr)
    num_buses: int = 33
    num_branches: int = 32
    num_laterals: int = 4


@dataclass
class ScenarioConfig:
    """A single benchmark scenario configuration."""
    name: str
    num_nodes: int                          # Total nodes (EVs + DN)
    num_traitors: int                       # Number of Byzantine traitors
    num_shards: int = 4                     # For Sharding-BFT
    sharding_strategy: ShardingStrategy = ShardingStrategy.GEOGRAPHIC
    attack_type: AttackType = AttackType.CONFLICTING_BROADCAST
    num_transactions: int = 50              # Transaction batch size
    num_trials: int = 10                    # Repeated trials for statistics
    network: NetworkConfig = field(default_factory=NetworkConfig)
    ev: EVConfig = field(default_factory=EVConfig)


# ─────────────────────────────────────────────────────────────
# Preset Scenarios
# ─────────────────────────────────────────────────────────────

def paper_baseline() -> ScenarioConfig:
    """Paper scenario: 50 EVs + 1 DN, f=16 traitors, 150 kWh demand."""
    return ScenarioConfig(
        name="paper_baseline",
        num_nodes=51,
        num_traitors=16,
        num_transactions=50,
        num_trials=20,
    )


def scalability_sweep() -> List[ScenarioConfig]:
    """Scalability sweep across varying network sizes."""
    configs = []
    for n in [10, 25, 50, 100, 200, 500]:
        f = (n - 1) // 3  # Max tolerable traitors
        configs.append(ScenarioConfig(
            name=f"scale_n{n}",
            num_nodes=n,
            num_traitors=f,
            num_transactions=50,
            num_trials=10,
        ))
    return configs


def om_scalability_sweep() -> List[ScenarioConfig]:
    """OM(m)-specific sweep — capped at n=50."""
    configs = []
    for n in [10, 25, 50]:
        f = (n - 1) // 3
        configs.append(ScenarioConfig(
            name=f"om_scale_n{n}",
            num_nodes=n,
            num_traitors=f,
            num_transactions=20,
            num_trials=10,
        ))
    return configs


def fault_sweep() -> List[ScenarioConfig]:
    """Consensus success rate across fault levels (fixed n=51)."""
    configs = []
    for f in [0, 5, 10, 15, 16, 17, 20, 25]:
        configs.append(ScenarioConfig(
            name=f"fault_f{f}",
            num_nodes=51,
            num_traitors=f,
            num_transactions=50,
            num_trials=100,  # 100 trials for statistical significance
        ))
    return configs


def throughput_sweep() -> List[ScenarioConfig]:
    """Throughput under increasing transaction load."""
    configs = []
    for tx_count in [10, 50, 100, 500, 1000]:
        configs.append(ScenarioConfig(
            name=f"throughput_tx{tx_count}",
            num_nodes=51,
            num_traitors=10,
            num_transactions=tx_count,
            num_trials=10,
        ))
    return configs


def attack_type_sweep() -> List[ScenarioConfig]:
    """Test all attack types from the paper."""
    configs = []
    for attack in AttackType:
        configs.append(ScenarioConfig(
            name=f"attack_{attack.value}",
            num_nodes=51,
            num_traitors=16,
            attack_type=attack,
            num_transactions=50,
            num_trials=20,
        ))
    return configs


# Algorithm-specific max node counts
ALGORITHM_MAX_NODES = {
    "oral_message": 51,
    "pbft": 500,
    "dag_bft": 500,
    "sharding_bft": 500,
    "tower_bft": 500,
}

# All algorithm names
ALGORITHM_NAMES = list(ALGORITHM_MAX_NODES.keys())
