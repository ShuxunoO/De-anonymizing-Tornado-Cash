"""
@file BTFI_gas_funding_detection.py
@brief Balance-Trough First-In (BTFI) Gas Funding Detection Algorithm.

@details
Detects gas funding behavior on Ethereum where someone transfers small amounts
of ETH to addresses with near-zero balance to pay for transaction fees.

Algorithm:
1. Reconstruct ETH balance timeline for target address
2. Use state machine to identify all "balance trough windows" (balance < threshold)
3. Within each trough window, take the first qualifying ETH external transfer as candidate
4. Score candidates based on balance and amount metrics
5. Merge hits from same sender across multiple trough windows

Key insight: Initial state balance=0 naturally satisfies balance < threshold,
so "first activation" is captured as the first trough window without special handling.

Design principle: Pursue precision over recall (high precision preferred).
"""
import psycopg2
from util import db_tools
from util import fio
from tqdm import tqdm
import json
import bisect
import os


EXCLUDED_ADDRESSES = set(
    fio.load_json("/Shuxun/AML_for_Blockchain/tornadocash_data/address_tags/exclude_address_by_key_words.json")
)

GAS_COST_JSON_PATH = "/Shuxun/AML_for_Blockchain/code/data/cumulative_gas_cost.json"

WEIGHT_BALANCE = 0.5
WEIGHT_AMOUNT = 0.5
LOW_BALANCE_THRESHOLD = 0.005
SCORE_THRESHOLD = 0.5
MIN_GAS_FUNDING_VALUE = 0.0001

POOL_TABLE_MAP = {
    "100ETH": [
        "tornadocash_100eth_withdraw_transfers_none_relayer_caller_addre",
        "tornadocash_100eth_deposit_withdraw_address_onestep_in_out_trac",
        "tornadocash_proxy_router_100eth_deposit_withdraw_address_oneste",
    ],
    "10ETH": [
        "tornadocash_10eth_deposit_withdraw_address_onestep_in_out_trace",
        "tornadocash_10eth_withdraw_transfers_none_relayer_caller_addres",
        "tornadocash_proxy_router_10eth_deposit_withdraw_address_onestep",
    ],
    "1ETH": [
        "tornadocash_1eth_deposit_withdraw_address_onestep_in_out_trace_",
        "tornadocash_1eth_withdraw_transfers_none_relayer_caller_address",
        "tornadocash_proxy_router_1eth_deposit_withdraw_address_onestep_",
    ],
    "0_1ETH": [
        "tornadocash_0_1eth_deposit_withdraw_address_onestep_in_out_trac",
        "tornadocash_0_1eth_withdraw_transfers_none_relayer_caller_addre",
        "tornadocash_proxy_router_0_1eth_deposit_withdraw_address_oneste",
    ],
}

RESULT_SCHEMA = "onestep_clues"


def get_result_table(pool_name):
    """
    @brief Generates the fully-qualified result table name for a given pool.
    @param pool_name Pool name (e.g., '100ETH', '10ETH').
    @return Table name like 'onestep_clues."100ETH_BTFI_gas_funding_candidates_v2"'.
    """
    return f'{RESULT_SCHEMA}."{pool_name}_BTFI_gas_funding_candidates_v2"'


def _is_none_relayer_table(table_name):
    """
    @brief Checks if table name belongs to none_relayer_caller type.
    @param table_name Database table name in onestep_clues schema.
    @return True if the table is none_relayer_caller type.
    """
    return 'none_relayer_caller' in table_name.lower()


_GAS_COST_CACHE = None


