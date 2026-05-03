# Tornado Cash 存取款特征提取与实证分析框架

## 1. 目标与已确认约束

本框架用于指导基于 Tornado Cash（TC）链接线索开展特征提取和实证分析，重点服务于论文中这部分叙事：

1. TC 用户或背后实体在存款前、池内等待、取款后分别表现出怎样的时间行为。
2. 已重建出的存取款链接在线索图上呈现出怎样的结构模式。
3. 这些链接如何帮助我们重建被 TC 打断的资金流局部结构，从而体现实际调查价值。

结合 [answers-tc-analysis-framework.md](xxx/docs/answers-tc-analysis-framework.md)，目前已经明确的约束如下：

1. 线索表中的 `withdraw_address` 明确指 TC withdrawal 的 `recipient`，不是 relayer，也不是发起 withdrawal 的 caller。
2. 线索表包含 `clue` 这种关联模式字段，但不把 `score` 当作置信度使用。
3. `pool_name` 已经给出固定的四类池子：`100ETH`、`10ETH`、`1ETH`、`0_1ETH`。在当前数据里，pool 和 denomination 可以视为同一个维度。
4. 存款/取款 raw 交易表以及地址历史交易表都包含 `internal transaction`，并且包含 `recipient` 收到 ETH 的那条内部转账记录。
5. 地址历史交易表是“摊平”的，可能同时混有 `external`、`internal` 和部分 ERC-20 transfer；现阶段只分析 `asset == ETH` 的记录。
6. 上游数据提供者已经剔除了所有与公共地址交互的交易，因此历史交易表更接近“去公共地址噪声之后的私有交互子图”。
7. 实验环境以 `ipynb` notebook 为主，适合先在 notebook 中完成数据清洗、特征提取、统计分析和可视化。

这些约束会直接影响分析口径。尤其是第 6 点非常重要：后续所有上游/下游、地址年龄、资金深度指标，都应被解释为“在去除了公共地址交互后的子图中观测到的结果”，而不是完整以太坊全图上的绝对结果。

## 2. 分析对象与解释边界

建议把分析对象组织成如下多层结构：

```text
过滤后的上游地址 U  ->  存款地址 D  ->  Tornado Cash Pool  ->  取款地址 W  ->  过滤后的下游地址 V
                                  \___________________________________________/
                                         已发现的 D-W 链接线索（同 pool 内）
```

后续分析分四个层级：

1. `transaction-level`：单条 ETH 转账记录或单次 TC 存款/取款事件。
2. `address-level`：单个存款地址或取款地址的行为特征。
3. `edge-level`：一个 `deposit_address -> withdraw_address` 线索对的联合特征。
4. `component-level`：链接图中一个连通分量的整体结构和行为。

这里需要明确一条解释边界，尤其对应此前未完全确定的第 8 个问题。

对于 `1-to-many`、`many-to-1`、`many-to-many` 结构，不建议在论文里把每一条边都表述为“逐笔资金已经被完全确证的一一映射关系”。更稳妥、也更符合数据事实的解释分三层：

1. `edge-level`：一条 `D-W` 边表示该存款地址与该取款地址之间存在高价值链接线索。
2. `component-level`：若多个地址通过线索连接成同一连通分量，则可以将其解释为“高概率由同一实体控制，或由同一操作链条紧密协调的一组地址”。
3. `narrative-level`：论文表述应优先使用“linked addresses”“associated address set”“likely common-control or coordinated-use cluster”，避免写成“所有地址都已被完全确认属于同一实体”的过强结论。

推荐在论文中采用如下保守表述：

> 我们将同一连通分量中的地址解释为高概率属于同一操作者或同一协调操作链条，而不将其中每一笔存取款自动视为已完成逐笔精确配对。

## 3. 实际输入数据与字段映射

当前可用输入不是抽象的四张理想表，而是五张实际 CSV 表。后续 framework 应以这五张表为准。

### 3.1 线索表

关键字段：

```text
id
pool_name
clue
deposit_address
withdraw_address
deposit_num
first_deposit_hash
first_deposit_timestamp
last_deposit_timestamp
withdraw_num
first_withdraw_hash
first_withdraw_timestamp
last_withdraw_timestamp
```

