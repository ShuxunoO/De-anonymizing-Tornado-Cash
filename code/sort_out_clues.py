"""
@file sort_out_clues.py
@brief Sorts and categorizes clues from one-hop trace data.

@details
Computes various clue categories (a1, a2, a3, b1-b4, c1-c3) by analyzing
set intersections between deposit addresses, withdraw addresses, and their
transfer in/out addresses from the one-hop trace database.

Each clue type represents a different pattern of association:
- a* : Direct reuse or direct transfer between addresses
- b* : Shared third-party addresses
- c* : Relations involving non-relayer caller addresses
"""
from util import fio
import os
from config import config


clues_definition = """Clue Categories

Internal time constraints for clues:
    1. Deposit time must be earlier than withdraw time
    2. Gas funding time must be earlier than withdraw time

a1: Same address used for both deposit and withdraw (address_reuse)
    Statistical method: Intersection of deposit and withdraw address sets

a2: Deposit address transferred to withdraw address directly
    Method 1: to_address of deposit's transfer-out exists in withdraw address set
    Method 2: from_address of withdraw's transfer-in exists in deposit address set

a3: Withdraw address transferred to deposit address directly
    Method 1: to_address of withdraw's transfer-out exists in deposit address set
    Method 2: from_address of deposit's transfer-in exists in withdraw address set

b1: Deposit and withdraw addresses share the same incoming address
    Method: Intersection of deposit's transfer-in from_address and withdraw's transfer-in from_address

b2: Withdraw address's outgoing address transferred to deposit address
    Method: Intersection of withdraw's transfer-out to_address and deposit's transfer-in from_address

b3: Both deposit and withdraw addresses transferred to same non-exchange hot wallet/contract
    Method: Intersection of deposit's transfer-out to_address and withdraw's transfer-out to_address

b4: Deposit address's outgoing address transferred to withdraw address
    Method: Intersection of deposit's transfer-out to_address and withdraw's transfer-in from_address

c1: Deposit address directly initiated withdraw transaction
    Method: Intersection of deposit address set and withdraw tx initiator set

c2: Deposit address transferred to withdraw tx initiator directly
    Method 1: Withdraw tx initiator set intersects with deposit's transfer-out to_address
    Method 2: Withdraw tx initiator's transfer-in from_address intersects with deposit address set

c3: Withdraw tx initiator transferred to deposit address directly
    Method 1: Withdraw tx initiator's transfer-out to_address intersects with deposit address set
    Method 2: Deposit address's transfer-in from_address intersects with withdraw tx initiator set
"""


