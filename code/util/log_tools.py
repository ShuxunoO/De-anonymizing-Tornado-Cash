"""
@file log_tools.py
@brief Logging utility for setting up structured logging.

@details
Provides a single function to initialize and configure a logger with both
file and console handlers, with proper encoding support for Chinese characters.
"""
import logging
import os

from config.config import log_dir


def setup_logger(log_file_name: str) -> logging.Logger:
    """
    @brief Initializes and configures a logger instance.
    @param log_file_name Name of the log file (e.g., 'training.log').
    @return Configured logger instance.
    """
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logger = logging.getLogger(log_file_name)
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger

    log_file_path = os.path.join(log_dir, log_file_name)

    file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger