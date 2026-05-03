"""
@file get_internal_transfer_caller.py
@brief Fetches transaction initiators via Alchemy Trace API.

@details
Queries transaction initiators (EOA callers) for Tornado Cash withdraw transactions
using the trace_transaction API. Each tx_hash is processed to find the top-level
trace (traceAddress == []) which represents the original EOA caller.

Multi-threaded processing with thread pool of 10 workers.
"""
import requests
import time
import concurrent.futures
import threading

from util import db_tools, log_tools
from config import config


BASE_URL = config.ALCHEMY_BASE_URL


tornado_cash_withdraw_table_list = [
    "tornadocash_0_1eth_withdraw_transfers",
    "tornadocash_1eth_withdraw_transfers",
    "tornadocash_10eth_withdraw_transfers",
    "tornadocash_100eth_withdraw_transfers",
]

logger = log_tools.setup_logger("get_internal_transaction_caller.log")


def send_request(payload):
    """
    @brief Sends HTTP POST request to Alchemy API with exponential backoff retry.
    @param payload Request payload dict.
    @return Response JSON dict.
    @throws Exception if all retries fail.
    """
    headers = {"accept": "application/json", "content-type": "application/json"}
    max_retries = 5

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(BASE_URL, json=payload, headers=headers, timeout=15)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.warning(f"Request failed (attempt {attempt}/{max_retries}): {e}")
            if attempt == max_retries:
                logger.error(f"All {max_retries} attempts failed. Payload: {payload}")
                raise
            logger.info("Network jitter detected. Retrying...")
            time.sleep(2 ** attempt)


def get_tx_initiator(tx_hash):
    """
    @brief Queries transaction initiator (EOA) using trace_transaction API.
    @param tx_hash Transaction hash.
    @return Initiator address string or None if not found.
    """
    payload = {"id": 1, "jsonrpc": "2.0", "method": "trace_transaction", "params": [tx_hash]}

    try:
        data = send_request(payload)
        result = data.get("result")

        if not result:
            logger.warning(f"No trace data found for transaction: {tx_hash}")
            return None

        for trace in result:
            if trace.get("traceAddress") == []:
                action = trace.get("action", {})
                initiator = action.get("from")
                logger.info(f"Found {tx_hash} caller: {initiator}")
                return initiator

        logger.warning("Could not find top-level trace (traceAddress == []).")
        return None

    except Exception as e:
        logger.error(f"Error processing transaction {tx_hash}: {e}")
        return None


def process_tables():
    """
    @brief Main processing function: queries tx initiators and updates database.
    """
    conn = db_tools.connect_db()
    if not conn:
        logger.error("Cannot connect to database. Exiting.")
        return

    db_lock = threading.Lock()

    try:
        for table_name in tornado_cash_withdraw_table_list:
            logger.info(f"========== Processing table: {table_name} ==========\n\n")

            with conn.cursor() as cur:
                logger.info(f"Ensuring column 'none_relayer_caller_address' exists in {table_name}...")
                alter_query = f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS none_relayer_caller_address VARCHAR(42);"
                cur.execute(alter_query)
                conn.commit()

                logger.info(f"Fetching target transactions from {table_name}...")
                select_query = f"""
                SELECT tx_hash FROM (
                    SELECT tx_hash, none_relayer_caller_address, COUNT(*) OVER (PARTITION BY tx_hash) as cnt
                    FROM {table_name}
                ) sub
                WHERE cnt = 1 AND none_relayer_caller_address IS NULL;
                """
                cur.execute(select_query)
                rows = cur.fetchall()

            total_rows = len(rows)
            logger.info(f"Found {total_rows} transactions to process in {table_name}")

            def process_tx_task(row, idx):
                tx_hash = row[0]
                logger.info(f"[{idx + 1}/{total_rows}] Processing tx: {tx_hash}")

                initiator = get_tx_initiator(tx_hash)

                if initiator:
                    logger.info(f"Result - Tx Hash: {tx_hash}, Initiator: {initiator}")
                    with db_lock:
                        with conn.cursor() as update_cur:
                            update_query = f"UPDATE {table_name} SET none_relayer_caller_address = %s WHERE tx_hash = %s;"
                            update_cur.execute(update_query, (initiator, tx_hash))
                            conn.commit()
                else:
                    logger.warning(f"Failed to find initiator for {tx_hash}")

                time.sleep(0.1)

            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(process_tx_task, row, index) for index, row in enumerate(rows)]
                concurrent.futures.wait(futures)

    except Exception as e:
        logger.error(f"Database error occurred: {e}")
    finally:
        if conn:
            conn.close()
            logger.info("Database connection closed.")


if __name__ == "__main__":
    process_tables()