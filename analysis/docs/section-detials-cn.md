# Tornado Cash Linkage Empirical Analysis 细节

## 1. 这一节应该讲什么故事

Tornado Cash 的核心设计目标是切断 deposit address 和 withdrawal recipient 之间的显式链上联系。传统叙事往往把这种切断理解成一个瞬时动作：资金进入 mixer，经过一段匿名池，随后从另一个地址流出。但我们基于高置信度 linkage dataset 的实证结果显示，真实使用模式并不只是“进池”和“出池”两个点。下文用 $D$ 表示 deposit address，用 $W$ 表示 withdrawal recipient；在这个口径下，一条被 TC 打断但由 linkage 恢复的局部操作链可以写成：

$$
\text{private upstream} \rightarrow D \rightarrow \text{TC pool} \rightarrow W \rightarrow \text{private downstream}
$$

这条链条强调的是分析视角：我们不只观察 TC deposit 和 withdrawal 两个事件点，也同时观察它们前后的 private upstream 和 private downstream 交互。论文这一节可以围绕三个核心发现展开。

第一，结构上，TC 使用既有大量简单端对端 component，也有少量但非常重要的复杂多地址 component。换言之，dataset 的“数量中心”是简单的，但“调查价值中心”在复杂尾部。

第二，时间上，TC 并不只是一个瞬时匿名跳板。资金在入池前、池内、出池后都可能经历显著滞留。TC 在实践中同时充当地址断链工具和时间缓冲层。

第三，资金流上，即使 TC 打断了 $D$ 与 $W$ 的直接关联，$W$ 后的一跳释放路径往往仍然很窄、金额也高度集中。这意味着 linkage dataset 对真实调查仍然有实际价值：它不仅恢复了被 mixer 隐藏的 $D-W$ 关系，也提供了继续追踪的下游入口。

这三个发现可以组织成一条完整叙事：

$$
\text{who is linked} \rightarrow \text{how long funds wait} \rightarrow \text{where funds remain traceable}
$$

## 2. 数据和解释边界

当前 run 的基础规模如下。

| 对象                         |   数量 |
| ---------------------------- | -----: |
| linked clue rows             | 10,853 |
| TC deposit events            | 33,135 |
| TC withdrawal events         | 73,807 |
| pool-level linked components |  5,714 |
| folded cross-pool components |  4,902 |

论文写作时需要保留三个解释边界。这里的“边界”不应写成被动限制，而应写成主动的方法设计：它们让分析更贴近 TC 的隐私机制、更适合识别实体控制的地址簇，并且降低 reviewer 对过度解释的质疑。

第一，上下游和生命周期指标都发生在“公共地址交互已剔除的过滤子图”中。这是为了让 fan-in/fan-out、归集/分散和共享对手方分析更接近实体控制地址簇，而不是被公共服务地址污染。交易所、桥、DeFi 合约、矿池或大型服务地址会自然连接大量无关用户；如果不剔除这些地址，`filtered_upstream_count` 和 `filtered_downstream_count` 会被机械放大，component-level shared counterparty 也会产生虚假的共同控制信号。过滤公共地址后，我们分析的是 private counterparty neighborhood：它更适合观察非公共地址之间的资金组织、归集入口、释放路径和协同操作。因此这里的上游和下游不是完整以太坊全图上的全部交易对象，而是为了行为解释而构造的去公共地址局部视图。

第二，本轮所有资金准备和释放时间都是 value-based approximation。这个选择的目的不是逃避精确余额问题，而是让跨样本的时间指标保持一致、透明和可复现。本文要回答的是资金何时进入 deposit address、何时进入 TC、何时从 withdrawal recipient 释放，而不是逐交易精确余额审计。普通 gas fee 相对 0.1/1/10/100 ETH pool 面额通常较小；若强行纳入 gas，则需要额外 receipt 级数据，并可能因为不同交易类型和内部转账口径引入新的估算误差。因此，基于 ETH `value` 的 backward funding scan 和 forward release scan 是与本文行为分析目标相匹配的近似。正式论文中仍应把 `funding_span_approx`、`half_release_gap_approx`、`full_release_gap_approx` 写成近似资金准备/释放时间，而不是严格余额清算时间。

### 2.1 记号表

后文公式会在各自段落中定义具体指标，例如 $\Delta_{\mathrm{recent}}$、$\mathrm{HHI}$、$\mathrm{TopK}$、$\mathrm{shared\_pair\_ratio}$ 等。下表只列出这些公式共同依赖的底层记号，方便读者在进入指标定义前先理解符号含义。

