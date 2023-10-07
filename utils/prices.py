import csv
import logging
import os
import traceback
from datetime import datetime, tzinfo

import pandas as pd
import requests
from dateutil import parser
from tzlocal import get_localzone

TIMES = [
    "00:00",
    "00:30",
    "01:00",
    "01:30",
    "02:00",
    "02:30",
    "03:00",
    "03:30",
    "04:00",
    "04:30",
    "05:00",
    "05:30",
    "06:00",
    "06:30",
    "07:00",
    "07:30",
    "08:00",
    "08:30",
    "09:00",
    "09:30",
    "10:00",
    "10:30",
    "11:00",
    "11:30",
    "12:00",
    "12:30",
    "13:00",
    "13:30",
    "14:00",
    "14:30",
    "15:00",
    "15:30",
    "16:00",
    "16:30",
    "17:00",
    "17:30",
    "18:00",
    "18:30",
    "19:00",
    "19:30",
    "20:00",
    "20:30",
    "21:00",
    "21:30",
    "22:00",
    "22:30",
    "23:00",
    "23:30",
]


def convert_price_csv_to_dict(filename: str) -> pd.DataFrame:
    """
    Reads a CSV file containing time and price data, and returns a dictionary
    mapping time to price.

    Args:
        filename (str): The path to the CSV file.

    Returns:
        dict: A dictionary mapping time (str) to price (float16).
    """
    prices_df = pd.read_csv(
        filename,
        dtype={"Time": "str", "Price": "float32"},
        parse_dates=["Date"],
    )
    time_to_price_map = prices_df.set_index("Time").to_dict()["Price"]
    return time_to_price_map


def get_offline_prices(config: dict, prices_directory: str) -> dict:
    """
    Returns a dictionary mapping time to price from an offline CSV file.

    Args:
        config (dict): A dictionary containing configuration parameters.
        prices_directory (str): The directory containing the offline CSV files.

    Returns:
        dict: A dictionary mapping time to price.
    """
    time_to_price_map = {}
    if config["OCTOPUS_TARIFF"] == "AGILE":
        price_csv_filename = os.path.join(prices_directory, "offline", config["OFFLINE_AGILE_PRICES_FILE"])
    elif config["OCTOPUS_TARIFF"] == "GO":
        price_csv_filename = os.path.join(prices_directory, "offline", config["OFFLINE_GO_PRICES_FILE"])
    elif config["OCTOPUS_TARIFF"] == "TRACKER":
        price_csv_filename = os.path.join(prices_directory, "offline", config["OFFLINE_TRACKER_PRICES_FILE"])
    else:
        price_csv_filename = os.path.join(prices_directory, "offline", config["OFFLINE_FLEXIBLE_PRICES_FILE"])

    logging.info(f"Tariff configured: {config['OCTOPUS_TARIFF']}")
    logging.info(f"Using offline prices from: {price_csv_filename}")

    time_to_price_map = convert_price_csv_to_dict(price_csv_filename)

    return time_to_price_map


def get_energy_price_url(config: dict) -> str:
    """
    Returns the URL for the energy prices based on the selected tariff in the configuration.

    Args:
        config (dict): A dictionary containing the configuration values.

    Returns:
        str: The URL for the energy prices based on the selected tariff.
    """
    if config["OCTOPUS_TARIFF"] == "AGILE":
        return config["AGILE_PRICES_URL"]
    elif config["OCTOPUS_TARIFF"] == "GO":
        return config["GO_PRICES_URL"]
    elif config["OCTOPUS_TARIFF"] == "TRACKER":
        return config["TRACKER_PRICES_URL"]
    else:
        return config["FLEXIBLE_PRICES_URL"]


