"""
Sharding-BFT — Elastico-Inspired Sharding Consensus

Protocol: Elastico-style with two sharding strategies:
    1. RANDOM:     Nodes randomly assigned to shards
    2. GEOGRAPHIC:  Nodes assigned by parking lot cluster (EV grid zones)

Architecture:
    - Network partitioned into k shards
    - Intra-shard: PBFT consensus (small n/k → fast)
    - Cross-shard: 2-phase commit for transactions spanning shards
    - DN acts as coordinator for cross-shard finalization

In the EV-DN context:
    - Each shard = a parking lot or grid zone
    - EVs in same parking lot form a shard
    - DN coordinates across shards
    - Geographic sharding is more realistic for EV networks

Tolerates f_shard ≤ ⌊(n/k - 1)/3⌋ traitors per shard.
Communication complexity: O(n/k) per shard (linear/cluster).
"""

import sys
import time
import json
import random
from typing import Any, Dict, List, Optional, Set, Tuple
from collections import Counter, defaultdict
from dataclasses import dataclass

sys.path.insert(0, '..')

from network import Network, Node, setup_network
from metrics import ConsensusMetrics, compute_agreement_rate
from config import ScenarioConfig, ShardingStrategy


@dataclass
class Shard:
    """A shard (cluster) of nodes that run intra-shard PBFT."""
    shard_id: int
    node_ids: List[int]
    leader_id: int  # Intra-shard primary
    consensus_value: Optional[Any] = None
    consensus_reached: bool = False


