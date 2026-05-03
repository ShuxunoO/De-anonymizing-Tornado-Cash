# Empirical Analysis of Tornado Cash Linkage Dataset

## 1. Research Background

Tornado Cash (TC) is a prominent mixing protocol on Ethereum that uses zero-knowledge proofs to break the on-chain linkage between deposit and withdrawal addresses. This anonymity mechanism has made it widely used for laundering proceeds from hacks and other crimes on blockchain. Existing on-chain forensic studies mainly rely on shallow heuristic features such as gas fees, temporal proximity, amount similarity, and ENS ownership, which heavily depend on subjective assumptions and expert intuition. The lack of publicly available high-quality labeled datasets has further hindered research on TC deposit-withdrawal address linkage.

To address these challenges, we propose a multidimensional transaction-feature-based detection method that identifies linkage between Tornado Cash deposit and withdrawal addresses by leveraging the historical transaction patterns of key entities involved in the Tornado Cash protocol.

## 2. Data Analysis Framework

### 2.1 Input Data Schema

Our analysis is built upon five CSV tables:

| Table | Description |
|---|---|
| `tornadocash_onestep_clues.csv` | Main linkage table with deposit-recipient pairs (10,853 records) |
| `tornadocash_onestep_clues_details.csv` | Transaction-step evidence for each linkage (25,615 records) |
| `tornadocash_raw_deposit_transactions.csv` | Raw deposit transactions for linked addresses |
| `tornadocash_raw_withdrawal_transactions.csv` | Raw withdrawal transactions for linked addresses |
| `tornadocash_deposit_address_onestep_trace_history.csv` | One-hop trace history for deposit addresses |
| `tornadocash_withdrawal_address_onestep_trace_history.csv` | One-hop trace history for withdrawal addresses |

The key constraint is that public infrastructure addresses (exchanges, bridges, mining pools, large DeFi contracts) have been pre-filtered from the trace history tables, meaning all counterparty analysis operates on a **filtered private ETH interaction subgraph** rather than the complete Ethereum graph.

### 2.2 Multi-Level Analysis Hierarchy

We organize the analysis across four hierarchical levels:

```
Filtered Upstream U → Deposit Address D → TC Pool → Withdraw Address W → Filtered Downstream V
                                    \_______________________________________/
                                          Discovered D-W Linkage Clues
```

| Level | Description |
|---|---|
| **Transaction-level** | Individual ETH transfers or TC deposit/withdrawal events |
| **Address-level** | Behavioral features of a single deposit or withdrawal address |
| **Edge-level** | Joint features of a `(deposit_address, withdraw_address)` clue pair |
| **Component-level** | Structural and behavioral characteristics of a connected component in the linkage graph |

### 2.3 Structural Classification

For each TC pool, we construct a bipartite graph $G_p = (V_D^p \cup V_W^p, E_p)$ where $V_D^p$ is the set of deposit addresses, $V_W^p$ is the set of withdrawal recipients, and an edge $(d, w) \in E_p$ exists if a high-confidence clue links $d$ and $w$ in pool $p$.

Each linkage edge is classified into one of four structural classes based on endpoint degrees:

| Class | Condition | Interpretation |
|---|---|---|
| **1-to-1** | $\deg_D(d;p) = 1 \land \deg_W(w;p) = 1$ | Simple endpoint-to-endpoint usage |
| **1-to-many** | $\deg_D(d;p) > 1 \land \deg_W(w;p) = 1$ | One deposit feeds multiple withdrawals |
| **Many-to-1** | $\deg_D(d;p) = 1 \land \deg_W(w;p) > 1$ | Multiple deposits aggregate to one withdrawal |
| **Many-to-many** | $\deg_D(d;p) > 1 \land \deg_W(w;p) > 1$ | Complex multi-address coordination |

### 2.4 Temporal Behavior Decomposition

We decompose the timeline around TC usage into three stages:

**Stage 1 — Pre-TC Funding**: Measures how long funds stay around the deposit address before entering TC.

