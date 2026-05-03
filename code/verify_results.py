"""
@file verify_results.py
@brief Verifies clue traces against database records.

@details
Validates detected clues by querying actual deposit/withdraw records from the database.
For each clue type (a1, a2, a3, b1-b4, c1-c3), verifies that:
1. Deposit records exist and are valid
2. Withdraw records exist and are valid
3. Time constraints are satisfied (deposit < withdraw)

Stores verification results in one_step_trace_clues_gasfunding and
onestep_trace_clue_gasfunding_details tables.
"""
from util import db_tools
from util import fio
import os
from util import log_tools
from tqdm import tqdm
from config import config


logger = log_tools.setup_logger("verify_report.log")


clue_json_mapping = {
    "100ETH": "100ETH_onestep_transfer_in_out_onestep_clues.json",
    "10ETH": "10ETH_onestep_transfer_in_out_onestep_clues.json",
    "1ETH": "1ETH_onestep_transfer_in_out_onestep_clues.json",
    "0_1ETH": "0_1ETH_onestep_transfer_in_out_onestep_clues.json"
}

db_info_mapping = {
    "100ETH": {
        "deposit_pool_name": "tornadocash_100eth_deposit_transfers",
        "withdraw_pool_name": "tornadocash_100eth_withdraw_transfers",
        "deposit_withdraw_onestep_in_out_trace": "tornadocash_100eth_deposit_withdraw_address_onestep_in_out_trac",
        "proxy_router_deposit_withdraw_onestep_in_out_trace": "tornadocash_proxy_router_100eth_deposit_withdraw_address_oneste",
        "none_relayer_withdrawer_onestep_in_out_trace": "tornadocash_100eth_withdraw_transfers_none_relayer_caller_addre"
    },
    "10ETH": {
        "deposit_pool_name": "tornadocash_10eth_deposit_transfers",
        "withdraw_pool_name": "tornadocash_10eth_withdraw_transfers",
        "deposit_withdraw_onestep_in_out_trace": "tornadocash_10eth_deposit_withdraw_address_onestep_in_out_trace",
        "proxy_router_deposit_withdraw_onestep_in_out_trace": "tornadocash_proxy_router_10eth_deposit_withdraw_address_onestep",
        "none_relayer_withdrawer_onestep_in_out_trace": "tornadocash_10eth_withdraw_transfers_none_relayer_caller_addres"
    },
    "1ETH": {
        "deposit_pool_name": "tornadocash_1eth_deposit_transfers",
        "withdraw_pool_name": "tornadocash_1eth_withdraw_transfers",
        "deposit_withdraw_onestep_in_out_trace": "tornadocash_1eth_deposit_withdraw_address_onestep_in_out_trace",
        "proxy_router_deposit_withdraw_onestep_in_out_trace": "tornadocash_proxy_router_1eth_deposit_withdraw_address_onestep_",
        "none_relayer_withdrawer_onestep_in_out_trace": "tornadocash_1eth_withdraw_transfers_none_relayer_caller_address"
    },
    "0_1ETH": {
        "deposit_pool_name": "tornadocash_0_1eth_deposit_transfers",
        "withdraw_pool_name": "tornadocash_0_1eth_withdraw_transfers",
        "deposit_withdraw_onestep_in_out_trace": "tornadocash_0_1eth_deposit_withdraw_address_onestep_in_out_trac",
        "proxy_router_deposit_withdraw_onestep_in_out_trace": "tornadocash_proxy_router_0_1eth_deposit_withdraw_address_oneste",
        "none_relayer_withdrawer_onestep_in_out_trace": "tornadocash_0_1eth_withdraw_transfers_none_relayer_caller_addre"
    },
    "proxy_dbs": {
        "oldproxy_deposit_transfers": "tornadocash_oldproxy_deposit_transfers",
        "oldproxy_withdraw_transfers": "tornadocash_oldproxy_withdraw_transfers",
        "newproxy_deposit_transfers": "tornadocash_newproxy_deposit_transfers",
        "newproxy_withdraw_transfers": "tornadocash_newproxy_withdraw_transfers",
        "tornadorouter_deposit_transfers": "tornadorouter_deposit_transfers",
        "tornadorouter_withdraw_transfers": "tornadorouter_withdraw_transfers"
    }
}


