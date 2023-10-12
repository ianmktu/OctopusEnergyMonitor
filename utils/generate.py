import argparse
import csv
import datetime
import logging
import os
import sys
import traceback

import pandas as pd
import requests
from config import get_config_from_yaml
from logger import setup_logging
from prices import TIMES, api_prices_to_dict, convert_price_csv_to_dict, get_energy_prices_from_api
from tzlocal import get_localzone


def arg_parse() -> argparse.Namespace:
    """
    Parses command line arguments for the Octopus Energy Tariff Cost and Usage Generator.

    Args:
        None

    Returns:
        argparse.Namespace: An object containing the parsed arguments.
    """
    parser = argparse.ArgumentParser(description="Octopus Energy Tariff Cost and Usage Generator")
    parser.add_argument(
        "-b",
        "--basis",
        type=str,
        default=None,
        help="Day to calculate cost for. Format: YYYY-MM-DD. Default: None (Will use: 2023-10-04).",
    )
    parser.add_argument(
        "-t",
        "--target",
        type=str,
        default=None,
        help="Day to calculate cost for. Format: YYYY-MM-DD. Default: None (Will use: 2023-10-05).",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="Output file to write to. Default: None (Will not generate any stats).",
    )
    parser.add_argument(
        "-c",
        "--cutoff",
        type=str,
        default=None,
        help="Time to stop generating readings. Format: HH:MM. Default: None (generate for the whole day).",
    )

    parser.add_argument(
        "-s",
        "--stats",
        action="store_true",
        help="Print stats comparison of different tariffs for the past 30 days.",
    )

    parser.add_argument(
        "-d",
        "--days",
        type=int,
        default=30,
        help="Number of days to generate stats for. Default: 30.",
    )

    parser.add_argument(
        "-fd",
        "--from_date",
        type=str,
        default=None,
        help=(
            "Date to start generating stats from. Format: YYYY-MM-DD. Needs to be couple with --to_date."
            " Default: None (Will use args.days when generating stats if args.from_date and args.to_date not given)."
        ),
    )

    parser.add_argument(
        "-td",
        "--to_date",
        type=str,
        default=None,
        help=(
            "Date to stop generating stats to. Format: YYYY-MM-DD. Needs to be couple with --from_date."
            " Default: None (Will use args.days when generating stats if args.from_date and args.to_date not given)."
        ),
    )

    parser.add_argument(
        "-r",
        "--regen",
        action="store_true",
        help="Regenerate data. Default: False.",
    )

    if len(sys.argv) == 1:
        logging.info("No arguments provided, showing help...")
        parser.print_help(sys.stderr)
        sys.exit(1)

    return parser.parse_args()