- `recent_in_gap`: Time between the most recent incoming ETH transfer and the TC deposit event.
- `funding_span_approx`: Time from when accumulated incoming transfers approximately cover the TC deposit amount to the deposit event.

**Stage 2 — In-Pool Dwell Time**: Measures the time gap between matched deposit and withdrawal events within the same pool.

- `candidate_gap`: Distribution of time gaps across all valid `(deposit_time < withdraw_time)` pairs.
- `nearest_forward_gap`: For each withdrawal, the gap to the closest preceding deposit.
- `temporal_matching_gap`: Gap under ordered temporal bipartite matching that maximizes matched pairs then minimizes total waiting time.

**Stage 3 — Post-Withdrawal Release**: Measures how long the withdrawal recipient holds funds before releasing them to private downstream counterparties.

- `first_out_gap`: Time from TC withdrawal receipt to the first outgoing ETH transfer.
- `half_release_gap_approx`: Time until 50% of the withdrawn amount is released.
- `full_release_gap_approx`: Time until the full withdrawn amount is released.

### 2.5 Counterparty Analysis in Filtered Subgraph

Since the trace history operates on a filtered subgraph (public addresses removed), all counterparty metrics must be interpreted as observations within the filtered private interaction view, not absolute values on the full Ethereum graph.

**One-hop breadth metrics:**

- `filtered_upstream_count(D)`: Number of unique source addresses that sent ETH to deposit address $D$.
- `filtered_downstream_count(W)`: Number of unique destination addresses that received ETH from withdrawal recipient $W$.
- `outflow_counterparty_count(e)`: Number of unique downstream addresses observed during the post-withdrawal release scan.

**Value concentration metrics:**

- **HHI (Herfindahl-Hirschman Index)**: $\mathrm{HHI} = \sum_i (x_i / X)^2$, where $x_i$ is the cumulative ETH value for counterparty $i$ and $X$ is the total. Higher HHI indicates stronger concentration.
- **Top-k value share**: $\mathrm{TopK} = \sum_{i \in \mathrm{largest}\ k} x_i / X$. The median downstream top-1 share and top-3 share reveal how concentrated post-TC flows are.

### 2.6 Component-Level Interpretation

A critical interpretive boundary separates what individual edges and components represent:

| Level | Interpretation |
|---|---|
| **Edge-level** | A `(D, W)` edge represents a high-value linkage clue between the deposit address and the withdrawal recipient. It does not imply a one-to-one confirmed fund mapping for every transaction. |
| **Component-level** | Multiple addresses connected through linkage clues in the same connected component are interpreted as likely controlled by a common entity or tightly coordinated through the same operational chain. |
| **Narrative-level** | We use phrasing such as "linked addresses," "associated address set," and "likely common-control or coordinated-use cluster." We avoid over-stating that all addresses in a component are definitively confirmed to belong to a single entity. |

## 3. Dataset Overview

The Tornado Cash Linkage Dataset contains **10,853 high-confidence linkage clues** covering four ETH-denominated pools:

| Pool | Linkage Records |
|---|---:|
| `0_1ETH` | 3,809 |
| `1ETH` | 3,902 |
| `10ETH` | 2,273 |
| `100ETH` | 869 |

These linkages span three broad categories:

| Category | Clue Types | Records |
|---|---|---:|
| **Direct linkage** | `dl_1`, `dl_2` | 4,729 |
| **Gas funding linkage** | `gf_1`, `gf_2` | 5,251 |
| **Transaction-intensity linkage** | `ti_1`, `ti_2` | 873 |

### Clue Type Definitions

| Type | Description |
|---|---|
| `dl_1` | Deposit-recipient address reuse (same address used for deposit and withdrawal) |
| `dl_2` | Deposit address appears as a non-relayer withdrawal initiator, linking it to the withdrawal recipient |
| `gf_1` | Deposit address and withdrawal recipient share the same third-party gas funder |
| `gf_2` | Deposit address funds the withdrawal initiator that submits the withdrawal transaction |
| `ti_1` | High-intensity transfers between the deposit address and the withdrawal recipient |
| `ti_2` | High-intensity transfers between the deposit address and the non-relayer withdrawal initiator |