def get_energy_prices_from_api(
    url: dict, api_key: str, api_pass: str, start_date: datetime, end_date: datetime, timezone: tzinfo
) -> dict:
    """
    Fetches energy prices from an API for a given time period.

    Args:
        url (str): The URL of the API.
        api_key (str): The API key (if required).
        api_pass (str): The API password (if required).
        start_date (datetime): The start date of the time period.
        end_date (datetime): The end date of the time period.
        timezone (tzinfo): The timezone to use for the time period.

    Returns:
        dict: A dictionary containing the energy prices for the given time period.
    """

    # Convert the start and end dates to the local timezone
    start_date_localized = start_date.astimezone(timezone)
    end_date_localized = end_date.astimezone(timezone)
    period_from_and_to_params = {
        "period_from": start_date_localized.isoformat(),
        "period_to": end_date_localized.isoformat(),
    }

    if api_key is not None and api_key != "":
        r = requests.get(url, auth=requests.auth.HTTPBasicAuth(api_key, api_pass), params=period_from_and_to_params)
    else:
        r = requests.get(url, params=period_from_and_to_params)

    prices_json_data = r.json()
    prices = prices_json_data["results"]

    return prices


def write_prices_to_csv(time_to_price_map: dict, current_date: datetime, csv_filename: str) -> None:
    """
    Write the given time-to-price mapping to a CSV file with the given filename.

    Args:
        time_to_price_map (dict): A dictionary mapping times to prices.
        current_date (datetime): The current date.
        csv_filename (str): The filename of the CSV file to write to.
    """
    with open(csv_filename, "w", newline="\n") as f:
        csv_writer = csv.writer(f, delimiter=",", quotechar="|", quoting=csv.QUOTE_MINIMAL)
        csv_writer.writerow(["Date", "Time", "Price"])
        for time_key in sorted(time_to_price_map):
            csv_writer.writerow(
                [
                    current_date.strftime("%Y-%m-%d"),
                    time_key,
                    time_to_price_map[time_key],
                ]
            )


def api_prices_to_dict(
    prices: dict,
    current_date: datetime,
    current_timezone: tzinfo,
    tariff: str,
    config: dict,
    csv_filename: str,
) -> dict:
    """
    Converts API prices to a dictionary of time-to-price mappings based on the given configuration.

    Args:
        prices (dict): A dictionary of prices from the API.
        current_date (datetime): The current date.
        current_timezone (tzinfo): The current timezone.
        tariff (str): The tariff to use.
        csv_filename (str): The filename of the CSV file to write the prices to. If None, then no CSV file is written.
        config (dict): A dictionary of configuration options.

    Returns:
        dict: A dictionary of time-to-price mappings.
    """
    time_to_price_map = dict()
    if tariff == "AGILE":
        for price in prices:
            interval_start_string = parser.isoparse(price["valid_from"]).astimezone(current_timezone).strftime("%H:%M")
            price = price["value_inc_vat"]
            time_to_price_map[interval_start_string] = float(price)
    elif tariff == "GO":
        for time in TIMES:
            current_time = datetime(
                year=current_date.year,
                month=current_date.month,
                day=current_date.day,
                hour=int(time[0:2]),
                minute=int(time[3:5]),
                tzinfo=current_timezone,
            )
            for price in prices:
                if (
                    parser.isoparse(price["valid_from"]).astimezone(current_timezone).isoformat(timespec="seconds")
                    <= current_time.isoformat(timespec="seconds")
                    < parser.isoparse(price["valid_to"]).astimezone(current_timezone).isoformat(timespec="seconds")
                ):
                    time_to_price_map[time] = price["value_inc_vat"]
                    break
    elif tariff == "TRACKER":
        for time in TIMES:
            time_to_price_map[time] = prices[0]["value_inc_vat"]
    else:
        price = 0
        for p in prices:
            if p["payment_method"] == "DIRECT_DEBIT":
                price = p["value_inc_vat"]
                break
        for time in TIMES:
            time_to_price_map[time] = price

    if csv_filename is not None:
        os.makedirs(os.path.dirname(csv_filename), exist_ok=True)
        write_prices_to_csv(time_to_price_map=time_to_price_map, current_date=current_date, csv_filename=csv_filename)

    return time_to_price_map


