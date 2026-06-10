"""
Metrics collection for BFT Consensus Comparison Framework.

Captures per-run and aggregate results including:
- Latency, throughput, message complexity
- Agreement rate (not just boolean success)
- Simulated CPU operations and memory usage
- Consensus success boundaries
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
import json
import csv
import os
import math
import statistics


@dataclass
class ConsensusMetrics:
    """
    Metrics captured from a single consensus run.

    Key addition from reviewer feedback:
    - agreement_rate: fraction of honest nodes that agree (e.g., 0.97 = 97/100)
      This is richer than a simple boolean success/fail.
    - cpu_operations: simulated count of hash computations, comparisons, etc.
    - memory_peak_entries: peak number of entries stored in any node's state
    """
    # Identification
    algorithm: str = ""
    scenario: str = ""
    num_nodes: int = 0
    num_traitors: int = 0
    trial: int = 0

    # Core performance metrics
    latency_ms: float = 0.0             # Time to reach consensus (simulated ms)
    throughput_tps: float = 0.0         # Transactions per second
    total_messages: int = 0             # Total messages exchanged
    total_bytes: int = 0                # Total communication overhead (bytes)
    rounds_to_consensus: int = 0        # Number of communication rounds
    dropped_messages: int = 0           # Messages lost to network impairments

    # Consensus quality
    consensus_success: bool = False     # Did consensus complete successfully?
    agreement_rate: float = 0.0         # Fraction of honest nodes that agree (0.0 to 1.0)
    agreed_value: Optional[Any] = None  # The majority-agreed value (if any)

    # Resource usage (simulated)
    cpu_operations: int = 0             # Hash computations + comparisons + message processing
    memory_peak_entries: int = 0        # Peak entries in any node's data structure

    # EV trading specific
    energy_traded_kwh: float = 0.0      # Total energy successfully traded
    num_transactions: int = 0           # Number of transactions in this round

    def to_dict(self) -> dict:
        """Convert to dictionary, handling non-serializable fields."""
        d = asdict(self)
        # Convert agreed_value to string if not serializable
        if d.get("agreed_value") is not None:
            try:
                json.dumps(d["agreed_value"])
            except (TypeError, ValueError):
                d["agreed_value"] = str(d["agreed_value"])
        return d


@dataclass
class AggregateMetrics:
    """
    Aggregated metrics across multiple trials of the same scenario.

    Computes mean, std, min, max for all numeric fields.
    """
    algorithm: str = ""
    scenario: str = ""
    num_nodes: int = 0
    num_traitors: int = 0
    num_trials: int = 0

    # Aggregated performance (mean ± std)
    latency_mean: float = 0.0
    latency_std: float = 0.0
    throughput_mean: float = 0.0
    throughput_std: float = 0.0
    messages_mean: float = 0.0
    messages_std: float = 0.0
    bytes_mean: float = 0.0
    bytes_std: float = 0.0
    rounds_mean: float = 0.0
    rounds_std: float = 0.0

    # Consensus quality
    success_rate: float = 0.0           # Fraction of trials where consensus succeeded
    agreement_rate_mean: float = 0.0    # Mean agreement rate across trials
    agreement_rate_std: float = 0.0

    # Resource usage
    cpu_ops_mean: float = 0.0
    cpu_ops_std: float = 0.0
    memory_mean: float = 0.0
    memory_std: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_trials(trials: List[ConsensusMetrics]) -> 'AggregateMetrics':
        """Compute aggregate metrics from a list of trial results."""
        if not trials:
            return AggregateMetrics()

        first = trials[0]
        n = len(trials)

        def mean_std(values: List[float]):
            m = statistics.mean(values) if values else 0.0
            s = statistics.stdev(values) if len(values) > 1 else 0.0
            return m, s

        lat_m, lat_s = mean_std([t.latency_ms for t in trials])
        thr_m, thr_s = mean_std([t.throughput_tps for t in trials])
        msg_m, msg_s = mean_std([float(t.total_messages) for t in trials])
        byt_m, byt_s = mean_std([float(t.total_bytes) for t in trials])
        rnd_m, rnd_s = mean_std([float(t.rounds_to_consensus) for t in trials])
        agr_m, agr_s = mean_std([t.agreement_rate for t in trials])
        cpu_m, cpu_s = mean_std([float(t.cpu_operations) for t in trials])
        mem_m, mem_s = mean_std([float(t.memory_peak_entries) for t in trials])

        success_count = sum(1 for t in trials if t.consensus_success)

        return AggregateMetrics(
            algorithm=first.algorithm,
            scenario=first.scenario,
            num_nodes=first.num_nodes,
            num_traitors=first.num_traitors,
            num_trials=n,
            latency_mean=lat_m, latency_std=lat_s,
            throughput_mean=thr_m, throughput_std=thr_s,
            messages_mean=msg_m, messages_std=msg_s,
            bytes_mean=byt_m, bytes_std=byt_s,
            rounds_mean=rnd_m, rounds_std=rnd_s,
            success_rate=success_count / n if n > 0 else 0.0,
            agreement_rate_mean=agr_m, agreement_rate_std=agr_s,
            cpu_ops_mean=cpu_m, cpu_ops_std=cpu_s,
            memory_mean=mem_m, memory_std=mem_s,
        )


def compute_agreement_rate(nodes_decisions: Dict[int, Any], traitor_ids: set) -> float:
    """
    Compute the fraction of honest nodes that agree on the same value.

    This is richer than a simple boolean — it tells us HOW MUCH
    agreement was reached (e.g., 97% vs 100% vs 60%).

    Args:
        nodes_decisions: {node_id: decided_value} for all nodes
        traitor_ids:     Set of traitor node IDs (excluded from agreement calc)

    Returns:
        Agreement rate as float in [0.0, 1.0]
    """
    honest_decisions = {
        nid: val for nid, val in nodes_decisions.items()
        if nid not in traitor_ids and val is not None
    }

    if not honest_decisions:
        return 0.0

    # Find the majority value
    value_counts: Dict[str, int] = {}
    for val in honest_decisions.values():
        key = json.dumps(val, sort_keys=True, default=str)
        value_counts[key] = value_counts.get(key, 0) + 1

    if not value_counts:
        return 0.0

    max_count = max(value_counts.values())
    return max_count / len(honest_decisions)


def export_results_csv(
    results: List[AggregateMetrics],
    filepath: str,
):
    """Export aggregate results to CSV."""
    if not results:
        return

    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    fieldnames = list(results[0].to_dict().keys())
    with open(filepath, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow(r.to_dict())


def export_results_json(
    results: List[AggregateMetrics],
    filepath: str,
):
    """Export aggregate results to JSON."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    data = [r.to_dict() for r in results]
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2, default=str)