## 4. Key Findings Summary

### 4.1 Graph Structure — Head Simple, Tail Complex

- **1-to-1 edges** account for **46.6%** of all edges, indicating simple endpoint-to-endpoint usage is common.
- **Many-to-many edges** account for **38.5%**, while 1-to-many and many-to-1 account for **9.8%** and **5.1%** respectively.
- **89.4%** of pool-level components contain only one linkage edge, yet these single-edge components contribute only **46.6%** of all linkage edges.
- The largest component contains **35 deposit addresses, 59 withdrawal recipients, and 644 linkage edges**.

This reveals a **head-simple, tail-complex pattern**: simple components dominate in count, but a small number of dense components carry disproportionate investigative value.

### 4.2 Temporal Behavior — TC as a Latency Stack

- **Pre-TC funding**: The median `recent_in_gap` is **17.2 hours** (fast last hop), but the median `funding_span_approx` is **2,305 hours (~96 days)** (slow funding preparation).
- **In-pool dwell time**: Under ordered temporal bipartite matching, the median `temporal_matching_gap` is **944.0 hours (~39.3 days)**.
- **Post-withdrawal release**: The median `first_out_gap` is **2,425.6 hours (~101 days)**, and the median `full_release_gap_approx` is **4,159.0 hours (~173.2 days)**.

This indicates that TC behaves as a **temporal buffer** before, inside, and after the mixer.

### 4.3 Counterparty Neighborhood — Post-TC Funnel

- The median `outflow_counterparty_count` is **one**: **70%** of withdrawal events touch at most **one** downstream counterparty during the release scan.
- The median downstream **top-1 value share** is **82.4%**, and the median downstream **top-3 value share** reaches **100%**.
- The median downstream **HHI** is **0.704**, compared with **0.560** on the upstream side.

This pattern is better described as a **post-mixer funnel** than immediate broad dispersion: the funds released after a specific TC withdrawal often move through a small number of downstream targets, making the withdrawal recipient remain useful for downstream investigation even when the exact in-pool path is uncertain.

## 5. Practical Implications

The analysis demonstrates that TC weakens direct deposit-withdrawal transaction continuity, but it does not necessarily erase operational continuity around the mixer. The most distinctive behavioral signals are:

1. **Traceability shifts from the broken deposit-withdrawal edge to the timing and neighborhood around the withdrawal recipient.** Post-TC flows are frequently not diffuse; the local downstream neighborhood often remains focused enough to support downstream investigation.

2. **The component, rather than the individual edge, is the appropriate unit for understanding high-value TC linkage evidence.** The simple head of the component distribution is useful for direct endpoint analysis, whereas the dense tail may expose repeated use, role reuse, and shared counterparties.

3. **The relevant investigative question is not only which deposit may correspond to which withdrawal, but also how value was staged, hidden, and released around the mixer.** Funds may be assembled over ~100 days before deposit, delayed ~40 days inside the pool, and then held again for ~173 days after withdrawal.

## 6. Dataset Files

The release contains seven CSV files:

| File | Description |
|---|---|
| `tornadocash_onestep_clues.csv` | Main linkage table (10,853 records) |
| `tornadocash_onestep_clues_details.csv` | Transaction-step evidence (25,615 records) |
| `tornadocash_raw_deposit_transactions.csv` | Raw deposit transactions for linked addresses |
| `tornadocash_raw_withdrawal_transactions.csv` | Raw withdrawal transactions for linked addresses |
| `tornadocash_deposit_address_onestep_trace_history.csv` | One-hop trace history for deposit addresses |
| `tornadocash_withdrawal_address_onestep_trace_history.csv` | One-hop trace history for withdrawal addresses |

For detailed field documentation, see `Tornado_Cash_Linkage_Dataset_introduction.md` in the dataset directory.