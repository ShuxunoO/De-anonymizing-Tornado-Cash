"""
@file get_final_output_onestep_clues.py
@brief Final output generation for Tornado Cash one-step clue integration.

@details
This script integrates clues from three source groups into a unified output table:
1. public.one_step_trace_clues_gasfunding -> direct_linkage
2. onestep_clues.one_step_trace_clues_gasfunding -> gas_funding
3. onestep_clues.onestep_trace_clue_frequent_transation -> transaction_intensity_linkage

Features:
- Initializes output schema and tables
- Inserts data from three source groups with ID offset handling
- Deduplicates by (deposit_address, withdraw_address) pairs
- Exports final clues, details, and raw transaction CSVs
- Blacklist filtering for known burn addresses
"""
import csv
import os

from util import db_tools


BLACK_ADDRESS_LIST = [
    "0x0000000000000000000000000000000000000000",
    "0x000000000000000000000000000000000000dEaD",
    "0x000000000000000000000000000000000000dead",
    "0x0000000000000000000000000000000000000001",
    "0xdead000000000000000000000000000000000000",
    "0x00000000000000000000000000000000deadbeef",
    "0x000000000000000000000000000000000000beef",
    "0x000000000000000000000000000000000000cafe",
    "0x000000000000000000000000000000000000babe",
    "0x000000000000000000000000000000000000feed",
    "0x000000000000000000000000000000000000c0fe",
]
NORMALIZED_BLACK_ADDRESS_LIST = sorted({address.lower() for address in BLACK_ADDRESS_LIST})

TARGET_MAIN_TABLE = "onestep_clues_output.tornadocash_onestep_clues"
TARGET_DETAIL_TABLE = "onestep_clues_output.tornadocash_onestep_clues_details"
OUTPUT_DIRECTORIES = [
    "xxx/data/final_output",
    "xxx",
]
EXPORT_FILENAMES = {
    "main": "tornadocash_onestep_clues.csv",
    "detail": "tornadocash_onestep_clues_details.csv",
    "raw_deposit": "tornadocash_raw_deposit_transactions.csv",
    "raw_withdrawal": "tornadocash_raw_withdrawal_transactions.csv",
    "onestep_deposit_history": "tornadocash_deposit_address_onestep_trace_history.csv",
    "onestep_withdrawal_history": "tornadocash_withdrawal_address_onestep_trace_history.csv",
}
RAW_TRANSACTION_EXPORT_COLUMNS = """
tx.unique_id, tx.block_num, tx.block_timestamp, tx.tx_hash, tx.from_address, tx.to_address,
tx.value, tx.asset, tx.category, tx.gas_limit, tx.gas_price, tx.max_fee_per_gas,
tx.max_priority_fee_per_gas, tx.effectivegasprice, tx.gasused, tx.nonce, tx.transaction_index,
tx.input_data, tx.tx_type, tx.chain_id, tx.none_relayer_caller_address, tx."gas_cost_ETH" AS "gas_cost_ETH"
"""
ONESTEP_TRANSACTION_EXPORT_COLUMNS = """
tx.unique_id, tx.transaction_type, tx.direction, tx.block_num, tx.block_timestamp, tx.tx_hash,
tx.from_address, tx.to_address, tx.value, tx.asset, tx.category
"""
ONESTEP_DEPOSIT_TRANSACTION_TYPE_SQL = "'deposit', 'proxy_deposit'"
ONESTEP_WITHDRAWAL_TRANSACTION_TYPE_SQL = "'withdraw'"

GROUP_CONFIGS = [
    {
        "name": "public.one_step_trace_clues_gasfunding",
        "main_table": "one_step_trace_clues_gasfunding",
        "detail_table": "onestep_trace_clue_gasfunding_details",
        "clue": "direct_linkage",
        "where_sql": "(m.clue_type = 'a1' OR m.clue_type = 'c1') AND m.verify_status = true",
        "score_expr": "NULL::NUMERIC(10,4)",
        "total_tx_count_expr": "NULL::INT",
        "total_usd_value_expr": "NULL::NUMERIC(15,2)",
        "remark_expr": "NULL::TEXT",
        "step_order_expr": "CAST(d.step_order AS VARCHAR(20))",
    },
    {
        "name": "onestep_clues.one_step_trace_clues_gasfunding",
        "main_table": "onestep_clues.one_step_trace_clues_gasfunding",
        "detail_table": "onestep_clues.onestep_trace_clue_gasfunding_details",
        "clue": "gas_funding",
        "where_sql": "m.verify_status = true",
        "score_expr": "m.score",
        "total_tx_count_expr": "NULL::INT",
        "total_usd_value_expr": "NULL::NUMERIC(15,2)",
        "remark_expr": "m.remark",
        "step_order_expr": "CAST(d.step_order AS VARCHAR(20))",
    },
    {
        "name": "onestep_clues.onestep_trace_clue_frequent_transation",
        "main_table": "onestep_clues.onestep_trace_clue_frequent_transation",
        "detail_table": "onestep_clues.onestep_trace_clue_frequent_transation_details",
        "clue": "transaction_intensity_linkage",
        "where_sql": "m.verify_status = true AND ((m.total_tx_count = 2 AND m.score >= 0.9) OR (m.total_tx_count BETWEEN 3 AND 10 AND m.score >= 0.5) OR (m.total_tx_count >= 11 AND m.score >= 0.4))",
        "score_expr": "m.score",
        "total_tx_count_expr": "m.total_tx_count",
        "total_usd_value_expr": "m.total_usd_value",
        "remark_expr": "m.remark",
        "step_order_expr": "CAST(d.step_order AS VARCHAR(20))",
    },
]

