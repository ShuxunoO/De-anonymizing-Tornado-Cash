"""
@file filter_tornado_cash_proxy_address.py
@brief Extracts Tornado Cash proxy/router deposit addresses.

@details
Queries three proxy/router tables (tornadorouter, newproxy, oldproxy) to find
deposit addresses that used proxy contracts, then merges and deduplicates across pools.
"""
from util import fio
from util import db_tools
import os


def merge_two_list(list1, list2):
    """
    @brief Merges two lists and removes duplicates.
    @param list1 First list.
    @param list2 Second list.
    @return Merged and deduplicated list.
    """
    merged_set = set(list1) | set(list2)
    return list(merged_set)


def extract_data_from_sql_query_twotables(conn, table1_name, table2_name, transaction_type, direction):
    """
    @brief Extracts address data from two tables using SQL query.
    @param conn Database connection.
    @param table1_name First table name.
    @param table2_name Second table name.
    @param transaction_type 'deposit' or 'withdraw'.
    @param direction 'transfer_in' or 'transfer_out'.
    @return List of addresses.
    """
    target = "from_address" if direction == "transfer_in" else "to_address"

    query_sql = f"""
        SELECT {target} FROM {table1_name}
        WHERE transaction_type = '{transaction_type}' AND direction = '{direction}'
        UNION
        SELECT {target} FROM {table2_name}
        WHERE transaction_type = '{transaction_type}' AND direction = '{direction};
    """
    result = db_tools.execute_query(conn, query_sql)
    return [row[0] for row in result]


def extract_data_from_sql_query_onetable(conn, table_name, transaction_type, direction):
    """
    @brief Extracts address data from a single table.
    @param conn Database connection.
    @param table_name Table name.
    @param transaction_type 'deposit' or 'withdraw'.
    @param direction 'transfer_in' or 'transfer_out'.
    @return List of addresses.
    """
    target = "from_address" if direction == "transfer_in" else "to_address"

    query_sql = f"""SELECT DISTINCT {target} FROM {table_name}
                    WHERE transaction_type = '{transaction_type}'
                    AND direction = '{direction}';"""
    result = db_tools.execute_query(conn, query_sql)
    return [row[0] for row in result]