| 记号            | 含义                                                 | 说明                                                         |
| --------------- | ---------------------------------------------------- | ------------------------------------------------------------ |
| $p$             | Tornado Cash pool                                    | 本文中 pool 与 denomination 对应，例如 0.1/1/10/100 ETH pool。 |
| $D$             | deposit address                                      | 发起或承载 TC deposit 的地址；在不同公式中可表示一个具体地址。 |
| $W$             | withdrawal recipient                                 | TC withdrawal 中实际收到 ETH 的 recipient address，不是 relayer 或 caller。 |
| $d,w$           | 图结构中的具体 deposit/withdrawal 地址               | 常用于表示二部图中的一个具体地址对。                         |
| $a$             | 泛指任意地址                                         | 用于跨池复用、角色统计或生命周期公式。                       |
| $e$             | 局部上下文中的 event 或 edge                         | 若 $e=(d,w,p)$，表示图中的 linkage edge；若 $e=(D,p,t_e,a_e)$，表示某次 TC event。 |
| $c$             | linkage clue 或地址对上下文                          | 常写作 $c=(D,W,p)$，表示同一 pool 下的一个 deposit-withdrawal linkage context。 |
| $C$             | connected component                                  | pool-level 或 folded cross-pool linkage graph 中的连通分量；具体上下文会说明是哪一种图。 |
| $u$             | upstream counterparty                                | 在过滤 ETH 子图中向 deposit address 转入 ETH 的非公共对手方。 |
| $v$             | downstream counterparty                              | 在过滤 ETH 子图中从 withdrawal address 接收 ETH 的非公共对手方。 |
| $t$             | 时间戳                                               | 所有时间均来自标准化后的 UTC block timestamp。               |
| $t_e$           | event $e$ 的时间戳                                   | 常用于某次 deposit 或 withdrawal event。                     |
| $a_e$           | event $e$ 的 ETH 金额                                | 常用于某次 deposit/withdrawal 的 value-based scan。          |
| $t_i$           | 第 $i$ 条历史交易的时间戳                            | 用于地址历史交易扫描。                                       |
| $value_i$       | 第 $i$ 条历史交易的 ETH 金额                         | 只考虑 ETH transfer value，不扣除普通历史交易 gas。          |
| $direction_i$   | 第 $i$ 条历史交易方向                                | 取值为 `transfer_in` 或 `transfer_out`。                     |
| $tx$            | transaction hash                                     | 用于区分 TC event 或历史交易记录。                           |
| $H$             | 某地址的过滤 ETH 历史交易集合                        | 已剔除公共地址交互，只保留当前分析口径下的 ETH history。     |
| $H_D^{<e}$      | deposit address $D$ 在 event $e$ 之前的过滤 ETH 历史 | 用于入池前 funding scan。                                    |
| $TC\_hashes$    | 某地址相关 TC event 的 transaction hash 集合         | 用于计算 single-purpose score。                              |
| $\mathcal{D}_c$ | clue $c$ 对应的 deposit event 序列                   | 同一 $D-W-pool$ 下的 deposit events。                        |
| $\mathcal{W}_c$ | clue $c$ 对应的 withdrawal event 序列                | 同一 $D-W-pool$ 下的 withdrawal events。                     |
| $S_a$           | 地址 $a$ 的对手方集合                                | 在存款侧可表示 upstream set，在取款侧可表示 downstream set。 |
| $roles(a)$      | 地址 $a$ 在 linkage graph 中出现过的角色集合         | 可能包含 `deposit`、`withdraw` 或二者。                      |
| $i,j,k$         | 索引                                                 | 用于枚举历史交易、deposit/withdrawal events 或匹配对。       |
| $\mu,\sigma$    | 均值与标准差                                         | 用于 burstiness 计算中的 interarrival statistics。           |

## 3. 第一层故事：简单边很多，但复杂 component 承载了大量调查价值

### 3.1 Pool 内二部图如何构造

对每个 pool $p$，我们构造一个二部图：

$$
G_p=(D_p \cup W_p, E_p)
$$

其中 $D_p$ 是该 pool 中出现过的 deposit addresses，$W_p$ 是该 pool 中出现过的 withdrawal recipient addresses。若存在一条 linkage clue $(d,w,p)$，则加入一条边：

$$
e=(d,w,p)\in E_p
$$

对边两端定义 pool 内度数：

