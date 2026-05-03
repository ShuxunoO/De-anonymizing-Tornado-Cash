"""
@file fio.py
@brief File I/O utilities for JSON and CSV operations.

@details
Provides helper functions for reading and writing JSON and CSV files
with automatic directory creation and error handling.
"""
import os
import json
import pandas as pd


def save_to_json(obj, path):
    """
    @brief Saves an object to a JSON file.
    @param obj Object to save (string or JSON-serializable object).
    @param path Target file path.
    """
    try:
        dirname = os.path.dirname(path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)

        with open(path, 'w', encoding='utf-8') as f:
            if isinstance(obj, str):
                f.write(obj)
            else:
                json.dump(obj, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"[Error] Failed to save JSON: {e}")


def load_json(path):
    """
    @brief Loads an object from a JSON file.
    @param path Path to the JSON file.
    @return Loaded object, None on failure.
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[Error] Failed to load JSON: {e}")
        return None


def load_csv(path):
    """
    @brief Loads data from a CSV file using pandas.
    @param path Path to the CSV file.
    @return DataFrame, None on failure.
    """
    try:
        df = pd.read_csv(path, dtype=str)
        return df
    except Exception as e:
        print(f"[Error] Failed to load CSV: {e}")
        return None


def save_to_csv(data, path):
    """
    @brief Saves data to a CSV file using pandas.
    @param data Data to save (DataFrame or dict).
    @param path Target file path.
    """
    try:
        dirname = os.path.dirname(path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)

        if isinstance(data, pd.DataFrame):
            data.to_csv(path, index=False)
        elif isinstance(data, dict):
            df = pd.DataFrame([data])
            df.to_csv(path, index=False)
        else:
            print(f"[Error] Unsupported data type: {type(data)}")
    except Exception as e:
        print(f"[Error] Failed to save CSV: {e}")