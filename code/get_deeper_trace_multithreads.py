"""
@file get_deeper_trace_multithreads.py
@brief Fetches one-hop transfer traces for Tornado Cash addresses via Alchemy API.

@details
Traverses all Tornado Cash deposit/withdraw addresses and fetches their
one-hop transfer records (both incoming and outgoing) using Alchemy's
alchemy_getAssetTransfers API with multi-threading.

Each address is processed to capture:
- Incoming transfers (toAddress = address)
- Outgoing transfers (fromAddress = address)

Data is stored in database tables with naming: {json_filename}_oneStep_in_out_trace.

Thread pool with configurable MAX_WORKERS (default 15).
"""
import os
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import time

from util.db_tools import connect_db
from util.log_tools import setup_logger
from config.config import ALCHEMY_BASE_URL


FILTER_CONTRACTS = {
    "0x12d66f87a04a9e220743712ce6d9bb1b5616b8fc",
    "0x47ce0c6ed5b0ce3d3a51fdb1c52dc66a7c3c2936",
    "0x910cbd523d972eb0a6f4cae4618ad62622b39dbf",
    "0xa160cdab225685da1d56aa342ad8841c3b53f291",
    "0x905b63fff465b9ffbf41dea908ceb12478ec7601",
    "0x722122df12d4e14e13ac3b6895a86e84145b6967",
    "0xd90e2f925da726b50c4ed8d0fb90ad053324f31b",
}

MAX_WORKERS = 15


def create_table(conn, table_name):
    """
    @brief Creates database table for one-hop trace data.
    @param conn Database connection.
    @param table_name Table name to create.
    """
    create_sql = f"""
    CREATE TABLE IF NOT EXISTS {table_name} (
        unique_id VARCHAR(255) PRIMARY KEY,
        transaction_type VARCHAR(20),
        direction VARCHAR(20),
        block_num BIGINT,
        block_timestamp TIMESTAMP,
        tx_hash VARCHAR(66),
        from_address VARCHAR(42),
        to_address VARCHAR(42),
        value NUMERIC,
        asset VARCHAR(255),
        category VARCHAR(100),
        raw_data JSONB,
        none_relayer_caller_address VARCHAR(42) DEFAULT NULL
    );
    """
    try:
        with conn.cursor() as cur:
            cur.execute(create_sql)
        conn.commit()
        logger.info(f"Table {table_name} checked/created successfully.")
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to create table {table_name}: {e}")


def fetch_alchemy_transfers(params):
    """
    @brief Calls Alchemy API to fetch asset transfer records.
    @param params API parameters dict.
    @return API response result dict or None on failure.
    """
    payload = {"id": 1, "jsonrpc": "2.0", "method": "alchemy_getAssetTransfers", "params": [params]}
    headers = {"Content-Type": "application/json"}

    for attempt in range(5):
        try:
            response = requests.post(ALCHEMY_BASE_URL, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            if "error" in data:
                logger.error(f"Alchemy API Error: {data['error']}, params: {params}")
                return None
            return data.get("result")
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1} failed: {e}, params: {params}")
            time.sleep(2 * (attempt + 1))

    logger.error(f"Max retries reached for Alchemy API. params: {params}")
    return None