def check_prices_file_exists(config: dict, prices_directory: str, current_date: datetime) -> bool:
    """
    Check if the prices file exists for the given tariff and date.

    Args:
        config (dict): A dictionary containing the configuration settings.
        prices_directory (str): The directory where the prices files are stored.
        current_date (datetime): The date for which to check the prices file.

    Returns:
        bool: True if the prices file exists, False otherwise.
    """
    tariff = config["OCTOPUS_TARIFF"].lower()
    price_csv_filename = os.path.join(
        prices_directory,
        tariff,
        "{}.csv".format(current_date.strftime("%Y-%m-%d")),
    )
    return os.path.exists(price_csv_filename)


def get_energy_prices(start_date, end_date, config, prices_directory):
    """
    Get energy prices from the Octopus API endpoint or from a local CSV file.

    Args:
        start_date (datetime): The start date for the energy prices.
        end_date (datetime): The end date for the energy prices.
        config (dict): A dictionary containing configuration settings.
        prices_directory (str): The directory where the energy prices are stored.

    Returns:
        dict: A dictionary mapping time to energy prices in pence.

    Raises:
        Exception: If no energy prices are returned from the API.
    """
    if config["OFFLINE"]:
        return get_offline_prices(config, prices_directory)

    try:
        # Get the filename for the CSV file containing the energy prices
        tariff = config["OCTOPUS_TARIFF"].lower()
        price_csv_filename = os.path.join(
            prices_directory,
            tariff,
            "{}.csv".format(start_date.strftime("%Y-%m-%d")),
        )

        # If the file exists and has 48 lines, then we skip requesting latest prices from online
        if os.path.exists(price_csv_filename):
            time_to_price_map = convert_price_csv_to_dict(price_csv_filename)
            if len(time_to_price_map) == 48:
                return time_to_price_map

        # Get the local timezone
        current_timezone = get_localzone()

        # Get the latest energy prices from the Octopus API endpoint
        electricity_price_url = get_energy_price_url(config)
        api_prices = get_energy_prices_from_api(
            url=electricity_price_url,
            api_key=config["API_KEY"],
            api_pass=config["API_PASS"],
            start_date=start_date,
            end_date=end_date,
            timezone=current_timezone,
        )

        if len(api_prices) == 0:
            raise Exception("No energy prices returned from API")

        # Convert the API prices to a dictionary, mapping time to price in pence
        time_to_price_map = api_prices_to_dict(
            prices=api_prices,
            current_date=start_date,
            current_timezone=current_timezone,
            tariff=config["OCTOPUS_TARIFF"],
            config=config,
            csv_filename=price_csv_filename,
        )
    except Exception:
        logging.error(f"Error getting energy prices: {traceback.format_exc()}")
        logging.info("Using offline prices instead ...")
        time_to_price_map = get_offline_prices(config, prices_directory)

    return time_to_price_map


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.realpath(__file__))
    from config import get_config_from_yaml

    config = get_config_from_yaml(os.path.join(script_dir, "..", "data", "config.yaml"))
    prices_directory = os.path.join(script_dir, "..", "data", "prices")

    offline_prices = get_offline_prices(config, prices_directory)
    print(offline_prices)

    config["OCTOPUS_TARIFF"] = "GO"
    url = get_energy_price_url(config)
    start_date = datetime(2023, 10, 5, 0, 0, 0)
    end_date = datetime(2023, 10, 5, 23, 59, 59)
    tz = get_localzone()
    prices = get_energy_prices_from_api(
        url=url,
        api_key=config["API_KEY"],
        api_pass=config["API_PASS"],
        start_date=start_date,
        end_date=end_date,
        timezone=tz,
    )

    time_to_price_map = {}
    for price in prices:
        print(price)

    time_to_price_map = api_prices_to_dict(
        prices=prices,
        current_date=start_date,
        current_timezone=tz,
        tariff=config["OCTOPUS_TARIFF"],
        config=config,
        csv_filename=None,
    )

    # for price in prices:
    #     interval_start_string = parser.isoparse(price["valid_from"]).astimezone(tz).strftime("%H:%M")
    #     price = price["value_inc_vat"]
    #     time_to_price_map[interval_start_string] = float(price)

    print(time_to_price_map)
    print(len(time_to_price_map))
    print(sum(time_to_price_map.values()) / len(time_to_price_map))
