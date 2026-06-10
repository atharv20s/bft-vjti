"""
Classical PBFT — Practical Byzantine Fault Tolerance
Castro & Liskov (1999)

Three-phase consensus protocol:
    Phase 1 — Pre-Prepare: Primary (leader) proposes a value
    Phase 2 — Prepare:     Each node broadcasts PREPARE; waits for 2f matching
    Phase 3 — Commit:      Each node broadcasts COMMIT; waits for 2f+1 matching

In the EV-DN context:
    - Primary = DN node (or round-robin among nodes)
    - Replicas = EV nodes
    - Value = energy trading transaction block
    - View-change triggered on primary timeout

Tolerates f traitors with n >= 3f + 1.
Communication complexity: O(n²) per consensus round.
"""

import sys
import time
import json
from typing import Any, Dict, List, Optional, Set
from collections import Counter, defaultdict

sys.path.insert(0, '..')

from network import Network, Node, Message, MessageType, setup_network
from metrics import ConsensusMetrics, compute_agreement_rate
from config import ScenarioConfig, AttackType


class PBFTProtocol:
    """
    Implements the three-phase PBFT protocol.

    Simulates Pre-Prepare → Prepare → Commit with
    full message counting and Byzantine fault injection.
    """

    def __init__(self, network: Network, primary_id: int = 0):
        self.network = network
        self.primary_id = primary_id
        self.message_count = 0
        self.cpu_operations = 0
        self.memory_entries = 0
        self.max_memory = 0
        self.rounds = 0
        self.view_number = 0

    def run(self, value: Any) -> Dict[int, Any]:
        """
        Execute 3-phase PBFT and return each node's decided value.

        Args:
            value: The proposed block/transaction data

        Returns:
            Dict mapping node_id -> decided_value
        """
        n = self.network.num_nodes
        f = len(self.network.get_traitor_nodes())
        all_ids = list(self.network.nodes.keys())
        replica_ids = [nid for nid in all_ids if nid != self.primary_id]

        decisions: Dict[int, Any] = {}

        # ── Phase 1: Pre-Prepare ──
        # Primary sends PRE-PREPARE to all replicas
        primary = self.network.nodes[self.primary_id]

        pre_prepare_msg = {
            "view": self.view_number,
            "sequence": 1,
            "value": value,
        }

        # Track what each node receives in pre-prepare
        received_pre_prepare: Dict[int, Any] = {}

        for replica_id in replica_ids:
            sent_value = primary.traitor_value(pre_prepare_msg, replica_id)

            if sent_value is not None:
                self.message_count += 1
                self.cpu_operations += 2  # Signature verify + hash check
                received_pre_prepare[replica_id] = sent_value
            else:
                received_pre_prepare[replica_id] = None

        # Primary also has its own pre-prepare
        received_pre_prepare[self.primary_id] = pre_prepare_msg

        self.rounds += 1
        self.memory_entries += len(received_pre_prepare)
        self.max_memory = max(self.max_memory, self.memory_entries)

        # ── Phase 2: Prepare ──
        # Each replica broadcasts PREPARE with the value it received
        # A node accepts if it receives 2f matching PREPAREs

        prepare_messages: Dict[int, List[Any]] = defaultdict(list)

        for sender_id in all_ids:
            sender = self.network.nodes[sender_id]
            pp = received_pre_prepare.get(sender_id)
            if pp is None:
                continue

            prepare_value = pp.get("value", value) if isinstance(pp, dict) else pp

            for receiver_id in all_ids:
                if receiver_id == sender_id:
                    continue

                sent_val = sender.traitor_value(prepare_value, receiver_id)

                if sent_val is not None:
                    self.message_count += 1
                    self.cpu_operations += 1
                    prepare_messages[receiver_id].append(sent_val)

        self.rounds += 1

        # Each node checks for 2f matching prepares
        prepared_value: Dict[int, Any] = {}
        for node_id in all_ids:
            msgs = prepare_messages[node_id]
            self.memory_entries += len(msgs)
            self.max_memory = max(self.max_memory, self.memory_entries)

            if len(msgs) >= 2 * f:
                # Find most common value
                str_msgs = [json.dumps(m, sort_keys=True, default=str) for m in msgs]
                counter = Counter(str_msgs)
                most_common, count = counter.most_common(1)[0]

                self.cpu_operations += len(msgs)  # Comparison operations

                if count >= 2 * f:
                    # Find original value
                    for m, s in zip(msgs, str_msgs):
                        if s == most_common:
                            prepared_value[node_id] = m
                            break
                else:
                    prepared_value[node_id] = None
            else:
                prepared_value[node_id] = None

        # ── Phase 3: Commit ──
        # Each prepared node broadcasts COMMIT
        # A node commits if it receives 2f+1 matching COMMITs

        commit_messages: Dict[int, List[Any]] = defaultdict(list)

        for sender_id in all_ids:
            sender = self.network.nodes[sender_id]
            pval = prepared_value.get(sender_id)
            if pval is None:
                continue

            for receiver_id in all_ids:
                if receiver_id == sender_id:
                    continue

                sent_val = sender.traitor_value(pval, receiver_id)

                if sent_val is not None:
                    self.message_count += 1
                    self.cpu_operations += 1
                    commit_messages[receiver_id].append(sent_val)

        self.rounds += 1

        # Each node checks for 2f+1 matching commits
        for node_id in all_ids:
            msgs = commit_messages[node_id]
            self.memory_entries += len(msgs)
            self.max_memory = max(self.max_memory, self.memory_entries)

            if len(msgs) >= 2 * f + 1:
                str_msgs = [json.dumps(m, sort_keys=True, default=str) for m in msgs]
                counter = Counter(str_msgs)
                most_common, count = counter.most_common(1)[0]

                self.cpu_operations += len(msgs)

                if count >= 2 * f + 1:
                    for m, s in zip(msgs, str_msgs):
                        if s == most_common:
                            decisions[node_id] = m
                            self.network.nodes[node_id].decided_value = m
                            break
                else:
                    decisions[node_id] = None
            else:
                decisions[node_id] = None

        return decisions