def process_address(address, address_type, table_name, progress_counter, total_tasks, progress_lock):
    """
    @brief Processes single address transfers and stores to database.
    @param address Target address to trace.
    @param address_type 'deposit' or 'withdraw'.
    @param table_name Database table name for storage.
    @param progress_counter Shared progress counter list.
    @param total_tasks Total number of tasks.
    @param progress_lock Lock for progress counter.
    """
    with progress_lock:
        progress_counter[0] += 1
        current_idx = progress_counter[0]

    conn = connect_db()

    if address.lower() in FILTER_CONTRACTS:
        return

    if not conn:
        logger.error(f"Skipping address {address} due to DB connection failure.")
        return

    try:
        directions = [
            {"type": "incoming", "params": {"toAddress": address}, "dir_label": "transfer_in"},
            {"type": "outgoing", "params": {"fromAddress": address}, "dir_label": "transfer_out"}
        ]

        for direction in directions:
            seen_addresses = set()
            page_key = None
            while True:
                params = {
                    "fromBlock": "0x0",
                    "toBlock": "latest",
                    "category": ["external", "erc20"],
                    "withMetadata": True,
                    "excludeZeroValue": True,
                    "maxCount": "0x3e8",
                    "order": "asc"
                }
                params.update(direction["params"])
                if page_key:
                    params["pageKey"] = page_key

                result = fetch_alchemy_transfers(params)
                if not result:
                    break

                transfers = result.get("transfers", [])
                insert_data_list = []

                for tx in transfers:
                    if tx.get("asset") not in ["ETH", "USDC", "DAI", "WETH", "USDT", "TORN", "WBTC"]:
                        continue

                    from_addr = tx.get("from")
                    to_addr = tx.get("to")
                    counterparty = from_addr if direction["type"] == "incoming" else to_addr
                    counterparty_lower = counterparty.lower() if counterparty else None

                    if counterparty_lower and counterparty_lower in FILTER_CONTRACTS:
                        continue

                    if counterparty_lower in seen_addresses:
                        continue

                    if counterparty_lower:
                        seen_addresses.add(counterparty_lower)

                    unique_id = tx.get("uniqueId")
                    block_num = int(tx.get("blockNum"), 16) if tx.get("blockNum") else None
                    block_timestamp = tx.get("metadata", {}).get("blockTimestamp")
                    tx_hash = tx.get("hash")
                    value = tx.get("value")
                    asset = tx.get("asset")
                    category = tx.get("category")

                    from psycopg2.extras import Json
                    insert_data_list.append((
                        unique_id,
                        address_type,
                        direction["dir_label"],
                        block_num,
                        block_timestamp,
                        tx_hash,
                        from_addr,
                        to_addr,
                        value,
                        asset,
                        category,
                        Json(tx),
                        None
                    ))

                if insert_data_list:
                    from psycopg2.extras import execute_batch
                    insert_sql = f"""
                    INSERT INTO {table_name} (
                        unique_id, transaction_type, direction, block_num, block_timestamp,
                        tx_hash, from_address, to_address, value, asset, category,
                        raw_data, none_relayer_caller_address
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (unique_id) DO UPDATE SET
                        transaction_type = EXCLUDED.transaction_type,
                        direction = EXCLUDED.direction,
                        block_num = EXCLUDED.block_num,
                        block_timestamp = EXCLUDED.block_timestamp,
                        tx_hash = EXCLUDED.tx_hash,
                        from_address = EXCLUDED.from_address,
                        to_address = EXCLUDED.to_address,
                        value = EXCLUDED.value,
                        asset = EXCLUDED.asset,
                        category = EXCLUDED.category,
                        raw_data = EXCLUDED.raw_data,
                        none_relayer_caller_address = EXCLUDED.none_relayer_caller_address;
                    """
                    try:
                        with conn.cursor() as cur:
                            execute_batch(cur, insert_sql, insert_data_list)
                        conn.commit()
                    except Exception as e:
                        conn.rollback()
                        logger.error(f"DB Insert Error for {address}: {e}")

                page_key = result.get("pageKey")
                if not page_key:
                    break

    except Exception as e:
        logger.error(f"Error processing address {address}: {e}")
    finally:
        conn.close()


def get_deeper_trace_four_pools(file_paths):
    """
    @brief Processes four pool files to fetch one-hop traces.
    @param file_paths List of JSON file paths for deposit/withdraw addresses.
    """
    global logger
    for file_path in file_paths:
        file_name = os.path.basename(file_path)
        table_name = os.path.splitext(file_name)[0] + "_oneStep_in_out_trace"
        logger = setup_logger(f"{table_name}.log")

        if not os.path.exists(file_path):
            logger.warning(f"File not found: {file_path}")
            continue

        conn = connect_db()
        if conn:
            create_table(conn, table_name)
            conn.close()
        else:
            logger.error("Initial DB connection failed. Exiting.")
            exit()

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to read JSON {file_path}: {e}")
            continue

        deposit_addresses = data.get("deposit_address", [])
        withdraw_addresses = data.get("withdraw_address", [])

        total_tasks = len(deposit_addresses) + len(withdraw_addresses)
        logger.info(f"Processing {file_name}: {total_tasks} tasks ({len(deposit_addresses)} deposits, {len(withdraw_addresses)} withdraws).")

        tasks = []
        progress_counter = [0]
        progress_lock = threading.Lock()

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            for addr in deposit_addresses:
                tasks.append(executor.submit(process_address, addr, "deposit", table_name, progress_counter, total_tasks, progress_lock))
            for addr in withdraw_addresses:
                tasks.append(executor.submit(process_address, addr, "withdraw", table_name, progress_counter, total_tasks, progress_lock))

            for future in as_completed(tasks):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Task failed: {e}")

        logger.info(f"Finished processing file: {file_path}")