def query_percentage(json_filepath, pool_size, input_value):
    """
    @brief Queries percentage value from gas cost JSON for given input.
    @param json_filepath Path to cumulative gas cost JSON file.
    @param pool_size Pool name (e.g., '100ETH').
    @param input_value Value to query.
    @return Percentage value, 0.0 if not found or invalid.
    """
    global _GAS_COST_CACHE
    if input_value > 0.1 or input_value <= 0:
        return 0.0

    if _GAS_COST_CACHE is None:
        if not os.path.exists(json_filepath):
            return 0.0
        with open(json_filepath, 'r', encoding='utf-8') as f:
            _GAS_COST_CACHE = json.load(f)

    data = _GAS_COST_CACHE
    if pool_size not in data:
        return 0.0

    pool_data = data[pool_size]
    if not hasattr(query_percentage, 'threshold_cache'):
        query_percentage.threshold_cache = {}
    cache_key = pool_size
    if cache_key not in query_percentage.threshold_cache:
        query_percentage.threshold_cache[cache_key] = [float(k) for k in pool_data.keys()]

    thresholds = query_percentage.threshold_cache[cache_key]
    idx = bisect.bisect_right(thresholds, input_value)

    if idx >= len(thresholds):
        return 0.0

    target_threshold = str(thresholds[idx])
    return pool_data[target_threshold]


def amount_score(value, pool_name):
    """
    @brief Calculates transaction amount gas funding similarity score.
    @param value Transaction value in ETH.
    @param pool_name Pool name.
    @return Normalized score (0.0 to 1.0).
    """
    return query_percentage(GAS_COST_JSON_PATH, pool_name, value) / 100.0


def balance_score(balance_before, pool_name):
    """
    @brief Calculates balance-based gas funding credibility score.
    @param balance_before Balance before transaction in ETH.
    @param pool_name Pool name.
    @return Normalized score (0.0 to 1.0).
    """
    return 1.0 - (query_percentage(GAS_COST_JSON_PATH, pool_name, balance_before) / 100.0)


def load_target_transactions(conn, table_name, target_address):
    """
    @brief Loads all transactions for target address from onestep_clues table.
    @param conn Database connection.
    @param table_name Table name in onestep_clues schema.
    @param target_address Target address (lowercase).
    @return List of transaction dicts sorted by block_timestamp ASC.
    """
    sql = f"""
        SELECT unique_id, direction, block_timestamp, tx_hash,
               from_address, to_address, value, asset, category
        FROM onestep_clues.{table_name}
        WHERE to_address = %s OR from_address = %s
        ORDER BY block_timestamp ASC;
    """
    try:
        cursor = conn.cursor()
        cursor.execute(sql, (target_address, target_address))
        rows = cursor.fetchall()
        cursor.close()
    except psycopg2.Error as e:
        print(f"[Error] Failed to load transactions (table={table_name}, target={target_address}): {e}")
        return []

    return [
        {
            'unique_id': row[0],
            'direction': row[1],
            'block_timestamp': row[2],
            'tx_hash': row[3],
            'from_address': row[4],
            'to_address': row[5],
            'value': float(row[6]) if row[6] is not None else 0.0,
            'asset': row[7],
            'category': row[8],
        }
        for row in rows
    ]


def get_all_target_addresses(conn, table_names):
    """
    @brief Extracts all target addresses requiring gas funding detection.
    @param conn Database connection.
    @param table_names List of table names to scan.
    @return Set of (address, address_type) tuples.
    """
    all_targets = set()
    for table_name in table_names:
        is_caller_table = _is_none_relayer_table(table_name)

        sql = f"""
            SELECT DISTINCT to_address, transaction_type
            FROM onestep_clues.{table_name}
            WHERE direction = 'transfer_in';
        """
        try:
            cursor = conn.cursor()
            cursor.execute(sql)
            rows = cursor.fetchall()
            cursor.close()
            for row in rows:
                if row[0]:
                    addr = row[0].lower()
                    if is_caller_table:
                        all_targets.add((addr, 'none_relayer_caller_address'))
                    else:
                        tx_type = (row[1] or '').lower()
                        if tx_type == 'withdraw':
                            all_targets.add((addr, 'recipient_address'))
                        else:
                            all_targets.add((addr, 'deposit_address'))
        except psycopg2.Error as e:
            print(f"[Error] Failed to get target addresses (table={table_name}): {e}")
    return all_targets