if __name__ == "__main__":
    conn = db_tools.connect_db()
    if conn is None:
        print("Database connection failed")
        exit(1)

    tornadocash_data_dir = "/Shuxun/AML_for_Blockchain/tornadocash_data"
    output_dir = os.path.join(tornadocash_data_dir, "onestep_clues_v2_gasfunding")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    file_mapping = {
        "100ETH": {"pool_address_file": "tornadocash_100eth_deposit_withdraw_address.json",
                   "proxy_router_address_file": "tornadocash_proxy_router_100ETH_deposit_withdraw_address.json",
                   "none_relayer_withdrawer_address_file": "tornadocash_100eth_withdraw_transfers_none_relayer_caller_address.json",
                   "pool_onestep_in_out_trace_db": "tornadocash_100eth_deposit_withdraw_address_onestep_in_out_trac",
                   "proxy_router_onestep_in_out_trace_db": "tornadocash_proxy_router_100eth_deposit_withdraw_address_oneste",
                   "none_relayer_withdrawer_address_onestep_in_out_trace_db": "tornadocash_100eth_withdraw_transfers_none_relayer_caller_addre"},
        "10ETH": {"pool_address_file": "tornadocash_10eth_deposit_withdraw_address.json",
                  "proxy_router_address_file": "tornadocash_proxy_router_10ETH_deposit_withdraw_address.json",
                  "none_relayer_withdrawer_address_file": "tornadocash_10eth_withdraw_transfers_none_relayer_caller_address.json",
                  "pool_onestep_in_out_trace_db": "tornadocash_10eth_deposit_withdraw_address_onestep_in_out_trace",
                  "proxy_router_onestep_in_out_trace_db": "tornadocash_proxy_router_10eth_deposit_withdraw_address_onestep",
                  "none_relayer_withdrawer_address_onestep_in_out_trace_db": "tornadocash_10eth_withdraw_transfers_none_relayer_caller_addres"},
        "1ETH": {"pool_address_file": "tornadocash_1eth_deposit_withdraw_address.json",
                 "proxy_router_address_file": "tornadocash_proxy_router_1ETH_deposit_withdraw_address.json",
                 "none_relayer_withdrawer_address_file": "tornadocash_1eth_withdraw_transfers_none_relayer_caller_address.json",
                 "pool_onestep_in_out_trace_db": "tornadocash_1eth_deposit_withdraw_address_onestep_in_out_trace",
                 "proxy_router_onestep_in_out_trace_db": "tornadocash_proxy_router_1eth_deposit_withdraw_address_onestep_",
                 "none_relayer_withdrawer_address_onestep_in_out_trace_db": "tornadocash_1eth_withdraw_transfers_none_relayer_caller_address"},
        "0_1ETH": {"pool_address_file": "tornadocash_0_1eth_deposit_withdraw_address.json",
                   "proxy_router_address_file": "tornadocash_proxy_router_0_1ETH_deposit_withdraw_address.json",
                   "none_relayer_withdrawer_address_file": "tornadocash_0_1eth_withdraw_transfers_none_relayer_caller_address.json",
                   "pool_onestep_in_out_trace_db": "tornadocash_0_1eth_deposit_withdraw_address_onestep_in_out_trac",
                   "proxy_router_onestep_in_out_trace_db": "tornadocash_proxy_router_0_1eth_deposit_withdraw_address_oneste",
                   "none_relayer_withdrawer_address_onestep_in_out_trace_db": "tornadocash_0_1eth_withdraw_transfers_none_relayer_caller_addre"}
    }

    output_data_template = {
        "deposit_address": [], "deposit_address_num": 0,
        "deposit_address_transfer_in_address": [], "deposit_address_transfer_in_address_num": 0,
        "deposit_address_transfer_out_address": [], "deposit_address_transfer_out_address_num": 0,
        "recipient_address": [], "recipient_address_num": 0,
        "recipient_address_transfer_in_address": [], "recipient_address_transfer_in_address_num": 0,
        "recipient_address_transfer_out_address": [], "recipient_address_transfer_out_address_num": 0,
        "none_relayer_withdrawer_address": [], "none_relayer_withdrawer_address_num": 0,
        "none_relayer_withdrawer_address_transfer_in_address": [], "none_relayer_withdrawer_address_transfer_in_address_num": 0,
        "none_relayer_withdrawer_address_transfer_out_address": [], "none_relayer_withdrawer_address_transfer_out_address_num": 0
    }

    pool_size_list = ["100ETH", "10ETH", "1ETH", "0_1ETH"]
    transaction_type_list = ["deposit", "withdraw"]
    direction_list = ["transfer_in", "transfer_out"]

    for pool_size in pool_size_list:
        print(f"\n\nProcessing pool size: {pool_size}...\n\n")
        output_data = output_data_template.copy()

        pool_address_file = fio.load_json(os.path.join(tornadocash_data_dir, file_mapping[pool_size]["pool_address_file"]))
        proxy_router_address_file = fio.load_json(os.path.join(tornadocash_data_dir, file_mapping[pool_size]["proxy_router_address_file"]))

        if pool_address_file is None:
            pool_address_file = {}
        if proxy_router_address_file is None:
            proxy_router_address_file = {}

        pool_deposit_address_list = pool_address_file.get("deposit_address", [])
        proxy_router_deposit_address_list = proxy_router_address_file.get("deposit_address", [])
        merged_deposit_address_list = merge_two_list(pool_deposit_address_list, proxy_router_deposit_address_list)
        output_data["deposit_address"] = merged_deposit_address_list
        output_data["deposit_address_num"] = len(merged_deposit_address_list)

        output_data["recipient_address"] = pool_address_file.get("withdraw_address", [])
        output_data["recipient_address_num"] = len(output_data["recipient_address"])

        none_relayer_withdrawer_address_file = fio.load_json(os.path.join(tornadocash_data_dir, file_mapping[pool_size]["none_relayer_withdrawer_address_file"]))
        if none_relayer_withdrawer_address_file is None:
            none_relayer_withdrawer_address_file = {}

        output_data["none_relayer_withdrawer_address"] = none_relayer_withdrawer_address_file.get("none_relayer_caller_address", [])
        output_data["none_relayer_withdrawer_address_num"] = len(output_data["none_relayer_withdrawer_address"])

        table1_name = file_mapping[pool_size]["pool_onestep_in_out_trace_db"]
        table2_name = file_mapping[pool_size]["proxy_router_onestep_in_out_trace_db"]

        for transaction_type in transaction_type_list:
            for direction in direction_list:
                target_address_list = extract_data_from_sql_query_twotables(conn, table1_name, table2_name, transaction_type, direction)
                target_address_list = list(set(target_address_list))

                if transaction_type == "deposit":
                    output_data[f"{transaction_type}_address_{direction}_address"] = target_address_list
                    output_data[f"{transaction_type}_address_{direction}_address_num"] = len(target_address_list)
                else:
                    output_data[f"recipient_address_{direction}_address"] = target_address_list
                    output_data[f"recipient_address_{direction}_address_num"] = len(target_address_list)

        for direction in direction_list:
            table_name = file_mapping[pool_size]["none_relayer_withdrawer_address_onestep_in_out_trace_db"]
            target_address_list = extract_data_from_sql_query_onetable(conn, table_name, "withdraw", direction)
            target_address_list = list(set(target_address_list))
            output_data[f"none_relayer_withdrawer_address_{direction}_address"] = target_address_list
            output_data[f"none_relayer_withdrawer_address_{direction}_address_num"] = len(target_address_list)

        fio.save_to_json(output_data, os.path.join(output_dir, f"{pool_size}_onestep_transfer_in_out.json"))

    if conn:
        conn.close()