$$
\mathrm{outdeg}(d,p)=|\{w:(d,w,p)\in E_p\}|
$$

$$
\mathrm{indeg}(w,p)=|\{d:(d,w,p)\in E_p\}|
$$

然后每条 edge 按度数划分为四类：

| 类别           | 判定条件                             | 论文解释                                                     |
| -------------- | ------------------------------------ | ------------------------------------------------------------ |
| `1-to-1`       | $\mathrm{outdeg}=1,\mathrm{indeg}=1$ | 单一 deposit address 与单一 withdrawal address 关联          |
| `1-to-many`    | $\mathrm{outdeg}>1,\mathrm{indeg}=1$ | 一个 deposit address 对应多个 withdrawal recipients，偏向资金分散 |
| `many-to-1`    | $\mathrm{outdeg}=1,\mathrm{indeg}>1$ | 多个 deposit addresses 对应同一 withdrawal recipient，偏向资金归集 |
| `many-to-many` | $\mathrm{outdeg}>1,\mathrm{indeg}>1$ | 两侧都有多地址参与，偏向复杂协同或批处理                     |

![Linked edge structure share](../figs/png/structure_class_share_pie.png)

**图 1. Pool 内 linkage edge 的结构类型占比。**

这张图的第一层信息很直接：`1-to-1` 占 46.6%，接近一半。它说明高置信 linkage 中确实存在大量端对端形态，即一个 deposit address 只对应一个 withdrawal recipient，并且该 withdrawal recipient 也只对应这个 deposit address。在论文中，这一点可以用来支持 dataset 的可解释性：许多 linkage 不是只能在复杂图中间接理解，而是可以作为简单、直观的关联边来阅读。

但真正值得展开的是第二层信息：`many-to-many` 占 38.5%。这不是极少数异常，而是接近四成的 edges。它说明大量资金行为发生在多地址互相连接的局部结构中。如果只把 TC 使用者想象成“一个人用一个地址存款，再用另一个地址取款”，就会低估真实操作的组织性。更合理的说法是：TC 使用者呈现双峰结构，一端是简单端对端使用，另一端是多地址协同使用。

这种结构结果可以引出论文中的第一个重要论点：

$$
\text{TC linkage graph is numerically simple but operationally heterogeneous.}
$$

用中文表达就是：TC linkage graph 在 component 数量上以简单结构为主，但在操作模式上高度异质。

### 3.2 连通分量：为什么“少数大 component”比数量占比更重要

对每个 pool-level connected component $C$，定义它包含的 linkage edge 数：

$$
\mathrm{edge\_count}(C)=|\{(d,w,p)\in E_p:d\in C,w\in C\}|
$$

![Component edge count distribution](../figs/png/component_edge_count_distribution.png)

**图 2. Pool-level connected component 中 linkage edge 数量的分布。**

这张图容易被误读，所以论文准备阶段要把口径讲清楚。横轴不是 pool 数量，也不是地址数量，而是同一个 pool-level connected component 中包含多少条 $D-W$ linkage edge。由于这个图本身是按 pool 构建的，因此不能用它说明“是否跨多个 TC pool”。跨池复用要看 folded cross-pool graph。

当前结果为：超过五千个 pool-level components 中，89.4% 只有一条 edge，95.8% 不超过两条 edge，中位 edge count 为 1。这说明绝大多数 component 非常小。如果从 component 数量看，TC linkage dataset 的主体确实是简单结构。

但是，单边 components 只贡献了 46.6% 的 total edges。也就是说，剩余 10.6% 的 components 承载了超过一半的 linkage edges。最大 component 包含 35 个 deposit addresses、59 个 withdrawal addresses 和 644 条 edges。这种分布非常适合写成 head-tail story：

$$
\text{many small components} \quad + \quad \text{few dense operational clusters}
$$

这比单纯说“1-to-1 占比接近一半”更有论文价值。它提示我们：如果论文目标只是证明 linkage 方法能恢复 $D-W$ 边，那么小 component 足够说明问题；但如果目标是展示 dataset 的调查价值，那么大 component 才是重点，因为它们揭示的是地址簇、操作链条和批处理组织。

可以写入论文的解释：

> Although most connected components contain only one linkage edge, a small number of large components account for a disproportionate share of all reconstructed edges. This head-simple, tail-complex pattern suggests that Tornado Cash usage includes both isolated transfers and organized multi-address operations.

## 4. 第二层故事：TC 是地址断链工具，也是时间缓冲层

