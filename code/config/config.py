"""
@file config.py
@brief Configuration constants and paths for the Tornado Cash analysis project.

@details
Defines base directories, API keys, and other configuration constants
used across the codebase.
"""
import os

base_dir = "xxx"
log_dir = os.path.join(base_dir, "logs")
if not os.path.exists(log_dir):
    os.makedirs(log_dir)
tornadocash_data_dir = os.path.join(base_dir, "tornadocash_data")
if not os.path.exists(tornadocash_data_dir):
    os.makedirs(tornadocash_data_dir)

ALCHEMY_API_KEY = "xxx"
ALCHEMY_BASE_URL = f"https://eth-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}"

Alchemy_API_key_list = [
    "xxx",
]

Blocksec_address_lable_apikey = "xxx"
Etherscan_api_key = "xxx"

Etherscan_api_key_list = [
    "xxx",
]