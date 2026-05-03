## Section Draft

### Empirical Analysis of Reconstructed Tornado Cash Linkages

We analyze the reconstructed Tornado Cash linkage dataset from three complementary perspectives: graph structure, temporal behavior, and local fund-flow organization. The artifact run used in this section contains 10,853 high-confidence linkage clues 5,714 pool-level linked components, and 4,902 folded cross-pool components. The formal definitions of all the metrics in this section can be found in Appendix A.

To reduce confounding from public infrastructure, we measure upstream and downstream behavior in a filtered private ETH interaction subgraph. Public service addresses such as exchanges, bridges, mining pools, and large DeFi contracts can mechanically connect many unrelated users and inflate fan-in, fan-out, and shared-counterparty statistics. By using the filtered subgraph, the analysis focuses on private counterparties that are more informative for aggregation, dispersion, and coordinated-use patterns.  Similarly, the dwell-time features are value-based approximations: we scan ETH transfer values around each TC event without subtracting ordinary gas fees if there are negligible compared to the transfer value. This design keeps timing metrics consistent across all samples and matches our behavioral question: when funds arrive, when they enter TC, and when they are released after withdrawal.

#### Structural Organization of Linked Address Pairs

We first analyze the structural organization of linked address pairs. Based on our result, *the pool-level linkage graph contains many simple address pairs but also a large operationally complex tail.* For each pool, we build a bipartite graph between deposit addresses and withdrawal recipients, and classify every linkage edge by the degree of its two endpoints (see Appendix A.2 for the formal definition). As shown in Fig. 1, `1-to-1` edges account for 46.6% of all edges, which indicates that simple endpoint-to-endpoint usage is common. However, `many-to-many` edges account for 38.5%, while `many-to-1` and `1-to-many` edges account for 9.8% and 5.1%, respectively. This distribution shows that a substantial share of linked activity is embedded in multi-address structures rather than isolated transfers.

![Linked edge structure share](../figs/png/structure_class_share_pie.png)

**Figure 1.** Pool-level linkage edge classes. The distribution is edge-level: a `many-to-many` edge belongs to a local structure where both the deposit side and withdrawal side have multiple linked addresses.

The connected-component distribution reveals why component-level analysis is necessary in addition to edge-level classification. As shown in Fig. 2, 89.4% of pool-level components contain only one linkage edge, and 95.8% contain at most two edges. At first glance, this suggests that most components are simple. However, these single-edge components contribute only 46.6% of all linkage edges, meaning that the remaining 10.6% of components carry more than half of the reconstructed edges. The largest component contains 35 deposit addresses, 59 withdrawal recipients, and 644 linkage edges. The graph therefore has a head-simple, tail-complex pattern: simple components dominate the count, *but a small number of dense components carry disproportionate investigative value*.![Component edge count distribution](../figs/png/component_edge_count_distribution.png)

**Figure 2.** Distribution of linkage edges per pool-level connected component. This plot does not measure cross-pool behavior; it measures how many linked deposit-withdrawal edges appear inside each pool-level component.

#### Temporal Behavior Around Tornado Cash

We decompose timing behavior into three stages: pre-TC funding, in-pool waiting, and post-withdrawal release. The pre-TC stage measures how long funds stay around the deposit address before entering Tornado Cash. The in-pool stage measures the time gap between matched deposit and withdrawal events within the same pool. The post-withdrawal stage measures how long the withdrawal recipient holds funds before releasing them to private downstream counterparties. This decomposition separates last-hop urgency from broader operational timing, which is important because a short final transfer into TC does not imply that the full funding process was short.

Pre-TC funding exhibits two different time scales: a short last-hop gap and a much longer funding-span approximation. The median `recent_in_gap` is 17.2 hours, and over half of samples enter TC within 24 hours of the most recent incoming ETH transfer. This shows that many deposit addresses move quickly after receiving their last incoming transfer. In contrast, the value-based `funding_span_approx`, which scans backward until incoming transfers approximately cover the TC deposit amount (see Appendix A.3 for the formulation), has a median of 2,305.4 hours, or about 96 days; 75% of samples exceed 4 days. Fig. 3 visualizes this longer preparation window. The contrast indicates that last-hop urgency and full funding preparation capture different behaviors: *the final step into TC may be fast even when the funds were accumulated or staged over a much longer period*.