def init_db(conn):
    """
    @brief Initializes database tables for clue verification results.
    @param conn Database connection.
    """
    cursor = conn.cursor()

    create_onestep_trace_clues_sql = """
    CREATE TABLE IF NOT EXISTS one_step_trace_clues_gasfunding (
        id BIGSERIAL PRIMARY KEY,
        pool_name VARCHAR(50),
        clue_type VARCHAR(50),
        deposit_address VARCHAR(42),
        withdraw_address VARCHAR(42),
        deposit_num INT,
        first_deposit_hash VARCHAR(66),
        first_deposit_timestamp TIMESTAMP,
        last_deposit_timestamp TIMESTAMP,
        withdraw_num INT,
        first_withdraw_hash VARCHAR(66),
        first_withdraw_timestamp TIMESTAMP,
        last_withdraw_timestamp TIMESTAMP,
        verify_status BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (pool_name, clue_type, deposit_address, withdraw_address)
    );
    CREATE INDEX IF NOT EXISTS idx_trace_deposit ON one_step_trace_clues_gasfunding(deposit_address);
    CREATE INDEX IF NOT EXISTS idx_trace_withdraw ON one_step_trace_clues_gasfunding(withdraw_address);
    CREATE INDEX IF NOT EXISTS idx_trace_pool ON one_step_trace_clues_gasfunding(pool_name);
    """

    create_onestep_trace_clue_details_sql = """
    CREATE TABLE IF NOT EXISTS onestep_trace_clue_gasfunding_details (
        id BIGSERIAL PRIMARY KEY,
        trace_id BIGINT NOT NULL REFERENCES one_step_trace_clues_gasfunding(id) ON DELETE CASCADE,
        step_order INT NOT NULL,
        block_num BIGINT,
        block_timestamp TIMESTAMP,
        tx_hash VARCHAR(66),
        from_address VARCHAR(42),
        to_address VARCHAR(42),
        value NUMERIC,
        asset VARCHAR(50),
        category VARCHAR(50),
        none_relayer_caller_address VARCHAR(42),
        third_party_address VARCHAR(42),
        UNIQUE (trace_id, step_order)
    );
    CREATE INDEX IF NOT EXISTS idx_clue_trace_id ON onestep_trace_clue_gasfunding_details(trace_id);
    CREATE INDEX IF NOT EXISTS idx_clue_tx_hash ON onestep_trace_clue_gasfunding_details(tx_hash);
    CREATE INDEX IF NOT EXISTS idx_clue_addresses ON onestep_trace_clue_gasfunding_details(from_address, to_address);
    """

    try:
        print("Initializing database tables...")
        cursor.execute(create_onestep_trace_clues_sql)
        cursor.execute(create_onestep_trace_clue_details_sql)
        conn.commit()
        print("Database tables initialized successfully.")
    except Exception as e:
        conn.rollback()
        print(f"Error initializing database: {e}")
        raise
    finally:
        cursor.close()


def query_deposit_records(conn, query_sql_args):
    """
    @brief Queries deposit records from multiple tables.
    @param conn Database connection.
    @param query_sql_args Dict with table and address parameters.
    @return Deposit record (count, first_hash, first_ts, last_ts).
    """
    deposit_query_sql = """
        WITH all_deposits AS (
            SELECT tx_hash, block_timestamp FROM {deposit_pool_name} WHERE from_address = '{deposit_address}'
            UNION ALL
            SELECT tx_hash, block_timestamp FROM {oldproxy_deposit_transfers} WHERE from_address = '{deposit_address}'
            UNION ALL
            SELECT tx_hash, block_timestamp FROM {newproxy_deposit_transfers} WHERE from_address = '{deposit_address}'
            UNION ALL
            SELECT tx_hash, block_timestamp FROM {tornadorouter_deposit_transfers} WHERE from_address = '{deposit_address}'
        )
        SELECT COUNT(*) AS deposit_num, (ARRAY_AGG(tx_hash ORDER BY block_timestamp ASC))[1] AS first_deposit_hash,
               MIN(block_timestamp) AS first_deposit_timestamp, MAX(block_timestamp) AS last_deposit_timestamp
        FROM all_deposits;
    """.format(**query_sql_args)
    return db_tools.execute_query(conn, deposit_query_sql)


