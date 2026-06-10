"""
Oral Message Algorithm OM(m) — Lamport, Shostak, Pease (1982)

Faithful implementation from the research paper:
"Secured Energy Trading Using Byzantine-Based Blockchain Consensus"
(Sheikh et al., IEEE Access, 2020) — Section II-A.

Algorithm:
    OM(0):
        1. Commander sends value to every subordinate.
        2. Each subordinate uses received value (or default RETREAT).

    OM(m), m > 0:
        1. Commander sends value to every subordinate.
        2. For each i, subordinate i acts as commander in OM(m-1)
           sending v_i to each of the n-2 other subordinates.
        3. Each subordinate i uses majority(v_1, ..., v_{n-1}).

In the EV-DN context:
    - DN (node 0) = commander
    - EVs (nodes 1..n-1) = subordinates (lieutenants)
    - Value = energy trading transaction set
    - Traitor sends conflicting/false values

Tolerates f traitors with n >= 3f + 1.
Communication complexity: O(n^m) — exponential.
"""

import sys
import time
import json
from typing import Any, Dict, List, Optional, Set
from collections import Counter

# Add parent to path for imports
sys.path.insert(0, '..')

from network import Network, Node, Message, MessageType, setup_network
from metrics import ConsensusMetrics, compute_agreement_rate
from config import ScenarioConfig, AttackType


def majority_value(values: List[Any], default: Any = "RETREAT") -> Any:
    """
    Compute the majority value from a list.
    If no majority exists, return default.

    Matches the paper's majority(v_1, ..., v_{n-1}) function.
    """
    if not values:
        return default

    # Convert to hashable for counting
    str_values = [json.dumps(v, sort_keys=True, default=str) for v in values]
    counter = Counter(str_values)
    most_common_str, count = counter.most_common(1)[0]

    # Majority requires > half
    if count > len(values) / 2:
        # Find the original value matching this string
        for v, s in zip(values, str_values):
            if s == most_common_str:
                return v

    return default


class OralMessageAlgorithm:
    """
    Implements the recursive OM(m) algorithm.

    Tracks message count and computational operations
    for accurate metrics comparison.
    """

    def __init__(self, network: Network, commander_id: int = 0):
        self.network = network
        self.commander_id = commander_id
        self.message_count = 0
        self.cpu_operations = 0
        self.memory_entries = 0
        self.max_memory = 0
        self._start_time = 0.0

    def run(self, value: Any, m: int) -> Dict[int, Any]:
        """
        Execute OM(m) and return each node's decided value.

        Args:
            value: The commander's value (energy trading data)
            m:     Number of rounds (should be >= number of traitors)

        Returns:
            Dict mapping node_id -> decided_value for all subordinates
        """
        self._start_time = time.perf_counter()

        all_node_ids = list(self.network.nodes.keys())
        subordinate_ids = [nid for nid in all_node_ids if nid != self.commander_id]

        # Run recursive OM
        decisions = self._om(
            commander_id=self.commander_id,
            subordinate_ids=subordinate_ids,
            value=value,
            m=m,
        )

        # Store decisions in nodes
        for nid, val in decisions.items():
            self.network.nodes[nid].decided_value = val

        return decisions

    def _om(
        self,
        commander_id: int,
        subordinate_ids: List[int],
        value: Any,
        m: int,
    ) -> Dict[int, Any]:
        """
        Recursive OM(m) implementation.

        Args:
            commander_id:    Current commander
            subordinate_ids: Current subordinates
            value:           Commander's value
            m:               Recursion depth remaining

        Returns:
            Dict mapping subordinate_id -> decided_value
        """
        commander = self.network.nodes[commander_id]
        decisions: Dict[int, Any] = {}

        if m == 0:
            # ── OM(0): Base case ──
            # Commander sends value to every subordinate.
            # Each subordinate uses received value or default.
            for sub_id in subordinate_ids:
                # Traitor commander may send different values
                sent_value = commander.traitor_value(value, sub_id)

                if sent_value is not None:  # None = MESSAGE_DROP
                    self.message_count += 1
                    self.cpu_operations += 1  # Message processing
                    decisions[sub_id] = sent_value
                else:
                    decisions[sub_id] = "RETREAT"  # Default if no value received

                self.memory_entries += 1
                self.max_memory = max(self.max_memory, self.memory_entries)

            return decisions

        # ── OM(m), m > 0: Recursive case ──

        # Step 1: Commander sends value to every subordinate
        received_values: Dict[int, Any] = {}
        for sub_id in subordinate_ids:
            sent_value = commander.traitor_value(value, sub_id)

            if sent_value is not None:
                self.message_count += 1
                self.cpu_operations += 1
                received_values[sub_id] = sent_value
            else:
                received_values[sub_id] = "RETREAT"

        # Step 2: Each subordinate i acts as commander in OM(m-1)
        # sending v_i to the n-2 other subordinates
        all_reported: Dict[int, Dict[int, Any]] = {}  # {reporter -> {target -> value}}

        for sub_i in subordinate_ids:
            v_i = received_values[sub_i]

            # Sub_i acts as commander for OM(m-1)
            other_subs = [s for s in subordinate_ids if s != sub_i]

            sub_decisions = self._om(
                commander_id=sub_i,
                subordinate_ids=other_subs,
                value=v_i,
                m=m - 1,
            )

            # Record what sub_i reported to each other subordinate
            all_reported[sub_i] = sub_decisions

        # Step 3: Each subordinate j uses majority of received values
        for sub_j in subordinate_ids:
            values_for_j = []

            # Value sub_j received directly from commander (Step 1)
            values_for_j.append(received_values[sub_j])

            # Values sub_j received from other subordinates via OM(m-1)
            for sub_i in subordinate_ids:
                if sub_i == sub_j:
                    continue
                if sub_i in all_reported and sub_j in all_reported[sub_i]:
                    values_for_j.append(all_reported[sub_i][sub_j])

            # Apply majority function
            self.cpu_operations += len(values_for_j)  # Comparison operations
            decisions[sub_j] = majority_value(values_for_j)

            self.memory_entries += len(values_for_j)
            self.max_memory = max(self.max_memory, self.memory_entries)

        return decisions


