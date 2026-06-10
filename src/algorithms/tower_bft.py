"""
Tower BFT — PoH-Adapted for EV Consensus

Based on Solana's Tower BFT, explicitly adapted for EV-DN energy trading.

Adaptation disclaimer (for research validity):
    "PoH-enabled BFT adapted for EV consensus with uniform validator weights.
     Stake weighting is replaced by equal validator weights (weight=1 per node).
     PoH is used purely for event ordering, not economic security bootstrapping."

Core mechanisms:
    1. Proof-of-History clock: Sequential SHA-256 hash chain providing
       verifiable slot ordering: h_{i+1} = SHA256(h_i)
    2. Slots and ticks: Each slot = fixed number of PoH ticks
    3. Voting: Each EV/DN node votes once per slot on the canonical fork
    4. Exponential lockout: Voting for slot s → locked out of contradicting
       forks for 2^(vote_depth) slots
    5. Fork choice: Heaviest fork by vote count (equal weights, no stake)
    6. Finality: A slot is final when lockout exceeds rollback horizon

In the EV-DN context:
    - Each node (EV or DN) acts as a validator with equal weight
    - PoH provides ordering for energy transactions
    - No economic stake mechanism
    - One vote per node per slot → O(n) message complexity

Tolerates f traitors with n >= 3f + 1 (assuming >2/3 honest vote weight).
Communication complexity: O(n) per slot — one vote per node.
"""

import sys
import time
import json
import hashlib
import random
from typing import Any, Dict, List, Optional, Set, Tuple
from collections import Counter, defaultdict
from dataclasses import dataclass, field

sys.path.insert(0, '..')

from network import Network, Node, setup_network
from metrics import ConsensusMetrics, compute_agreement_rate
from config import ScenarioConfig


@dataclass
class PoHTick:
    """A single tick in the Proof-of-History chain."""
    index: int
    hash: str
    previous_hash: str
    data: Optional[Any] = None  # Transaction data interleaved into the chain


@dataclass
class Slot:
    """
    A slot in the Tower BFT timeline.
    Each slot contains a batch of PoH ticks and associated transactions.
    """
    slot_number: int
    ticks: List[PoHTick] = field(default_factory=list)
    transactions: List[Any] = field(default_factory=list)
    parent_slot: int = -1   # For fork tracking
    votes: Dict[int, int] = field(default_factory=dict)  # node_id -> vote_depth
    total_vote_weight: int = 0


@dataclass
class ValidatorState:
    """Per-validator state for Tower BFT."""
    node_id: int
    vote_stack: List[Tuple[int, int]] = field(default_factory=list)  # (slot_number, lockout)
    last_voted_slot: int = -1
    weight: int = 1  # Equal weight for all EV validators (no stake)