def build_eth_balance_timeline(all_transactions):
    """
    @brief Builds ETH balance change timeline from transaction list.
    @param all_transactions List of transactions sorted by block_timestamp ASC.
    @return List of dicts with balance_before and balance_after for each ETH tx.
    """
    balance = 0.0
    timeline = []
    for tx in all_transactions:
        if (tx.get('asset') or '').upper() != 'ETH':
            continue
        balance_before = balance
        value = tx.get('value', 0.0)
        if tx['direction'] == 'transfer_in':
            balance += value
        elif tx['direction'] == 'transfer_out':
            balance -= value
        timeline.append({
            'tx': tx,
            'balance_before': balance_before,
            'balance_after': balance,
        })
    return timeline


def btfi_detect(target_address, all_transactions, pool_name, target_address_type='deposit_address'):
    """
    @brief BTFI (Balance-Trough First-In) gas funding detection core algorithm.

    @details
    Uses state machine to traverse ETH balance timeline and identify balance trough windows.
    Within each trough window, extracts first qualifying transaction as candidate.

    State machine states:
    - Abundant balance (in_trough=False): balance_before >= LOW_BALANCE_THRESHOLD
    - Trough window (in_trough=True): balance_before < LOW_BALANCE_THRESHOLD

    Hard filter conditions for candidates:
    1. direction = 'transfer_in'
    2. asset = 'ETH'
    3. category = 'external'
    4. MIN_GAS_FUNDING_VALUE <= value <= GAS_FUNDING_MAX_VALUE
    5. from_address not in EXCLUDED_ADDRESSES

    Scoring: Score = WEIGHT_BALANCE × S_balance + WEIGHT_AMOUNT × S_amount

    @param target_address Target address (lowercase).
    @param all_transactions Transaction list sorted by (block_timestamp, direction).
    @param pool_name Pool name (for amount scoring).
    @param target_address_type One of: 'deposit_address', 'recipient_address', 'none_relayer_caller_address'.
    @return List of detection results sorted by score descending.
    """
    timeline = build_eth_balance_timeline(all_transactions)
    if not timeline:
        return []

    hits = []
    in_trough = False
    trough_found = False

    for i, entry in enumerate(timeline):
        tx = entry['tx']
        bb = entry['balance_before']
        ba = entry['balance_after']

        if bb < LOW_BALANCE_THRESHOLD:
            if not in_trough:
                in_trough = True
                trough_found = False

            if not trough_found:
                if (tx.get('direction') == 'transfer_in'
                        and (tx.get('asset') or '').upper() == 'ETH'
                        and (tx.get('category') or '').lower() == 'external'
                        and tx.get('value', 0.0) >= MIN_GAS_FUNDING_VALUE
                        and tx.get('from_address', '').lower() not in EXCLUDED_ADDRESSES):

                    value = tx['value']
                    s_b = balance_score(bb, pool_name)
                    s_a = amount_score(value, pool_name)
                    score = WEIGHT_BALANCE * s_b + WEIGHT_AMOUNT * s_a

                    if score >= SCORE_THRESHOLD:
                        hits.append({
                            'from_address': tx['from_address'].lower(),
                            'score': score,
                            's_balance': s_b,
                            's_amount': s_a,
                            'tx_hash': tx.get('tx_hash'),
                            'value': value,
                            'block_timestamp': tx.get('block_timestamp'),
                        })
                        trough_found = True

            if ba >= LOW_BALANCE_THRESHOLD:
                in_trough = False
        else:
            in_trough = False

    if not hits:
        return []

    funder_map = {}
    for h in hits:
        addr = h['from_address']
        if addr not in funder_map:
            funder_map[addr] = {
                'pool_name': pool_name,
                'target_address': target_address,
                'target_address_type': target_address_type,
                'gas_funder': addr,
                'max_score': h['score'],
                'hit_count': 1,
                'best_s_balance': h['s_balance'],
                'best_s_amount': h['s_amount'],
                'tx_hashes': [h['tx_hash']],
                'values': [h['value']],
                'timestamps': [h['block_timestamp']],
            }
        else:
            e = funder_map[addr]
            e['hit_count'] += 1
            if h['score'] > e['max_score']:
                e['max_score'] = h['score']
                e['best_s_balance'] = h['s_balance']
                e['best_s_amount'] = h['s_amount']
            e['tx_hashes'].append(h['tx_hash'])
            e['values'].append(h['value'])
            e['timestamps'].append(h['block_timestamp'])

    return sorted([
        {
            'pool_name': v['pool_name'],
            'target_address': v['target_address'],
            'target_address_type': v['target_address_type'],
            'gas_funder': v['gas_funder'],
            'score': v['max_score'],
            'hit_count': v['hit_count'],
            's_balance': v['best_s_balance'],
            's_amount': v['best_s_amount'],
            'tx_hashes': v['tx_hashes'],
            'values': v['values'],
            'timestamps': v['timestamps'],
        }
        for v in funder_map.values()
    ], key=lambda x: -x['score'])