![Funding span approximation distribution](../figs/png/timing_funding_span_approx_distribution.png)

The in-pool waiting time remains long even under a conservative ordered temporal matching approximation. For each linked `(deposit address, withdrawal recipient, pool)` context, we match deposit and withdrawal events in temporal order, allowing only pairs where the deposit precedes the withdrawal, maximizing the number of matched pairs and then minimizing total waiting time (see Appendix A.4 for the formulation). This avoids interpreting all possible event combinations as separate flows. Under this approximation, the median `temporal_matching_gap` is 944.0 hours, or about 39.3 days, and 75% of matched samples exceed 6 days. As shown in Fig. 4, the distribution is not concentrated near zero. *Tornado Cash therefore appears not only as a topological link-breaking mechanism but also as a temporal buffer that separates deposit and withdrawal activity over weeks or months.*

![Temporal matching gap distribution](../figs/png/timing_temporal_matching_gap_distribution.png)

**Figure 4.** In-pool dwell time estimated by ordered temporal bipartite matching.

Post-withdrawal release is also delayed, indicating that the withdrawal recipient often acts as a temporary holding address rather than an immediate final destination. Among samples with observed release behavior, the median `first_out_gap` is 2,425.6 hours, or about 101 days. The median `half_release_gap` is 3,554.9 hours, or about 148.1 days, and the median `full_release_gap` is 4,159.0 hours, or about 173.2 days. Among completed release samples, 75% take more than 9 days to approximately release the full withdrawn amount. Fig. 5, Fig. 6, and Fig. 4 show the three release views. *These results imply that TC usage creates a temporal buffer before, inside, and after the mixer, and that the temporal buffer around TC extends beyond the mixer itself: funds may be staged before deposit, delayed inside the pool, and then held again after withdrawal.*

![First out gap distribution](../figs/png/timing_first_out_gap_distribution.png)

**Figure 5.** Time from TC withdrawal receipt to the first observed outgoing ETH transfer.



![Half release gap distribution](../figs/png/timing_half_release_gap_distribution.png)

**Figure 6.** Time until 50% of the withdrawn amount is released.

![Full release gap distribution](../figs/png/timing_full_release_gap_distribution.png)

**Figure 7.** Time until the full withdrawn amount is released.

#### One-Hop Private Counterparty Neighborhoods

Time analysis explains "how long the money waited," while counterparty analysis explains "where the money went." Based on the results, the post-withdrawal release path is often narrow even when the address-level neighborhood is broader. Deposit addresses and withdrawal recipients each have a median of five filtered upstream or downstream counterparties at the address-history level. However, the release-level `outflow_counterparty_count` (see Appendix A.5 for the formal definition) has a median of one: 70% of withdrawal events touch at most one downstream counterparty during the release scan, 80% touch at most four, and 90% touch at most ten. Fig. 8, Fig. 9, and Fig. 10 show the three breadth distributions. *This distinction is important: an address may have a broader historical neighborhood, but the funds released after a specific TC withdrawal often move through a small number of downstream targets.*

![Filtered upstream breadth](../figs/png/counterparty_filtered_upstream_breadth_distribution.png)

**Figure 8.** Number of filtered private upstream counterparties for deposit addresses.

![Filtered downstream breadth](../figs/png/counterparty_filtered_downstream_breadth_distribution.png)

**Figure 9.** Number of filtered private downstream counterparties for withdrawal recipients.

![Release outflow breadth](../figs/png/counterparty_release_outflow_breadth_distribution.png)

**Figure 10.** Number of unique downstream counterparties observed during post-withdrawal release scans.

