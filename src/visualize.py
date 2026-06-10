"""
Visualization module for BFT Consensus Comparison.

Generates publication-quality charts using matplotlib/seaborn:
    1. Latency vs Number of Nodes
    2. Message Complexity vs Number of Nodes (log-scale)
    3. Consensus Success Rate vs Fault Level (KEY RESEARCH GRAPH)
    4. Throughput vs Number of Nodes
    5. Radar/Spider Chart (multi-dimensional comparison)
    6. Communication Overhead

All charts exported as high-res PNG to results/charts/.
"""

import sys
import os
import json
import math
import numpy as np
from typing import List, Dict, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from metrics import AggregateMetrics

# Attempt imports — will be checked at runtime
try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker
    from matplotlib.patches import FancyBboxPatch
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

# ─────────────────────────────────────────────────────────────
# Style Configuration
# ─────────────────────────────────────────────────────────────

# Algorithm colors — consistent across all charts
ALGO_COLORS = {
    "oral_message": "#E74C3C",    # Red
    "pbft": "#3498DB",            # Blue
    "dag_bft": "#2ECC71",         # Green
    "sharding_bft": "#F39C12",    # Orange
    "tower_bft": "#9B59B6",       # Purple
}

ALGO_LABELS = {
    "oral_message": "OM(m)",
    "pbft": "Classical PBFT",
    "dag_bft": "Hashgraph DAG-BFT",
    "sharding_bft": "Sharding-BFT",
    "tower_bft": "Tower BFT",
}

ALGO_MARKERS = {
    "oral_message": "o",
    "pbft": "s",
    "dag_bft": "D",
    "sharding_bft": "^",
    "tower_bft": "P",
}


def _setup_style():
    """Configure matplotlib for publication-quality output."""
    if not HAS_MPL:
        return
    plt.rcParams.update({
        'figure.figsize': (10, 6),
        'figure.dpi': 150,
        'font.size': 12,
        'font.family': 'serif',
        'axes.grid': True,
        'grid.alpha': 0.3,
        'axes.spines.top': False,
        'axes.spines.right': False,
        'legend.framealpha': 0.9,
        'legend.edgecolor': '0.8',
    })


def load_results(json_path: str) -> List[AggregateMetrics]:
    """Load benchmark results from JSON."""
    with open(json_path, 'r') as f:
        data = json.load(f)

    results = []
    for d in data:
        agg = AggregateMetrics(**{k: v for k, v in d.items()
                                   if k in AggregateMetrics.__dataclass_fields__})
        results.append(agg)
    return results


def _filter_results(
    results: List[AggregateMetrics],
    scenario_prefix: str,
    algorithm: Optional[str] = None,
) -> List[AggregateMetrics]:
    """Filter results by scenario prefix and optionally algorithm."""
    filtered = [r for r in results if r.scenario.startswith(scenario_prefix)]
    if algorithm:
        filtered = [r for r in filtered if r.algorithm == algorithm]
    return filtered


# ─────────────────────────────────────────────────────────────
# Chart 1: Latency vs Number of Nodes
# ─────────────────────────────────────────────────────────────

