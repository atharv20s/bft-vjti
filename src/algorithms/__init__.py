"""
BFT Consensus Algorithm Implementations.

Five algorithms for comparative analysis:
1. oral_message  - OM(m) Lamport et al. 1982
2. pbft          - Classical PBFT Castro & Liskov 1999
3. dag_bft       - Hashgraph Baird 2016
4. sharding_bft  - Elastico-style Sharding BFT
5. tower_bft     - Tower BFT (PoH-adapted for EV consensus)
"""

from algorithms.oral_message import run_oral_message
from algorithms.pbft import run_pbft
from algorithms.dag_bft import run_dag_bft
from algorithms.sharding_bft import run_sharding_bft
from algorithms.tower_bft import run_tower_bft

ALGORITHM_REGISTRY = {
    "oral_message": run_oral_message,
    "pbft": run_pbft,
    "dag_bft": run_dag_bft,
    "sharding_bft": run_sharding_bft,
    "tower_bft": run_tower_bft,
}