def get_deeper_trace_for_none_relayer_caller_address(file_paths):
    """
    @brief Processes none_relayer_caller_address files to fetch one-hop traces.
    @param file_paths List of JSON file paths for none_relayer_caller addresses.
    """
    global logger
    for file_path in file_paths:
        file_name = os.path.basename(file_path)
        table_name = os.path.splitext(file_name)[0] + "_oneStep_in_out_trace"
        logger = setup_logger(f"{table_name}.log")

        if not os.path.exists(file_path):
            logger.warning(f"File not found: {file_path}")
            continue

        conn = connect_db()
        if conn:
            create_table(conn, table_name)
            conn.close()
        else:
            logger.error("Initial DB connection failed. Exiting.")
            exit()

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to read JSON {file_path}: {e}")
            continue

        none_relayer_caller_address = data.get("none_relayer_caller_address", [])

        total_tasks = len(none_relayer_caller_address)
        logger.info(f"Processing {file_name}: {total_tasks} tasks ({len(none_relayer_caller_address)} none_relayer_caller_address).")

        tasks = []
        progress_counter = [0]
        progress_lock = threading.Lock()

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            for addr in none_relayer_caller_address:
                tasks.append(executor.submit(process_address, addr, "withdraw", table_name, progress_counter, total_tasks, progress_lock))

            for future in as_completed(tasks):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Task failed: {e}")

        logger.info(f"Finished processing file: {file_path}")


if __name__ == "__main__":
    tornadocash_pool_file_path = [
        "/Shuxun/AML_for_Blockchain/tornadocash_data/tornadocash_100eth_deposit_withdraw_address.json",
        "/Shuxun/AML_for_Blockchain/tornadocash_data/tornadocash_10eth_deposit_withdraw_address.json",
        "/Shuxun/AML_for_Blockchain/tornadocash_data/tornadocash_1eth_deposit_withdraw_address.json",
        "/Shuxun/AML_for_Blockchain/tornadocash_data/tornadocash_0_1eth_deposit_withdraw_address.json",
        "/Shuxun/AML_for_Blockchain/tornadocash_data/tornadocash_proxy_router_100ETH_deposit_withdraw_address.json",
        "/Shuxun/AML_for_Blockchain/tornadocash_data/tornadocash_proxy_router_10ETH_deposit_withdraw_address.json",
        "/Shuxun/AML_for_Blockchain/tornadocash_data/tornadocash_proxy_router_1ETH_deposit_withdraw_address.json",
        "/Shuxun/AML_for_Blockchain/tornadocash_data/tornadocash_proxy_router_0_1ETH_deposit_withdraw_address.json"
    ]

    get_deeper_trace_four_pools(tornadocash_pool_file_path)

    tornadocash_pool_file_path = [
        "/Shuxun/AML_for_Blockchain/tornadocash_data/tornadocash_100eth_withdraw_transfers_none_relayer_caller_address.json",
        "/Shuxun/AML_for_Blockchain/tornadocash_data/tornadocash_10eth_withdraw_transfers_none_relayer_caller_address.json",
        "/Shuxun/AML_for_Blockchain/tornadocash_data/tornadocash_1eth_withdraw_transfers_none_relayer_caller_address.json",
        "/Shuxun/AML_for_Blockchain/tornadocash_data/tornadocash_0_1eth_withdraw_transfers_none_relayer_caller_address.json"
    ]

    get_deeper_trace_for_none_relayer_caller_address(tornadocash_pool_file_path)