时间分析是这组图最适合讲故事的部分。它可以把 TC 使用从一个静态 graph 问题变成一个动态资金生命周期问题。我们将每条资金链拆成三段：

$$
\text{pre-TC funding} \rightarrow \text{in-pool waiting} \rightarrow \text{post-TC release}
$$

这三段分别回答三个问题：

| 阶段   | 问题                                           | 核心指标                                                     |
| ------ | ---------------------------------------------- | ------------------------------------------------------------ |
| 入池前 | 资金进入 deposit address 后多久进入 TC？       | `recent_in_gap`, `dominant_inflow_gap`, `funding_span_approx` |
| 池内   | deposit event 和 withdrawal event 之间隔多久？ | `candidate_gap`, `nearest_forward_gap`, `temporal_matching_gap`, `window_overlap` |
| 出池后 | withdrawal recipient 收到 ETH 后多久释放？     | `first_out_gap`, `half_release_gap_approx`, `full_release_gap_approx` |

### 4.1 入池前：最近一跳可以很急，但完整准备周期很长

对某次 TC deposit event $e=(D,p,t_e,a_e)$，令 $H_D^{<e}$ 表示 deposit address $D$ 在 $t_e$ 前的过滤 ETH 历史。

最近入账间隔定义为：

$$
\Delta_{\mathrm{recent}}(e)=t_e-\max\{t_i:i\in H_D^{<e}, direction_i=\mathrm{in}\}
$$

这个指标回答的是：地址是否刚收到钱就进入 TC。

但最近一笔入账并不一定覆盖 pool 面额，也不一定代表主要资金来源。因此我们进一步使用 value-based backward scan。初始化剩余待覆盖金额：

$$
R_0=a_e
$$

从 $t_e$ 向前扫描历史交易，遇到转出则增加待覆盖金额，遇到转入则减少待覆盖金额：

$$
R \leftarrow R+value_i \quad \text{if } direction_i=\mathrm{out}
$$

$$
R \leftarrow R-value_i \quad \text{if } direction_i=\mathrm{in}
$$

直到 $R\le 0$ 或历史耗尽。若纳入的入账集合为 $F_e$，则 funding span 为：

$$
\Delta_{\mathrm{funding\_span}}(e)=t_e-\min_{i\in F_e}t_i
$$

dominant inflow gap 使用同一 funding window 中金额最大的入账：

$$
i^*=\arg\max_{i\in F_e}value_i,\qquad
\Delta_{\mathrm{dominant}}(e)=t_e-t_{i^*}
$$

![Funding span approximation distribution](../figs/png/timing_funding_span_approx_distribution.png)

**图 3. 入池前 value-based funding span 的分布。**

结果给出一个很适合写入论文的反差。`recent_in_gap` 的中位数只有 17.2 小时，超过一半的样本在 24 小时内进入 TC。这个结果支持“部分操作具有急迫性”的直觉。

但是 `funding_span_approx` 的中位数达到 2305.4 小时，约 96 天；75% 的样本超过 4 天。也就是说，如果只看最近一笔入账，容易得出“资金很快进入 TC”的结论；但如果追问“凑齐这次 TC 存款金额的资金窗口有多长”，就会看到一个更长的准备周期。

这可以形成一个新颖解释：TC 入池前存在两种时间尺度。

$$
\text{last-hop urgency} \ne \text{full funding preparation}
$$

现实意义是，很多 deposit address 可能在最后一跳显得很急，但其背后资金来源早已在地址附近积累。这类行为更像是“长期准备后的集中入池”，而不是“临时收到资金后立即混币”。论文中可以用它来回应 reviewer 对滞留时间口径的质疑：我们不是只用最近一笔入账，而是同时提供 dominant inflow 和 funding span 两个更稳健的近似口径。

### 4.2 池内：即使用更严格的事件匹配，等待时间仍然很长

对一条 clue $c=(D,W,p)$，令同一 pool 下的 deposit event 序列为：

$$
\mathcal{D}_c=\{d_i=(t_i^D,tx_i^D)\}
$$

withdrawal event 序列为：

$$
\mathcal{W}_c=\{w_j=(t_j^W,tx_j^W)\}
$$

所有池内 gap 都要求：

$$
t_i^D<t_j^W
$$

最宽的口径是 candidate gap，枚举所有合法组合：

$$
\Delta_{\mathrm{candidate}}(i,j)=t_j^W-t_i^D
$$

更保守的口径是 nearest forward gap，对每个 withdrawal 找最近的前序 deposit：