解释：

1. `pool_name` 是当前线索所属的 TC 池子。
2. `clue` 是主关联模式，可对应论文中的 `direct linkage`、`gas-funding linkage`、`transaction-intensity linkage`。
3. `deposit_num`、`withdraw_num` 是该地址在该 pool 下的存款/取款次数摘要。
4. `first_*`、`last_*` 字段适合做快速描述统计或一致性校验，但更细粒度的事件级分析应优先依赖 raw 存取款表。

现阶段不建议把 `score` 直接解释为模型置信度，也不需要使用 `total_usd_value`。

### 3.2 Raw 存款交易表

关键字段：

```text
pool_name
address_type
target_address
unique_id
block_num
block_timestamp
tx_hash
from_address
to_address
value
asset
category
gas_cost_ETH
transaction_index
```

解释：

1. `address_type` 固定为 `deposit_address`。
2. `target_address` 是该条记录对应的存款地址，通常与 `from_address` 相同。
3. `unique_id` 是事件级唯一标识，优先级高于 `tx_hash`。
4. `asset == ETH` 才进入当前分析范围。
5. 由于一笔链上交易可能在表中展开成多条记录，因此做事件聚合时要同时区分“记录级”和“交易级”。

### 3.3 Raw 取款交易表

字段与 raw 存款表基本一致。

关键解释：

1. `address_type` 固定为 `withdrawal_address`。
2. `target_address` 是取款地址，即 TC withdrawal 的 `recipient`。
3. 由于取款过程可能同时包含 external 和 internal 记录，后续构建“取款到账事件”时应优先定位 `to_address == target_address` 且 `asset == ETH` 的到账记录，而不是简单按 `tx_hash` 去重。

### 3.4 存款地址历史交易表

关键字段：

```text
address_type
target_address
unique_id
direction
block_num
block_timestamp
tx_hash
from_address
to_address
value
asset
category
```

解释：

1. `address_type` 固定为 `deposit_address`。
2. `target_address` 是该历史交易对应的存款地址。
3. `direction` 只有 `transfer_in` 和 `transfer_out` 两类。
4. 表中混有 `external`、`internal` 和部分 token transfer，因此必须先筛 `asset == ETH`。

### 3.5 取款地址历史交易表

字段与存款地址历史交易表一致。需要注意原始数据里 `address_type` 可能写成 `withdrawl_address`，导入时应统一规范为 `withdrawal_address`。

## 4. 预处理与数据建模建议

在 notebook 中，建议先完成一层稳定的数据标准化。后续所有特征都建立在这一层之上。

### 4.1 标准化原则

1. 时间字段统一解析为 `UTC datetime`。
2. 地址统一转小写。
3. `pool_name` 统一映射为数值面额：

```text
100ETH -> 100.0
10ETH  -> 10.0
1ETH   -> 1.0
0_1ETH -> 0.1
```

4. 所有分析默认先筛 `asset == ETH`。
5. `unique_id` 作为记录级主键，`tx_hash` 作为交易级主键。
6. `withdrawl_address` 统一纠正为 `withdrawal_address`。

### 4.2 事件构建原则

建议把线索表视为“摘要与索引表”，把 raw 存款表和 raw 取款表视为“事件锚点表”。

1. TC 存款事件优先从 raw 存款表构建。
2. TC 取款到账事件优先从 raw 取款表构建。
3. 线索表中的 `deposit_num`、`withdraw_num`、`first_*`、`last_*` 用于校验事件构建是否合理。

推荐构建两类中间表：

1. `deposit_events`

```text
pool_name, deposit_address, tx_hash, block_num, block_timestamp, value_eth
```

2. `withdraw_events`

```text
pool_name, withdraw_address, tx_hash, block_num, block_timestamp, value_eth
```

### 4.3 历史交易解释边界

由于历史交易表不包含完整 gas 信息，以下结论成立：

1. 可以做“基于 ETH 转账值”的资金到达、资金转出、资金年龄近似分析。
2. 不适合直接声称“精确重建了地址全历史余额轨迹”，因为普通历史交易的 gas 支出未被完整记录。
3. 如果后续确实需要严格余额模拟，需要再补充交易 receipt 或 gas 字段。