def plot_latency_vs_nodes(results: List[AggregateMetrics], output_dir: str):
    """
    Line chart: consensus latency vs network size for all algorithms.
    OM(m) shown with dashed theoretical extension beyond n=50.
    """
    if not HAS_MPL:
        print("[WARN] matplotlib not available, skipping chart")
        return

    _setup_style()
    fig, ax = plt.subplots(figsize=(12, 7))

    for algo in ALGO_COLORS:
        scale_data = _filter_results(results, "scale_", algo)
        om_data = _filter_results(results, "om_scale_", algo)
        data = om_data + scale_data

        if not data:
            continue

        # Sort by num_nodes and deduplicate
        seen = set()
        unique_data = []
        for d in sorted(data, key=lambda x: x.num_nodes):
            if d.num_nodes not in seen:
                seen.add(d.num_nodes)
                unique_data.append(d)
        data = unique_data

        nodes = [d.num_nodes for d in data]
        latencies = [d.latency_mean for d in data]
        errors = [d.latency_std for d in data]

        ax.errorbar(
            nodes, latencies,
            yerr=errors,
            label=ALGO_LABELS[algo],
            color=ALGO_COLORS[algo],
            marker=ALGO_MARKERS[algo],
            markersize=8,
            linewidth=2,
            capsize=4,
        )

        # For OM(m): add theoretical extrapolation beyond n=50
        if algo == "oral_message" and data:
            last_n = max(d.num_nodes for d in data)
            last_lat = data[-1].latency_mean
            if last_n <= 50:
                # Theoretical O(n^m) curve, m=2
                extra_nodes = [100, 200, 500]
                extra_latencies = [last_lat * (en / last_n) ** 2 for en in extra_nodes]
                ax.plot(
                    extra_nodes, extra_latencies,
                    '--', color=ALGO_COLORS[algo], alpha=0.5,
                    linewidth=1.5,
                )
                ax.annotate(
                    'OM(m) theoretical\n(O(n^m))',
                    xy=(extra_nodes[1], extra_latencies[1]),
                    fontsize=9, color=ALGO_COLORS[algo], alpha=0.7,
                )

    ax.set_xlabel('Number of Nodes (n)', fontsize=14)
    ax.set_ylabel('Consensus Latency (ms)', fontsize=14)
    ax.set_title('Consensus Latency vs Network Size', fontsize=16, fontweight='bold')
    ax.legend(loc='upper left', fontsize=11)
    ax.set_xscale('log')
    ax.set_yscale('log')

    plt.tight_layout()
    path = os.path.join(output_dir, "latency_vs_nodes.png")
    fig.savefig(path, dpi=200, bbox_inches='tight')
    plt.close(fig)
    print(f"  [SAVED] {path}")


# ─────────────────────────────────────────────────────────────
# Chart 2: Message Complexity vs Number of Nodes
# ─────────────────────────────────────────────────────────────

def plot_messages_vs_nodes(results: List[AggregateMetrics], output_dir: str):
    """Log-scale chart of total messages vs network size."""
    if not HAS_MPL:
        return

    _setup_style()
    fig, ax = plt.subplots(figsize=(12, 7))

    for algo in ALGO_COLORS:
        scale_data = _filter_results(results, "scale_", algo)
        om_data = _filter_results(results, "om_scale_", algo)
        data = om_data + scale_data

        if not data:
            continue

        seen = set()
        unique = []
        for d in sorted(data, key=lambda x: x.num_nodes):
            if d.num_nodes not in seen:
                seen.add(d.num_nodes)
                unique.append(d)

        nodes = [d.num_nodes for d in unique]
        msgs = [d.messages_mean for d in unique]

        ax.plot(
            nodes, msgs,
            label=ALGO_LABELS[algo],
            color=ALGO_COLORS[algo],
            marker=ALGO_MARKERS[algo],
            markersize=8,
            linewidth=2,
        )

    # Add theoretical complexity reference lines
    ref_n = np.array([10, 50, 100, 200, 500])
    ax.plot(ref_n, ref_n ** 2, ':', color='gray', alpha=0.3, label='O(n²) reference')
    ax.plot(ref_n, ref_n, ':', color='lightgray', alpha=0.3, label='O(n) reference')

    ax.set_xlabel('Number of Nodes (n)', fontsize=14)
    ax.set_ylabel('Total Messages (log scale)', fontsize=14)
    ax.set_title('Message Complexity vs Network Size', fontsize=16, fontweight='bold')
    ax.legend(fontsize=10)
    ax.set_xscale('log')
    ax.set_yscale('log')

    plt.tight_layout()
    path = os.path.join(output_dir, "messages_vs_nodes.png")
    fig.savefig(path, dpi=200, bbox_inches='tight')
    plt.close(fig)
    print(f"  [SAVED] {path}")