$$
i^*(j)=\arg\max_i\{t_i^D:t_i^D<t_j^W\}
$$

$$
\Delta_{\mathrm{nearest}}(j)=t_j^W-t_{i^*(j)}^D
$$

最适合写入正文的是 temporal bipartite matching gap。我们在时间排序的 deposit 和 withdrawal 序列之间寻找有序匹配集合 $M$：

$$
M=\{(i_k,j_k)\}_{k=1}^{K}
$$

满足：

$$
i_1<i_2<\cdots<i_K,\quad j_1<j_2<\cdots<j_K,\quad t_{i_k}^D<t_{j_k}^W
$$

优化目标是先最大化匹配数，再最小化总等待时间：

$$
\max |M|,\qquad \min \sum_{(i,j)\in M}(t_j^W-t_i^D)
$$

![Temporal matching gap distribution](../figs/png/timing_temporal_matching_gap_distribution.png)

**图 4. 有序二部匹配得到的 TC 池内等待时间分布。**

这张图可以作为 paper 中“池内等待时间”的主图。原因是它比 candidate gap 更克制，也比 nearest forward gap 更像事件级一对一近似。当前结果显示，`temporal_matching_gap` 的中位数为 944.04 小时，约 39.3 天；75% 的匹配样本超过 6 天。即使采用这种较严格的匹配，TC 池内等待仍然不是短时间现象。

这个结论在叙事上非常重要。许多读者可能默认 mixer 的使用是“存入后很快取出”。但结果显示，在高置信 linkage 中，大量资金在 TC pool 中对应的 deposit-withdrawal 时间差达到数周甚至数月。正式论文中可以把它写成：

$$
\text{TC anonymity is partly temporal, not only topological.}
$$

也就是，TC 的匿名性不只来自地址关系断开，也来自时间上的延迟和错位。

### 4.4 出池后：withdrawal recipient 往往继续承担暂存功能

对某次 withdrawal event $e=(W,p,t_e,a_e)$，从 $t_e$ 之后扫描 withdrawal address 的 filtered ETH history。初始化剩余金额：

$$
R_0=a_e
$$

遇到转出：

$$
R \leftarrow R-value_i
$$

遇到转入：

$$
R \leftarrow R+value_i
$$

首次释放时间为：

$$
\Delta_{\mathrm{first\_out}}=t_{\mathrm{first\ out}}-t_e
$$

半额释放时间为：

$$
\Delta_{\mathrm{half}}=\min\{t-t_e:R_t\le a_e/2\}
$$

近似全额释放时间为：

$$
\Delta_{\mathrm{full}}=\min\{t-t_e:R_t\le 0\}
$$

![First out gap distribution](../figs/png/timing_first_out_gap_distribution.png)

**图 5. Withdrawal recipient 首次向外转出 ETH 的时间。**

![Half release gap distribution](../figs/png/timing_half_release_gap_distribution.png)

**图 6. Withdrawal 后近似释放 50% 金额所需时间。**

![Full release gap distribution](../figs/png/timing_full_release_gap_distribution.png)

**图 7. Withdrawal 后近似释放全部金额所需时间。**

释放阶段的结果同样呈现长时间滞留。`first_out_gap` 的中位数为 2,425.6 小时，约 101 天；`half_release_gap_approx` 的中位数为 3,554.9 小时，约 148.1 天；`full_release_gap_approx` 的中位数为 4,159 小时，约 173.2 天。在完整释放样本中，75% 超过 9 天。

这个结果很适合和池内等待连在一起讲。资金离开 TC 并不意味着调查链条结束，也不意味着资金立即进入最终归宿。withdrawal recipient 往往继续扮演暂存、等待、分批释放的角色。这样，整个 TC 使用链条从“一个 mixer transaction”扩展成了“三段时间缓冲”：

$$
\underbrace{\Delta_{\mathrm{funding}}}_{\text{preparation}}
+\underbrace{\Delta_{\mathrm{matching}}}_{\text{in-pool waiting}}
+\underbrace{\Delta_{\mathrm{release}}}_{\text{post-withdrawal release}}
$$

正式论文中可以把这一段作为最重要的 behavioral finding：TC usage creates a temporal buffer before, inside, and after the mixer.

## 5. 第三层故事：TC 后路径并不一定扩散，释放通道常常很窄

时间分析解释“钱等了多久”，对手方分析解释“钱往哪里走”。这一部分可以直接服务于论文的 practical investigation value：即使 TC 隐藏了 deposit 和 withdrawal 的直接联系，withdrawal recipient 的一跳下游仍然常常给出清晰入口。