def detect_gas_funding_for_address(conn, target_address, pool_name, table_names, target_address_type='deposit_address'):
    """
    @brief Executes complete BTFI detection flow for a single address.
    @param conn Database connection.
    @param target_address Target address (lowercase).
    @param pool_name Pool name.
    @param table_names List of tables for this pool.
    @param target_address_type Address type.
    @return List of detection results.
    """
    all_txs = []
    for table_name in table_names:
        all_txs.extend(load_target_transactions(conn, table_name, target_address))

    seen = set()
    deduped = []
    for tx in all_txs:
        if tx['unique_id'] not in seen:
            seen.add(tx['unique_id'])
            deduped.append(tx)

    deduped = [tx for tx in deduped if tx.get('block_timestamp') is not None]
    deduped.sort(key=lambda tx: (tx['block_timestamp'], tx['direction']))

    return btfi_detect(target_address, deduped, pool_name, target_address_type=target_address_type)


def ensure_result_table(conn, pool_name):
    """
    @brief Creates result table for BTFI detection if not exists.
    @param conn Database connection.
    @param pool_name Pool name.
    """
    result_table = get_result_table(pool_name)
    sql = f"""
        CREATE TABLE IF NOT EXISTS {result_table} (
            id                  SERIAL PRIMARY KEY,
            pool_name           VARCHAR(20)  NOT NULL,
            target_address      VARCHAR(42)  NOT NULL,
            target_address_type VARCHAR(42)  NOT NULL,
            gas_funder          VARCHAR(42)  NOT NULL,
            score               NUMERIC(6,4) NOT NULL,
            s_balance           NUMERIC(6,4) NOT NULL,
            s_amount            NUMERIC(6,4) NOT NULL,
            hit_count           INTEGER      NOT NULL DEFAULT 1,
            tx_hashes           TEXT[],
            values_eth          NUMERIC(18,8)[],
            timestamps          TIMESTAMP[],
            UNIQUE(pool_name, target_address, target_address_type, gas_funder)
        );
    """
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        conn.commit()
        cursor.close()
    except psycopg2.Error as e:
        conn.rollback()
        print(f"[Error] Failed to create result table ({result_table}): {e}")
        raise