if __name__ == '__main__':
    onestep_base_dir = os.path.join(config.tornadocash_data_dir, "onestep_clues_gasfunding")
    if not os.path.exists(onestep_base_dir):
        os.makedirs(onestep_base_dir)

    file_list = [
        "100ETH_onestep_transfer_in_out.json",
        "10ETH_onestep_transfer_in_out.json",
        "1ETH_onestep_transfer_in_out.json",
        "0_1ETH_onestep_transfer_in_out.json",
    ]

    for file_name in file_list:
        data = fio.load_json(os.path.join(onestep_base_dir, file_name))
        deposit_address = data['deposit_address']
        deposit_address_transfer_in_address = data['deposit_address_transfer_in_address']
        deposit_address_transfer_out_address = data['deposit_address_transfer_out_address']

        recipient_address = data['recipient_address']
        recipient_address_transfer_in_address = data['recipient_address_transfer_in_address']
        recipient_address_transfer_out_address = data['recipient_address_transfer_out_address']

        none_relayer_withdrawer_address = data['none_relayer_withdrawer_address']
        none_relayer_withdrawer_address_transfer_in_address = data['none_relayer_withdrawer_address_transfer_in_address']
        none_relayer_withdrawer_address_transfer_out_address = data['none_relayer_withdrawer_address_transfer_out_address']
        output_data = {"clues_definition": clues_definition}

        output_data['a1'] = list(set(deposit_address) & set(recipient_address))
        output_data['a1_num'] = len(output_data['a1'])
        print(f"[Stats] {file_name} | a1: found {output_data['a1_num']} clues")

        a2_1 = list(set(deposit_address_transfer_out_address) & set(recipient_address))
        output_data["a2_1"] = a2_1
        output_data["a2_1_num"] = len(a2_1)
        print(f"[Stats] {file_name} | a2_1: found {len(a2_1)} clues")

        a2_2 = list(set(recipient_address_transfer_in_address) & set(deposit_address))
        output_data["a2_2"] = a2_2
        output_data["a2_2_num"] = len(a2_2)
        print(f"[Stats] {file_name} | a2_2: found {len(a2_2)} clues")

        a3_1 = list(set(recipient_address_transfer_out_address) & set(deposit_address))
        output_data["a3_1"] = a3_1
        output_data["a3_1_num"] = len(a3_1)
        print(f"[Stats] {file_name} | a3_1: found {len(a3_1)} clues")

        a3_2 = list(set(deposit_address_transfer_in_address) & set(recipient_address))
        output_data["a3_2"] = a3_2
        output_data["a3_2_num"] = len(a3_2)
        print(f"[Stats] {file_name} | a3_2: found {len(a3_2)} clues")

        b1 = list(set(deposit_address_transfer_in_address) & set(recipient_address_transfer_in_address))
        output_data["b1"] = b1
        output_data["b1_num"] = len(b1)
        print(f"[Stats] {file_name} | b1: found {len(b1)} clues")

        b2 = list(set(recipient_address_transfer_out_address) & set(deposit_address_transfer_in_address))
        output_data["b2"] = b2
        output_data["b2_num"] = len(b2)
        print(f"[Stats] {file_name} | b2: found {len(b2)} clues")

        b3 = list(set(deposit_address_transfer_out_address) & set(recipient_address_transfer_out_address))
        output_data["b3"] = b3
        output_data["b3_num"] = len(b3)
        print(f"[Stats] {file_name} | b3: found {len(b3)} clues")

        b4 = list(set(deposit_address_transfer_out_address) & set(recipient_address_transfer_in_address))
        output_data["b4"] = b4
        output_data["b4_num"] = len(b4)
        print(f"[Stats] {file_name} | b4: found {len(b4)} clues")

        c1 = list(set(deposit_address) & set(none_relayer_withdrawer_address))
        output_data["c1"] = c1
        output_data["c1_num"] = len(c1)
        print(f"[Stats] {file_name} | c1: found {len(c1)} clues")

        c2_1 = list(set(deposit_address_transfer_out_address) & set(none_relayer_withdrawer_address))
        output_data["c2_1"] = c2_1
        output_data["c2_1_num"] = len(c2_1)
        print(f"[Stats] {file_name} | c2_1: found {len(c2_1)} clues")

        c2_2 = list(set(none_relayer_withdrawer_address_transfer_in_address) & set(deposit_address))
        output_data["c2_2"] = c2_2
        output_data["c2_2_num"] = len(c2_2)
        print(f"[Stats] {file_name} | c2_2: found {len(c2_2)} clues")

        c3_1 = list(set(none_relayer_withdrawer_address_transfer_out_address) & set(deposit_address))
        output_data["c3_1"] = c3_1
        output_data["c3_1_num"] = len(c3_1)
        print(f"[Stats] {file_name} | c3_1: found {len(c3_1)} clues")

        c3_2 = list(set(deposit_address_transfer_in_address) & set(none_relayer_withdrawer_address))
        output_data["c3_2"] = c3_2
        output_data["c3_2_num"] = len(c3_2)
        print(f"[Stats] {file_name} | c3_2: found {len(c3_2)} clues")

        fio.save_to_json(output_data, os.path.join(onestep_base_dir, f"{file_name[:-5]}_onestep_clues.json"))