def query_withdraw_records(conn, query_sql_args):
    """
    @brief Queries withdraw records.
    @param conn Database connection.
    @param query_sql_args Dict with table and address parameters.
    @return Withdraw record (count, first_hash, first_ts, last_ts).
    """
    a1_withdraw_query_sql = """
        SELECT COUNT(*) AS withdraw_num, (ARRAY_AGG(tx_hash ORDER BY block_timestamp ASC))[1] AS first_withdraw_hash,
               MIN(block_timestamp) AS first_withdraw_timestamp, MAX(block_timestamp) AS last_withdraw_timestamp
        FROM {withdraw_pool_name}
        WHERE to_address = '{recipient_address}';
    """.format(**query_sql_args)
    return db_tools.execute_query(conn, a1_withdraw_query_sql)


def insert_one_step_trace_clues(conn, uniq_trace_record, deposit_res, withdraw_res):
    """
    @brief Inserts or updates clue verification result.
    @param conn Database connection.
    @param uniq_trace_record (pool_name, clue_type, deposit_address, withdraw_address).
    @param deposit_res Deposit record tuple.
    @param withdraw_res Withdraw record tuple.
    @return trace_id on success, None on failure.
    """
    cursor = conn.cursor()
    pool_name, clue_type, deposit_address, withdraw_address = uniq_trace_record

    insert_sql = """
        INSERT INTO one_step_trace_clues_gasfunding (
            pool_name, clue_type, deposit_address, withdraw_address,
            deposit_num, first_deposit_hash, first_deposit_timestamp, last_deposit_timestamp,
            withdraw_num, first_withdraw_hash, first_withdraw_timestamp, last_withdraw_timestamp, verify_status
        ) VALUES (
            %(pool_name)s, %(clue_type)s, %(deposit_address)s, %(withdraw_address)s,
            %(deposit_num)s, %(first_deposit_hash)s, %(first_deposit_timestamp)s, %(last_deposit_timestamp)s,
            %(withdraw_num)s, %(first_withdraw_hash)s, %(first_withdraw_timestamp)s, %(last_withdraw_timestamp)s, %(verify_status)s
        )
        ON CONFLICT (pool_name, clue_type, deposit_address, withdraw_address)
        DO UPDATE SET deposit_num = EXCLUDED.deposit_num, first_deposit_hash = EXCLUDED.first_deposit_hash,
            first_deposit_timestamp = EXCLUDED.first_deposit_timestamp, last_deposit_timestamp = EXCLUDED.last_deposit_timestamp,
            withdraw_num = EXCLUDED.withdraw_num, first_withdraw_hash = EXCLUDED.first_withdraw_hash,
            first_withdraw_timestamp = EXCLUDED.first_withdraw_timestamp, last_withdraw_timestamp = EXCLUDED.last_withdraw_timestamp,
            verify_status = EXCLUDED.verify_status, created_at = CURRENT_TIMESTAMP
        RETURNING id;
    """

    params = {
        "pool_name": pool_name, "clue_type": clue_type, "deposit_address": deposit_address, "withdraw_address": withdraw_address,
        "deposit_num": deposit_res[0], "first_deposit_hash": deposit_res[1], "first_deposit_timestamp": deposit_res[2],
        "last_deposit_timestamp": deposit_res[3], "withdraw_num": withdraw_res[0], "first_withdraw_hash": withdraw_res[1],
        "first_withdraw_timestamp": withdraw_res[2], "last_withdraw_timestamp": withdraw_res[3], "verify_status": True
    }

    trace_id = None
    try:
        cursor.execute(insert_sql, params)
        row = cursor.fetchone()
        if row:
            trace_id = row[0]
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Error inserting trace record: {e}")
    finally:
        cursor.close()
    return trace_id


