"""
Benchmark Runner for BFT Consensus Comparison.

Orchestrates all five algorithms across four scenario types:
    Scenario 1 — Paper Baseline:   n=51, f=16 (50 EVs + 1 DN)
    Scenario 2 — Scalability Sweep: n ∈ {10..500}, OM(m) capped at 50
    Scenario 3 — Fault Sweep:       f ∈ {0..25}, 100 trials each
    Scenario 4 — Throughput:        tx ∈ {10..1000}
    Scenario 5 — Attack Types:      All four AttackType variants

Results exported to results/benchmark_results.csv and .json.
"""

import sys
import os
import time
import json
import argparse
from typing import List, Dict

# Ensure src is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    ScenarioConfig, ALGORITHM_NAMES, ALGORITHM_MAX_NODES,
    paper_baseline, scalability_sweep, om_scalability_sweep,
    fault_sweep, throughput_sweep, attack_type_sweep,
)
from metrics import ConsensusMetrics, AggregateMetrics, export_results_csv, export_results_json
from algorithms import ALGORITHM_REGISTRY


def run_scenario(
    algorithm_name: str,
    scenario: ScenarioConfig,
    num_trials: int = None,
) -> List[ConsensusMetrics]:
    """
    Run a single algorithm on a single scenario for multiple trials.

    Args:
        algorithm_name: Name of the algorithm (e.g., "pbft")
        scenario:       Scenario configuration
        num_trials:     Override number of trials

    Returns:
        List of ConsensusMetrics, one per trial
    """
    runner = ALGORITHM_REGISTRY.get(algorithm_name)
    if runner is None:
        print(f"  [SKIP] Unknown algorithm: {algorithm_name}")
        return []

    # Check node count limit
    max_n = ALGORITHM_MAX_NODES.get(algorithm_name, 500)
    if scenario.num_nodes > max_n:
        print(f"  [SKIP] {algorithm_name}: n={scenario.num_nodes} > max={max_n}")
        return []

    trials = num_trials or scenario.num_trials
    results = []

    for trial in range(trials):
        seed = 42 + trial  # Reproducible but varying seeds
        try:
            metrics = runner(scenario, seed=seed)
            metrics.trial = trial
            results.append(metrics)
        except Exception as e:
            print(f"  [ERROR] {algorithm_name} trial {trial}: {e}")
            # Record failed trial
            results.append(ConsensusMetrics(
                algorithm=algorithm_name,
                scenario=scenario.name,
                num_nodes=scenario.num_nodes,
                num_traitors=scenario.num_traitors,
                trial=trial,
                consensus_success=False,
                agreement_rate=0.0,
            ))

    return results


