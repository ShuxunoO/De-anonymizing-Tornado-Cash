"""
@file get_tornadoCash_gas_data_by_Alchemy_multithreading.py
@brief Fetches Tornado Cash transaction details via Alchemy API with multi-threading.

@details
Retrieves transaction details (eth_getTransactionByHash + eth_getTransactionReceipt)
from Alchemy API to supplement missing data in existing database records.

Features:
1. Modifies database schema to add missing fields
2. Fetches transaction details by hash
3. Round-robin API key management with failure handling
4. Batch processing with progress tracking
5. Incremental updates to avoid reprocessing
"""
from util import db_tools
from util import log_tools
from config import config
import requests
import time
from tqdm import tqdm
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed


conn = db_tools.connect_db()
api_list = config.Alchemy_API_key_list
logger = None


class ApiKeyManager:
    """
    @brief Manages multiple Alchemy API keys for round-robin polling in multi-threaded environment.
    """
    def __init__(self, keys):
        self.keys = keys
        self.current_index = 0
        self.failed_keys = set()
        self.call_count = 0
        self.lock = threading.Lock()

    def get_key(self):
        """@brief Returns next available API key in round-robin fashion."""
        with self.lock:
            if len(self.failed_keys) >= len(self.keys):
                return None
            for _ in range(len(self.keys)):
                key = self.keys[self.current_index % len(self.keys)]
                self.current_index += 1
                if key not in self.failed_keys:
                    return key
            return None

    def mark_failed(self, key):
        """@brief Marks a key as failed due to rate limiting or errors."""
        with self.lock:
            if key not in self.failed_keys:
                self.failed_keys.add(key)
                remaining = len(self.keys) - len(self.failed_keys)
                logger.warning(f"Alchemy API Key ...{key[-4:]} marked failed, remaining: {remaining}")

    def reset_failed(self):
        """@brief Resets all failed keys to available state."""
        with self.lock:
            self.failed_keys.clear()
            logger.info("Reset all Alchemy API Key failure states")

    def increment_call(self):
        """@brief Increments total call counter."""
        with self.lock:
            self.call_count += 1

    def get_stats(self):
        """@brief Returns API usage statistics."""
        with self.lock:
            return {
                "total_calls": self.call_count,
                "total_keys": len(self.keys),
                "failed_keys": len(self.failed_keys),
                "available_keys": len(self.keys) - len(self.failed_keys)
            }


api_manager = None


def hex_to_int(hex_str):
    """
    @brief Converts hex string to integer.
    @param hex_str Hex string (e.g., '0x1a4').
    @return Integer value or None if conversion fails.
    """
    if hex_str and isinstance(hex_str, str) and hex_str.startswith('0x'):
        try:
            return int(hex_str, 16)
        except ValueError:
            return None
    return None


def update_db_schema(table_name_list):
    """
    @brief Adds missing columns to database tables for transaction details.
    @param table_name_list List of table names to update.
    """
    cursor = conn.cursor()
    for table_name in table_name_list:
        logger.info(f"Updating schema for table: {table_name}")
        alter_statements = [
            f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS gas_limit NUMERIC",
            f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS gas_price NUMERIC",
            f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS max_fee_per_gas NUMERIC",
            f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS max_priority_fee_per_gas NUMERIC",
            f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS effectiveGasPrice NUMERIC",
            f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS gasUsed NUMERIC",
            f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS nonce BIGINT",
            f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS transaction_index INTEGER",
            f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS input_data TEXT",
            f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS tx_type VARCHAR(10)",
            f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS chain_id VARCHAR(50)"
        ]
        try:
            for sql in alter_statements:
                cursor.execute(sql)
            conn.commit()
            logger.info(f"Table {table_name} schema update complete")
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to update table {table_name} schema: {e}")
    cursor.close()


def get_pending_tx_hashes(table_name, batch_size=100):
    """
    @brief Gets transaction hashes that are missing details.
    @param table_name Table name.
    @param batch_size Number of records to fetch.
    @return List of transaction hashes.
    """
    cursor = conn.cursor()
    select_sql = f"""
        SELECT tx_hash FROM {table_name}
        WHERE effectiveGasPrice IS NULL OR gasUsed IS NULL
        LIMIT {batch_size};
    """
    cursor.execute(select_sql)
    rows = cursor.fetchall()
    cursor.close()
    return [row[0] for row in rows]