TORNADOCASH_RAW_DATATABLE_LIST = {
    "schema": "public",
    "mainpool_deposit_table_list": [
        "tornadocash_100eth_deposit_transfers",
        "tornadocash_10eth_deposit_transfers",
        "tornadocash_1eth_deposit_transfers",
        "tornadocash_0_1eth_deposit_transfers"
    ],
    "proxy_deposit_table_list": [
        "tornadocash_newproxy_deposit_transfers",
        "tornadocash_oldproxy_deposit_transfers",
        "tornadorouter_deposit_transfers"
    ],
    "withdraw_table_list": [
        "tornadocash_100eth_withdraw_transfers",
        "tornadocash_10eth_withdraw_transfers",
        "tornadocash_1eth_withdraw_transfers",
        "tornadocash_0_1eth_withdraw_transfers"
    ]
}
MAINPOOL_DEPOSIT_TABLE_BY_POOL = {
    "100ETH": "tornadocash_100eth_deposit_transfers",
    "10ETH": "tornadocash_10eth_deposit_transfers",
    "1ETH": "tornadocash_1eth_deposit_transfers",
    "0_1ETH": "tornadocash_0_1eth_deposit_transfers",
}
WITHDRAW_TABLE_BY_POOL = {
    "100ETH": "tornadocash_100eth_withdraw_transfers",
    "10ETH": "tornadocash_10eth_withdraw_transfers",
    "1ETH": "tornadocash_1eth_withdraw_transfers",
    "0_1ETH": "tornadocash_0_1eth_withdraw_transfers",
}
POOL_VALUE_SQL_BY_NAME = {
    "100ETH": "100.0",
    "10ETH": "10.0",
    "1ETH": "1.0",
    "0_1ETH": "0.1",
}
ONESTEP_TRANSACTION_TRACE_TABLE_LIST = {
    "100ETH": "tornadocash_100eth_onestep_in_out_transactions_onepiece",
    "10ETH": "tornadocash_10eth_onestep_in_out_transactions_onepiece",
    "1ETH": "tornadocash_1eth_onestep_in_out_transactions_onepiece",
    "0_1ETH": "tornadocash_0_1eth_onestep_in_out_transactions_onepiece"
}


def get_tornadocash_tables(table_groups):
    """
    @brief Returns fully qualified table names for the specified table groups.
    @param table_groups List of group names to include.
    @return List of fully qualified table names with schema.
    """
    schema = TORNADOCASH_RAW_DATATABLE_LIST.get("schema", "public")
    full_table_names = []
    for group_name in table_groups:
        table_list = TORNADOCASH_RAW_DATATABLE_LIST.get(group_name, [])
        for table_name in table_list:
            full_table_names.append(f'{schema}."{table_name}"')
    return full_table_names


def get_qualified_raw_table_name(table_name):
    """
    @brief Returns fully qualified raw transaction table name with schema.
    @param table_name Table name without schema.
    @return Fully qualified table name.
    """
    schema = TORNADOCASH_RAW_DATATABLE_LIST.get("schema", "public")
    return f'{schema}."{table_name}"'


def get_qualified_onestep_table_name(table_name):
    """
    @brief Returns fully qualified one-hop trace table name with schema.
    @param table_name Table name without schema.
    @return Fully qualified table name.
    """
    return f'onestep_clues."{table_name}"'


def build_distinct_target_source_sql(pool_name, address_column):
    """
    @brief Builds SQL to query distinct (pool_name, address) pairs from final clues table.
    @param pool_name Pool name (e.g., '100ETH').
    @param address_column Column name ('deposit_address' or 'withdraw_address').
    @return SQL string.
    """
    if address_column not in {"deposit_address", "withdraw_address"}:
        raise ValueError(f"Unsupported address column: {address_column}")
    return f"""
        SELECT DISTINCT pool_name, {address_column} AS target_address
        FROM {TARGET_MAIN_TABLE}
        WHERE pool_name = '{pool_name}' AND {address_column} IS NOT NULL AND {address_column} <> ''
    """


def ensure_output_directories():
    """
    @brief Ensures all output directories exist.
    """
    for output_dir in OUTPUT_DIRECTORIES:
        os.makedirs(output_dir, exist_ok=True)


def export_query_to_csv(conn, sql, output_filename):
    """
    @brief Exports query results to CSV and writes to all output directories.
    @param conn Database connection.
    @param sql Export query.
    @param output_filename Output filename.
    """
    ensure_output_directories()
    primary_output_path = os.path.join(OUTPUT_DIRECTORIES[0], output_filename)
    with open(primary_output_path, "w", encoding="utf-8", newline="") as csv_file:
        with conn.cursor() as cursor:
            copy_sql = f"COPY ({sql}) TO STDOUT WITH CSV HEADER"
            cursor.copy_expert(copy_sql, csv_file)
    print(f"Exported CSV: {primary_output_path}")


def export_final_output_tables(conn):
    """
    @brief Exports final clues main table and details table to CSV.
    @param conn Database connection.
    """
    main_sql = f"SELECT * FROM {TARGET_MAIN_TABLE} ORDER BY id ASC"
    detail_sql = f"SELECT * FROM {TARGET_DETAIL_TABLE} ORDER BY trace_id ASC, step_order ASC, id ASC"
    export_query_to_csv(conn, main_sql, EXPORT_FILENAMES["main"])
    export_query_to_csv(conn, detail_sql, EXPORT_FILENAMES["detail"])


def fetch_distinct_deposit_sources(conn):
    """
    @brief Queries distinct (pool_name, deposit_address) combinations from final clues table.
    @param conn Database connection.
    @return List of (pool_name, deposit_address) tuples.
    """
    sql = f"""
        SELECT DISTINCT pool_name, deposit_address
        FROM {TARGET_MAIN_TABLE}
        WHERE deposit_address IS NOT NULL AND deposit_address <> ''
        ORDER BY pool_name ASC, deposit_address ASC
    """
    with conn.cursor() as cursor:
        cursor.execute(sql)
        return cursor.fetchall()