因此，原先框架里较强的 `sufficient_balance_gap`、`fifo_fund_age` 这类指标，在当前数据条件下应改成近似版本，或者作为后续增强项。

### 4.4 公共地址已剔除的影响

上游数据已经移除了所有与公共地址交互的交易，这会带来两个直接后果：

1. 上下游计数更聚焦于“非公共对手方”，有利于观察私有资金组织结构。
2. 但任何“地址年龄”“资金路径深度”“counterparty 总数”都不是完整链上绝对值，而是过滤子图中的观测值。

因此，后续涉及年龄和深度的指标建议显式加上 `filtered_` 前缀，避免过度解释。

## 5. 核心分析主线

基于当前数据条件，建议把实证分析集中到三条最稳的主线上：

```text
时间急迫性 + 结构组织方式 + 过滤子图中的资金流特征
```

其中：

1. 时间急迫性回答“资金进来后多久存，池内等多久，取出后多久走”。
2. 结构组织方式回答“地址之间是一对一、拆分、归集还是复杂协同”。
3. 过滤子图中的资金流特征回答“非公共对手方是如何在 TC 前后与这些地址发生交互的”。

## 6. 时间行为分析

### 6.1 存款地址内滞留时间

目标是衡量资金进入存款地址后，过了多久才被送入 TC：

```text
资金进入 D 的时间 -> D 发起 TC 存款的时间
```

考虑到历史交易表缺少完整 gas，建议优先使用以下稳健指标：

1. `recent_in_gap`
   定义：某次 TC 存款前最近一笔 ETH `transfer_in` 到该次存款之间的时间间隔。
   作用：最简单、最稳。

2. `dominant_inflow_gap`
   定义：某次 TC 存款前，最近一个“大额入账来源”的时间到存款时间的间隔。大额可定义为该次 pool 面额的最大单笔贡献来源。
   作用：比 `recent_in_gap` 更接近真正为该次存款提供资金的核心入账。

3. `funding_span_approx`
   定义：在忽略普通历史交易 gas 的前提下，向前回溯若干 ETH 入账，直到累计净流入近似覆盖该次 pool 面额；用最早纳入的一笔入账时间到存款时间的间隔表示。
   作用：刻画“为这次存款准备资金”大致持续了多久。

4. `multi_funding_count`
   定义：近似覆盖该次存款所需的入账笔数。
   作用：区分“一笔到位后立即存入”和“多笔归集后再存入”。

当前阶段不建议直接报告“精确余额达到存款阈值的时间”或“严格 FIFO 资金年龄”，除非后续补全 gas 数据。

### 6.2 TC 池内滞留时间

目标是衡量资金从进入 TC 到离开 TC 的等待时间：

```text
D 的 TC 存款时间 -> W 的 TC 取款到账时间
```

这里必须坚持两个约束：

1. 只在相同 `pool_name` 内匹配。
2. 不把一个 `D-W` 地址对自动解释为逐笔一一配对关系。

建议同时保留三套口径：

1. `candidate_gap_distribution`
   定义：对同一 `D-W-pool` 下所有满足 `deposit_time < withdraw_time` 的存取款组合计算时间差。
   作用：给出所有可解释候选等待时间的分布。

2. `nearest_forward_gap`
   定义：对每笔取款，寻找最近的一笔前序存款，计算时间差。
   作用：刻画“最短可解释池内等待时间”。

3. `temporal_bipartite_matching_gap`
   定义：在同一 `D-W-pool` 下，对存款事件和取款事件做最小时间差的一对一二部匹配；若两边数量不等，则只匹配较小的一侧。
   作用：给出更强但仍保守的配对近似。

此外，可以增加一个地址对层面的窗口比较指标：

4. `deposit_withdraw_window_overlap`
   定义：比较某个线索对的存款时间窗口和取款时间窗口是否高度重叠、快速衔接或明显分离。
   作用：帮助区分“持续性使用”与“短时批处理”两种模式。

### 6.3 取款地址内滞留时间