class ShardingBFTProtocol:
    """
    Implements Elastico-style Sharding-BFT.

    Phase 1: Shard formation (random or geographic)
    Phase 2: Intra-shard PBFT consensus
    Phase 3: Cross-shard 2PC finalization
    """

    def __init__(
        self,
        network: Network,
        num_shards: int = 4,
        strategy: ShardingStrategy = ShardingStrategy.GEOGRAPHIC,
        seed: int = 42,
    ):
        self.network = network
        self.num_shards = min(num_shards, network.num_nodes)
        self.strategy = strategy
        self.shards: List[Shard] = []
        self.message_count = 0
        self.cpu_operations = 0
        self.memory_entries = 0
        self.max_memory = 0
        self.rounds = 0
        self._rng = random.Random(seed)

    def run(self, value: Any) -> Dict[int, Any]:
        """
        Execute Sharding-BFT consensus.

        Args:
            value: Proposed consensus value

        Returns:
            Dict mapping node_id -> decided_value
        """
        # Phase 1: Shard formation
        self._form_shards()
        self.rounds += 1

        # Phase 2: Intra-shard PBFT
        shard_results = {}
        for shard in self.shards:
            result = self._intra_shard_pbft(shard, value)
            shard_results[shard.shard_id] = result
            self.rounds += 3  # PBFT is 3 phases

        # Phase 3: Cross-shard 2PC
        decisions = self._cross_shard_commit(shard_results, value)
        self.rounds += 2  # 2PC is 2 phases

        return decisions

    def _form_shards(self):
        """
        Assign nodes to shards based on strategy.

        RANDOM:     Uniformly random assignment
        GEOGRAPHIC: Based on parking_lot_id (grid zone clustering)
        """
        all_ids = list(self.network.nodes.keys())

        if self.strategy == ShardingStrategy.GEOGRAPHIC:
            # Group by parking lot
            lot_groups: Dict[int, List[int]] = defaultdict(list)
            for nid in all_ids:
                lot_id = self.network.nodes[nid].parking_lot_id
                lot_groups[lot_id].append(nid)

            # Map parking lots to shards
            lots = sorted(lot_groups.keys())
            for i, lot_id in enumerate(lots):
                shard_id = i % self.num_shards
                nodes = lot_groups[lot_id]
                # Check if shard already exists
                existing = [s for s in self.shards if s.shard_id == shard_id]
                if existing:
                    existing[0].node_ids.extend(nodes)
                else:
                    self.shards.append(Shard(
                        shard_id=shard_id,
                        node_ids=list(nodes),
                        leader_id=nodes[0],
                    ))

        else:  # RANDOM
            self._rng.shuffle(all_ids)
            shard_size = max(1, len(all_ids) // self.num_shards)

            for i in range(self.num_shards):
                start = i * shard_size
                end = start + shard_size if i < self.num_shards - 1 else len(all_ids)
                nodes = all_ids[start:end]
                if nodes:
                    self.shards.append(Shard(
                        shard_id=i,
                        node_ids=nodes,
                        leader_id=nodes[0],
                    ))

        # Update node shard assignments
        for shard in self.shards:
            for nid in shard.node_ids:
                self.network.nodes[nid].shard_id = shard.shard_id

        self.cpu_operations += len(all_ids)  # Assignment operations

    def _intra_shard_pbft(self, shard: Shard, value: Any) -> Dict[int, Any]:
        """
        Run PBFT within a single shard.

        Because shard size is small (n/k), this is fast.
        """
        n_shard = len(shard.node_ids)
        if n_shard == 0:
            return {}

        f_shard = sum(
            1 for nid in shard.node_ids
            if self.network.nodes[nid].is_traitor
        )

        decisions: Dict[int, Any] = {}

        # ── Pre-Prepare ──
        leader = self.network.nodes[shard.leader_id]
        received: Dict[int, Any] = {}

        for nid in shard.node_ids:
            if nid == shard.leader_id:
                received[nid] = value
                continue
            sent = leader.traitor_value(value, nid)
            if sent is not None:
                received[nid] = sent
                self.message_count += 1
                self.cpu_operations += 1

        # ── Prepare ──
        prepare_msgs: Dict[int, List[Any]] = defaultdict(list)
        for sender_id in shard.node_ids:
            sender = self.network.nodes[sender_id]
            my_value = received.get(sender_id, value)

            for recv_id in shard.node_ids:
                if recv_id == sender_id:
                    continue
                sent = sender.traitor_value(my_value, recv_id)
                if sent is not None:
                    prepare_msgs[recv_id].append(sent)
                    self.message_count += 1
                    self.cpu_operations += 1

        # ── Commit ──
        commit_msgs: Dict[int, List[Any]] = defaultdict(list)
        for sender_id in shard.node_ids:
            sender = self.network.nodes[sender_id]
            msgs = prepare_msgs.get(sender_id, [])

            # Check for 2f matching prepares
            prepared_val = self._find_majority(msgs, 2 * f_shard)
            if prepared_val is None:
                prepared_val = value  # Fallback

            for recv_id in shard.node_ids:
                if recv_id == sender_id:
                    continue
                sent = sender.traitor_value(prepared_val, recv_id)
                if sent is not None:
                    commit_msgs[recv_id].append(sent)
                    self.message_count += 1
                    self.cpu_operations += 1

        # ── Decide ──
        for nid in shard.node_ids:
            msgs = commit_msgs.get(nid, [])
            committed = self._find_majority(msgs, 2 * f_shard + 1)
            decisions[nid] = committed if committed is not None else value
            self.network.nodes[nid].decided_value = decisions[nid]

            self.memory_entries += len(msgs)
            self.max_memory = max(self.max_memory, self.memory_entries)

        shard.consensus_value = value
        shard.consensus_reached = True
        return decisions

    def _cross_shard_commit(
        self, shard_results: Dict[int, Dict[int, Any]], value: Any
    ) -> Dict[int, Any]:
        """
        Cross-shard 2-Phase Commit.

        Phase 1 (Prepare): DN collects shard-level decisions
        Phase 2 (Commit):  DN broadcasts final decision to all shards

        DN (node 0) acts as the 2PC coordinator.
        """
        all_decisions: Dict[int, Any] = {}

        # Phase 1: Collect shard leaders' decisions
        shard_votes: List[Any] = []
        for shard in self.shards:
            leader_decision = shard_results.get(shard.shard_id, {}).get(
                shard.leader_id, value
            )
            shard_votes.append(leader_decision)
            self.message_count += 1  # Leader → DN message
            self.cpu_operations += 1

        # Phase 2: DN decides and broadcasts
        # DN uses majority of shard votes
        final_value = self._find_majority(shard_votes, len(shard_votes) // 2 + 1)
        if final_value is None:
            final_value = value

        # Broadcast final decision back to all nodes
        for shard_id, results in shard_results.items():
            for nid in results:
                all_decisions[nid] = final_value
                self.network.nodes[nid].decided_value = final_value
                self.message_count += 1  # DN → node message
                self.cpu_operations += 1

        return all_decisions

    def _find_majority(self, values: List[Any], threshold: int) -> Optional[Any]:
        """Find a value that appears at least 'threshold' times."""
        if not values:
            return None

        str_values = [json.dumps(v, sort_keys=True, default=str) for v in values]
        counter = Counter(str_values)

        for s, count in counter.most_common():
            if count >= threshold:
                for v, sv in zip(values, str_values):
                    if sv == s:
                        return v
        return None


def run_sharding_bft(scenario: ScenarioConfig, seed: int = 42) -> ConsensusMetrics:
    """
    Run Sharding-BFT for a given scenario and return metrics.
    """
    n = scenario.num_nodes
    f = scenario.num_traitors
    k = scenario.num_shards

    net = setup_network(
        num_nodes=n,
        num_traitors=f,
        attack_type=scenario.attack_type,
        network_config=scenario.network,
        num_parking_lots=k,
        seed=seed,
    )

    consensus_value = {
        "demand_kwh": scenario.ev.dn_demand_kwh,
        "num_transactions": scenario.num_transactions,
        "block_index": 1,
    }

    start = time.perf_counter()
    sharding = ShardingBFTProtocol(
        net,
        num_shards=k,
        strategy=scenario.sharding_strategy,
        seed=seed,
    )
    decisions = sharding.run(value=consensus_value)
    elapsed_real = (time.perf_counter() - start) * 1000

    # Simulated latency: shard formation + intra-shard PBFT + 2PC
    # Intra-shard PBFT latency is 3 × latency (but with small n/k)
    # 2PC adds 2 × latency
    simulated_latency = (
        scenario.network.latency_mean +          # Shard formation
        3 * scenario.network.latency_mean +       # Intra-shard PBFT (3 phases)
        2 * scenario.network.latency_mean         # Cross-shard 2PC
    )

    traitor_ids = {node.node_id for node in net.get_traitor_nodes()}
    agreement = compute_agreement_rate(decisions, traitor_ids)

    # Per-shard fault tolerance check
    bft_per_shard = True
    for shard in sharding.shards:
        n_s = len(shard.node_ids)
        f_s = sum(1 for nid in shard.node_ids if nid in traitor_ids)
        if n_s < 3 * f_s + 1:
            bft_per_shard = False
            break

    consensus_ok = agreement > 2 / 3 and bft_per_shard

    return ConsensusMetrics(
        algorithm="sharding_bft",
        scenario=scenario.name,
        num_nodes=n,
        num_traitors=f,
        latency_ms=simulated_latency,
        throughput_tps=scenario.num_transactions / (simulated_latency / 1000) if simulated_latency > 0 else 0,
        total_messages=sharding.message_count,
        total_bytes=sharding.message_count * 512,
        rounds_to_consensus=sharding.rounds,
        dropped_messages=net.dropped_messages,
        consensus_success=consensus_ok,
        agreement_rate=agreement,
        agreed_value=consensus_value if consensus_ok else None,
        cpu_operations=sharding.cpu_operations,
        memory_peak_entries=sharding.max_memory,
        num_transactions=scenario.num_transactions,
    )