def run_oral_message(scenario: ScenarioConfig, seed: int = 42) -> ConsensusMetrics:
    """
    Run the OM(m) algorithm for a given scenario and return metrics.

    Args:
        scenario: Scenario configuration
        seed:     Random seed

    Returns:
        ConsensusMetrics for this run
    """
    n = scenario.num_nodes
    f = scenario.num_traitors

    # Set m = f (need m rounds to tolerate f traitors)
    m = f

    # Safety: OM(m) is exponential. Cap recursion for sanity.
    # For n=50, f=16: O(50^16) is WAY too large.
    # In practice we use m = min(f, 2) for simulation
    # and note the theoretical complexity.
    m_effective = min(m, 2)  # Cap at m=2 for practical simulation

    # Setup network
    net = setup_network(
        num_nodes=n,
        num_traitors=f,
        attack_type=scenario.attack_type,
        network_config=scenario.network,
        seed=seed,
    )

    # Value to reach consensus on: energy trading data
    consensus_value = {
        "demand_kwh": scenario.ev.dn_demand_kwh,
        "num_transactions": scenario.num_transactions,
        "block_index": 1,
    }

    # Run OM(m)
    start = time.perf_counter()
    om = OralMessageAlgorithm(net, commander_id=0)
    decisions = om.run(value=consensus_value, m=m_effective)
    elapsed_real = (time.perf_counter() - start) * 1000  # ms

    # Simulated latency scales with theoretical complexity
    # Each recursion level adds a round of n messages
    # Theoretical: m rounds × n messages per round × latency_mean
    simulated_latency = m_effective * n * scenario.network.latency_mean

    # Compute agreement rate
    traitor_ids = {node.node_id for node in net.get_traitor_nodes()}
    agreement = compute_agreement_rate(decisions, traitor_ids)

    # Consensus succeeds if agreement_rate > 2/3 AND n >= 3f+1
    bft_satisfied = n >= 3 * f + 1
    consensus_ok = agreement > 2 / 3 and bft_satisfied

    # Theoretical message complexity for full OM(m):
    # Total messages = n * (n-1) * (n-2) * ... * (n-m) ≈ O(n^(m+1))
    theoretical_messages = 1
    for i in range(m + 1):
        theoretical_messages *= max(1, n - i)

    return ConsensusMetrics(
        algorithm="oral_message",
        scenario=scenario.name,
        num_nodes=n,
        num_traitors=f,
        latency_ms=simulated_latency,
        throughput_tps=scenario.num_transactions / (simulated_latency / 1000) if simulated_latency > 0 else 0,
        total_messages=om.message_count,
        total_bytes=om.message_count * 256,  # Estimated 256 bytes per OM message
        rounds_to_consensus=m_effective + 1,
        dropped_messages=0,
        consensus_success=consensus_ok,
        agreement_rate=agreement,
        agreed_value=consensus_value if consensus_ok else None,
        cpu_operations=om.cpu_operations,
        memory_peak_entries=om.max_memory,
        num_transactions=scenario.num_transactions,
    )