# ─────────────────────────────────────────────────────────────
# Chart 3: Consensus Success Rate vs Fault Level (KEY GRAPH)
# ─────────────────────────────────────────────────────────────

def plot_success_rate_vs_faults(results: List[AggregateMetrics], output_dir: str):
    """
    The most important research graph.
    Shows consensus success rate as fault level increases.
    Validates the paper's core claim: tolerates f ≤ ⌊(n-1)/3⌋.
    """
    if not HAS_MPL:
        return

    _setup_style()
    fig, ax = plt.subplots(figsize=(12, 7))

    for algo in ALGO_COLORS:
        data = _filter_results(results, "fault_", algo)
        if not data:
            continue

        data.sort(key=lambda x: x.num_traitors)
        faults = [d.num_traitors for d in data]
        success = [d.success_rate * 100 for d in data]

        ax.plot(
            faults, success,
            label=ALGO_LABELS[algo],
            color=ALGO_COLORS[algo],
            marker=ALGO_MARKERS[algo],
            markersize=9,
            linewidth=2.5,
        )

    # Mark theoretical BFT boundary: f = floor((n-1)/3) = 16 for n=51
    bft_boundary = (51 - 1) // 3
    ax.axvline(
        x=bft_boundary, color='red', linestyle='--', alpha=0.7, linewidth=2,
        label=f'BFT Boundary (f = ⌊(n-1)/3⌋ = {bft_boundary})',
    )

    # Shade the safe zone
    ax.axvspan(0, bft_boundary, alpha=0.05, color='green')
    ax.axvspan(bft_boundary, 25, alpha=0.05, color='red')

    ax.set_xlabel('Number of Traitors (f)', fontsize=14)
    ax.set_ylabel('Consensus Success Rate (%)', fontsize=14)
    ax.set_title(
        'Consensus Success Rate vs Byzantine Fault Level (n=51)',
        fontsize=16, fontweight='bold',
    )
    ax.set_ylim(-5, 105)
    ax.legend(loc='lower left', fontsize=11)

    plt.tight_layout()
    path = os.path.join(output_dir, "success_rate_vs_faults.png")
    fig.savefig(path, dpi=200, bbox_inches='tight')
    plt.close(fig)
    print(f"  [SAVED] {path}")


# ─────────────────────────────────────────────────────────────
# Chart 4: Throughput vs Number of Nodes
# ─────────────────────────────────────────────────────────────