目标是衡量取款地址收到 ETH 后，过了多久又把 ETH 转走：

```text
W 收到 TC 取款 -> W 向外转出 ETH
```

建议使用以下指标：

1. `first_out_gap`
   定义：某次 TC 取款到账后，第一次 ETH `transfer_out` 的时间间隔。

2. `half_release_gap_approx`
   定义：取款后累计 ETH 转出额达到该次取款金额 50% 所需时间。

3. `full_release_gap_approx`
   定义：取款后累计 ETH 转出额近似达到该次取款金额所需时间。

4. `outflow_counterparty_count`
   定义：该次取款后，在释放相应 ETH 的过程中接触到的唯一下游地址数量。

由于这里同样缺少普通历史交易 gas 信息，`half_release_gap_approx` 和 `full_release_gap_approx` 应解释为“基于 ETH outward transfer 的释放时间”，而不是“地址真实余额被完全清空的时间”。

若在观测窗口结束前仍未释放完，可将样本标记为右删失，必要时用生存分析方法处理。

### 6.4 多次存取款节奏分析

若一个地址有多次 TC 存款或取款，建议提取：

1. `deposit_span`
   首次存款到最后一次存款的时间跨度。

2. `withdraw_span`
   首次取款到最后一次取款的时间跨度。

3. `deposit_interarrival`
   连续两次存款之间的时间间隔。

4. `withdraw_interarrival`
   连续两次取款之间的时间间隔。

5. `burstiness`
   用于衡量操作是否集中爆发在短时间窗口内。

这些指标可以与三段滞留时间结合，用来识别：

1. 快速进入、快速取出、快速转走的“急迫型”实体。
2. 长期归集、集中存款、集中取款的“批处理型”实体。
3. 长期小批量复用地址的“持续运营型”实体。

## 7. 链接图结构分析

### 7.1 Pool 内二部图

建议先以 `pool_name` 为单位构建二部图：

```text
(deposit_address, pool_name) -> (withdraw_address, pool_name)
```

在 pool 内图上统计：

1. `out_degree`
   一个存款地址对应多少个取款地址。

2. `in_degree`
   一个取款地址对应多少个存款地址。

3. `component_size`
   连通分量中的存款地址数、取款地址数和边数。

4. `component_edge_density`
   连通分量内部边密度。

5. `clue_mix`
   一个连通分量中不同 `clue` 类型的组成比例。

基于这些指标，可把结构模式分为：

1. `1-to-1`
2. `1-to-many`
3. `many-to-1`
4. `many-to-many`

### 7.2 跨 Pool 地址复用

同一地址可能在多个 pool 中出现，因此建议再构建一个地址折叠后的复用视角：

1. `pool_diversity(address)`
   某个地址出现过多少种 `pool_name`。

2. `cross_pool_role_consistency`
   某地址是否在不同 pool 中持续扮演相似角色，例如总是作为存款地址或总是作为取款地址。

3. `component_pool_diversity`
   同一连通分量是否跨越多个 pool。

这一层有助于区分“只在单一面额池中活动”的实体与“跨面额协同操作”的实体。

## 8. 过滤子图中的上下游与对手方共享分析

由于公共地址交互已经被预先剔除，这一部分不再强调 CEX、桥或 DeFi 标签，而是强调过滤子图中的私有对手方结构。

### 8.1 一跳上下游特征

对单个地址提取：

1. `filtered_upstream_count`
   给存款地址打 ETH 的唯一起源地址数量。

2. `filtered_downstream_count`
   取款地址向外转 ETH 的唯一下游地址数量。

3. `filtered_upstream_concentration`
   上游金额是否集中于少数地址，可用 top-k 占比或 HHI。

4. `filtered_downstream_concentration`
   下游金额是否集中流向少数地址。

### 8.2 组件内部共享对手方

对同一连通分量中的多个地址，进一步提取：

1. `shared_upstream_ratio`
   多个存款地址是否共享上游对手方。

2. `shared_downstream_ratio`
   多个取款地址是否共享下游对手方。

3. `counterparty_jaccard_similarity`
   地址之间上游集合或下游集合的 Jaccard 相似度。