def run_pbft(scenario: ScenarioConfig, seed: int = 42) -> ConsensusMetrics:
    """
    Run Classical PBFT for a given scenario and return metrics.

    Args:
        scenario: Scenario configuration
        seed:     Random seed

    Returns:
        ConsensusMetrics for this run
    """
    n = scenario.num_nodes
    f = scenario.num_traitors

    # Setup network
    net = setup_network(
        num_nodes=n,
        num_traitors=f,
        attack_type=scenario.attack_type,
        network_config=scenario.network,
        seed=seed,
    )

    # Consensus value: energy trading block
    consensus_value = {
        "demand_kwh": scenario.ev.dn_demand_kwh,
        "num_transactions": scenario.num_transactions,
        "block_index": 1,
    }

    # Run PBFT
    start = time.perf_counter()
    pbft = PBFTProtocol(net, primary_id=0)
    decisions = pbft.run(value=consensus_value)
    elapsed_real = (time.perf_counter() - start) * 1000

    # Simulated latency: 3 phases × network latency
    simulated_latency = 3 * scenario.network.latency_mean

    # Agreement rate
    traitor_ids = {node.node_id for node in net.get_traitor_nodes()}
    agreement = compute_agreement_rate(decisions, traitor_ids)

    bft_satisfied = n >= 3 * f + 1
    consensus_ok = agreement > 2 / 3 and bft_satisfied

    return ConsensusMetrics(
        algorithm="pbft",
        scenario=scenario.name,
        num_nodes=n,
        num_traitors=f,
        latency_ms=simulated_latency,
        throughput_tps=scenario.num_transactions / (simulated_latency / 1000) if simulated_latency > 0 else 0,
        total_messages=pbft.message_count,
        total_bytes=pbft.message_count * 512,  # PBFT messages include signatures
        rounds_to_consensus=pbft.rounds,
        dropped_messages=net.dropped_messages,
        consensus_success=consensus_ok,
        agreement_rate=agreement,
        agreed_value=consensus_value if consensus_ok else None,
        cpu_operations=pbft.cpu_operations,
        memory_peak_entries=pbft.max_memory,
        num_transactions=scenario.num_transactions,
    )