def plot_throughput_vs_nodes(results: List[AggregateMetrics], output_dir: str):
    """Grouped bar chart of throughput across algorithms."""
    if not HAS_MPL:
        return

    _setup_style()
    fig, ax = plt.subplots(figsize=(12, 7))

    algos_with_data = []
    for algo in ALGO_COLORS:
        data = _filter_results(results, "scale_", algo)
        om_data = _filter_results(results, "om_scale_", algo)
        if data or om_data:
            algos_with_data.append(algo)

    if not algos_with_data:
        plt.close(fig)
        return

    # Get unique node counts
    all_n = sorted(set(
        d.num_nodes for d in results
        if d.scenario.startswith("scale_") or d.scenario.startswith("om_scale_")
    ))

    x = np.arange(len(all_n))
    width = 0.15
    offset = -(len(algos_with_data) - 1) / 2 * width

    for i, algo in enumerate(algos_with_data):
        scale_data = _filter_results(results, "scale_", algo)
        om_data = _filter_results(results, "om_scale_", algo)
        combined = {d.num_nodes: d for d in om_data + scale_data}

        throughputs = [combined.get(n, AggregateMetrics()).throughput_mean for n in all_n]

        ax.bar(
            x + offset + i * width,
            throughputs,
            width,
            label=ALGO_LABELS[algo],
            color=ALGO_COLORS[algo],
            alpha=0.85,
        )

    ax.set_xlabel('Number of Nodes (n)', fontsize=14)
    ax.set_ylabel('Throughput (tx/sec)', fontsize=14)
    ax.set_title('Throughput vs Network Size', fontsize=16, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(all_n)
    ax.legend(fontsize=10)

    plt.tight_layout()
    path = os.path.join(output_dir, "throughput_vs_nodes.png")
    fig.savefig(path, dpi=200, bbox_inches='tight')
    plt.close(fig)
    print(f"  [SAVED] {path}")


# ─────────────────────────────────────────────────────────────
# Chart 5: Radar/Spider Chart
# ─────────────────────────────────────────────────────────────

def plot_radar_chart(results: List[AggregateMetrics], output_dir: str):
    """
    Multi-dimensional comparison radar chart.
    Dimensions: Latency (inv), Throughput, Msg Efficiency (inv),
                Fault Tolerance, Agreement Rate
    """
    if not HAS_MPL:
        return

    _setup_style()

    # Get baseline results for each algorithm
    baseline_data = {}
    for algo in ALGO_COLORS:
        data = _filter_results(results, "paper_baseline", algo)
        if data:
            baseline_data[algo] = data[0]

    if len(baseline_data) < 2:
        print("  [SKIP] Not enough baseline data for radar chart")
        return

    # Dimensions for comparison
    categories = [
        'Low Latency',
        'Throughput',
        'Msg Efficiency',
        'Fault Tolerance',
        'Agreement Rate',
    ]
    N = len(categories)

    # Normalize each metric to [0, 1]
    all_latency = [d.latency_mean for d in baseline_data.values()]
    all_throughput = [d.throughput_mean for d in baseline_data.values()]
    all_msgs = [d.messages_mean for d in baseline_data.values()]

    max_lat = max(all_latency) if all_latency else 1
    max_thr = max(all_throughput) if all_throughput else 1
    max_msg = max(all_msgs) if all_msgs else 1

    fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))

    angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
    angles += angles[:1]  # Complete the circle

    for algo, data in baseline_data.items():
        values = [
            1 - (data.latency_mean / max_lat) if max_lat > 0 else 0,
            data.throughput_mean / max_thr if max_thr > 0 else 0,
            1 - (data.messages_mean / max_msg) if max_msg > 0 else 0,
            data.success_rate,
            data.agreement_rate_mean,
        ]
        values += values[:1]

        ax.plot(angles, values, 'o-', linewidth=2,
                label=ALGO_LABELS[algo], color=ALGO_COLORS[algo])
        ax.fill(angles, values, alpha=0.1, color=ALGO_COLORS[algo])

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(categories, fontsize=11)
    ax.set_ylim(0, 1.1)
    ax.set_title('Multi-Dimensional Algorithm Comparison\n(Paper Baseline: n=51, f=16)',
                 fontsize=14, fontweight='bold', pad=20)
    ax.legend(loc='upper right', bbox_to_anchor=(1.3, 1.1), fontsize=10)

    plt.tight_layout()
    path = os.path.join(output_dir, "radar_comparison.png")
    fig.savefig(path, dpi=200, bbox_inches='tight')
    plt.close(fig)
    print(f"  [SAVED] {path}")


# ─────────────────────────────────────────────────────────────
# Chart 6: Communication Overhead
# ─────────────────────────────────────────────────────────────

