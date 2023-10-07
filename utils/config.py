import logging
import traceback

import yaml


def get_config_from_yaml(yaml_file_path):
    """
    Get the configuration from a YAML file.

    Args:
        yaml_file_path (str): The path to the YAML file.

    Returns:
        dict: The configuration.
    """
    try:
        with open(yaml_file_path) as file:
            config = yaml.safe_load(file)
    except Exception as e:
        logging.error(f"Error reading the configuration file: {traceback.format_exc()}")
        raise e
    return config
