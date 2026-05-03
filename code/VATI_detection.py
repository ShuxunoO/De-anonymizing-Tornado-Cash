"""
@file VATI_detection.py
@brief Frequent Transfer Association Detection Algorithm.

@details
Detects potential fund flow relationships between Tornado Cash deposit addresses,
withdraw recipient addresses, and non-relayer withdraw caller addresses through
transaction frequency analysis (transaction count ratio, value ratio, bidirectional
interaction) and computes association weight W.

Core process:
1. Data loading and filtering: Get transaction data by pool from dw, proxy, nrc tables
2. Extract address sets: Deposit addresses (A), withdraw recipient addresses (B),
   non-relayer caller addresses (C)
3. Build candidate pairs: Construct address pairs and their counterparty relations
4. Deduplication and filtering: Remove duplicates by tx_hash, filter by threshold
5. USD conversion: Fetch historical prices for value conversion
6. Feature calculation: Score based on directional (F1 count ratio, F2 value ratio)
   and global (F3 bidirectional interaction) features
7. Scoring and output: Write results per pool

Design principle: Prefer precision over recall (high precision preferred).
All addresses converted to lowercase.
"""
import psycopg2
import requests
import json
import time
import datetime
import random
from collections import defaultdict
from tqdm import tqdm

from util import db_tools, fio
from typing import Optional, Union
from config import config


ALCHEMY_KEYS = config.Alchemy_API_key_list


EXCLUDED_ADDRESSES = set()
try:
    EXCLUDED_ADDRESSES = set(addr.lower() for addr in fio.load_json(
        "/Shuxun/AML_for_Blockchain/tornadocash_data/address_tags/exclude_address_by_key_words.json"
    ))
except Exception:
    pass


POOL_TABLE_MAP = {
    "100ETH": ["tornadocash_100eth_withdraw_transfers_none_relayer_caller_addre",
               "tornadocash_100eth_deposit_withdraw_address_onestep_in_out_trac",
               "tornadocash_proxy_router_100eth_deposit_withdraw_address_oneste"],
    "10ETH": ["tornadocash_10eth_deposit_withdraw_address_onestep_in_out_trace",
              "tornadocash_10eth_withdraw_transfers_none_relayer_caller_addres",
              "tornadocash_proxy_router_10eth_deposit_withdraw_address_onestep"],
    "1ETH": ["tornadocash_1eth_deposit_withdraw_address_onestep_in_out_trace_",
            "tornadocash_1eth_withdraw_transfers_none_relayer_caller_address",
            "tornadocash_proxy_router_1eth_deposit_withdraw_address_onestep_"],
    "0_1ETH": ["tornadocash_0_1eth_deposit_withdraw_address_onestep_in_out_trac",
              "tornadocash_0_1eth_withdraw_transfers_none_relayer_caller_addre",
              "tornadocash_proxy_router_0_1eth_deposit_withdraw_address_oneste"],
}


MIN_TX_COUNT = 1
SCORE_THRESHOLD = 0.1
MIN_F1 = 0.1
MIN_F2 = 0.1
SCORE_DIR_W1_REL = 0.3
SCORE_DIR_W2_REL = 0.7
W_BASE = 0.85
W_F3 = 0.15
DEFAULT_BETA1 = 0.5
DEFAULT_BETA2 = 0.5

STABLECOINS = {'USDT', 'USDC', 'DAI', 'BUSD', 'TUSD', 'FRAX'}
PRICE_CACHE_FILE = "/Shuxun/AML_for_Blockchain/data/price_cache.json"
PRICE_CACHE = fio.load_json(PRICE_CACHE_FILE) or {}


def get_result_table(pool_name):
    """
    @brief Generates result table name for a given pool.
    @param pool_name Pool name (e.g., '100ETH').
    @return Table name like 'onestep_clues.frequent_transfer_results_usdweight_100ETH_V2'.
    """
    return f'onestep_clues.frequent_transfer_results_usdweight_{pool_name.upper()}_v2'


def _is_none_relayer_table(table_name):
    """
    @brief Checks if table is non-relayer transaction data table.
    @param table_name Database table name.
    @return True if table contains 'none_relayer_caller'.
    """
    return 'none_relayer_caller' in table_name.lower()