def print_deposit_source_summary(deposit_sources):
    """
    @brief Prints summary statistics of deposit address sources by pool.
    @param deposit_sources List of (pool_name, deposit_address) tuples.
    @return Dict mapping pool_name to count.
    """
    pool_counts = {}
    for pool_name, _deposit_address in deposit_sources:
        pool_counts[pool_name] = pool_counts.get(pool_name, 0) + 1
    print("[raw_deposit] Step 1: distinct (pool_name, deposit_address) summary")
    for pool_name in sorted(pool_counts):
        print(f"[raw_deposit]   {pool_name}: {pool_counts[pool_name]} deposit addresses")
    print(f"[raw_deposit]   total: {len(deposit_sources)} distinct combinations")
    return pool_counts


def fetch_raw_deposit_rows_for_source(conn, pool_name, deposit_address):
    """
    @brief Queries raw deposit transactions for a single (pool_name, deposit_address) pair.
    @param conn Database connection.
    @param pool_name Pool name (100ETH, 10ETH, 1ETH, 0_1ETH).
    @param deposit_address Deposit initiator address.
    @return List of transaction rows.
    """
    if pool_name not in MAINPOOL_DEPOSIT_TABLE_BY_POOL:
        return []
    if pool_name not in POOL_VALUE_SQL_BY_NAME:
        return []

    mainpool_table_name = get_qualified_raw_table_name(MAINPOOL_DEPOSIT_TABLE_BY_POOL[pool_name])
    proxy_tables = get_tornadocash_tables(["proxy_deposit_table_list"])
    pool_value = POOL_VALUE_SQL_BY_NAME[pool_name]

    base_select_sql = f"""
        SELECT %s AS pool_name, 'deposit_address' AS address_type, %s AS target_address,
               {RAW_TRANSACTION_EXPORT_COLUMNS}
        FROM {{table_name}} tx WHERE tx.from_address = %s
    """

    rows = []
    with conn.cursor() as cursor:
        cursor.execute(base_select_sql.format(table_name=mainpool_table_name),
                      (pool_name, deposit_address, deposit_address))
        rows.extend(cursor.fetchall())

        proxy_sql = base_select_sql + " AND tx.category = 'external' AND tx.value = %s"
        for proxy_table_name in proxy_tables:
            cursor.execute(proxy_sql.format(table_name=proxy_table_name),
                          (pool_name, deposit_address, deposit_address, pool_value))
            rows.extend(cursor.fetchall())
    return rows