Value concentration reinforces the same conclusion: *post-TC flows often go to a small number of economically dominant counterparties.* The median downstream top-1 share is 82.4% (see Appendix A.6 for the top-k and HHI formulation), and the median downstream top-3 share reaches 100%. The upstream side is also concentrated, with a median top-1 share of 70.8% and a median top-3 share of 99.9%, but downstream concentration is stronger. The median downstream HHI is 0.704, compared with 0.560 on the upstream side. Fig. 11 through Fig. 16 show these concentration views. Together, breadth and concentration suggest that TC may break the direct deposit-withdrawal link, but the local post-withdrawal neighborhood often remains focused enough to support downstream investigation.

![Upstream HHI distribution](../figs/png/counterparty_upstream_hhi_distribution.png)

**Figure 11.** Upstream value concentration measured by HHI.

![Downstream HHI distribution](../figs/png/counterparty_downstream_hhi_distribution.png)

**Figure 12.** Downstream value concentration measured by HHI.

![Upstream top1 share distribution](../figs/png/counterparty_upstream_top1_share_distribution.png)

**Figure 13.** Upstream top-1 value share.

![Downstream top1 share distribution](../figs/png/counterparty_downstream_top1_share_distribution.png)

**Figure 14.** Downstream top-1 value share.

![Upstream top3 share distribution](../figs/png/counterparty_upstream_top3_share_distribution.png)

**Figure 15.** Upstream top-3 value share.

![Downstream top3 share distribution](../figs/png/counterparty_downstream_top3_share_distribution.png)

**Figure 16.** Downstream top-3 value share.

#### Conclusions

The reconstructed linkage dataset suggests a more nuanced view of Tornado Cash than either "the mixer erases all traceability". The empirical signal is redistributed across three layers: graph structure, time, and local private neighborhoods. Structurally, many links are simple, but a small tail of components is highly organized. Temporally, funds are buffered before, inside, and after the mixer. Locally, post-withdrawal flows often remain narrow and value-concentrated. The central implication is that TC weakens direct transaction continuity, but it does not necessarily erase operational continuity around the mixer.

The most distinctive behavioral signal is that traceability often shifts from the broken deposit-withdrawal edge to the timing and neighborhood around the withdrawal recipient. On the neighborhood side, the downstream flow is frequently not diffuse: the median `outflow_counterparty_count` is one, 70% of release scans touch at most one downstream counterparty, and the median downstream top-3 value share is 100%. This pattern is better described as a post-mixer funnel than as immediate broad dispersion, meaning that a reconstructed withdrawal recipient can remain useful even when the exact in-pool path is uncertain. On the timing side, TC behaves as a latency stack rather than only a topological mixer. The short median `recent_in_gap` indicates that many addresses deposit soon after their last incoming transfer, but the much longer `funding_span_approx` shows that the value needed for a deposit may have been assembled over roughly 100 days at the median. Inside the pool, ordered temporal matching still gives a median dwell time of about 40 days; after withdrawal, completed full-release samples have a median release gap of about 173 days. Thus, the relevant investigative question is not only which deposit may correspond to which withdrawal, but also how value was staged, hidden, and released around the mixer.

These results also show why the component, rather than the individual edge alone, is the appropriate unit for understanding high-value TC linkage evidence. A typical component can look simple, but the investigative signal is concentrated in the tail: 89.4% of pool-level components contain only one linkage edge, yet single-edge components account for only 46.6% of all linkage edges, and the largest component contains 644 edges. The simple head is useful for direct endpoint analysis, whereas the dense tail may expose repeated use, role reuse, and shared counterparties. 

## Appendix A. Formal Definitions of Metrics

This appendix gives the exact notation and metric definitions used in the empirical section. All timestamps are standardized UTC block timestamps, and all reported time gaps are timestamp differences converted to hours for plotting and summary statistics. Unless otherwise stated, one-hop histories are computed in the filtered private ETH interaction subgraph, where public service addresses and high-degree public infrastructure are removed. Value-based scans use only ETH transfer `value`. We do not subtract ordinary historical gas fees because the purpose is to measure behavioral timing around TC value movement, not to reconstruct exact account balances.

### A.1 Basic Notation