def _call_alchemy_rpc(method: str, tx_hash: str):
    """
    @brief Calls Alchemy JSON-RPC API (eth_getTransactionByHash or eth_getTransactionReceipt).
    @param method RPC method name.
    @param tx_hash Transaction hash.
    @return Result dict or None on failure.
    """
    max_retries = len(api_list)

    for attempt in range(max_retries):
        api_key = api_manager.get_key()
        if api_key is None:
            logger.error("All Alchemy API keys failed")
            return None

        url = f"https://eth-mainnet.g.alchemy.com/v2/{api_key}"

        payload = {"jsonrpc": "2.0", "method": method, "params": [tx_hash], "id": attempt + 1}

        try:
            if attempt > 0:
                time.sleep(0.2)

            response = requests.post(url, json=payload, timeout=12)
            data = response.json()
            api_manager.increment_call()

            if "error" in data:
                err = data["error"]
                msg = err.get("message", "")
                logger.warning(f"Alchemy RPC Error [{method}] (Key ...{api_key[-4:]}): {msg}")

                if response.status_code == 429 or "rate limit" in msg.lower() or err.get("code") == -32005:
                    api_manager.mark_failed(api_key)
                time.sleep(0.6)
                continue

            return data.get("result")

        except requests.exceptions.RequestException as e:
            logger.error(f"Network request exception [{method}] {tx_hash}: {e}")
            time.sleep(0.5)
        except Exception as e:
            logger.error(f"Processing failed [{method}] {tx_hash}: {e}")
            time.sleep(0.5)

    return None


def fetch_transaction_detail(tx_hash):
    """
    @brief Fetches both transaction and receipt data and merges them.
    @param tx_hash Transaction hash.
    @return Merged dict or None if both calls fail.
    """
    basic_info = _call_alchemy_rpc("eth_getTransactionByHash", tx_hash)
    receipt_info = _call_alchemy_rpc("eth_getTransactionReceipt", tx_hash)

    if basic_info is None and receipt_info is None:
        logger.warning(f"Failed to fetch any data for: {tx_hash}")
        return None

    merged = {}
    if isinstance(basic_info, dict):
        merged.update(basic_info)
    if isinstance(receipt_info, dict):
        merged.update(receipt_info)

    return merged


def update_transaction_record(cursor, table_name, tx_hash, tx_detail):
    """
    @brief Updates a single transaction record with fetched details.
    @param cursor Database cursor.
    @param table_name Table name.
    @param tx_hash Transaction hash.
    @param tx_detail Merged transaction detail dict.
    @return True on success, False on failure.
    """
    try:
        gas_limit = hex_to_int(tx_detail.get('gas'))
        gas_price = hex_to_int(tx_detail.get('gasPrice'))
        nonce = hex_to_int(tx_detail.get('nonce'))
        tx_index = hex_to_int(tx_detail.get('transactionIndex'))
        max_fee = hex_to_int(tx_detail.get('maxFeePerGas'))
        max_priority = hex_to_int(tx_detail.get('maxPriorityFeePerGas'))
        gas_used = hex_to_int(tx_detail.get('gasUsed'))
        effective_gas_price = hex_to_int(tx_detail.get('effectiveGasPrice'))
        input_data = tx_detail.get('input') or '0x'
        tx_type = tx_detail.get('type')
        chain_id = tx_detail.get('chainId')

        update_sql = f"""
            UPDATE {table_name} SET
                gas_limit = %s, gas_price = %s, max_fee_per_gas = %s,
                max_priority_fee_per_gas = %s, effectiveGasPrice = %s, gasUsed = %s,
                nonce = %s, transaction_index = %s, input_data = %s,
                tx_type = %s, chain_id = %s
            WHERE tx_hash = %s
        """
        cursor.execute(update_sql, (
            gas_limit, gas_price, max_fee, max_priority,
            effective_gas_price, gas_used, nonce, tx_index,
            input_data, tx_type, chain_id, tx_hash
        ))
        return True
    except Exception as e:
        logger.error(f"Failed to update record {tx_hash}: {e}")
        return False