def ensure_result_table(conn, pool_name):
    """
    @brief Creates result table for frequent transfer detection if not exists.
    @param conn Database connection.
    @param pool_name Pool name.
    """
    table_name = get_result_table(pool_name)
    sql = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            id SERIAL PRIMARY KEY, pool VARCHAR(20), address_a VARCHAR(42), address_a_type VARCHAR(30),
            address_b VARCHAR(42), address_b_type VARCHAR(30), relation_direction VARCHAR(50),
            total_tx_count INTEGER DEFAULT 0, total_usd_value NUMERIC, is_bidirectional BOOLEAN DEFAULT FALSE,
            weighted_score NUMERIC, dir_ab_tx_count INTEGER DEFAULT 0, dir_ab_total_value_usd NUMERIC DEFAULT 0,
            dir_ab_f1_count_ratio NUMERIC DEFAULT 0, dir_ab_f2_value_ratio NUMERIC DEFAULT 0, dir_ab_score NUMERIC DEFAULT 0,
            dir_ab_sender_total_out_count INTEGER, dir_ab_sender_total_out_usd NUMERIC,
            dir_ba_tx_count INTEGER DEFAULT 0, dir_ba_total_value_usd NUMERIC DEFAULT 0,
            dir_ba_f1_count_ratio NUMERIC DEFAULT 0, dir_ba_f2_value_ratio NUMERIC DEFAULT 0, dir_ba_score NUMERIC DEFAULT 0,
            dir_ba_sender_total_out_count INTEGER, dir_ba_sender_total_out_usd NUMERIC,
            bidirectional_f3 NUMERIC DEFAULT 0, tx_details JSONB, created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE (pool, address_a, address_b)
        );
    """
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        conn.commit()
        cursor.close()
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] Failed to create result table {table_name}: {e}")
        raise


def get_usd_price(asset: str, block_timestamp: Union[str, datetime.datetime], max_retries: int = 5) -> Optional[float]:
    """
    @brief Fetches USD historical price with multi-provider fallback.
    @param asset Asset symbol (e.g., 'ETH', 'USDC').
    @param block_timestamp Transaction timestamp.
    @param max_retries Max retries per provider.
    @return USD price or None if all providers fail.
    """
    if not asset:
        return None
    asset_upper = asset.upper()
    if asset_upper in STABLECOINS:
        return 1.0
    if isinstance(block_timestamp, str):
        try:
            block_timestamp = datetime.datetime.strptime(block_timestamp, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    elif not isinstance(block_timestamp, datetime.datetime):
        return None

    TOKEN_COINGECKO_MAP = {"ETH": "ethereum", "WETH": "ethereum", "USDC": "usd-coin", "DAI": "dai",
                           "USDT": "tether", "TORN": "tornado-cash", "WBTC": "wrapped-bitcoin"}
    if asset_upper not in TOKEN_COINGECKO_MAP:
        return None
    date_str = block_timestamp.strftime('%Y-%m-%d')
    cache_key = f"{asset_upper}_{date_str}"
    if cache_key in PRICE_CACHE:
        return PRICE_CACHE[cache_key]
    coin_id = TOKEN_COINGECKO_MAP[asset_upper]
    cc_symbol = "ETH" if asset_upper == "WETH" else asset_upper
    timestamp_sec = int(block_timestamp.timestamp())

    def try_alchemy() -> Optional[float]:
        start_time = block_timestamp.strftime('%Y-%m-%dT%H:%M:%SZ')
        end_time = (block_timestamp + datetime.timedelta(minutes=15)).strftime('%Y-%m-%dT%H:%M:%SZ')
        payload = {"symbol": cc_symbol, "startTime": start_time, "endTime": end_time, "interval": "5m"}
        for attempt in range(max_retries):
            api_key = random.choice(ALCHEMY_KEYS)
            url = f"https://api.g.alchemy.com/prices/v1/{api_key}/tokens/historical"
            try:
                response = requests.post(url, json=payload, timeout=10)
                if response.status_code == 429:
                    time.sleep(1)
                    continue
                response.raise_for_status()
                data = response.json()
                price_data = data.get('data', [])
                if price_data and 'value' in price_data[0]:
                    return float(price_data[0]['value'])
            except Exception:
                if attempt < max_retries - 1:
                    time.sleep(1.5)
        return None

    def try_defillama() -> Optional[float]:
        url = f"https://coins.llama.fi/prices/historical/{timestamp_sec}/coingecko:{coin_id}"
        for attempt in range(max_retries):
            try:
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                data = response.json()
                price = data.get('coins', {}).get(f'coingecko:{coin_id}', {}).get('price')
                if price is not None:
                    return float(price)
            except Exception:
                if attempt < max_retries - 1:
                    time.sleep(1.5)
        return None

    def try_cryptocompare() -> Optional[float]:
        url = f"https://min-api.cryptocompare.com/data/pricehistorical?fsym={cc_symbol}&tsyms=USD&ts={timestamp_sec}"
        for attempt in range(max_retries):
            try:
                response = requests.get(url, timeout=12)
                response.raise_for_status()
                data = response.json()
                price = data.get(cc_symbol, {}).get("USD")
                if price is not None:
                    return float(price)
            except Exception:
                if attempt < max_retries - 1:
                    time.sleep(1.3)
        return None

    def try_coingecko() -> Optional[float]:
        from_ts = timestamp_sec - 86400
        to_ts = timestamp_sec + 86400
        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart/range?vs_currency=usd&from={from_ts}&to={to_ts}"
        for attempt in range(max_retries):
            try:
                response = requests.get(url, timeout=12)
                response.raise_for_status()
                data = response.json()
                prices = data.get('prices', [])
                if not prices:
                    return None
                closest = min(prices, key=lambda x: abs(x[0] - timestamp_sec))
                return float(closest[1])
            except Exception:
                if attempt < max_retries - 1:
                    time.sleep(1.5)
        return None

    for name, func in [("Alchemy", try_alchemy), ("DefiLlama", try_defillama),
                       ("CryptoCompare", try_cryptocompare), ("CoinGecko", try_coingecko)]:
        price = func()
        if price is not None:
            PRICE_CACHE[cache_key] = price
            fio.save_to_json(PRICE_CACHE, PRICE_CACHE_FILE)
            return price
    PRICE_CACHE[cache_key] = None
    fio.save_to_json(PRICE_CACHE, PRICE_CACHE_FILE)
    return None


def _extract_date_str(ts) -> Optional[str]:
    """
    @brief Extracts date string YYYY-MM-DD from timestamp.
    @param ts datetime object or string.
    @return Date string or None.
    """
    if isinstance(ts, datetime.datetime):
        return ts.strftime('%Y-%m-%d')
    elif isinstance(ts, str):
        return ts.split(" ")[0]
    return None


def load_and_filter_pool_data(conn, table_names):
    """
    @brief Loads and filters transaction data for a pool from multiple tables.
    @param conn Database connection.
    @param table_names List of tables to scan.
    @return Sorted list of transaction dicts.
    """
    all_txs = []
    cursor = conn.cursor()
    for table in table_names:
        is_nrc = _is_none_relayer_table(table)
        source_label = 'nrc' if is_nrc else 'dw_combined'
        sql = f"""
            SELECT unique_id, transaction_type, direction, block_timestamp,
                    tx_hash, from_address, to_address, value, asset, category
            FROM onestep_clues.{table}
            WHERE value > 0 AND from_address != to_address;
        """
        try:
            cursor.execute(sql)
            rows = cursor.fetchall()
            for row in tqdm(rows, desc=f"Loading {table}"):
                if row[3] is None:
                    continue
                from_addr = row[5].lower() if row[5] else ""
                to_addr = row[6].lower() if row[6] else ""
                if from_addr in EXCLUDED_ADDRESSES or to_addr in EXCLUDED_ADDRESSES:
                    continue
                all_txs.append({
                    'unique_id': row[0], 'transaction_type': row[1].lower() if row[1] else "",
                    'direction': row[2].lower() if row[2] else "", 'block_timestamp': row[3], 'tx_hash': row[4],
                    'from_address': from_addr, 'to_address': to_addr,
                    'value': float(row[7]) if row[7] else 0.0, 'asset': row[8], 'category': row[9], 'source': source_label
                })
        except Exception as e:
            print(f"[ERROR] Error reading table {table}: {e}")
    cursor.close()
    all_txs.sort(key=lambda x: x['block_timestamp'])
    return all_txs


def extract_seed(tx):
    """
    @brief Extracts core address from transaction direction.
    @param tx Transaction dict.
    @return Address string or None.
    """
    if tx['direction'] == 'transfer_out':
        return tx['from_address']
    elif tx['direction'] == 'transfer_in':
        return tx['to_address']
    return None


def extract_address_sets(all_txs):
    """
    @brief Extracts three core address sets from transactions.
    @param all_txs All transactions.
    @return (A_set deposit, B_set withdraw, C_set none_relayer_caller).
    """
    A_set, B_set, C_set = set(), set(), set()
    for tx in tqdm(all_txs, desc="Building address sets"):
        seed_addr = extract_seed(tx)
        if not seed_addr:
            continue
        if tx['source'] == 'dw_combined':
            if tx['transaction_type'] == 'deposit':
                A_set.add(seed_addr)
            elif tx['transaction_type'] == 'withdraw':
                B_set.add(seed_addr)
        elif tx['source'] == 'nrc':
            C_set.add(seed_addr)
    return A_set, B_set, C_set


def build_candidate_pairs(all_txs, A_set, B_set, C_set):
    """
    @brief Builds candidate address pairs through graph intersection.
    @param all_txs All transactions.
    @param A_set Deposit addresses.
    @param B_set Withdraw addresses.
    @param C_set Non-relayer caller addresses.
    @return Set of (addr_a, addr_b, b_type) tuples.
    """
    out_peers = defaultdict(set)
    in_peers = defaultdict(set)
    for tx in tqdm(all_txs, desc="Building network topology"):
        out_peers[tx['from_address']].add(tx['to_address'])
        in_peers[tx['to_address']].add(tx['from_address'])

    candidates = set()
    for a in tqdm(A_set, desc="Generating candidate pairs"):
        peers_of_a = out_peers[a].union(in_peers[a])
        for b in peers_of_a.intersection(B_set):
            candidates.add((a, b, 'withdraw'))
        for c in peers_of_a.intersection(C_set):
            candidates.add((a, c, 'none_relayer_caller'))
    return candidates


def filter_and_dedup_candidates(all_txs, candidates, min_tx_count):
    """
    @brief Filters and deduplicates candidate pairs by tx_hash.
    @param all_txs All transactions.
    @param candidates Candidate pairs.
    @param min_tx_count Minimum transaction count threshold.
    @return (filtered_pairs dict, valid_senders set).
    """
    candidate_map = {(a, b): b_role for a, b, b_role in candidates}
    pair_txs_raw = defaultdict(lambda: {'ab': [], 'ba': []})

    for tx in tqdm(all_txs, desc="Filling relation buckets"):
        fr, to = tx['from_address'], tx['to_address']
        if (fr, to) in candidate_map:
            pair_txs_raw[(fr, to)]['ab'].append(tx)
        if (to, fr) in candidate_map:
            pair_txs_raw[(to, fr)]['ba'].append(tx)

    filtered_pairs = {}
    valid_senders = set()

    for (a, b), tx_dicts in tqdm(pair_txs_raw.items(), desc="Dedup and filter"):
        seen_tx_hashes = set()
        dedup_ab = [tx for tx in tx_dicts['ab'] if tx['tx_hash'] not in seen_tx_hashes and not seen_tx_hashes.add(tx['tx_hash'])]
        dedup_ba = [tx for tx in tx_dicts['ba'] if tx['tx_hash'] not in seen_tx_hashes and not seen_tx_hashes.add(tx['tx_hash'])]
        total_tx = len(dedup_ab) + len(dedup_ba)
        if total_tx >= min_tx_count:
            b_type = candidate_map[(a, b)]
            filtered_pairs[(a, b, b_type)] = {'ab': dedup_ab, 'ba': dedup_ba}
            valid_senders.add(a)
            valid_senders.add(b)

    return filtered_pairs, valid_senders


def calculate_sender_totals_with_usd(all_txs, valid_senders, filtered_pairs):
    """
    @brief Calculates sender totals with USD conversion.
    @param all_txs All transactions.
    @param valid_senders Set of valid sender addresses.
    @param filtered_pairs Filtered pairs.
    @return sender_out_totals dict.
    """
    required_price_keys = set()
    for pair_dic in filtered_pairs.values():
        for tx in pair_dic['ab'] + pair_dic['ba']:
            ast = (tx['asset'] or 'ETH').upper()
            ds = _extract_date_str(tx['block_timestamp'])
            if ast not in STABLECOINS and ds:
                required_price_keys.add((ast, ds))

    seen_tx_hashes_for_keys = set()
    for tx in all_txs:
        if tx['tx_hash'] in seen_tx_hashes_for_keys:
            continue
        seen_tx_hashes_for_keys.add(tx['tx_hash'])
        if tx['from_address'] in valid_senders:
            ast = (tx['asset'] or 'ETH').upper()
            ds = _extract_date_str(tx['block_timestamp'])
            if ast not in STABLECOINS and ds:
                required_price_keys.add((ast, ds))

    local_daily_prices = {}
    for ast, ds in tqdm(required_price_keys, desc="Fetching daily prices"):
        cache_key = f"{ast}_{ds}"
        if cache_key in PRICE_CACHE:
            local_daily_prices[(ast, ds)] = PRICE_CACHE[cache_key]
        else:
            try:
                dt = datetime.datetime.strptime(ds, "%Y-%m-%d")
            except:
                continue
            price = get_usd_price(ast, dt)
            if price is not None:
                local_daily_prices[(ast, ds)] = price

    def get_local_daily_price(asset, ts) -> Optional[float]:
        ast = (asset or 'ETH').upper()
        if ast in STABLECOINS:
            return 1.0
        ds = _extract_date_str(ts)
        return local_daily_prices.get((ast, ds), None)

    for pair_dic in filtered_pairs.values():
        for tx in pair_dic['ab'] + pair_dic['ba']:
            if 'value_usd' not in tx:
                price = get_local_daily_price(tx['asset'], tx['block_timestamp'])
                tx['value_usd'] = tx['value'] * price if price is not None else None

    sender_out_totals = defaultdict(lambda: {'count': 0, 'usd': 0.0})
    seen_tx_hashes = set()
    for tx in tqdm(all_txs, desc="Calculating sender totals"):
        if tx['tx_hash'] in seen_tx_hashes:
            continue
        seen_tx_hashes.add(tx['tx_hash'])
        sender = tx['from_address']
        if sender in valid_senders:
            sender_out_totals[sender]['count'] += 1
            price = get_local_daily_price(tx['asset'], tx['block_timestamp'])
            if price is not None:
                sender_out_totals[sender]['usd'] += tx['value'] * price

    return sender_out_totals


def _calc_dir_scores(tx_list, sender_addr, sender_out_totals):
    """
    @brief Calculates directional scores (F1 count ratio, F2 value ratio).
    @param tx_list Transaction list.
    @param sender_addr Sender address.
    @param sender_out_totals Sender totals dict.
    @return (count, usd, tot_count, tot_usd, f1, f2, score).
    """
    if not tx_list:
        return 0, 0.0, 0, 0.0, 0.0, 0.0, 0.0
    tot_count = sender_out_totals[sender_addr]['count']
    tot_usd = sender_out_totals[sender_addr]['usd']
    f1 = min(1.0, len(tx_list) / tot_count) if tot_count > 0 else 0
    dir_usd = sum((tx['value_usd'] for tx in tx_list if tx['value_usd'] is not None))
    f2 = min(1.0, dir_usd / tot_usd) if tot_usd > 0 else 0
    score = SCORE_DIR_W1_REL * f1 + SCORE_DIR_W2_REL * f2
    return len(tx_list), dir_usd, tot_count, tot_usd, f1, f2, score


def score_and_filter_candidates(filtered_pairs, sender_out_totals, pool_name):
    """
    @brief Scores and filters candidate pairs based on transfer characteristics.
    @param filtered_pairs Filtered pairs.
    @param sender_out_totals Sender totals.
    @param pool_name Pool name.
    @return List of scored results.
    """
    results = []
    for (a, b, b_type), pair_dic in tqdm(filtered_pairs.items(), desc="Scoring candidates"):
        dir_ab, dir_ba = pair_dic['ab'], pair_dic['ba']
        n1, n2 = len(dir_ab), len(dir_ba)
        ab_n, ab_usd, a_tot_n, a_tot_u, ab_f1, ab_f2, sc_ab = _calc_dir_scores(dir_ab, a, sender_out_totals)
        ba_n, ba_usd, b_tot_n, b_tot_u, ba_f1, ba_f2, sc_ba = _calc_dir_scores(dir_ba, b, sender_out_totals)

        total_usd = ab_usd + ba_usd
        beta1 = ab_usd / total_usd if total_usd > 0 else DEFAULT_BETA1
        beta2 = ba_usd / total_usd if total_usd > 0 else DEFAULT_BETA2
        s_base = beta1 * sc_ab + beta2 * sc_ba
        f3 = 1.0 if (n1 > 0 and n2 > 0) else 0.0
        w_final = W_BASE * s_base + W_F3 * f3

        if w_final >= SCORE_THRESHOLD and (ab_f1 >= MIN_F1 or ab_f2 >= MIN_F2 or ba_f1 >= MIN_F1 or ba_f2 >= MIN_F2):
            final_details = []
            for d, t_dir in [(dir_ab, "a_to_b"), (dir_ba, "b_to_a")]:
                for tx in d:
                    final_details.append({
                        "direction": t_dir, "tx_hash": tx['tx_hash'],
                        "block_timestamp": tx['block_timestamp'].isoformat(), "asset": tx['asset'],
                        "value": tx['value'],
                        "unit_price_usd": tx['value_usd'] / tx['value'] if tx['value'] and tx.get('value_usd') else None,
                        "value_usd": tx.get('value_usd')
                    })

            dir_relation = ""
            if b_type == 'none_relayer_caller':
                dir_relation = "deposit_none_relayer_caller_bidirectional" if f3 == 1.0 else ("deposit_to_none_relayer_caller" if ab_n > 0 else "none_relayer_caller_to_deposit")
            else:
                dir_relation = "deposit_withdraw_bidirectional" if f3 == 1.0 else ("deposit_to_withdraw" if ab_n > 0 else "withdraw_to_deposit")

            results.append({
                'pool': pool_name, 'address_a': a, 'address_a_type': 'deposit', 'address_b': b, 'address_b_type': b_type,
                'relation_direction': dir_relation, 'total_tx_count': n1 + n2, 'total_usd_value': total_usd,
                'is_bidirectional': f3 == 1.0, 'weighted_score': w_final,
                'dir_ab_tx_count': ab_n, 'dir_ab_total_value_usd': ab_usd, 'dir_ab_f1_count_ratio': ab_f1,
                'dir_ab_f2_value_ratio': ab_f2, 'dir_ab_score': sc_ab, 'dir_ab_sender_total_out_count': a_tot_n,
                'dir_ab_sender_total_out_usd': a_tot_u, 'dir_ba_tx_count': ba_n, 'dir_ba_total_value_usd': ba_usd,
                'dir_ba_f1_count_ratio': ba_f1, 'dir_ba_f2_value_ratio': ba_f2, 'dir_ba_score': sc_ba,
                'dir_ba_sender_total_out_count': b_tot_n, 'dir_ba_sender_total_out_usd': b_tot_u,
                'bidirectional_f3': f3, 'tx_details': json.dumps(final_details)
            })
    return results


def calculate_frequent_transfers_for_pool(conn, pool_name, table_names):
    """
    @brief Executes frequent transfer detection for a single pool.
    @param conn Database connection.
    @param pool_name Pool name.
    @param table_names Tables for this pool.
    @return List of high-confidence transfer pairs.
    """
    start_time = time.time()
    print(f"\n[{pool_name}] Starting frequent transfer detection...")
    all_txs = load_and_filter_pool_data(conn, table_names)
    print(f"[{pool_name}] Loaded {len(all_txs)} filtered transactions.")
    A_set, B_set, C_set = extract_address_sets(all_txs)
    candidates = build_candidate_pairs(all_txs, A_set, B_set, C_set)
    print(f"[{pool_name}] Generated {len(candidates)} candidate pairs.")
    filtered_pairs, valid_senders = filter_and_dedup_candidates(all_txs, candidates, MIN_TX_COUNT)
    print(f"[{pool_name}] {len(filtered_pairs)} valid candidate pairs after dedup.")
    sender_out_totals = calculate_sender_totals_with_usd(all_txs, valid_senders, filtered_pairs)
    results = score_and_filter_candidates(filtered_pairs, sender_out_totals, pool_name)
    print(f"[{pool_name}] {len(results)} high-confidence pairs, time: {time.time()-start_time:.2f}s")
    return results


def save_pool_results(conn, pool_name, results):
    """
    @brief Saves pool detection results to database.
    @param conn Database connection.
    @param pool_name Pool name.
    @param results List of results.
    """
    if not results:
        return
    ensure_result_table(conn, pool_name)
    table_name = get_result_table(pool_name)
    sql = f"""
        INSERT INTO {table_name} (pool, address_a, address_a_type, address_b, address_b_type, relation_direction,
            total_tx_count, total_usd_value, is_bidirectional, weighted_score,
            dir_ab_tx_count, dir_ab_total_value_usd, dir_ab_f1_count_ratio, dir_ab_f2_value_ratio, dir_ab_score,
            dir_ab_sender_total_out_count, dir_ab_sender_total_out_usd,
            dir_ba_tx_count, dir_ba_total_value_usd, dir_ba_f1_count_ratio, dir_ba_f2_value_ratio, dir_ba_score,
            dir_ba_sender_total_out_count, dir_ba_sender_total_out_usd,
            bidirectional_f3, tx_details
        ) VALUES (
            %(pool)s, %(address_a)s, %(address_a_type)s, %(address_b)s, %(address_b_type)s, %(relation_direction)s,
            %(total_tx_count)s, %(total_usd_value)s, %(is_bidirectional)s, %(weighted_score)s,
            %(dir_ab_tx_count)s, %(dir_ab_total_value_usd)s, %(dir_ab_f1_count_ratio)s, %(dir_ab_f2_value_ratio)s, %(dir_ab_score)s,
            %(dir_ab_sender_total_out_count)s, %(dir_ab_sender_total_out_usd)s,
            %(dir_ba_tx_count)s, %(dir_ba_total_value_usd)s, %(dir_ba_f1_count_ratio)s, %(dir_ba_f2_value_ratio)s, %(dir_ba_score)s,
            %(dir_ba_sender_total_out_count)s, %(dir_ba_sender_total_out_usd)s,
            %(bidirectional_f3)s, %(tx_details)s
        ) ON CONFLICT (pool, address_a, address_b) DO UPDATE SET
            weighted_score = EXCLUDED.weighted_score, tx_details = EXCLUDED.tx_details;
    """
    try:
        cursor = conn.cursor()
        for r in results:
            cursor.execute(sql, r)
        conn.commit()
        cursor.close()
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] Failed to save {pool_name} results: {e}")


def main():
    """
    @brief Main entry point for frequent transfer detection.
    """
    conn = db_tools.connect_db()
    if not conn:
        print("[ERROR] Database connection failed")
        return
    print("=" * 60)
    print(" Frequent Transfer Association Detection ")
    print("=" * 60)
    try:
        pool_order = ["100ETH", "10ETH", "1ETH", "0_1ETH"]
        for pool in pool_order:
            if pool not in POOL_TABLE_MAP:
                continue
            res = calculate_frequent_transfers_for_pool(conn, pool, POOL_TABLE_MAP[pool])
            save_pool_results(conn, pool, res)
    except BaseException as e:
        print(f"[CRITICAL]: {e}")
    finally:
        conn.close()
        print("Done. DB closed.")


if __name__ == "__main__":
    main()