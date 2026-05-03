"""
@file get_tornado_cash_deposit_withdraw_caller_address.py
@brief Extracts Tornado Cash deposit/withdraw addresses and non-relayer caller addresses.

@details
Extracts addresses from four Tornado Cash pools (0.1/1/10/100 ETH) via direct interaction
and proxy contracts, then saves them as JSON files organized by pool.

Functions:
1. filter_tornadocash_address(conn) - Extracts EOA addresses from direct interactions
2. extract_none_relayer_caller_address(conn) - Extracts non-relayer withdraw caller addresses
3. filter_tornado_cash_proxy_address(conn, direct_data) - Extracts proxy deposit addresses

Output: 4 JSON files (one per pool) with deposit_address, withdraw_address,
        none_relayer_caller_address, and proxy_deposit_address arrays.
"""
import re
import os

from util import fio
from util import db_tools


OUT_PUT_DIR = "/Shuxun/AML_for_Blockchain/tornadocash_data/temp"
POOL_KEYS = ["0_1", "1", "10", "100"]

TORNADOCASH_DIRECT_TABLE_LIST = [
    {"withdraw": "tornadocash_0_1eth_withdraw_transfers", "deposit": "tornadocash_0_1eth_deposit_transfers", "pool_key": "0_1"},
    {"withdraw": "tornadocash_1eth_withdraw_transfers", "deposit": "tornadocash_1eth_deposit_transfers", "pool_key": "1"},
    {"withdraw": "tornadocash_10eth_withdraw_transfers", "deposit": "tornadocash_10eth_deposit_transfers", "pool_key": "10"},
    {"withdraw": "tornadocash_100eth_withdraw_transfers", "deposit": "tornadocash_100eth_deposit_transfers", "pool_key": "100"},
]

TORNADOCASH_PROXY_TABLE_LIST = [
    ["tornadorouter_deposit_transfers", "tornadorouter_withdraw_transfers"],
    ["tornadocash_newproxy_deposit_transfers", "tornadocash_newproxy_withdraw_transfers"],
    ["tornadocash_oldproxy_deposit_transfers", "tornadocash_oldproxy_withdraw_transfers"],
]

VALUE_TO_POOL_KEY = {100.0: "100", 10.0: "10", 1.0: "1", 0.1: "0_1"}

WITHDRAW_TABLE_MAPPING = [
    {"table": "tornadocash_100eth_withdraw_transfers", "pool_key": "100"},
    {"table": "tornadocash_10eth_withdraw_transfers", "pool_key": "10"},
    {"table": "tornadocash_1eth_withdraw_transfers", "pool_key": "1"},
    {"table": "tornadocash_0_1eth_withdraw_transfers", "pool_key": "0_1"},
]


def filter_tornadocash_address(conn):
    """
    @brief Extracts deposit and withdraw EOA addresses from Tornado Cash direct interaction tables.
    @param conn Database connection object.
    @return dict Map of pool_key to {"deposit_address": [...], "withdraw_address": [...]}.
    """
    cursor = conn.cursor()
    result = {}

    for table_pair in TORNADOCASH_DIRECT_TABLE_LIST:
        deposit_table = table_pair["deposit"]
        withdraw_table = table_pair["withdraw"]
        pool_key = table_pair["pool_key"]

        cursor.execute(f"SELECT DISTINCT from_address FROM {deposit_table} WHERE category = 'external';")
        deposit_addresses = [row[0] for row in cursor.fetchall()]

        cursor.execute(f"""
            SELECT DISTINCT to_address FROM (
                SELECT DISTINCT ON (tx_hash) to_address FROM {withdraw_table}
                ORDER BY tx_hash, value DESC
            ) AS unique_tx_representatives;
        """)
        withdraw_addresses = [row[0] for row in cursor.fetchall()]

        result[pool_key] = {"deposit_address": deposit_addresses, "withdraw_address": withdraw_addresses}

    cursor.close()
    return result


def extract_none_relayer_caller_address(conn):
    """
    @brief Extracts non-relayer caller addresses from withdraw tables.
    @param conn Database connection object.
    @return dict Map of pool_key to none_relayer_caller_address list.
    """
    cursor = conn.cursor()
    result = {}

    for item in WITHDRAW_TABLE_MAPPING:
        table_name = item["table"]
        pool_key = item["pool_key"]

        cursor.execute(f"""
            SELECT DISTINCT none_relayer_caller_address FROM {table_name}
            WHERE none_relayer_caller_address IS NOT NULL AND none_relayer_caller_address != '';
        """)
        result[pool_key] = [row[0] for row in cursor.fetchall()]

    cursor.close()
    return result


def filter_tornado_cash_proxy_address(conn, direct_data):
    """
    @brief Extracts proxy deposit addresses and removes those already in direct_data.
    @param conn Database connection object.
    @param direct_data Result from filter_tornadocash_address().
    @return dict Map of pool_key to proxy deposit/withdraw address lists.
    """
    cursor = conn.cursor()
    pools = {pk: {"proxy_deposit_address": [], "proxy_withdraw_address": []} for pk in POOL_KEYS}

    for table_pair in TORNADOCASH_PROXY_TABLE_LIST:
        deposit_table = table_pair[0]
        withdraw_table = table_pair[1]

        cursor.execute(f"""
            SELECT DISTINCT from_address, value FROM {deposit_table}
            WHERE value IN (100.0, 10.0, 1.0, 0.1) AND category = 'external';
        """)
        results = cursor.fetchall()

        for row in results:
            address, value = row[0], float(row[1])
            pool_key = VALUE_TO_POOL_KEY.get(value)
            if pool_key:
                pools[pool_key]["proxy_deposit_address"].append(address)

    for pool_key in POOL_KEYS:
        pools[pool_key]["proxy_deposit_address"] = list(set(pools[pool_key]["proxy_deposit_address"]))

        if pool_key in direct_data:
            direct_deposit_set = set(direct_data[pool_key].get("deposit_address", []))
            pools[pool_key]["proxy_deposit_address"] = list(
                set(pools[pool_key]["proxy_deposit_address"]) - direct_deposit_set
            )

    cursor.close()
    return pools


if __name__ == "__main__":
    if not os.path.exists(OUT_PUT_DIR):
        os.makedirs(OUT_PUT_DIR)

    conn = db_tools.connect_db()

    direct_data = filter_tornadocash_address(conn)
    none_relayer_data = extract_none_relayer_caller_address(conn)
    proxy_data = filter_tornado_cash_proxy_address(conn, direct_data)

    for pool_key in POOL_KEYS:
        deposit_address = direct_data.get(pool_key, {}).get("deposit_address", [])
        withdraw_address = direct_data.get(pool_key, {}).get("withdraw_address", [])
        none_relayer_addr = none_relayer_data.get(pool_key, [])
        proxy_deposit_addr = proxy_data.get(pool_key, {}).get("proxy_deposit_address", [])

        merged_data = {
            "deposit_address": deposit_address,
            "deposit_address_num": len(deposit_address),
            "proxy_deposit_address": proxy_deposit_addr,
            "proxy_deposit_address_num": len(proxy_deposit_addr),
            "withdraw_address": withdraw_address,
            "withdraw_address_num": len(withdraw_address),
            "none_relayer_caller_address": none_relayer_addr,
            "none_relayer_caller_address_num": len(none_relayer_addr)
        }

        filename = f"tornadocash_{pool_key}eth_all_addresses.json"
        fio.save_to_json(merged_data, os.path.join(OUT_PUT_DIR, filename))

    conn.close()