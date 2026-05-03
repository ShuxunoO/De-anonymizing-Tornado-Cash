"""
@file build_exclude_address.py
@brief Builds exclusion address list from Tornado Cash tags and keywords.

@details
Filters Tornado Cash contract addresses and addresses with specific entity tags
to build an exclusion list used for filtering noise in analysis.

Keywords cover: exchanges, DeFi protocols, services, staking, gambling, DAO,
NFT markets, contract/pool/vault labels, and Bot/MEV addresses.
"""
import json
import os


FILTER_CONTRACTS = {
    "0x12d66f87a04a9e220743712ce6d9bb1b5616b8fc",
    "0x47ce0c6ed5b0ce3d3a51fdb1c52dc66a7c3c2936",
    "0x910cbd523d972eb0a6f4cae4618ad62622b39dbf",
    "0xa160cdab225685da1d56aa342ad8841c3b53f291",
    "0x905b63fff465b9ffbf41dea908ceb12478ec7601",
    "0x722122df12d4e14e13ac3b6895a86e84145b6967",
    "0xd90e2f925da726b50c4ed8d0fb90ad053324f31b",
}


KEY_WORDS_LIST = [
    "EXCHANGE", "DEX", "ECOMMERCE", "OTC DESK", "SWAP", "TRADING",
    "Maker", "STABLE COIN", "RWA", "LENDING", "BORROWING", "YIELD",
    "Protocol", "Finance", "Compound", "Aave", "Curve", "Balancer",
    "SushiSwap", "Uniswap", "PancakeSwap",
    "SERVICES", "MARKETPLACE", "BRIDGE", "ROUTER", "GATEWAY",
    "RELAYER", "ORACLE", "REGISTRY", "PROXY",
    "GAMING", "GAMBLING",
    "DAO", "GOVERNANCE", "MULTISIG", "TREASURY", "Safe Multisig",
    "GnosisSafe", "GnosisSafeProxy",
    "OpenSea", "MARKETPLACE",
    "LP Token", "LP-Token", "Liquidity Pool", "Pool", "Vault",
    "Farm", "Staking", "Contract", "Token Sale",
    "Factory", "V2:", "V3:", "V1:", "Uniswap V2", "Uniswap V3",
    "SushiSwap:", "Balancer:", "Curve.fi",
    "Bot", "MEV",
    "Proxy"
]


TAG_FILE = os.path.join(os.path.dirname(__file__), "..", "tornadocash_data", "address_tags", "TornadoCash_address_tag.json")
OUTPUT_FILE = os.path.join(os.path.dirname(TAG_FILE), "exclude_address_by_key_words.json")


def match_keywords(text: str) -> bool:
    """
    @brief Checks if text contains any keyword (case-insensitive).
    @param text String to check.
    @return True if any keyword is found, False otherwise.
    """
    if not text:
        return False
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in KEY_WORDS_LIST)


def main():
    with open(TAG_FILE, "r", encoding="utf-8") as f:
        address_tags = json.load(f)

    exclude_set = set(FILTER_CONTRACTS)

    for addr, info in address_tags.items():
        fields_to_check = [info.get("main_entity", ""), info.get("nameTag", ""), info.get("attributes", "")]
        if any(match_keywords(field) for field in fields_to_check):
            exclude_set.add(addr.lower())

    exclude_list = sorted(exclude_set)

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(exclude_list, f, indent=2, ensure_ascii=False)

    print(f"[INFO] Matched {len(exclude_set) - len(FILTER_CONTRACTS)} addresses from tags")
    print(f"[INFO] Combined with {len(FILTER_CONTRACTS)} Tornado Cash contracts")
    print(f"[INFO] Total exclude addresses: {len(exclude_list)}")


if __name__ == "__main__":
    main()