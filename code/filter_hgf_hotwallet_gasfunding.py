"""
@file filter_hgf_hotwallet_gasfunding.py
@brief Filters hot wallet addresses from gas funding detection results.

@details
Queries gas_funder addresses from BTFI detection results and checks their
labels in address_labels table. If any keyword match is found, updates
verify_status to false and adds a remark.

Used to filter out exchange service addresses that may have been incorrectly
identified as gas funders.
"""
from util import db_tools
from util import fio
import json
from tqdm import tqdm


conn = db_tools.connect_db()


def ensure_columns_exist(conn, table_name):
    """
    @brief Ensures verify_status and remark columns exist in target table.
    @param conn Database connection.
    @param table_name Target table name.
    """
    cursor = conn.cursor()
    columns_to_ensure = {
        'verify_status': 'BOOLEAN DEFAULT true',
        'remark': 'TEXT'
    }

    for col, definition in columns_to_ensure.items():
        check_sql = f"""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'onestep_clues' AND table_name = '{table_name}' AND column_name = '{col}'
        """
        cursor.execute(check_sql)
        if not cursor.fetchone():
            print(f"Adding column '{col}' to table 'onestep_clues.{table_name}'...")
            alter_sql = f"ALTER TABLE onestep_clues.\"{table_name}\" ADD COLUMN {col} {definition}"
            cursor.execute(alter_sql)
            conn.commit()
    cursor.close()


def filter_table_by_keywords(conn, table_name, key_word_list):
    """
    @brief Filters gas_funder addresses based on keyword match in address labels.
    @param conn Database connection.
    @param table_name Target table name.
    @param key_word_list List of keywords to filter (e.g., EXCHANGE, DEX, SERVICES).
    """
    cursor = conn.cursor()

    print(f"[{table_name}] Fetching records...")
    sql_get_records = f"SELECT id, gas_funder FROM onestep_clues.\"{table_name}\" WHERE gas_funder IS NOT NULL AND gas_funder != ''"
    try:
        cursor.execute(sql_get_records)
        records = cursor.fetchall()
    except Exception as e:
        print(f"[{table_name}] Error fetching records: {e}")
        conn.rollback()
        return

    unique_addresses = {rec[1] for rec in records if rec[1].strip()}
    if not unique_addresses:
        print(f"[{table_name}] No addresses found.")
        return

    address_list = list(unique_addresses)
    batch_size = 1000
    addr_label_map = {}

    print(f"[{table_name}] Fetching labels from database...")
    for i in tqdm(range(0, len(address_list), batch_size), desc="Fetching labels"):
        batch = address_list[i:i + batch_size]
        placeholders = ', '.join(['%s'] * len(batch))
        sql_labels = f"SELECT target_address, main_entity_info FROM onestep_clues.address_labels WHERE target_address IN ({placeholders})"
        cursor.execute(sql_labels, batch)
        results = cursor.fetchall()

        for addr, info_json in results:
            try:
                if info_json:
                    if isinstance(info_json, str):
                        addr_label_map[addr] = json.loads(info_json)
                    else:
                        addr_label_map[addr] = info_json
            except Exception:
                pass

    updates = []

    print(f"[{table_name}] Matching keywords...")
    for row_id, gas_funder in tqdm(records, desc="Matching"):
        if gas_funder in addr_label_map:
            entity_info = addr_label_map[gas_funder]
            entity_name = entity_info.get("entity", "Unknown")
            categories = entity_info.get("categories") or []

            matched_cat = None
            for cat in categories:
                cat_name = cat.get("name", "").upper()
                if cat_name in [k.upper() for k in key_word_list]:
                    matched_cat = cat_name
                    break

            if matched_cat:
                remark_str = f"Filtered: {entity_name} - {matched_cat}"
                updates.append((remark_str, row_id))

    if updates:
        print(f"[{table_name}] Updating {len(updates)} records...")
        sql_update = f"""
            UPDATE onestep_clues.\"{table_name}\"
            SET verify_status = false,
                remark = CONCAT_WS('\n', NULLIF(remark, ''), %s)
            WHERE id = %s
        """
        try:
            for i in tqdm(range(0, len(updates), 1000), desc="Updating DB"):
                cursor.executemany(sql_update, updates[i:i+1000])
                conn.commit()
            print(f"[{table_name}] Update completed.")
        except Exception as e:
            conn.rollback()
            print(f"[{table_name}] Error updating database: {e}")
    else:
        print(f"[{table_name}] No records matched the keywords.")

    cursor.close()


if __name__ == '__main__':
    table_list = [
        "100ETH_BTFI_gas_funding_candidates",
        "10ETH_BTFI_gas_funding_candidates",
        "1ETH_BTFI_gas_funding_candidates",
        "0_1ETH_BTFI_gas_funding_candidates"
    ]
    key_word_list = [
        "EXCHANGE", "SERVICES", "DEX", "STAKING", "GAMBLING",
        "Maker", "MARKETPLACE", "MINING POOL", "FARMING", "AGGREGATOR", "ECOMMERCE"
    ]

    if conn:
        for table in table_list:
            print(f"\n--- Processing table: {table} ---")
            ensure_columns_exist(conn, table)
            filter_table_by_keywords(conn, table, key_word_list)
        conn.close()
    else:
        print("Failed to connect to the database.")