def get_energy_usage_from_api(
    url: dict, api_key: str, api_pass: str, start_date: datetime, end_date: datetime, timezone: datetime.tzinfo
) -> dict:
    """
    Fetches electricity usage from an API for a given time period.

    Args:
        url (str): The URL of the API.
        api_key (str): The API key (if required).
        api_pass (str): The API password (if required).
        start_date (datetime): The start date of the time period.
        end_date (datetime): The end date of the time period.
        timezone (tzinfo): The timezone to use for the time period.

    Returns:
        dict: A dictionary containing the energy usage for the given time period.
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

    usage_json_data = r.json()
    electricity_usage = usage_json_data["results"]

    return electricity_usage


def write_electricity_usage_to_concise_csv(
    time_to_kilowatts_map: dict, target_date: datetime, csv_filename: str
) -> None:
    """
    Writes electricity usage data to a CSV file in a concise format.

    Args:
        time_to_kilowatts_map (dict): A dictionary mapping time keys to kilowatts usage.
        target_date (datetime): The target date for the usage data.
        csv_filename (str): The filename of the CSV file to write to.

    Returns:
        None
    """
    with open(csv_filename, "w", newline="\n") as f:
        csv_writer = csv.writer(f, delimiter=",", quotechar="|", quoting=csv.QUOTE_MINIMAL)
        csv_writer.writerow(["Date", "Time", "Usage (kW)"])
        for time_key in sorted(time_to_kilowatts_map):
            csv_writer.writerow(
                [
                    target_date.strftime("%Y-%m-%d"),
                    time_key,
                    time_to_kilowatts_map[time_key],
                ]
            )


def write_electricity_usage_to_csv(
    time_to_kilowatts_map: dict, target_date: datetime, csv_filename: str, cutoff_time: datetime = None
) -> None:
    """
    Writes electricity usage data to a CSV file.

    Args:
        time_to_kilowatts_map (dict): A dictionary mapping time keys to kilowatts.
        target_date (datetime): The target date for the data.
        csv_filename (str): The filename of the CSV file to write to.
        cutoff_time (datetime, optional): The cutoff time for the data. Defaults to None.
    """
    with open(csv_filename, "w", newline="\n") as f:
        csv_writer = csv.writer(f, delimiter=",", quotechar="|", quoting=csv.QUOTE_MINIMAL)
        for time_key in sorted(time_to_kilowatts_map):
            watts = int(round(time_to_kilowatts_map[time_key] * 1000))
            increments = 30 * 60.0 / watts

            current_time = datetime.datetime(
                year=target_date.year,
                month=target_date.month,
                day=target_date.day,
                hour=int(time_key[0:2]),
                minute=int(time_key[3:5]),
                tzinfo=get_localzone(),
            )

            for i in range(watts):
                current_datetime = current_time + datetime.timedelta(seconds=i * increments)
                csv_writer.writerow(
                    [
                        "000.00",
                        f"{current_datetime.timestamp():.6f}",
                        current_datetime.strftime("%H:%M:%S.%f"),
                        current_datetime.strftime("%Y-%m-%d") + " " + time_key + ":00",
                        "generated",
                    ]
                )
                if cutoff_time is not None and current_datetime.time() >= cutoff_time:
                    return


def set_datetime_to_min_time(dt: datetime.datetime) -> datetime.datetime:
    """
    Sets the time component of a datetime object to the minimum time (i.e., midnight).

    Args:
        dt (datetime.datetime): The datetime object to modify.

    Returns:
        datetime.datetime: A new datetime object with the same date as the original object and the minimum time.
    """
    return datetime.datetime.combine(dt.date(), datetime.time.min)


def set_datetime_to_max_time(dt: datetime.datetime) -> datetime.datetime:
    """
    Sets the time component of a datetime object to the maximum time (i.e., 23:59:59.999999).

    Args:
        dt (datetime.datetime): The datetime object to modify.

    Returns:
        datetime.datetime: A new datetime object with the same date as the original object and the maximum time.
    """
    return datetime.datetime.combine(dt.date(), datetime.time.max)


def generate_time_kilowatt_usage_dict(target_date: datetime, config: dict, csv_filename: str) -> dict:
    """
    Generates a dictionary of energy usage in kilowatts for each half-hour time interval of a given target date.

    Args:
        target_date (datetime): The target date for which to generate the energy usage dictionary.
        config (dict): A dictionary containing the API URL, API key, and API password.
        csv_filename (str): The filename of the CSV file to write the energy usage data to.
                            If None, no CSV file is written.

    Returns:
        dict: A dictionary mapping each half-hour time interval to its corresponding energy usage in kilowatts.
    """
    current_timezone = get_localzone()
    result = get_energy_usage_from_api(
        url=config["ELECTRICITY_USAGE_URL"],
        api_key=config["API_KEY"],
        api_pass=config["API_PASS"],
        start_date=set_datetime_to_min_time(target_date),
        end_date=set_datetime_to_max_time(target_date),
        timezone=current_timezone,
    )

    assert len(result) == 48, f"Expected 48 results for {target_date} from API, got {len(result)}"

    time_to_kilowatts_map = dict()
    for time_str in TIMES:
        current_time = datetime.datetime(
            year=target_date.year,
            month=target_date.month,
            day=target_date.day,
            hour=int(time_str[0:2]),
            minute=int(time_str[3:5]),
            tzinfo=current_timezone,
        )
        for usage in result:
            if (
                datetime.datetime.fromisoformat(usage["interval_start"])
                .astimezone(current_timezone)
                .isoformat(timespec="seconds")
                <= current_time.isoformat(timespec="seconds")
                < datetime.datetime.fromisoformat(usage["interval_end"])
                .astimezone(current_timezone)
                .isoformat(timespec="seconds")
            ):
                time_to_kilowatts_map[time_str] = usage["consumption"]
                break

    if len(time_to_kilowatts_map) != 48:
        raise ValueError(f"Expected 48 results for {target_date} after processing, got {len(time_to_kilowatts_map)}")

    if csv_filename is not None:
        os.makedirs(os.path.dirname(csv_filename), exist_ok=True)
        write_electricity_usage_to_csv(
            time_to_kilowatts_map=time_to_kilowatts_map, target_date=target_date, csv_filename=csv_filename
        )

    return time_to_kilowatts_map


def generate_dummy_readings_csv(
    config: dict,
    output_filename: str = "./test.csv",
    target_date: datetime.datetime = datetime.datetime(2023, 10, 5),
    basis_date: datetime.datetime = datetime.datetime(2023, 10, 4),
    cutoff_time: datetime.time = datetime.time(12, 00, 00),
) -> None:
    """
    Generates a dummy CSV file with electricity usage readings for a given target date.

    Args:
        config: A dictionary containing configuration parameters for generating the electricity usage readings.
        output_filename: The filename for the generated CSV file. Defaults to "./test.csv".
        target_date: The target date for which the electricity usage readings are to be generated.
                     Defaults to October 5 2023.
        basis_date: The basis date for generating the electricity usage readings. Defaults to October 4, 2023.
        cutoff_time: The cutoff time for the electricity usage readings. Defaults to 12:00:00 PM.

    Returns:
        None
    """

    time_to_kilowatts_map = generate_time_kilowatt_usage_dict(target_date=basis_date, config=config, csv_filename=None)
    write_electricity_usage_to_csv(
        time_to_kilowatts_map=time_to_kilowatts_map,
        target_date=target_date,
        csv_filename=output_filename,
        cutoff_time=cutoff_time,
    )

    logging.info(f'Successfully generated file at: "{output_filename}"')


def convert_concise_electricity_usage_csv_to_dict(filename: str) -> pd.DataFrame:
    """
    Reads a CSV file containing time and price data, and returns a dictionary
    mapping time to price.

    Args:
        filename (str): The path to the CSV file.

    Returns:
        dict: A dictionary mapping time (str) to electricity usage (float16).
    """
    prices_df = pd.read_csv(
        filename,
        dtype={"Time": "str", "Usage (kW)": "float32"},
        parse_dates=["Date"],
    )
    time_to_price_map = prices_df.set_index("Time").to_dict()["Usage (kW)"]
    return time_to_price_map


def generate_stats(
    config: dict,
    api_directory: str = None,
    prices_directory: str = None,
    days_to_go_back: int = 30,
    regen: bool = False,
    from_date: datetime.date = None,
    to_date: datetime.date = None,
) -> None:
    """
    Generates statistics for electricity usage and price data for a given number of days.

    Args:
        config (dict): A dictionary containing configuration information.
        api_directory (str): The directory to store the API data in.
        prices_directory (str): The directory to store the price data in.
        days_to_go_back (int, optional): The number of days to generate statistics for. Defaults to 30.
        regen (bool, optional): Whether to regenerate the data. Defaults to False.
        from_date (datetime.date, optional): The start date for the statistics.
                                             Defaults to None, will use days_to_go_back methods instead.
        to_date (datetime.date, optional): The end date for the statistics.
                                           Defaults to None, will use days_to_go_back methods instead.

    Returns:
        None
    """
    if from_date is None and to_date is None:
        current_datetime_min = datetime.datetime.combine(datetime.datetime.now(), datetime.time.min)
        days = days_to_go_back
    else:
        current_datetime_min = datetime.datetime.combine(to_date, datetime.time.min)
        days = (to_date - from_date).days + 1
    current_datetime_max = current_datetime_min + datetime.timedelta(days=1)

    while True:
        try:
            logging.info("")
            logging.info("Getting electricity usage data...")

            time_to_kilowatts_store = dict()
            for i in range(days):
                target_date = current_datetime_min - datetime.timedelta(days=i)

                if api_directory is not None:
                    electricity_usage_path = os.path.join(api_directory, "electricity_usage")
                    electricity_usage_filename = os.path.join(electricity_usage_path, f"{target_date.date()}.csv")
                    if regen and os.path.exists(electricity_usage_filename):
                        os.remove(electricity_usage_filename)
                else:
                    electricity_usage_filename = None

                logging.info(f"[   USAGE] [{i+1:2d}/{days:2d}] [{target_date.date()}] Getting day usage data...")

                if electricity_usage_filename is None or not os.path.exists(electricity_usage_filename):
                    time_to_kilowatts_store[target_date.date()] = generate_time_kilowatt_usage_dict(
                        target_date=target_date, config=config, csv_filename=electricity_usage_filename
                    )
                else:
                    logging.debug(
                        f"[   USAGE] [{i+1:2d}/{days:2d}] [{target_date.date()}]"
                        f" Reading CSV file: {electricity_usage_filename}"
                    )
                    time_to_kilowatts_store[target_date.date()] = convert_concise_electricity_usage_csv_to_dict(
                        electricity_usage_filename
                    )
                logging.info(
                    f"[   USAGE] [{i+1:2d}/{days:2d}] [{target_date.date()}]"
                    f" Total usage data: {sum(time_to_kilowatts_store[target_date.date()].values()):.3f} kW"
                )

                if api_directory is not None:
                    logging.debug(
                        f"[   USAGE] [{i+1:2d}/{days:2d}] [{target_date.date()}]"
                        f" Writing CSV file: {electricity_usage_filename}"
                    )
                    os.makedirs(electricity_usage_path, exist_ok=True)
                    write_electricity_usage_to_concise_csv(
                        time_to_kilowatts_map=time_to_kilowatts_store[target_date.date()],
                        target_date=target_date,
                        csv_filename=electricity_usage_filename,
                    )
                    logging.debug(
                        f"[   USAGE] [{i+1:2d}/{days:2d}] [{target_date.date()}]"
                        f" CSV file written: {electricity_usage_filename}"
                    )

            day_keys = sorted(list(time_to_kilowatts_store.keys()))
            logging.info("")
            logging.info(
                f"Successfully downloaded usage data from: '{day_keys[0]}' to '{day_keys[-1]}' ({len(day_keys)} days)"
            )
            logging.info("")

            current_timezone = get_localzone()

            logging.info("Getting electricity price data...")
            tariff_url_keys = [key for key in config if key.endswith("_PRICES_URL")]
            tariff_to_price_store = dict()
            for tariff_url_key in tariff_url_keys:
                tariff_name = tariff_url_key.replace("_PRICES_URL", "")

                for i in range(days):
                    url = config[tariff_url_key]
                    target_date_min = current_datetime_min - datetime.timedelta(days=i)
                    target_date_max = current_datetime_max - datetime.timedelta(days=i)
                    logging.debug(
                        f"[{tariff_name:>8s}] [{i+1:2d}/{days:2d}] [{target_date_min.date()}] Getting day price data..."
                    )

                    if prices_directory is not None:
                        price_path = os.path.join(prices_directory, tariff_name.lower())
                        tariff_price_filename = os.path.join(price_path, f"{target_date_min.date()}.csv")
                        if regen and os.path.exists(tariff_price_filename):
                            os.remove(tariff_price_filename)
                    else:
                        tariff_price_filename = None

                    if tariff_price_filename is None or not os.path.exists(tariff_price_filename):
                        api_prices = get_energy_prices_from_api(
                            url=url,
                            api_key=config["API_KEY"],
                            api_pass=config["API_PASS"],
                            start_date=target_date_min,
                            end_date=target_date_max,
                            timezone=current_timezone,
                        )

                        time_to_price_map = api_prices_to_dict(
                            prices=api_prices,
                            current_date=target_date_min,
                            current_timezone=current_timezone,
                            tariff=tariff_name,
                            config=config,
                            csv_filename=tariff_price_filename,
                        )
                    else:
                        logging.debug(
                            f"[{tariff_name:>8s}] [{i+1:2d}/{days:2d}] [{target_date_min.date()}]"
                            f" Reading CSV file: {tariff_price_filename}"
                        )
                        time_to_price_map = convert_price_csv_to_dict(tariff_price_filename)

                    if len(time_to_price_map) != 48:
                        raise ValueError(
                            f"Expected 48 results for {target_date_min.date()}, got {len(time_to_price_map)}"
                        )

                    if tariff_name not in tariff_to_price_store:
                        tariff_to_price_store[tariff_name] = dict()
                    tariff_to_price_store[tariff_name][target_date_min.date()] = time_to_price_map

                    average_price = sum(time_to_price_map.values()) / len(time_to_price_map)
                    logging.info(
                        f"[{tariff_name:>8s}] [{i+1:2d}/{days:2d}] [{target_date_min.date()}]"
                        f" Average price: {average_price:4.1f}p"
                    )

            logging.info("")
            logging.info(
                f"Successfully downloaded price data for the following tariffs: {list(tariff_to_price_store.keys())}"
            )
            logging.info("")

            stats = dict()
            for tariff_name in tariff_to_price_store:
                stats[tariff_name] = dict()
                stats[tariff_name]["power"] = 0.0
                stats[tariff_name]["cost"] = 0.0
                for target_date in tariff_to_price_store[tariff_name]:
                    current_time_to_price_map = tariff_to_price_store[tariff_name][target_date]
                    current_time_to_kilowatt_map = time_to_kilowatts_store[target_date]

                    for time_str in current_time_to_price_map:
                        stats[tariff_name]["power"] += current_time_to_kilowatt_map[time_str]
                        stats[tariff_name]["cost"] += (
                            current_time_to_kilowatt_map[time_str] * current_time_to_price_map[time_str]
                        )

                logging.info(
                    f"[{day_keys[0]} to {day_keys[-1]} ({len(day_keys)})] [{tariff_name:>8s}]"
                    f" [POWER: {stats[tariff_name]['power']:.1f} kW] [COST: £ {stats[tariff_name]['cost'] / 100:6.2f}]"
                    f" [COST PER KW: {stats[tariff_name]['cost'] / stats[tariff_name]['power']:4.1f}p]"
                )

            logging.info("")
            return
        except AssertionError as e:
            if from_date is not None and to_date is not None:
                logging.error(f"Error: {traceback.format_exc()}")
                raise e
            current_datetime_min -= datetime.timedelta(days=1)
            current_datetime_max -= datetime.timedelta(days=1)
        except Exception as e:
            logging.error(f"Error: {traceback.format_exc()}")
            raise e


def main() -> None:
    """
    This function generates either statistics or a dummy readings CSV file, depending on the command line arguments
    passed.

    If the --stats flag is passed, statistics are generated. If the --target flag is passed, a dummy readings CSV file
    is generated.

    Args:
        None

    Returns:
        None
    """
    try:
        script_dir = os.path.dirname(os.path.realpath(__file__))

        setup_logging(log_path=os.path.join(script_dir, "generate.log"))
        args = arg_parse()

        api_directory = os.path.join(script_dir, "..", "data", "api")
        os.makedirs(api_directory, exist_ok=True)

        prices_directory = os.path.join(script_dir, "..", "data", "prices")
        os.makedirs(prices_directory, exist_ok=True)

        config_path = os.path.join(script_dir, "..", "utils", "config.yaml")
        if not os.path.exists(config_path):
            config_path = os.path.join(script_dir, "..", "utils", "config.template.yaml")
        config = get_config_from_yaml(config_path)

        if args.stats:
            logging.info("Generating stats...")
            if args.from_date is None and args.to_date is None:
                generate_stats(
                    config=config,
                    api_directory=api_directory,
                    prices_directory=prices_directory,
                    days_to_go_back=args.days,
                    regen=args.regen,
                )
            else:
                if args.from_date is None or args.to_date is None:
                    logging.error(
                        f"Error: --from_date '{args.from_date}' and --to_date '{args.to_date}'"
                        " must be used together and neither None."
                    )
                    return

                from_date = datetime.datetime.strptime(args.from_date, "%Y-%m-%d").date()
                to_date = datetime.datetime.strptime(args.to_date, "%Y-%m-%d").date()

                if from_date > to_date:
                    logging.error(f"Error: --from_date '{args.from_date}' must be before --to_date '{args.to_date}'.")
                    return

                generate_stats(
                    config=config,
                    api_directory=api_directory,
                    prices_directory=prices_directory,
                    from_date=from_date,
                    to_date=to_date,
                    regen=args.regen,
                )
        else:
            if args.target is not None:
                target_date = datetime.datetime.strptime(args.target, "%Y-%m-%d").date()
            else:
                target_date = datetime.datetime(2023, 10, 5)

            if args.basis is not None:
                basis_date = datetime.datetime.strptime(args.basis, "%Y-%m-%d").date()
            else:
                basis_date = datetime.datetime(2023, 10, 4)

            if args.cutoff is not None:
                cutoff = datetime.datetime.strptime(args.cutoff, "%H:%M").time()
            else:
                cutoff = None

            if args.output is not None:
                if os.path.dirname(args.output) == "":
                    output = os.path.join(os.getcwd(), args.output)
                else:
                    output = args.output

                logging.info("Generating CSV...")
                logging.info(f"  Target date: {target_date}")
                logging.info(f"   Basis date: {basis_date}")
                logging.info(f"  Cutoff Time: {cutoff}")
                logging.info(f"       Output: {output}")

                generate_dummy_readings_csv(
                    config=config,
                    output_filename=output,
                    target_date=target_date,
                    basis_date=basis_date,
                    cutoff_time=cutoff,
                )
    except Exception as e:
        logging.error(f"Error: {traceback.format_exc()}")
        raise e


if __name__ == "__main__":
    main()