| Symbol          | Meaning                                                      |
| --------------- | ------------------------------------------------------------ |
| $p$             | A Tornado Cash pool, identified by denomination.             |
| $D$             | A deposit address.                                           |
| $W$             | A withdrawal recipient address.                              |
| $d,w$           | Concrete deposit-side and withdrawal-side vertices in a linkage graph. |
| $a$             | A generic address.                                           |
| $e$             | A TC event or a linkage edge, depending on context.          |
| $c=(D,W,p)$     | A linked deposit-withdrawal context in one pool.             |
| $C$             | A connected component in a pool-level or folded linkage graph. |
| $u$             | A filtered upstream counterparty of a deposit address.       |
| $v$             | A filtered downstream counterparty of a withdrawal recipient. |
| $t_e$           | Timestamp of event $e$.                                      |
| $a_e$           | ETH amount of event $e$.                                     |
| $H_a$           | Filtered ETH history of address $a$.                         |
| $H_D^{<e}$      | Filtered ETH history of deposit address $D$ before event $e$. |
| $\mathcal{D}_c$ | Deposit events associated with context $c$.                  |
| $\mathcal{W}_c$ | Withdrawal events associated with context $c$.               |
| $S_a$           | Counterparty set of address $a$, either upstream or downstream depending on side. |


### A.2 Linkage Graph and Structural Classes

For each pool $p$, we construct a bipartite graph:

$$
G_p=(V_D^p \cup V_W^p, E_p),
$$

where $V_D^p$ is the set of deposit addresses, $V_W^p$ is the set of withdrawal recipients, and

$$
(d,w)\in E_p
$$

if the linkage table contains a high-confidence clue between $d$ and $w$ in pool $p$. The pool-specific deposit-side and withdrawal-side degrees are:

$$
\deg_D(d;p)=|\{w:(d,w)\in E_p\}|,
$$

$$
\deg_W(w;p)=|\{d:(d,w)\in E_p\}|.
$$

Each linkage edge is assigned to one structural class:

$$
\mathrm{class}(d,w,p)=
\begin{cases}
\text{1-to-1}, & \deg_D(d;p)=1 \land \deg_W(w;p)=1,\\
\text{1-to-many}, & \deg_D(d;p)>1 \land \deg_W(w;p)=1,\\
\text{many-to-1}, & \deg_D(d;p)=1 \land \deg_W(w;p)>1,\\
\text{many-to-many}, & \deg_D(d;p)>1 \land \deg_W(w;p)>1.
\end{cases}
$$

Pool-level connected components are computed on $G_p$. Folded cross-pool components are computed after collapsing pool labels and connecting addresses that co-occur through any pool-level linkage edge.

### A.3 Pre-TC Funding Metrics

For a TC deposit event

$$
e=(D,p,t_e,a_e),
$$

let $H_D^{<e}$ denote filtered ETH transfers involving $D$ before $t_e$. The recent-in gap measures the last observed incoming ETH transfer before the TC deposit:

$$
\Delta_{\mathrm{recent}}(e)
=t_e-\max\{t_i:i\in H_D^{<e},\ direction_i=\mathrm{in}\}.
$$

The funding-span approximation uses a value-based backward scan. Initialize the remaining amount to cover:

$$
R_0=a_e.
$$

Scanning backward from $t_e$, update the remaining amount by:

$$
R \leftarrow R+value_i \quad \text{if } direction_i=\mathrm{out},
$$

$$
R \leftarrow R-value_i \quad \text{if } direction_i=\mathrm{in}.
$$

The scan stops when $R\le 0$ or the available history is exhausted. Let $F_e$ be the set of incoming transfers included before the stop condition. The funding-span approximation is:

$$
\Delta_{\mathrm{funding}}(e)
=t_e-\min_{i\in F_e} t_i.
$$

### A.4 In-Pool Dwell-Time Metrics

For a linked context $c=(D,W,p)$, let

$$
\mathcal{D}_c=\{d_i=(t_i^D,tx_i^D)\}_{i=1}^{m}
$$

be the TC deposit events of $D$ in pool $p$, and let