4. `component_counterparty_reuse`
   同一对手方是否同时与组件内多个地址发生过交互。

这些特征特别适合支撑“结构协同性”论点，因为它们不依赖完整资金路径，只依赖一跳局部交互。

### 8.3 典型流动模式

可以结合图结构和一跳对手方特征，识别如下模式：

1. `多源归集 -> TC -> 多地址分散`
2. `单源进入 -> TC -> 多地址分散`
3. `多源归集 -> TC -> 单地址归集`
4. `单源进入 -> TC -> 单下游转出`

由于公共地址已被移除，上述模式应解释为“在私有对手方子图中观测到的组织结构”。

## 9. 地址生命周期与角色刻画

由于历史交易经过公共地址过滤，生命周期指标必须使用保守命名。

建议提取：

1. `filtered_age_before_first_tc`
   过滤子图中，该地址首次出现到首次 TC 交互之间的时间。

2. `filtered_activity_after_last_tc`
   最后一次 TC 交互后，该地址在过滤子图中的后续活跃时间。

3. `is_fresh_in_filtered_view`
   地址是否几乎在首次出现后不久就参与 TC。

4. `tc_reuse_count`
   地址参与 TC 存款或取款的次数。

5. `post_tc_tx_count`
   TC 交互后继续发生的 ETH 交易数。

6. `single_purpose_score`
   地址全部 ETH 交易中，与 TC 使用直接相关的交易占比。

这一组特征有助于识别：

1. 一次性中转地址。
2. 长期复用地址。
3. 围绕 TC 高度专用的功能地址。
4. 在 TC 前后仍持续参与其他私有交互的活动地址。

## 10. 案例研究与论文表述建议

整体统计之外，建议至少挑选 4 类案例：

1. 一个典型 `1-to-many` 组件。
2. 一个典型 `many-to-1` 组件。
3. 一个跨多个 pool 的组件。
4. 一个时间上非常急迫、从上游进入到下游转出都很短的组件。

案例研究中建议遵守两个表述原则：

1. 把 `D-W` 边解释为高价值线索，而不是自动解释为逐笔确证映射。
2. 把连通分量解释为“可能由同一实体控制或由同一操作链条协调”的地址集合，而不是过度声称“完全同一实体”。

这会让论文在方法力度和解释审慎之间更平衡。

## 11. 建议的 Notebook 工作流

既然实验面板以 `ipynb` 为主，建议按如下顺序组织 notebook：

1. `01_load_and_normalize.ipynb`
   读入五张表，统一字段、时间、地址、pool 映射。

2. `02_build_tc_events.ipynb`
   从 raw 存款表和 raw 取款表构建 `deposit_events`、`withdraw_events`。

3. `03_time_features.ipynb`
   计算三段滞留时间和多次存取款节奏指标。

4. `04_graph_features.ipynb`
   构建 pool 内二部图、跨 pool 复用图和连通分量统计。

5. `05_counterparty_features.ipynb`
   计算过滤子图中的上下游和对手方共享特征。

6. `06_case_studies.ipynb`
   选取代表性组件，生成案例图和叙事材料。

7. `07_figures_for_paper.ipynb`
   汇总论文需要的图表和最终统计结果。

## 12. 第一阶段建议优先落地的结果

第一阶段建议优先实现不依赖额外链上补数、且最容易形成论文图表的一组结果：

1. `D-W-pool` 二部图结构统计：
   `1-to-1`、`1-to-many`、`many-to-1`、`many-to-many` 分布。

2. 多次存取款跨度：
   `deposit_span`、`withdraw_span`、`interarrival`、`burstiness`。

3. 池内候选等待时间：
   `candidate_gap_distribution`、`nearest_forward_gap`。

4. 取款后的首次转出：
   `first_out_gap`。

5. 过滤子图中的一跳结构：
   `filtered_upstream_count`、`filtered_downstream_count`、对手方集中度。

6. 连通分量级别统计：
   地址数、边数、pool 覆盖数、`clue` 类型混合情况。

这组结果已经足够支撑第一版实证分析。后续如果补到完整 gas 或更多链上辅助字段，再向更强的资金年龄建模和更精细的释放曲线推进。