def write_results_to_db(conn, results_batch, pool_name):
    """
    @brief Batch writes BTFI detection results to database.
    @param conn Database connection.
    @param results_batch List of detection results.
    @param pool_name Pool name.
    """
    if not results_batch:
        return

    results_batch = [r for r in results_batch if not all(v == 0 for v in r['values'])]
    if not results_batch:
        return

    result_table = get_result_table(pool_name)
    sql = f"""
        INSERT INTO {result_table}
            (pool_name, target_address, target_address_type, gas_funder, score,
            s_balance, s_amount, hit_count, tx_hashes, values_eth, timestamps)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (pool_name, target_address, target_address_type, gas_funder)
        DO UPDATE SET
            score      = EXCLUDED.score,
            s_balance  = EXCLUDED.s_balance,
            s_amount   = EXCLUDED.s_amount,
            hit_count  = EXCLUDED.hit_count,
            tx_hashes  = EXCLUDED.tx_hashes,
            values_eth = EXCLUDED.values_eth,
            timestamps = EXCLUDED.timestamps;
    """
    try:
        cursor = conn.cursor()
        for r in results_batch:
            cursor.execute(sql, (
                r['pool_name'], r['target_address'], r['target_address_type'], r['gas_funder'],
                r['score'], r['s_balance'], r['s_amount'], r['hit_count'],
                r['tx_hashes'], r['values'], r['timestamps'],
            ))
        conn.commit()
        cursor.close()
    except psycopg2.Error as e:
        conn.rollback()
        print(f"[Error] Failed to write results ({result_table}): {e}")


def run_btfi_for_pool(conn, pool_name, table_names):
    """
    @brief Executes BTFI detection for all addresses in a pool.
    @param conn Database connection.
    @param pool_name Pool name (e.g., '100ETH').
    @param table_names List of tables for this pool.
    @return Detection statistics dict.
    """
    print(f"\n{'='*60}")
    print(f"[INFO] BTFI Detection Start - Pool: {pool_name}")
    print(f"{'='*60}")

    ensure_result_table(conn, pool_name)

    target_set = get_all_target_addresses(conn, table_names)
    print(f"[INFO] Pool {pool_name} has {len(target_set)} (address, type) pairs to detect.")

    detected_count = 0
    total_funders = 0
    unique_funders = set()
    batch = []
    batch_size = 100

    for addr, addr_type in tqdm(target_set, desc=f"BTFI {pool_name}"):
        candidates = detect_gas_funding_for_address(conn, addr, pool_name, table_names, target_address_type=addr_type)
        if candidates:
            detected_count += 1
            total_funders += len(candidates)
            for c in candidates:
                unique_funders.add(c['gas_funder'])
            batch.extend(candidates)

        if len(batch) >= batch_size:
            write_results_to_db(conn, batch, pool_name)
            batch.clear()

    if batch:
        write_results_to_db(conn, batch, pool_name)

    result_table = get_result_table(pool_name)
    print(f"[INFO] Pool {pool_name} Detection Complete:")
    print(f"       {detected_count}/{len(target_set)} addresses detected gas funding")
    print(f"       Total {total_funders} candidates, {len(unique_funders)} unique funders")
    print(f"       Results written to table {result_table}")

    return {
        'total_addresses': len(target_set),
        'detected': detected_count,
        'total_candidates': total_funders,
        'unique_funders': len(unique_funders),
    }


def main():
    """
    @brief Program entry point: executes BTFI detection for all pools.
    """
    conn = db_tools.connect_db()
    if conn is None:
        print("[Error] Cannot connect to database. Exiting.")
        return

    try:
        pool_order = ["100ETH", "10ETH", "1ETH", "0_1ETH"]
        summary = {}

        for pool_name in pool_order:
            if pool_name not in POOL_TABLE_MAP:
                print(f"[WARN] Pool {pool_name} not in mapping, skipping.")
                continue
            summary[pool_name] = run_btfi_for_pool(conn, pool_name, POOL_TABLE_MAP[pool_name])

        print(f"\n{'='*60}")
        print("[INFO] BTFI Detection Summary")
        print(f"{'='*60}")
        for pool_name in pool_order:
            if pool_name in summary:
                s = summary[pool_name]
                result_table = get_result_table(pool_name)
                print(f"  {pool_name}: "
                      f"{s['detected']}/{s['total_addresses']} addresses detected, "
                      f"{s['total_candidates']} candidates, "
                      f"{s['unique_funders']} unique funders -> {result_table}")
        print(f"{'='*60}")
        print("[INFO] All pools BTFI detection complete.")

    except Exception as e:
        print(f"[Error] Program exception: {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()
        print("[INFO] Database connection closed.")


if __name__ == "__main__":
    main()