def plot_communication_overhead(results: List[AggregateMetrics], output_dir: str):
    """Stacked bar chart of communication bytes per algorithm."""
    if not HAS_MPL:
        return

    _setup_style()
    fig, ax = plt.subplots(figsize=(10, 6))

    baseline_data = {}
    for algo in ALGO_COLORS:
        data = _filter_results(results, "paper_baseline", algo)
        if data:
            baseline_data[algo] = data[0]

    if not baseline_data:
        plt.close(fig)
        return

    algos = list(baseline_data.keys())
    x = np.arange(len(algos))

    bytes_data = [baseline_data[a].bytes_mean / 1024 for a in algos]  # Convert to KB

    bars = ax.bar(
        x, bytes_data,
        color=[ALGO_COLORS[a] for a in algos],
        alpha=0.85,
        edgecolor='white',
        linewidth=1.5,
    )

    # Add value labels on bars
    for bar, val in zip(bars, bytes_data):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + max(bytes_data) * 0.02,
            f'{val:.1f} KB',
            ha='center', va='bottom', fontsize=10, fontweight='bold',
        )

    ax.set_xlabel('Algorithm', fontsize=14)
    ax.set_ylabel('Communication Overhead (KB)', fontsize=14)
    ax.set_title('Communication Overhead per Consensus Round\n(n=51, f=16)',
                 fontsize=16, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels([ALGO_LABELS[a] for a in algos], fontsize=11, rotation=15)

    plt.tight_layout()
    path = os.path.join(output_dir, "communication_overhead.png")
    fig.savefig(path, dpi=200, bbox_inches='tight')
    plt.close(fig)
    print(f"  [SAVED] {path}")


# ─────────────────────────────────────────────────────────────
# Summary Table
# ─────────────────────────────────────────────────────────────

def print_summary_table(results: List[AggregateMetrics]):
    """Print an extended version of Week 1 Table 1 with quantitative data."""
    baseline_data = {}
    for algo in ALGO_COLORS:
        data = _filter_results(results, "paper_baseline", algo)
        if data:
            baseline_data[algo] = data[0]

    if not baseline_data:
        print("  No baseline data for summary table")
        return

    print("\n" + "=" * 110)
    print("COMPARATIVE ANALYSIS — EXTENDED TABLE (Paper Baseline: n=51, f=16)")
    print("=" * 110)
    header = f"{'Algorithm':<20} {'Latency(ms)':<14} {'Msgs':<10} {'Bytes(KB)':<12} " \
             f"{'Rounds':<8} {'Success%':<10} {'Agreement':<12} {'CPU Ops':<10}"
    print(header)
    print("-" * 110)

    for algo in ALGO_COLORS:
        if algo not in baseline_data:
            continue
        d = baseline_data[algo]
        print(
            f"{ALGO_LABELS[algo]:<20} "
            f"{d.latency_mean:<14.1f} "
            f"{d.messages_mean:<10.0f} "
            f"{d.bytes_mean / 1024:<12.1f} "
            f"{d.rounds_mean:<8.0f} "
            f"{d.success_rate * 100:<10.0f} "
            f"{d.agreement_rate_mean * 100:<12.1f} "
            f"{d.cpu_ops_mean:<10.0f}"
        )

    print("=" * 110)


# ─────────────────────────────────────────────────────────────
# Main: Generate All Charts
# ─────────────────────────────────────────────────────────────

def generate_all_charts(json_path: str = None, output_dir: str = None):
    """Generate all publication-quality charts from benchmark results."""
    if json_path is None:
        json_path = os.path.join(os.path.dirname(__file__), "..", "results", "benchmark_results.json")
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(__file__), "..", "results", "charts")

    os.makedirs(output_dir, exist_ok=True)

    print(f"\nLoading results from {json_path}...")
    results = load_results(json_path)
    print(f"  Loaded {len(results)} aggregate entries")

    if not results:
        print("  No results to visualize!")
        return

    # Print summary table
    print_summary_table(results)

    # Generate charts
    print("\nGenerating charts...")
    plot_latency_vs_nodes(results, output_dir)
    plot_messages_vs_nodes(results, output_dir)
    plot_success_rate_vs_faults(results, output_dir)
    plot_throughput_vs_nodes(results, output_dir)
    plot_radar_chart(results, output_dir)
    plot_communication_overhead(results, output_dir)

    print(f"\nAll charts saved to: {output_dir}")


if __name__ == "__main__":
    generate_all_charts()