class TowerBFTProtocol:
    """
    Implements Tower BFT adapted for EV consensus.

    The protocol runs for a fixed number of slots and determines
    which fork (if any) achieves finality.
    """

    def __init__(self, network: Network, ticks_per_slot: int = 8, num_slots: int = 0):
        self.network = network
        self.n = network.num_nodes
        self.ticks_per_slot = ticks_per_slot
        self.num_slots = num_slots or max(10, self.n // 2)

        # PoH state
        self.poh_chain: List[PoHTick] = []
        self.current_hash = "0" * 64

        # Slots
        self.slots: Dict[int, Slot] = {}

        # Validators (all nodes are validators with equal weight)
        self.validators: Dict[int, ValidatorState] = {}

        # Metrics
        self.message_count = 0
        self.cpu_operations = 0
        self.memory_entries = 0
        self.max_memory = 0

    def run(self, value: Any) -> Dict[int, Any]:
        """
        Execute Tower BFT consensus.

        Args:
            value: Proposed consensus value (energy trading data)

        Returns:
            Dict mapping node_id -> decided_value
        """
        all_ids = list(self.network.nodes.keys())

        # Initialize validators
        for nid in all_ids:
            self.validators[nid] = ValidatorState(node_id=nid, weight=1)

        # Generate PoH ticks and create slots
        self._generate_poh_slots(value)

        # Voting rounds: each validator votes on slots
        for slot_num in range(self.num_slots):
            self._voting_round(slot_num)

        # Determine finality
        decisions = self._determine_finality(value)

        return decisions

    def _generate_poh_slots(self, value: Any):
        """
        Generate the Proof-of-History chain and organize into slots.

        PoH: h_{i+1} = SHA256(h_i || data)
        Each slot contains ticks_per_slot sequential hashes.
        """
        tick_index = 0

        for slot_num in range(self.num_slots):
            slot = Slot(
                slot_number=slot_num,
                parent_slot=slot_num - 1 if slot_num > 0 else -1,
            )

            for t in range(self.ticks_per_slot):
                # Sequential SHA-256 hash chain (VDF simulation)
                content = f"{self.current_hash}:{tick_index}"
                new_hash = hashlib.sha256(content.encode()).hexdigest()

                tick = PoHTick(
                    index=tick_index,
                    hash=new_hash,
                    previous_hash=self.current_hash,
                    data=value if t == 0 and slot_num == 0 else None,
                )

                slot.ticks.append(tick)
                self.poh_chain.append(tick)
                self.current_hash = new_hash
                tick_index += 1

                self.cpu_operations += 1  # SHA-256 computation
                self.memory_entries += 1

            if slot_num == 0:
                slot.transactions = [value]

            self.slots[slot_num] = slot
            self.max_memory = max(self.max_memory, self.memory_entries)

    def _voting_round(self, slot_num: int):
        """
        Each validator votes on a slot.

        Tower BFT voting rules:
        1. Each validator votes for the slot on the fork it considers heaviest
        2. Each vote carries exponential lockout: if a validator has voted
           for k consecutive slots on the same fork, it's locked out of
           contradicting forks for 2^k slots
        3. Traitors may vote inconsistently
        """
        slot = self.slots[slot_num]

        for nid, validator in self.validators.items():
            node = self.network.nodes[nid]

            # Determine which slot to vote for
            if node.is_traitor:
                # Traitor behavior: may vote for wrong slot or not vote
                from config import AttackType
                if node.attack_type == AttackType.MESSAGE_DROP:
                    continue  # Don't vote
                elif node.attack_type == AttackType.CONFLICTING_BROADCAST:
                    # Vote for a random different slot
                    vote_slot = self._rng_choice(list(self.slots.keys()))
                else:
                    vote_slot = slot_num
            else:
                # Honest validator: vote for the heaviest fork
                vote_slot = self._find_heaviest_fork(slot_num)

            # Apply vote with lockout
            self._apply_vote(validator, vote_slot)
            self.message_count += 1  # One vote message per validator per slot
            self.cpu_operations += 1

    def _rng_choice(self, choices):
        """Random choice using deterministic RNG."""
        import random as _rng
        return _rng.choice(choices)

    def _find_heaviest_fork(self, current_slot: int) -> int:
        """
        Find the heaviest fork at the current slot.

        In the simplified EV model (no actual forks), this always
        returns the current slot (linear chain).
        """
        # In our simulation we model a single chain (no forks)
        # In a real implementation, this would traverse fork choices
        return current_slot

    def _apply_vote(self, validator: ValidatorState, slot_num: int):
        """
        Apply a vote with exponential lockout.

        If voting on the same fork, increase lockout exponentially.
        Lockout = 2^(consecutive_votes_on_this_fork)
        """
        if validator.last_voted_slot == slot_num - 1 or validator.last_voted_slot == -1:
            # Continuing on the same fork
            vote_depth = len(validator.vote_stack) + 1
            lockout = 2 ** min(vote_depth, 20)  # Cap at 2^20 to prevent overflow

            validator.vote_stack.append((slot_num, lockout))
            validator.last_voted_slot = slot_num

            # Expire old lockouts
            validator.vote_stack = [
                (s, l) for s, l in validator.vote_stack
                if s + l > slot_num
            ]
        else:
            # Switching forks — reset vote stack
            validator.vote_stack = [(slot_num, 2)]
            validator.last_voted_slot = slot_num

        # Record vote on the slot
        if slot_num in self.slots:
            self.slots[slot_num].votes[validator.node_id] = len(validator.vote_stack)
            self.slots[slot_num].total_vote_weight += validator.weight

        self.memory_entries += 1
        self.max_memory = max(self.max_memory, self.memory_entries)

    def _determine_finality(self, value: Any) -> Dict[int, Any]:
        """
        Determine which slots have achieved finality.

        A slot is considered final when:
        1. It has > 2/3 of total vote weight
        2. The lockout period for those votes exceeds the rollback horizon

        All honest validators that see a finalized slot will agree on
        the value in that slot.
        """
        decisions: Dict[int, Any] = {}
        n = self.network.num_nodes
        threshold = (2 * n) // 3 + 1  # >2/3 votes needed

        # Find the latest finalized slot
        finalized_slot = None
        for slot_num in sorted(self.slots.keys(), reverse=True):
            slot = self.slots[slot_num]
            if slot.total_vote_weight >= threshold:
                finalized_slot = slot_num
                break

        # Each node's decision based on finality
        for nid in self.network.nodes:
            node = self.network.nodes[nid]

            if node.is_traitor:
                # Traitor may report wrong value
                decisions[nid] = node.traitor_value(value, nid)
            elif finalized_slot is not None:
                decisions[nid] = value
            else:
                decisions[nid] = None  # No finality reached

            self.network.nodes[nid].decided_value = decisions[nid]

        return decisions


def run_tower_bft(scenario: ScenarioConfig, seed: int = 42) -> ConsensusMetrics:
    """
    Run Tower BFT for a given scenario and return metrics.
    """
    n = scenario.num_nodes
    f = scenario.num_traitors

    net = setup_network(
        num_nodes=n,
        num_traitors=f,
        attack_type=scenario.attack_type,
        network_config=scenario.network,
        seed=seed,
    )

    consensus_value = {
        "demand_kwh": scenario.ev.dn_demand_kwh,
        "num_transactions": scenario.num_transactions,
        "block_index": 1,
    }

    # Configure slots based on network size
    num_slots = max(10, n // 2)
    ticks_per_slot = 8

    start = time.perf_counter()
    tower = TowerBFTProtocol(net, ticks_per_slot=ticks_per_slot, num_slots=num_slots)
    decisions = tower.run(value=consensus_value)
    elapsed_real = (time.perf_counter() - start) * 1000

    # Simulated latency: PoH generation + voting rounds
    # Each slot: PoH tick time + one vote broadcast
    # PoH ticks are sequential but very fast (SHA-256)
    # Voting requires one network round per slot
    poh_time = num_slots * ticks_per_slot * 0.001  # SHA-256 is ~μs
    voting_time = scenario.network.latency_mean  # One round of votes
    simulated_latency = poh_time + voting_time

    traitor_ids = {node.node_id for node in net.get_traitor_nodes()}
    agreement = compute_agreement_rate(decisions, traitor_ids)

    bft_satisfied = n >= 3 * f + 1
    consensus_ok = agreement > 2 / 3 and bft_satisfied

    return ConsensusMetrics(
        algorithm="tower_bft",
        scenario=scenario.name,
        num_nodes=n,
        num_traitors=f,
        latency_ms=simulated_latency,
        throughput_tps=scenario.num_transactions / (simulated_latency / 1000) if simulated_latency > 0 else 0,
        total_messages=tower.message_count,
        total_bytes=tower.message_count * 128,  # Tower votes are compact
        rounds_to_consensus=num_slots,
        dropped_messages=net.dropped_messages,
        consensus_success=consensus_ok,
        agreement_rate=agreement,
        agreed_value=consensus_value if consensus_ok else None,
        cpu_operations=tower.cpu_operations,
        memory_peak_entries=tower.max_memory,
        num_transactions=scenario.num_transactions,
    )