def process_table(table_name):
    """
    @brief Multi-threaded processing for a single table.
    @param table_name Table name to process.
    @return Tuple of (total_success, total_failed) counts.
    """
    logger.info(f"\n\n========== Processing table: {table_name} ==========\n\n")
    cursor = conn.cursor()

    total_success = 0
    total_failed = 0
    batch_num = 0

    max_workers = len(api_list) if len(api_list) > 0 else 1
    logger.info(f"Thread pool max workers: {max_workers}")

    while True:
        batch_size = max_workers * 20
        tx_hashes = get_pending_tx_hashes(table_name, batch_size=batch_size)

        if not tx_hashes:
            logger.info(f"Table {table_name} no more pending records")
            break

        batch_num += 1
        logger.info(f"Batch {batch_num}: Fetching {len(tx_hashes)} records...")

        batch_results = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_tx = {executor.submit(fetch_transaction_detail, tx): tx for tx in tx_hashes}

            for future in tqdm(as_completed(future_to_tx), total=len(tx_hashes), desc=f"Batch {batch_num} (Fetching)", unit="tx"):
                tx_hash = future_to_tx[future]
                try:
                    result = future.result()
                    batch_results.append((tx_hash, result))
                except Exception as e:
                    logger.error(f"Thread task exception {tx_hash}: {e}")
                    batch_results.append((tx_hash, None))

        logger.info(f"Batch {batch_num}: Fetch complete, writing to database...")
        batch_success = 0
        batch_failed = 0

        for tx_hash, tx_detail in batch_results:
            if tx_detail:
                if update_transaction_record(cursor, table_name, tx_hash, tx_detail):
                    batch_success += 1
                else:
                    batch_failed += 1
            else:
                try:
                    cursor.execute(f"UPDATE {table_name} SET input_data = 'NOT_FOUND' WHERE tx_hash = %s", (tx_hash,))
                except Exception:
                    pass
                batch_failed += 1

        try:
            conn.commit()
            logger.info(f"Batch {batch_num} committed: success {batch_success}, failed {batch_failed}")
        except Exception as e:
            conn.rollback()
            logger.error(f"Batch {batch_num} commit failed: {e}")

        total_success += batch_success
        total_failed += batch_failed

    cursor.close()
    logger.info(f"Table {table_name} complete: total success {total_success}, total failed {total_failed}")
    return total_success, total_failed


if __name__ == "__main__":
    logger = log_tools.setup_logger("get_tornadoCash_data_by_Alchemy.log")

    api_manager = ApiKeyManager(api_list)

    db_name_list = [
        "tornadocash_100eth_deposit_transfers",
        "tornadocash_100eth_withdraw_transfers",
        "tornadocash_10eth_deposit_transfers",
        "tornadocash_10eth_withdraw_transfers",
        "tornadocash_1eth_deposit_transfers",
        "tornadocash_1eth_withdraw_transfers",
        "tornadocash_0_1eth_deposit_transfers",
        "tornadocash_0_1eth_withdraw_transfers",
        "tornadocash_oldproxy_deposit_transfers",
        "tornadocash_newproxy_deposit_transfers",
        "tornadorouter_deposit_transfers"
    ]

    logger.info("===== Script Start (Alchemy Node API) =====")
    logger.info(f"Available Alchemy API Keys: {len(api_list)}")

    grand_total_success = 0
    grand_total_failed = 0

    for db_name in db_name_list:
        try:
            success, failed = process_table(db_name)
            grand_total_success += success
            grand_total_failed += failed
        except Exception as e:
            logger.critical(f"Critical error processing table {db_name}: {e}")

    logger.info("===== All Tasks Complete =====")
    logger.info(f"Total API calls: {api_manager.call_count}")
    logger.info(f"Total success: {grand_total_success}, Total failed: {grand_total_failed}")

    conn.close()