### 5.1 上下游地址数：地址级不孤立，但释放级很窄

对 deposit address $D$，定义过滤上游集合：

$$
U_D=\{u:\exists\ transfer\_in(u\to D)\}
$$

$$
\mathrm{filtered\_upstream\_count}(D)=|U_D|
$$

对 withdrawal address $W$，定义过滤下游集合：

$$
V_W=\{v:\exists\ transfer\_out(W\to v)\}
$$

$$
\mathrm{filtered\_downstream\_count}(W)=|V_W|
$$

对单次 withdrawal release，定义释放扫描过程中出现的唯一下游数：

$$
\mathrm{outflow\_counterparty\_count}(e)=|\{v:W\to v \text{ during release scan}\}|
$$

![Filtered upstream breadth](../figs/png/counterparty_filtered_upstream_breadth_distribution.png)

**图 8. Deposit address 的过滤上游对手方数量。**

![Filtered downstream breadth](../figs/png/counterparty_filtered_downstream_breadth_distribution.png)

**图 9. Withdrawal address 的过滤下游对手方数量。**

![Release outflow breadth](../figs/png/counterparty_release_outflow_breadth_distribution.png)

**图 12. 单次 withdrawal release 过程中的唯一下游数量。**

地址级 upstream 和 downstream count 的中位数都是 5。这说明这些地址在过滤私有子图中并不是完全孤立的一次性点，而是常常与多个私有对手方发生交互。

但 release-level 的 `outflow_counterparty_count` 中位数只有 1。70% 的 withdrawal events 在释放扫描中最多接触 1 个下游地址，80% 最多接触 4 个，90% 最多接触 10 个。这一结果比地址级 count 更适合讲调查价值，因为它关注的是“某次从 TC 出来的钱，在释放过程中实际触达多少下游”。

可以写成：

> The post-withdrawal release path is often narrow even when the recipient address has a broader historical neighborhood.

这个表述比“下游地址数量少”更准确。它承认地址历史可能复杂，但强调具体释放过程通常集中。

### 5.2 金额集中度：对手方可以不止一个，但大部分钱流向少数目标

对某个地址的对手方集合，令每个对手方累计金额为 $x_i$，总金额为：

$$
X=\sum_i x_i
$$

HHI 定义为：

$$
\mathrm{HHI}=\sum_i\left(\frac{x_i}{X}\right)^2
$$

top-k share 定义为：

$$
\mathrm{TopK}=\frac{\sum_{i\in \mathrm{largest}\ k}x_i}{X}
$$

![Upstream HHI distribution](../figs/png/counterparty_upstream_hhi_distribution.png)

**图 13. Deposit side upstream value concentration。**

![Downstream HHI distribution](../figs/png/counterparty_downstream_hhi_distribution.png)

**图 14. Withdrawal side downstream value concentration。**

![Upstream top1 share distribution](../figs/png/counterparty_upstream_top1_share_distribution.png)

**图 15. Upstream top-1 value share。**

![Downstream top1 share distribution](../figs/png/counterparty_downstream_top1_share_distribution.png)

**图 16. Downstream top-1 value share。**

![Upstream top3 share distribution](../figs/png/counterparty_upstream_top3_share_distribution.png)

**图 17. Upstream top-3 value share。**

![Downstream top3 share distribution](../figs/png/counterparty_downstream_top3_share_distribution.png)

**图 18. Downstream top-3 value share。**

集中度图给出了更强的故事：即使对手方数量不是极小，金额也高度集中。上游 top-1 share 的中位数为 70.8%，下游 top-1 share 的中位数为 82.4%；上游 top-3 share 的中位数为 99.9%，下游 top-3 share 的中位数为 100%。

这说明 TC 后资金并没有在一跳内随机扩散到大量目标，而是常常由一个或少数几个地址吸收。更重要的是，下游集中度比上游更强：downstream HHI 中位数为 0.704，高于 upstream HHI 的 0.560；downstream top-1 share 中位数为 82.4%，高于 upstream top-1 的 70.8%。这支持一个不对称解释：

$$
\text{pre-TC side: aggregation from several sources}
\quad \rightarrow \quad
\text{post-TC side: concentrated absorption}
$$

在论文中，这一点可以服务于调查价值：如果已经通过 linkage 找到 withdrawal recipient，那么后续最重要的资金流向通常集中在少数下游地址，而不是立刻不可追踪地扩散。