def write_raw_deposit_rows_to_csv(rows, output_filename):
    """
    @brief Writes raw deposit transaction rows to CSV.
    @param rows Transaction rows.
    @param output_filename Output filename.
    @return Path to output CSV file.
    """
    ensure_output_directories()
    primary_output_path = os.path.join(OUTPUT_DIRECTORIES[0], output_filename)
    header = [
        "pool_name", "address_type", "target_address", "unique_id", "block_num", "block_timestamp",
        "tx_hash", "from_address", "to_address", "value", "asset", "category", "gas_limit", "gas_price",
        "max_fee_per_gas", "max_priority_fee_per_gas", "effectivegasprice", "gasused", "nonce",
        "transaction_index", "input_data", "tx_type", "chain_id", "none_relayer_caller_address", "gas_cost_ETH",
    ]
    sorted_rows = sorted(rows, key=get_raw_transaction_sort_key)
    with open(primary_output_path, "w", encoding="utf-8", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(header)
        writer.writerows(sorted_rows)
    print(f"[raw_deposit] Step 4: wrote {len(sorted_rows)} rows to {primary_output_path}")
    return primary_output_path


def get_raw_transaction_sort_key(row):
    """
    @brief Returns stable sort key for raw transaction rows.
    @param row Transaction row tuple.
    @return Tuple sort key.
    """
    return (row[5] is None, row[5], row[4] is None, row[4], row[6] or "", row[3] or "", row[0] or "", row[2] or "")


def deduplicate_raw_transaction_rows_by_tx_hash(rows, log_prefix):
    """
    @brief Deduplicates transaction rows by tx_hash, keeping first occurrence.
    @param rows Transaction rows.
    @param log_prefix Log prefix string.
    @return Tuple of (deduplicated_rows, duplicate_count).
    """
    seen_tx_hashes = set()
    deduplicated_rows = []
    duplicate_tx_hash_count = 0
    for row in sorted(rows, key=get_raw_transaction_sort_key):
        tx_hash = row[6]
        if tx_hash in seen_tx_hashes:
            duplicate_tx_hash_count += 1
            continue
        seen_tx_hashes.add(tx_hash)
        deduplicated_rows.append(row)
    print(f"[{log_prefix}]   skipped duplicate tx_hash rows: {duplicate_tx_hash_count}")
    return deduplicated_rows, duplicate_tx_hash_count


def count_raw_transaction_rows_by_pool(rows):
    """
    @brief Counts transaction rows per pool.
    @param rows Transaction rows.
    @return Dict mapping pool_name to row count.
    """
    pool_row_counts = {}
    for row in rows:
        pool_name = row[0]
        pool_row_counts[pool_name] = pool_row_counts.get(pool_name, 0) + 1
    return pool_row_counts


def fetch_distinct_onestep_address_sources(conn, address_column):
    """
    @brief Queries distinct (pool_name, address) sources for one-hop history export.
    @param conn Database connection.
    @param address_column 'deposit_address' or 'withdraw_address'.
    @return List of (pool_name, target_address) tuples.
    """
    if address_column not in {"deposit_address", "withdraw_address"}:
        raise ValueError(f"Unsupported address column: {address_column}")
    sql = f"""
        SELECT DISTINCT pool_name, {address_column} AS target_address
        FROM {TARGET_MAIN_TABLE}
        WHERE {address_column} IS NOT NULL AND {address_column} <> ''
    """
    with conn.cursor() as cursor:
        cursor.execute(sql)
        return cursor.fetchall()


def deduplicate_onestep_sources_by_address(address_sources, log_prefix):
    """
    @brief Deduplicates address sources by address globally.
    @param address_sources List of (pool_name, target_address).
    @param log_prefix Log prefix.
    @return List of deduplicated (pool_name, target_address).
    """
    pool_order = {pool_name: index for index, pool_name in enumerate(ONESTEP_TRANSACTION_TRACE_TABLE_LIST)}
    supported_pool_count = len(pool_order)
    sorted_sources = sorted(address_sources, key=lambda row: (
        pool_order.get(row[0], supported_pool_count), row[1] or ""))
    seen_addresses = set()
    selected_sources = []
    skipped_duplicate_address_count = 0
    skipped_unsupported_pool_count = 0
    for pool_name, target_address in sorted_sources:
        if pool_name not in pool_order:
            skipped_unsupported_pool_count += 1
            continue
        if target_address in seen_addresses:
            skipped_duplicate_address_count += 1
            continue
        seen_addresses.add(target_address)
        selected_sources.append((pool_name, target_address))
    print(f"[{log_prefix}] Step 1: distinct (pool_name, address) sources: {len(address_sources)}")
    print(f"[{log_prefix}]   selected unique addresses: {len(selected_sources)}")
    print(f"[{log_prefix}]   skipped duplicate address sources: {skipped_duplicate_address_count}")
    print(f"[{log_prefix}]   skipped unsupported pool sources: {skipped_unsupported_pool_count}")
    return selected_sources


def create_temp_onestep_source_table(conn, temp_table_name, address_sources):
    """
    @brief Creates temporary table for one-hop address sources.
    @param conn Database connection.
    @param temp_table_name Temp table name.
    @param address_sources List of (pool_name, target_address).
    """
    if not temp_table_name.isidentifier():
        raise ValueError(f"Unsafe temp table name: {temp_table_name}")
    with conn.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS pg_temp.{temp_table_name}")
        cursor.execute(f"""
            CREATE TEMP TABLE {temp_table_name} (
                pool_name VARCHAR(50), target_address VARCHAR(42)
            ) ON COMMIT PRESERVE ROWS
        """)
        if address_sources:
            cursor.executemany(f"INSERT INTO {temp_table_name} (pool_name, target_address) VALUES (%s, %s)",
                              address_sources)
        cursor.execute(f"CREATE INDEX ON {temp_table_name} (pool_name, target_address)")


def count_onestep_sources_by_pool(address_sources):
    """
    @brief Counts address sources per pool.
    @param address_sources List of (pool_name, target_address).
    @return Dict mapping pool_name to count.
    """
    pool_counts = {}
    for pool_name, _target_address in address_sources:
        pool_counts[pool_name] = pool_counts.get(pool_name, 0) + 1
    return pool_counts


def build_empty_onestep_history_sql(address_type):
    """
    @brief Builds empty result SQL with headers only.
    @param address_type 'deposit_address' or 'withdrawal_address'.
    @return SQL string returning empty results with correct headers.
    """
    return f"""
        SELECT '{address_type}'::TEXT AS address_type, NULL::VARCHAR(42) AS target_address,
               NULL::VARCHAR(255) AS unique_id, NULL::VARCHAR(20) AS transaction_type,
               NULL::VARCHAR(20) AS direction, NULL::BIGINT AS block_num,
               NULL::TIMESTAMP AS block_timestamp, NULL::VARCHAR(66) AS tx_hash,
               NULL::VARCHAR(42) AS from_address, NULL::VARCHAR(42) AS to_address,
               NULL::NUMERIC AS value, NULL::VARCHAR(255) AS asset, NULL::VARCHAR(100) AS category
        WHERE FALSE
    """


def write_raw_transaction_rows_to_csv(rows, output_filename, log_prefix):
    """
    @brief Writes raw transaction rows to CSV file.
    @param rows Transaction rows.
    @param output_filename Output filename.
    @param log_prefix Log prefix.
    @return Path to output file.
    """
    ensure_output_directories()
    primary_output_path = os.path.join(OUTPUT_DIRECTORIES[0], output_filename)
    header = [
        "pool_name", "address_type", "target_address", "unique_id", "block_num", "block_timestamp",
        "tx_hash", "from_address", "to_address", "value", "asset", "category", "gas_limit", "gas_price",
        "max_fee_per_gas", "max_priority_fee_per_gas", "effectivegasprice", "gasused", "nonce",
        "transaction_index", "input_data", "tx_type", "chain_id", "none_relayer_caller_address", "gas_cost_ETH",
    ]
    sorted_rows = sorted(rows, key=get_raw_transaction_sort_key)
    with open(primary_output_path, "w", encoding="utf-8", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(header)
        writer.writerows(sorted_rows)
    print(f"[{log_prefix}] Step 4: wrote {len(sorted_rows)} rows to {primary_output_path}")
    return primary_output_path


def export_raw_deposit_transactions(conn):
    """
    @brief Exports raw deposit transactions for distinct (pool_name, deposit_address) pairs.
    @param conn Database connection.
    """
    deposit_sources = fetch_distinct_deposit_sources(conn)
    print_deposit_source_summary(deposit_sources)
    all_rows = []
    print("[raw_deposit] Step 2/3: query raw mainpool and proxy deposit tables")
    for index, (pool_name, deposit_address) in enumerate(deposit_sources, start=1):
        rows = fetch_raw_deposit_rows_for_source(conn, pool_name, deposit_address)
        all_rows.extend(rows)
        if index % 500 == 0 or index == len(deposit_sources):
            print(f"[raw_deposit]   processed {index}/{len(deposit_sources)} address sources, matched rows so far: {len(all_rows)}")
    print(f"[raw_deposit]   total raw deposit rows before tx_hash dedup: {len(all_rows)}")
    deduplicated_rows, _ = deduplicate_raw_transaction_rows_by_tx_hash(all_rows, "raw_deposit")
    pool_row_counts = count_raw_transaction_rows_by_pool(deduplicated_rows)
    print("[raw_deposit] Step 3 summary: matched unique tx_hash raw deposit rows by pool")
    for pool_name in sorted(pool_row_counts):
        print(f"[raw_deposit]   {pool_name}: {pool_row_counts[pool_name]} rows")
    print(f"[raw_deposit]   total unique tx_hash raw deposit rows: {len(deduplicated_rows)}")
    write_raw_deposit_rows_to_csv(deduplicated_rows, EXPORT_FILENAMES["raw_deposit"])


def fetch_distinct_withdrawal_sources(conn):
    """
    @brief Queries distinct (pool_name, withdraw_address) combinations from final clues table.
    @param conn Database connection.
    @return List of (pool_name, withdraw_address) tuples.
    """
    sql = f"""
        SELECT DISTINCT pool_name, withdraw_address
        FROM {TARGET_MAIN_TABLE}
        WHERE withdraw_address IS NOT NULL AND withdraw_address <> ''
        ORDER BY pool_name ASC, withdraw_address ASC
    """
    with conn.cursor() as cursor:
        cursor.execute(sql)
        return cursor.fetchall()


def print_withdrawal_source_summary(withdrawal_sources):
    """
    @brief Prints summary statistics of withdrawal address sources by pool.
    @param withdrawal_sources List of (pool_name, withdraw_address) tuples.
    @return Dict mapping pool_name to count.
    """
    pool_counts = {}
    for pool_name, _withdraw_address in withdrawal_sources:
        pool_counts[pool_name] = pool_counts.get(pool_name, 0) + 1
    print("[raw_withdrawal] Step 1: distinct (pool_name, withdraw_address) summary")
    for pool_name in sorted(pool_counts):
        print(f"[raw_withdrawal]   {pool_name}: {pool_counts[pool_name]} withdrawal addresses")
    print(f"[raw_withdrawal]   total: {len(withdrawal_sources)} distinct combinations")
    return pool_counts


def fetch_raw_withdrawal_rows_for_source(conn, pool_name, withdraw_address):
    """
    @brief Queries raw withdrawal transactions for a single (pool_name, withdraw_address) pair.
    @param conn Database connection.
    @param pool_name Pool name (100ETH, 10ETH, 1ETH, 0_1ETH).
    @param withdraw_address Withdrawal recipient address.
    @return List of transaction rows.
    """
    if pool_name not in WITHDRAW_TABLE_BY_POOL:
        print(f"[raw_withdrawal] Skip unsupported pool_name={pool_name}, withdraw_address={withdraw_address}")
        return []
    table_name = get_qualified_raw_table_name(WITHDRAW_TABLE_BY_POOL[pool_name])
    sql = f"""
        SELECT %s AS pool_name, 'withdrawal_address' AS address_type, %s AS target_address,
               {RAW_TRANSACTION_EXPORT_COLUMNS}
        FROM {table_name} tx WHERE tx.to_address = %s
    """
    with conn.cursor() as cursor:
        cursor.execute(sql, (pool_name, withdraw_address, withdraw_address))
        return cursor.fetchall()


def export_raw_withdrawal_transactions(conn):
    """
    @brief Exports raw withdrawal transactions for distinct (pool_name, withdraw_address) pairs.
    @param conn Database connection.
    """
    withdrawal_sources = fetch_distinct_withdrawal_sources(conn)
    print_withdrawal_source_summary(withdrawal_sources)
    all_rows = []
    print("[raw_withdrawal] Step 2/3: query only the mapped withdraw table for each pool")
    for index, (pool_name, withdraw_address) in enumerate(withdrawal_sources, start=1):
        rows = fetch_raw_withdrawal_rows_for_source(conn, pool_name, withdraw_address)
        all_rows.extend(rows)
        if index % 500 == 0 or index == len(withdrawal_sources):
            print(f"[raw_withdrawal]   processed {index}/{len(withdrawal_sources)} address sources, matched rows so far: {len(all_rows)}")
    print(f"[raw_withdrawal]   total raw withdrawal rows before tx_hash dedup: {len(all_rows)}")
    deduplicated_rows, _ = deduplicate_raw_transaction_rows_by_tx_hash(all_rows, "raw_withdrawal")
    pool_row_counts = count_raw_transaction_rows_by_pool(deduplicated_rows)
    print("[raw_withdrawal] Step 3 summary: matched unique tx_hash raw withdrawal rows by pool")
    for pool_name in sorted(pool_row_counts):
        print(f"[raw_withdrawal]   {pool_name}: {pool_row_counts[pool_name]} rows")
    print(f"[raw_withdrawal]   total unique tx_hash raw withdrawal rows: {len(deduplicated_rows)}")
    write_raw_transaction_rows_to_csv(deduplicated_rows, EXPORT_FILENAMES["raw_withdrawal"], "raw_withdrawal")


def export_onestep_deposit_address_history(conn):
    """
    @brief Exports one-hop deposit address transaction history.
    @param conn Database connection.
    """
    address_sources = fetch_distinct_onestep_address_sources(conn, "deposit_address")
    selected_sources = deduplicate_onestep_sources_by_address(address_sources, "onestep_deposit_history")
    temp_table_name = "tmp_onestep_deposit_address_sources"
    create_temp_onestep_source_table(conn, temp_table_name, selected_sources)
    pool_source_counts = count_onestep_sources_by_pool(selected_sources)
    union_queries = []
    for pool_name, table_name in ONESTEP_TRANSACTION_TRACE_TABLE_LIST.items():
        if pool_source_counts.get(pool_name, 0) == 0:
            continue
        qualified_table_name = get_qualified_onestep_table_name(table_name)
        source_sql = f"SELECT pool_name, target_address FROM {temp_table_name} WHERE pool_name = '{pool_name}'"
        union_queries.append(f"""
            SELECT 'deposit_address' AS address_type, source.target_address AS target_address,
                   {ONESTEP_TRANSACTION_EXPORT_COLUMNS}
            FROM {qualified_table_name} tx
            JOIN ({source_sql}) source ON tx.from_address = source.target_address OR tx.to_address = source.target_address
            WHERE tx.transaction_type IN ({ONESTEP_DEPOSIT_TRANSACTION_TYPE_SQL})
        """)
    if union_queries:
        export_sql = f"""
        WITH unioned AS ({" UNION ALL ".join(union_queries)}),
        ranked AS (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY tx_hash ORDER BY block_timestamp ASC NULLS LAST, block_num ASC NULLS LAST, target_address ASC, unique_id ASC) AS rn
            FROM unioned
        )
        SELECT address_type, target_address, unique_id, transaction_type, direction, block_num, block_timestamp, tx_hash, from_address, to_address, value, asset, category
        FROM ranked WHERE rn = 1 ORDER BY target_address ASC, block_num ASC, tx_hash ASC
        """
    else:
        export_sql = build_empty_onestep_history_sql("deposit_address")
    export_query_to_csv(conn, export_sql, EXPORT_FILENAMES["onestep_deposit_history"])


def export_onestep_withdrawal_address_history(conn):
    """
    @brief Exports one-hop withdrawal address transaction history.
    @param conn Database connection.
    """
    address_sources = fetch_distinct_onestep_address_sources(conn, "withdraw_address")
    selected_sources = deduplicate_onestep_sources_by_address(address_sources, "onestep_withdrawal_history")
    temp_table_name = "tmp_onestep_withdrawal_address_sources"
    create_temp_onestep_source_table(conn, temp_table_name, selected_sources)
    pool_source_counts = count_onestep_sources_by_pool(selected_sources)
    union_queries = []
    for pool_name, table_name in ONESTEP_TRANSACTION_TRACE_TABLE_LIST.items():
        if pool_source_counts.get(pool_name, 0) == 0:
            continue
        qualified_table_name = get_qualified_onestep_table_name(table_name)
        source_sql = f"SELECT pool_name, target_address FROM {temp_table_name} WHERE pool_name = '{pool_name}'"
        union_queries.append(f"""
            SELECT 'withdrawal_address' AS address_type, source.target_address AS target_address,
                   {ONESTEP_TRANSACTION_EXPORT_COLUMNS}
            FROM {qualified_table_name} tx
            JOIN ({source_sql}) source ON tx.from_address = source.target_address OR tx.to_address = source.target_address
            WHERE tx.transaction_type IN ({ONESTEP_WITHDRAWAL_TRANSACTION_TYPE_SQL})
        """)
    if union_queries:
        export_sql = f"""
        WITH unioned AS ({" UNION ALL ".join(union_queries)}),
        ranked AS (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY tx_hash ORDER BY block_timestamp ASC NULLS LAST, block_num ASC NULLS LAST, target_address ASC, unique_id ASC) AS rn
            FROM unioned
        )
        SELECT address_type, target_address, unique_id, transaction_type, direction, block_num, block_timestamp, tx_hash, from_address, to_address, value, asset, category
        FROM ranked WHERE rn = 1 ORDER BY target_address ASC, block_num ASC, tx_hash ASC
        """
    else:
        export_sql = build_empty_onestep_history_sql("withdrawal_address")
    export_query_to_csv(conn, export_sql, EXPORT_FILENAMES["onestep_withdrawal_history"])


def query_tornadocash_transactions(address, table_groups, address_field, query_label):
    """
    @brief Queries Tornado Cash transactions across multiple tables.
    @param address Address to search.
    @param table_groups List of table groups to query.
    @param address_field Column name to search.
    @param query_label Log label.
    @return List of transaction rows.
    """
    conn = db_tools.connect_db()
    if not conn:
        return []
    tables = get_tornadocash_tables(table_groups)
    if not tables:
        print(f"[Warning] No tables configured for groups: {table_groups}")
        conn.close()
        return []
    queries = []
    for table in tables:
        queries.append(f"SELECT * FROM {table} WHERE \"{address_field}\" ILIKE %s")
    sql = " UNION ALL ".join(queries)
    results = db_tools.execute_query_params(conn, sql, [f"%{address}%"] * len(tables))
    conn.close()
    print(f"--- {query_label}: {address} ---")
    print("\ntotal rows:" + str(len(results)), "\n")
    for row in results:
        print("\n", row, "\n")
    return results


def query_transactions_by_from_address(address):
    """
    @brief Queries transactions from a specific from_address across deposit tables.
    @param address from_address to search.
    @return Transaction results.
    """
    return query_tornadocash_transactions(address, ["mainpool_deposit_table_list", "proxy_deposit_table_list"], "from_address", "Transactions from")


def query_transactions_by_to_address(address):
    """
    @brief Queries transactions to a specific to_address across withdraw tables.
    @param address to_address to search.
    @return Transaction results.
    """
    return query_tornadocash_transactions(address, ["withdraw_table_list"], "to_address", "Transactions to")


def init_db(conn):
    """
    @brief Initializes output schema and tables.
    @param conn Database connection.
    """
    cursor = conn.cursor()
    cursor.execute("CREATE SCHEMA IF NOT EXISTS onestep_clues_output;")
    create_main_table_sql = f"""
    CREATE TABLE IF NOT EXISTS {TARGET_MAIN_TABLE} (
        id BIGSERIAL PRIMARY KEY, pool_name VARCHAR(50), clue VARCHAR(100), clue_type VARCHAR(50),
        deposit_address VARCHAR(42), withdraw_address VARCHAR(42), score NUMERIC(10,4),
        total_tx_count INT, total_usd_value NUMERIC(15,2), deposit_num INT,
        first_deposit_hash VARCHAR(66), first_deposit_timestamp TIMESTAMP, last_deposit_timestamp TIMESTAMP,
        withdraw_num INT, first_withdraw_hash VARCHAR(66), first_withdraw_timestamp TIMESTAMP, last_withdraw_timestamp TIMESTAMP,
        verify_status BOOLEAN DEFAULT FALSE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, remark TEXT DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_trace_deposit ON {TARGET_MAIN_TABLE}(deposit_address);
    CREATE INDEX IF NOT EXISTS idx_trace_withdraw ON {TARGET_MAIN_TABLE}(withdraw_address);
    CREATE INDEX IF NOT EXISTS idx_trace_pool ON {TARGET_MAIN_TABLE}(pool_name);
    CREATE INDEX IF NOT EXISTS idx_trace_clue ON {TARGET_MAIN_TABLE}(clue);
    """
    create_detail_table_sql = f"""
    CREATE TABLE IF NOT EXISTS {TARGET_DETAIL_TABLE} (
        id BIGSERIAL PRIMARY KEY, trace_id BIGINT NOT NULL REFERENCES {TARGET_MAIN_TABLE}(id) ON DELETE CASCADE,
        step_order VARCHAR(20) NOT NULL, block_num BIGINT, block_timestamp TIMESTAMP, tx_hash VARCHAR(66),
        from_address VARCHAR(42), to_address VARCHAR(42), value NUMERIC, asset VARCHAR(50), category VARCHAR(100),
        none_relayer_caller_address VARCHAR(42), third_party_address VARCHAR(42), UNIQUE (trace_id, step_order)
    );
    CREATE INDEX IF NOT EXISTS idx_output_detail_trace_id ON {TARGET_DETAIL_TABLE}(trace_id);
    CREATE INDEX IF NOT EXISTS idx_output_detail_tx_hash ON {TARGET_DETAIL_TABLE}(tx_hash);
    CREATE INDEX IF NOT EXISTS idx_output_detail_addresses ON {TARGET_DETAIL_TABLE}(from_address, to_address);
    """
    cursor.execute(create_main_table_sql)
    cursor.execute(create_detail_table_sql)
    conn.commit()
    cursor.close()


def validate_output_detail_cascade_fk(conn):
    """
    @brief Validates that detail table has ON DELETE CASCADE foreign key.
    @param conn Database connection.
    """
    detail_schema, detail_table = TARGET_DETAIL_TABLE.split(".", 1)
    main_schema, main_table = TARGET_MAIN_TABLE.split(".", 1)
    cursor = conn.cursor()
    check_sql = """
    SELECT con.conname FROM pg_constraint con
    JOIN pg_class rel ON rel.oid = con.conrelid
    JOIN pg_namespace rel_nsp ON rel_nsp.oid = rel.relnamespace
    JOIN pg_class ref_rel ON ref_rel.oid = con.confrelid
    JOIN pg_namespace ref_nsp ON ref_nsp.oid = ref_rel.relnamespace
    JOIN pg_attribute src_att ON src_att.attrelid = rel.oid AND src_att.attnum = ANY(con.conkey)
    JOIN pg_attribute ref_att ON ref_att.attrelid = ref_rel.oid AND ref_att.attnum = ANY(con.confkey)
    WHERE con.contype = 'f' AND rel_nsp.nspname = %s AND rel.relname = %s
      AND ref_nsp.nspname = %s AND ref_rel.relname = %s
      AND src_att.attname = 'trace_id' AND ref_att.attname = 'id'
      AND con.confdeltype = 'c' LIMIT 1;
    """
    try:
        cursor.execute(check_sql, (detail_schema, detail_table, main_schema, main_table))
        fk_row = cursor.fetchone()
        if fk_row is None:
            raise RuntimeError(f"Missing required ON DELETE CASCADE foreign key: {TARGET_DETAIL_TABLE}.trace_id -> {TARGET_MAIN_TABLE}.id")
        print(f"Verified cascade foreign key: {fk_row[0]}")
    finally:
        cursor.close()


def clear_output_tables(conn):
    """
    @brief Truncates output main and detail tables.
    @param conn Database connection.
    """
    cursor = conn.cursor()
    cursor.execute(f"TRUNCATE TABLE {TARGET_DETAIL_TABLE}, {TARGET_MAIN_TABLE} RESTART IDENTITY CASCADE;")
    conn.commit()
    cursor.close()


def get_max_id(conn, table_name):
    """
    @brief Gets current max ID from a table.
    @param conn Database connection.
    @param table_name Fully qualified table name.
    @return Max ID, 0 if table is empty.
    """
    cursor = conn.cursor()
    cursor.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table_name};")
    max_id = cursor.fetchone()[0]
    cursor.close()
    return max_id


def import_group(conn, group_config):
    """
    @brief Imports one group of main and detail records into target table.
    @param conn Database connection.
    @param group_config Group configuration dict.
    """
    main_offset = get_max_id(conn, TARGET_MAIN_TABLE)
    detail_offset = get_max_id(conn, TARGET_DETAIL_TABLE)
    cursor = conn.cursor()

    main_insert_sql = f"""
    INSERT INTO {TARGET_MAIN_TABLE} (
        id, pool_name, clue, clue_type, deposit_address, withdraw_address,
        score, total_tx_count, total_usd_value, deposit_num,
        first_deposit_hash, first_deposit_timestamp, last_deposit_timestamp,
        withdraw_num, first_withdraw_hash, first_withdraw_timestamp, last_withdraw_timestamp,
        verify_status, created_at, remark
    )
    SELECT m.id + %s AS id, m.pool_name, %s AS clue, m.clue_type, m.deposit_address, m.withdraw_address,
           {group_config["score_expr"]} AS score, {group_config["total_tx_count_expr"]} AS total_tx_count,
           {group_config["total_usd_value_expr"]} AS total_usd_value, m.deposit_num,
           m.first_deposit_hash, m.first_deposit_timestamp, m.last_deposit_timestamp,
           m.withdraw_num, m.first_withdraw_hash, m.first_withdraw_timestamp, m.last_withdraw_timestamp,
           m.verify_status, m.created_at, {group_config["remark_expr"]} AS remark
    FROM {group_config["main_table"]} m
    WHERE {group_config["where_sql"]} ORDER BY m.id ASC;
    """

    detail_insert_sql = f"""
    INSERT INTO {TARGET_DETAIL_TABLE} (
        id, trace_id, step_order, block_num, block_timestamp, tx_hash,
        from_address, to_address, value, asset, category,
        none_relayer_caller_address, third_party_address
    )
    SELECT d.id + %s AS id, d.trace_id + %s AS trace_id,
           {group_config["step_order_expr"]} AS step_order, d.block_num, d.block_timestamp, d.tx_hash,
           d.from_address, d.to_address, d.value, d.asset, d.category,
           d.none_relayer_caller_address, d.third_party_address
    FROM {group_config["detail_table"]} d
    JOIN {group_config["main_table"]} m ON d.trace_id = m.id
    WHERE {group_config["where_sql"]} ORDER BY d.trace_id ASC, d.id ASC;
    """

    cursor.execute(main_insert_sql, (main_offset, group_config["clue"]))
    inserted_main_count = cursor.rowcount
    cursor.execute(detail_insert_sql, (detail_offset, main_offset))
    inserted_detail_count = cursor.rowcount
    conn.commit()
    cursor.close()
    print(f"Imported {group_config['name']}: {inserted_main_count} main rows, {inserted_detail_count} detail rows (main_offset={main_offset}, detail_offset={detail_offset})")


def clear_clue_type_data(conn, clue_type):
    """
    @brief Deletes all records of a specific clue_type from output table.
    @param conn Database connection.
    @param clue_type Clue type to delete.
    """
    cursor = conn.cursor()
    cursor.execute(f"DELETE FROM {TARGET_MAIN_TABLE} WHERE clue_type = %s", (clue_type,))
    deleted_count = cursor.rowcount
    conn.commit()
    cursor.close()
    print(f"Deleted {deleted_count} records with clue_type '{clue_type}'")


def build_blacklist_match_sql(table_alias=""):
    """
    @brief Builds SQL condition for blacklist address matching.
    @param table_alias Optional table alias.
    @return SQL condition string.
    """
    column_prefix = f"{table_alias}." if table_alias else ""
    return f"""
        ({column_prefix}deposit_address IS NOT NULL AND LOWER({column_prefix}deposit_address) = ANY(%s))
        OR ({column_prefix}withdraw_address IS NOT NULL AND LOWER({column_prefix}withdraw_address) = ANY(%s))
    """


def delete_blacklisted_clues(conn):
    """
    @brief Deletes clues where deposit_address or withdraw_address is blacklisted.
    @param conn Database connection.
    """
    if not NORMALIZED_BLACK_ADDRESS_LIST:
        print("No blacklisted addresses configured, skipped blacklist cleanup.")
        return
    cursor = conn.cursor()
    main_blacklist_match_sql = build_blacklist_match_sql()
    detail_blacklist_match_sql = build_blacklist_match_sql("m")
    count_main_sql = f"SELECT COUNT(*) FROM {TARGET_MAIN_TABLE} WHERE {main_blacklist_match_sql};"
    count_detail_sql = f"SELECT COUNT(*) FROM {TARGET_DETAIL_TABLE} d JOIN {TARGET_MAIN_TABLE} m ON d.trace_id = m.id WHERE {detail_blacklist_match_sql};"
    delete_main_sql = f"DELETE FROM {TARGET_MAIN_TABLE} WHERE {main_blacklist_match_sql};"
    params = (NORMALIZED_BLACK_ADDRESS_LIST, NORMALIZED_BLACK_ADDRESS_LIST)
    try:
        cursor.execute(count_main_sql, params)
        main_count = cursor.fetchone()[0]
        cursor.execute(count_detail_sql, params)
        detail_count = cursor.fetchone()[0]
        cursor.execute(delete_main_sql, params)
        deleted_main_count = cursor.rowcount
        conn.commit()
        print(f"Blacklist cleanup completed, removed {deleted_main_count} main rows and cascaded {detail_count} detail rows (matched_main_rows={main_count})")
    except Exception as e:
        conn.rollback()
        print(f"[Error] Blacklist cleanup failed: {e}")
        raise
    finally:
        cursor.close()


def deduplicate_by_addresses(conn):
    """
    @brief Deduplicates records by (pool_name, deposit_address, withdraw_address), keeping highest score.
    @param conn Database connection.
    """
    cursor = conn.cursor()
    count_total_sql = f"SELECT COUNT(*) FROM {TARGET_MAIN_TABLE};"
    deduplicate_sql = f"""
    WITH ranked_records AS (
        SELECT id, ROW_NUMBER() OVER (PARTITION BY pool_name, deposit_address, withdraw_address ORDER BY score DESC NULLS LAST, id ASC) AS rn
        FROM {TARGET_MAIN_TABLE}
    )
    DELETE FROM {TARGET_MAIN_TABLE} WHERE id IN (SELECT id FROM ranked_records WHERE rn > 1);
    """
    try:
        cursor.execute(count_total_sql)
        total_count = cursor.fetchone()[0]
        cursor.execute(deduplicate_sql)
        deleted_count = cursor.rowcount
        conn.commit()
        print(f"Deduplication completed, removed {deleted_count} duplicate records from {total_count} total main rows")
    except Exception as e:
        conn.rollback()
        print(f"[Error] Deduplication failed: {e}")
        raise
    finally:
        cursor.close()


def sync_serial_sequence(conn, table_name):
    """
    @brief Synchronizes serial sequence after explicit ID inserts.
    @param conn Database connection.
    @param table_name Fully qualified table name.
    """
    cursor = conn.cursor()
    sync_sql = f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), COALESCE((SELECT MAX(id) FROM {table_name}), 1), EXISTS (SELECT 1 FROM {table_name}));"
    cursor.execute(sync_sql)
    conn.commit()
    cursor.close()


def run_pipeline(conn):
    """
    @brief Executes complete data integration pipeline.
    @param conn Database connection.
    """
    export_onestep_deposit_address_history(conn)
    export_onestep_withdrawal_address_history(conn)


def main():
    """
    @brief Main entry point.
    """
    conn = db_tools.connect_db()
    if conn is None:
        raise RuntimeError("Database connection failed")
    try:
        run_pipeline(conn)
    finally:
        conn.close()


if __name__ == '__main__':
    main()