def run_benchmark_suite(scenarios: str = "all") -> List[AggregateMetrics]:
    """
    Run the complete benchmark suite.

    Args:
        scenarios: Which scenarios to run: "all", "baseline", "scale",
                   "fault", "throughput", "attack"

    Returns:
        List of AggregateMetrics across all algorithm × scenario combos
    """
    all_aggregates: List[AggregateMetrics] = []
    all_raw: List[ConsensusMetrics] = []

    run_set = scenarios.lower()

    # ── Scenario 1: Paper Baseline ──
    if run_set in ("all", "baseline"):
        print("=" * 60)
        print("SCENARIO 1: Paper Baseline (n=51, f=16)")
        print("=" * 60)
        baseline = paper_baseline()

        for algo in ALGORITHM_NAMES:
            print(f"  Running {algo}...", end=" ", flush=True)
            start = time.time()
            results = run_scenario(algo, baseline)
            elapsed = time.time() - start
            if results:
                agg = AggregateMetrics.from_trials(results)
                all_aggregates.append(agg)
                all_raw.extend(results)
                print(f"OK ({elapsed:.1f}s) | success={agg.success_rate:.0%} "
                      f"agreement={agg.agreement_rate_mean:.2%} "
                      f"msgs={agg.messages_mean:.0f}")
            else:
                print("SKIPPED")

    # ── Scenario 2: Scalability Sweep ──
    if run_set in ("all", "scale"):
        print("\n" + "=" * 60)
        print("SCENARIO 2: Scalability Sweep")
        print("=" * 60)

        # OM(m) sweep (capped at n=50)
        for scenario in om_scalability_sweep():
            print(f"\n  --- n={scenario.num_nodes}, f={scenario.num_traitors} ---")
            print(f"  Running oral_message...", end=" ", flush=True)
            start = time.time()
            results = run_scenario("oral_message", scenario)
            elapsed = time.time() - start
            if results:
                agg = AggregateMetrics.from_trials(results)
                all_aggregates.append(agg)
                all_raw.extend(results)
                print(f"OK ({elapsed:.1f}s)")
            else:
                print("SKIPPED")

        # Other algorithms sweep (up to n=500)
        for scenario in scalability_sweep():
            print(f"\n  --- n={scenario.num_nodes}, f={scenario.num_traitors} ---")
            for algo in ALGORITHM_NAMES:
                if algo == "oral_message" and scenario.num_nodes > 50:
                    continue  # Already handled above
                print(f"  Running {algo}...", end=" ", flush=True)
                start = time.time()
                results = run_scenario(algo, scenario)
                elapsed = time.time() - start
                if results:
                    agg = AggregateMetrics.from_trials(results)
                    all_aggregates.append(agg)
                    all_raw.extend(results)
                    print(f"OK ({elapsed:.1f}s)")
                else:
                    print("SKIPPED")

    # ── Scenario 3: Fault Sweep (Consensus Success Rate) ──
    if run_set in ("all", "fault"):
        print("\n" + "=" * 60)
        print("SCENARIO 3: Consensus Success Rate vs Fault Level")
        print("=" * 60)

        for scenario in fault_sweep():
            print(f"\n  --- f={scenario.num_traitors} ({scenario.num_trials} trials) ---")
            for algo in ALGORITHM_NAMES:
                if algo == "oral_message" and scenario.num_nodes > 50:
                    continue
                print(f"  Running {algo}...", end=" ", flush=True)
                start = time.time()
                results = run_scenario(algo, scenario)
                elapsed = time.time() - start
                if results:
                    agg = AggregateMetrics.from_trials(results)
                    all_aggregates.append(agg)
                    all_raw.extend(results)
                    print(f"OK ({elapsed:.1f}s) success={agg.success_rate:.0%}")
                else:
                    print("SKIPPED")

    # ── Scenario 4: Throughput Sweep ──
    if run_set in ("all", "throughput"):
        print("\n" + "=" * 60)
        print("SCENARIO 4: Throughput vs Transaction Load")
        print("=" * 60)

        for scenario in throughput_sweep():
            print(f"\n  --- tx={scenario.num_transactions} ---")
            for algo in ALGORITHM_NAMES:
                print(f"  Running {algo}...", end=" ", flush=True)
                start = time.time()
                results = run_scenario(algo, scenario)
                elapsed = time.time() - start
                if results:
                    agg = AggregateMetrics.from_trials(results)
                    all_aggregates.append(agg)
                    all_raw.extend(results)
                    print(f"OK ({elapsed:.1f}s)")
                else:
                    print("SKIPPED")

    # ── Scenario 5: Attack Type Sweep ──
    if run_set in ("all", "attack"):
        print("\n" + "=" * 60)
        print("SCENARIO 5: Attack Type Comparison")
        print("=" * 60)

        for scenario in attack_type_sweep():
            print(f"\n  --- {scenario.attack_type.value} ---")
            for algo in ALGORITHM_NAMES:
                print(f"  Running {algo}...", end=" ", flush=True)
                start = time.time()
                results = run_scenario(algo, scenario)
                elapsed = time.time() - start
                if results:
                    agg = AggregateMetrics.from_trials(results)
                    all_aggregates.append(agg)
                    all_raw.extend(results)
                    print(f"OK ({elapsed:.1f}s) success={agg.success_rate:.0%}")
                else:
                    print("SKIPPED")

    # ── Export Results ──
    results_dir = os.path.join(os.path.dirname(__file__), "..", "results")
    os.makedirs(results_dir, exist_ok=True)

    csv_path = os.path.join(results_dir, "benchmark_results.csv")
    json_path = os.path.join(results_dir, "benchmark_results.json")
    js_path = os.path.join(results_dir, "benchmark_results.js")

    export_results_csv(all_aggregates, csv_path)
    export_results_json(all_aggregates, json_path)

    # Write as a Javascript declaration for direct inclusion in the dashboard
    with open(js_path, 'w') as f:
        f.write("const BENCHMARK_RESULTS = ")
        json.dump([r.to_dict() for r in all_aggregates], f, indent=2, default=str)
        f.write(";\n")

    # Also export raw trial data
    raw_json_path = os.path.join(results_dir, "raw_trial_results.json")
    with open(raw_json_path, 'w') as f:
        json.dump([r.to_dict() for r in all_raw], f, indent=2, default=str)

    print(f"\n{'=' * 60}")
    print(f"BENCHMARK COMPLETE")
    print(f"  Aggregate results: {csv_path}")
    print(f"  Aggregate JSON:    {json_path}")
    print(f"  Raw trial data:    {raw_json_path}")
    print(f"  Total scenarios:   {len(all_aggregates)}")
    print(f"  Total trials:      {len(all_raw)}")
    print(f"{'=' * 60}")

    return all_aggregates


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BFT Consensus Benchmark Runner")
    parser.add_argument(
        "--scenarios", "-s",
        default="all",
        choices=["all", "baseline", "scale", "fault", "throughput", "attack"],
        help="Which scenario set to run (default: all)"
    )
    args = parser.parse_args()

    run_benchmark_suite(scenarios=args.scenarios)
