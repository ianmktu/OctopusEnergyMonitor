import logging
import os


def setup_logging(log_path, log_format="[%(asctime)s] [%(levelname)s] %(message)s", log_level=logging.INFO):
    """
    Set up logging for the application.

    Args:
        log_format (str): The format string for the log messages.
        log_level (int): The logging level to use.

    Returns:
        None
    """
    formatter = logging.Formatter(log_format)

    if log_path is not None:
        if not os.path.exists(log_path):
            os.makedirs(os.path.dirname(log_path), exist_ok=True)

        file_handler = logging.FileHandler(log_path)
        file_handler.setFormatter(formatter)

    # Create a StreamHandler object to output the log messages to the console
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # Add the handlers to the root logger
    if log_path is not None:
        logging.getLogger().addHandler(file_handler)
    logging.getLogger().addHandler(console_handler)

    # Set the logging level to log_level
    logging.getLogger().setLevel(log_level)