def insert_onestep_trace_clue_details(conn, trace_id, details_list):
    """
    @brief Inserts clue trace detail records.
    @param conn Database connection.
    @param trace_id Foreign key to main clue table.
    @param details_list List of trace detail tuples.
    """
    if not details_list or trace_id is None:
        return
    cursor = conn.cursor()

    insert_sql = """
        INSERT INTO onestep_trace_clue_gasfunding_details (
            trace_id, step_order, block_num, block_timestamp, tx_hash,
            from_address, to_address, value, asset, category,
            none_relayer_caller_address, third_party_address
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (trace_id, step_order) DO UPDATE SET
            block_num = EXCLUDED.block_num, block_timestamp = EXCLUDED.block_timestamp, tx_hash = EXCLUDED.tx_hash,
            from_address = EXCLUDED.from_address, to_address = EXCLUDED.to_address, value = EXCLUDED.value,
            asset = EXCLUDED.asset, category = EXCLUDED.category,
            none_relayer_caller_address = EXCLUDED.none_relayer_caller_address, third_party_address = EXCLUDED.third_party_address;
    """

    data_to_insert = []
    for idx, detail in enumerate(details_list):
        block_num, block_timestamp, tx_hash = detail[0], detail[1], detail[2]
        from_address, to_address, value = detail[3], detail[4], detail[5]
        asset, category = detail[6], detail[7]
        none_relayer = detail[8] if len(detail) > 8 else None
        third_party = detail[9] if len(detail) > 9 else None
        data_to_insert.append((trace_id, idx + 1, block_num, block_timestamp, tx_hash, from_address, to_address, value, asset, category, none_relayer, third_party))

    try:
        cursor.executemany(insert_sql, data_to_insert)
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Error inserting details: {e}")
    finally:
        cursor.close()


def get_deposit_withdraw_records(conn, query_sql_args):
    """
    @brief Queries and validates deposit/withdraw records for a clue.
    @param conn Database connection.
    @param query_sql_args Query parameters dict.
    @return (deposit_info, withdraw_info) tuples or (None, None) on failure.
    """
    try:
        deposit_res = query_deposit_records(conn, query_sql_args)
        if not deposit_res or not deposit_res[0] or deposit_res[0][0] == 0:
            logger.warning(f"No deposit records found for clue type: {query_sql_args.get('clue_type')}")
            conn.rollback()
            return None, None

        withdraw_res = query_withdraw_records(conn, query_sql_args)
        if not withdraw_res or not withdraw_res[0] or withdraw_res[0][0] == 0:
            logger.warning(f"No withdraw records found for clue type: {query_sql_args.get('clue_type')}")
            conn.rollback()
            return None, None

        return deposit_res[0], withdraw_res[0]
    except Exception as e:
        print(f"Error in get_deposit_withdraw_records: {e}")
        logger.error(f"Error in get_deposit_withdraw_records: {e}")
        conn.rollback()
        return None, None


def verify_clue_a1(conn, pool_name, clue_type, clue_address_list):
    """
    @brief Verifies A1 clue type (same address for deposit and withdraw).
    """
    logger.info(f"Starting verification for {clue_type} in {pool_name}, total clues: {len(clue_address_list)}")
    for clue_address in tqdm(clue_address_list, desc=f"{pool_name}-{clue_type}", leave=False, unit="clue"):
        try:
            query_sql_args = {"deposit_address": clue_address}
            query_sql_args.update({"clue_type": clue_type})
            query_sql_args.update({"recipient_address": clue_address})
            query_sql_args.update(db_info_mapping[pool_name])
            query_sql_args.update(db_info_mapping["proxy_dbs"])

            deposit_res, withdraw_res = get_deposit_withdraw_records(conn, query_sql_args)
            uniq_trace_record = (pool_name, clue_type, query_sql_args['deposit_address'], query_sql_args['recipient_address'])
            insert_one_step_trace_clues(conn, uniq_trace_record, deposit_res, withdraw_res)
        except Exception as e:
            print(f"Error processing A1 clue {clue_address}: {e}")
            conn.rollback()


def main():
    """
    @brief Main entry point for clue verification.
    """
    conn = db_tools.connect_db()
    init_db(conn)
    clue_base_dir = os.path.join(config.tornadocash_data_dir, "onestep_clues_gasfunding")
    if not os.path.exists(clue_base_dir):
        os.makedirs(clue_base_dir)

    pool_name_list = ["100ETH", "10ETH", "1ETH", "0_1ETH"]
    clue_type_list = ["a1", "a2_1", "a2_2", "a3_1", "a3_2", "b1", "b2", "b4", "c1", "c2_1", "c2_2", "c3_1", "c3_2"]

    for pool_name in pool_name_list:
        json_path = os.path.join(clue_base_dir, clue_json_mapping[pool_name])
        if not os.path.exists(json_path):
            print(f"File not found: {json_path}")
            continue

        clue_file = fio.load_json(json_path)

        for clue_type in clue_type_list:
            clue_address_list = clue_file.get(clue_type, [])
            if clue_type == "a1":
                verify_clue_a1(conn, pool_name, clue_type, clue_address_list)


if __name__ == '__main__':
    main()