$$
\mathcal{W}_c=\{w_j=(t_j^W,tx_j^W)\}_{j=1}^{n}
$$

be the TC withdrawal events received by $W$ in the same pool. We only allow temporally valid pairs with $t_i^D<t_j^W$.

The candidate gap enumerates all valid deposit-withdrawal event pairs:

$$
\Delta_{\mathrm{candidate}}(i,j)=t_j^W-t_i^D,\quad t_i^D<t_j^W.
$$

The nearest-forward gap assigns each withdrawal event to its closest preceding deposit event:

$$
i^*(j)=\arg\max_i\{t_i^D:t_i^D<t_j^W\},
$$

$$
\Delta_{\mathrm{nearest}}(j)=t_j^W-t_{i^*(j)}^D.
$$

The temporal bipartite matching gap approximates event-level pairing under ordering constraints. Let

$$
M=\{(i_k,j_k)\}_{k=1}^{K}
$$

be a matching such that

$$
i_1<i_2<\cdots<i_K,\quad j_1<j_2<\cdots<j_K,\quad t_{i_k}^D<t_{j_k}^W.
$$

We choose $M$ lexicographically: first maximize the number of matched pairs, then minimize total waiting time:

$$
\max |M|,\quad \min_M \sum_{(i,j)\in M}(t_j^W-t_i^D).
$$

The metric values are the gaps induced by the selected matching:

$$
\Delta_{\mathrm{temporal}}(i,j)=t_j^W-t_i^D,\quad (i,j)\in M.
$$

This matching avoids the combinatorial inflation of all-pairs candidate gaps while preserving event order.

### A.5 Post-Withdrawal Release Metrics

For a TC withdrawal event

$$
e=(W,p,t_e,a_e),
$$

we scan the filtered ETH history of $W$ after $t_e$. Initialize:

$$
R_0=a_e.
$$

For each transfer after the withdrawal:

$$
R \leftarrow R-value_i \quad \text{if } direction_i=\mathrm{out},
$$

$$
R \leftarrow R+value_i \quad \text{if } direction_i=\mathrm{in}.
$$

The first-out gap is:

$$
\Delta_{\mathrm{first\_out}}(e)=t_{\mathrm{first\ out}}-t_e.
$$

The half-release approximation is:

$$
\Delta_{\mathrm{half}}(e)=\min\{t-t_e:R_t\le a_e/2\}.
$$

The full-release approximation is:

$$
\Delta_{\mathrm{full}}(e)=\min\{t-t_e:R_t\le 0\}.
$$

The release-level downstream breadth is:

$$
\mathrm{outflow\_counterparty\_count}(e)
=|\{v: W\to v \text{ during the release scan}\}|.
$$

If the scan reaches the observation boundary before $R_t\le 0$, $\Delta_{\mathrm{full}}$ is undefined and the sample is marked as not fully released. Therefore, summaries of `full_release_gap_approx` are interpreted over completed release samples only.

### A.6 One-Hop Counterparty Breadth and Concentration

For a deposit address $D$, the filtered upstream set is:

$$
U_D=\{u:u\to D \text{ in the filtered ETH history}\},
$$

and the upstream breadth is:

$$
\mathrm{filtered\_upstream\_count}(D)=|U_D|.
$$

For a withdrawal recipient $W$, the filtered downstream set is:

$$
V_W=\{v:W\to v \text{ in the filtered ETH history}\},
$$

and the downstream breadth is:

$$
\mathrm{filtered\_downstream\_count}(W)=|V_W|.
$$

For either upstream or downstream counterparties, let $x_i$ be the cumulative ETH value associated with counterparty $i$ and let

$$
X=\sum_i x_i.
$$

The Herfindahl-Hirschman Index is:

$$
\mathrm{HHI}=\sum_i\left(\frac{x_i}{X}\right)^2.
$$

The top-$k$ value share is:

$$
\mathrm{TopK}=\frac{\sum_{i\in \mathrm{largest}\ k}x_i}{X}.
$$

Large HHI and top-$k$ values indicate that an address's private one-hop flow is economically dominated by a small number of counterparties.
