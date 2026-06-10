"""
Network simulation module for BFT Consensus Comparison Framework.

Provides:
- Lightweight Block and Message structures (no mining, no PoW)
- Node abstraction with honest/traitor behavior
- Network simulator with realistic impairments:
  - Configurable latency (gaussian)
  - Packet loss
  - Jitter
  - Burst delays
- Message counting and logging for metrics collection
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple, Callable
from enum import Enum
import hashlib
import json
import random
import time

from config import AttackType, NetworkConfig


# ─────────────────────────────────────────────────────────────
# Lightweight Blockchain Structures (NO mining, NO PoW)
# ─────────────────────────────────────────────────────────────

@dataclass
class Block:
    """
    Lightweight block for data integrity only.
    No mining, no nonce racing, no difficulty adjustment.
    The hash provides tamper-evidence, not proof-of-work.
    """
    index: int
    previous_hash: str
    transactions: List[dict]
    timestamp: float
    hash: str = field(init=False)

    def __post_init__(self):
        self.hash = self._compute_hash()

    def _compute_hash(self) -> str:
        """SHA-256 hash of block contents (matches paper's hash function)."""
        content = json.dumps({
            "index": self.index,
            "previous_hash": self.previous_hash,
            "transactions": self.transactions,
            "timestamp": self.timestamp,
        }, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()

    def verify(self) -> bool:
        """Verify block integrity by recomputing hash."""
        return self.hash == self._compute_hash()


def create_genesis_block() -> Block:
    """Create the genesis (first) block of the chain."""
    return Block(
        index=0,
        previous_hash="0" * 64,
        transactions=[],
        timestamp=0.0,
    )


# ─────────────────────────────────────────────────────────────
# Message Types
# ─────────────────────────────────────────────────────────────

class MessageType(Enum):
    """Types of messages exchanged during consensus."""
    # OM(m) messages
    OM_VALUE = "om_value"               # Commander/subordinate value broadcast

    # PBFT messages
    PRE_PREPARE = "pre_prepare"
    PREPARE = "prepare"
    COMMIT = "commit"
    VIEW_CHANGE = "view_change"

    # Hashgraph messages
    GOSSIP_SYNC = "gossip_sync"         # Gossip-about-gossip event sync

    # Sharding messages
    SHARD_CONSENSUS = "shard_consensus" # Intra-shard consensus message
    CROSS_SHARD = "cross_shard"         # Cross-shard 2PC message

    # Tower BFT messages
    POH_TICK = "poh_tick"               # Proof-of-History tick
    TOWER_VOTE = "tower_vote"           # Vote on a slot


@dataclass
class Message:
    """A network message between nodes."""
    msg_type: MessageType
    sender_id: int
    receiver_id: int
    payload: Any
    timestamp: float = 0.0
    size_bytes: int = 0                 # Estimated message size

    def __post_init__(self):
        if self.size_bytes == 0:
            # Estimate size from payload
            self.size_bytes = len(json.dumps(str(self.payload)).encode())


# ─────────────────────────────────────────────────────────────
# Node
# ─────────────────────────────────────────────────────────────

@dataclass
class Node:
    """
    A node in the consensus network (EV or DN).

    Attributes:
        node_id:        Unique identifier (0 = DN, 1..n = EVs)
        is_traitor:     Whether this node exhibits Byzantine behavior
        attack_type:    Type of Byzantine attack this traitor performs
        shard_id:       Shard assignment (for Sharding-BFT)
        parking_lot_id: Geographic cluster (for geographic sharding)
    """
    node_id: int
    is_traitor: bool = False
    attack_type: AttackType = AttackType.CONFLICTING_BROADCAST
    shard_id: int = 0
    parking_lot_id: int = 0

    # Internal state
    inbox: List[Message] = field(default_factory=list)
    decided_value: Optional[Any] = None
    is_dn: bool = False  # True if this is the Distribution Network node

    def receive(self, msg: Message):
        """Add a message to the node's inbox."""
        self.inbox.append(msg)

    def get_messages(self, msg_type: Optional[MessageType] = None) -> List[Message]:
        """Retrieve messages, optionally filtered by type."""
        if msg_type is None:
            return list(self.inbox)
        return [m for m in self.inbox if m.msg_type == msg_type]

    def clear_inbox(self):
        """Clear all messages."""
        self.inbox.clear()

    def traitor_value(self, honest_value: Any, target_id: int) -> Any:
        """
        Generate a Byzantine (incorrect) value based on attack type.

        Args:
            honest_value: The correct value this node should send
            target_id:    The node being sent to (for targeted attacks)

        Returns:
            Corrupted value if traitor, honest value otherwise
        """
        if not self.is_traitor:
            return honest_value

        if self.attack_type == AttackType.CONFLICTING_BROADCAST:
            # Send different values to different nodes
            if target_id % 2 == 0:
                return honest_value
            else:
                return self._corrupt_value(honest_value)

        elif self.attack_type == AttackType.FALSE_DEMAND:
            # Inflate demand (DN traitor scenario from paper Fig. 8)
            if isinstance(honest_value, (int, float)):
                return honest_value * 2.0
            return self._corrupt_value(honest_value)

        elif self.attack_type == AttackType.FALSE_SUPPLY:
            # Report inflated supply (EV traitor scenario from paper Fig. 9)
            if isinstance(honest_value, (int, float)):
                return honest_value * 3.0
            return self._corrupt_value(honest_value)

        elif self.attack_type == AttackType.MESSAGE_DROP:
            # Return None to signal message should be dropped
            return None

        return honest_value

    def _corrupt_value(self, value: Any) -> Any:
        """Corrupt a value for Byzantine behavior."""
        if isinstance(value, bool):
            return not value
        elif isinstance(value, (int, float)):
            return -value
        elif isinstance(value, str):
            return value[::-1]  # Reverse string
        elif isinstance(value, dict):
            corrupted = dict(value)
            for k in corrupted:
                if isinstance(corrupted[k], (int, float)):
                    corrupted[k] = -corrupted[k]
                    break
            return corrupted
        return value


# ─────────────────────────────────────────────────────────────
# Network Simulator
# ─────────────────────────────────────────────────────────────

class Network:
    """
    Simulated async network with realistic impairments.

    Features:
    - Configurable latency distribution (gaussian)
    - Packet loss
    - Jitter events
    - Burst delays
    - Complete message logging for metrics
    """

    def __init__(self, config: NetworkConfig, seed: Optional[int] = None):
        self.config = config
        self.nodes: Dict[int, Node] = {}
        self.message_log: List[Message] = []
        self.total_messages: int = 0
        self.total_bytes: int = 0
        self.dropped_messages: int = 0
        self.simulated_time: float = 0.0  # Current simulated time (ms)
        self._rng = random.Random(seed)

    def add_node(self, node: Node):
        """Register a node in the network."""
        self.nodes[node.node_id] = node

    def get_node(self, node_id: int) -> Node:
        """Get a node by ID."""
        return self.nodes[node_id]

    def get_all_nodes(self) -> List[Node]:
        """Get all nodes in the network."""
        return list(self.nodes.values())

    def get_honest_nodes(self) -> List[Node]:
        """Get all honest (non-traitor) nodes."""
        return [n for n in self.nodes.values() if not n.is_traitor]

    def get_traitor_nodes(self) -> List[Node]:
        """Get all traitor nodes."""
        return [n for n in self.nodes.values() if n.is_traitor]

    @property
    def num_nodes(self) -> int:
        return len(self.nodes)

    def send(self, msg: Message) -> bool:
        """
        Send a message through the network.

        Applies network impairments:
        - Packet loss: message silently dropped
        - Jitter: additional random delay
        - Burst delay: occasional large delay spikes

        Returns:
            True if message was delivered, False if dropped
        """
        # Packet loss
        if self._rng.random() < self.config.packet_loss_probability:
            self.dropped_messages += 1
            return False

        # Message drop attack (traitor omission)
        if msg.payload is None:
            self.dropped_messages += 1
            return False

        # Calculate delivery latency
        latency = max(
            self.config.latency_min,
            self._rng.gauss(self.config.latency_mean, self.config.latency_std)
        )

        # Jitter
        if self._rng.random() < self.config.jitter_probability:
            latency *= self._rng.uniform(1.0, self.config.jitter_multiplier)

        # Burst delay
        if self._rng.random() < self.config.burst_delay_probability:
            latency += self.config.burst_delay_ms

        # Update simulated time
        msg.timestamp = self.simulated_time + latency

        # Deliver to receiver
        if msg.receiver_id in self.nodes:
            self.nodes[msg.receiver_id].receive(msg)

        # Log
        self.message_log.append(msg)
        self.total_messages += 1
        self.total_bytes += msg.size_bytes

        return True

    def broadcast(self, sender_id: int, msg_type: MessageType,
                  payload: Any, exclude: Optional[Set[int]] = None) -> int:
        """
        Broadcast a message from sender to all other nodes.

        Args:
            sender_id: ID of the sending node
            msg_type:  Message type
            payload:   Message payload
            exclude:   Set of node IDs to exclude from broadcast

        Returns:
            Number of messages successfully delivered
        """
        exclude = exclude or set()
        exclude.add(sender_id)
        delivered = 0

        sender = self.nodes.get(sender_id)

        for receiver_id, receiver in self.nodes.items():
            if receiver_id in exclude:
                continue

            # Traitor may send corrupted value
            actual_payload = payload
            if sender and sender.is_traitor:
                actual_payload = sender.traitor_value(payload, receiver_id)

            msg = Message(
                msg_type=msg_type,
                sender_id=sender_id,
                receiver_id=receiver_id,
                payload=actual_payload,
            )

            if self.send(msg):
                delivered += 1

        return delivered

    def advance_time(self, delta_ms: float):
        """Advance simulated time."""
        self.simulated_time += delta_ms

    def reset_metrics(self):
        """Reset message counters (keep nodes)."""
        self.message_log.clear()
        self.total_messages = 0
        self.total_bytes = 0
        self.dropped_messages = 0
        self.simulated_time = 0.0
        for node in self.nodes.values():
            node.clear_inbox()
            node.decided_value = None

    def get_metrics_snapshot(self) -> dict:
        """Get current network metrics."""
        return {
            "total_messages": self.total_messages,
            "total_bytes": self.total_bytes,
            "dropped_messages": self.dropped_messages,
            "simulated_time_ms": self.simulated_time,
            "num_nodes": self.num_nodes,
            "num_traitors": len(self.get_traitor_nodes()),
        }


def setup_network(
    num_nodes: int,
    num_traitors: int,
    attack_type: AttackType = AttackType.CONFLICTING_BROADCAST,
    network_config: Optional[NetworkConfig] = None,
    num_parking_lots: int = 4,
    seed: Optional[int] = 42,
) -> Network:
    """
    Create and configure a network for consensus simulation.

    Node 0 = DN (commander in BGP terms)
    Nodes 1..n-1 = EVs (lieutenants)

    Traitors are randomly assigned among EVs (or DN can be traitor).

    Args:
        num_nodes:       Total nodes including DN
        num_traitors:    Number of Byzantine traitors
        attack_type:     Type of attack traitors perform
        network_config:  Network configuration (latency, loss, etc.)
        num_parking_lots: Geographic clusters for sharding
        seed:            Random seed for reproducibility

    Returns:
        Configured Network instance
    """
    if network_config is None:
        network_config = NetworkConfig()

    rng = random.Random(seed)
    net = Network(config=network_config, seed=seed)

    # Select traitor node IDs (random subset)
    all_ids = list(range(num_nodes))
    traitor_ids = set(rng.sample(all_ids, min(num_traitors, num_nodes)))

    for i in range(num_nodes):
        node = Node(
            node_id=i,
            is_traitor=(i in traitor_ids),
            attack_type=attack_type,
            parking_lot_id=i % num_parking_lots,
            is_dn=(i == 0),
        )
        net.add_node(node)

    return net
