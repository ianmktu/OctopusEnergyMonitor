#!/usr/bin/python3
"""
This script monitors the energy usage of a home using a Raspberry Pi and a 
Light to Frequency Sensor (LTR-559). It calculates the energy usage in 
Watts and the cost in GBP and displays the data on a screen. The energy 
usage is calculated by measuring the frequency of the light sensor, and
the cost is calculated using the Octopus API and calculated energy data.

The script is designed to be used with a Raspberry Pi running Raspbian 
Stretch Lite with the following additional hardware:

- LTR-559 Light to Frequency Sensor
- 2.4 inch LCD Display (240x320)
- 5V 2.5A Micro USB Power Supply
- 16GB Micro SD Card

"""

import glob
import logging
import os
import shutil
import tempfile
import threading
import time
import traceback
import zipfile
from collections import OrderedDict
from datetime import date, datetime, timedelta
from datetime import time as datetime_time

import numpy as np
import pandas as pd
import pygame
from file_read_backwards import FileReadBackwards

from utils.config import get_config_from_yaml
from utils.file import fix_data_corruption_of_latest_two_files, has_readings, line_count
from utils.logger import setup_logging
from utils.monitor import EnergyMonitor
from utils.prices import (
    TIMES,
    check_gas_price_file_exists,
    check_prices_file_exists,
    convert_price_csv_to_dict,
    get_energy_prices,
    get_gas_price,
)

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))


def update_fps(clock, font_path) -> pygame.Surface:
    """
    This function updates the frames per second (FPS) count on the screen.

    Args:
        clock (pygame.time.Clock): The clock object used to track time in the game.
        font_path (str): The path to the font file to be used for the FPS count.

    Returns:
        pygame.Surface: A surface object containing the FPS count text.
    """
    fps = str(int(clock.get_fps()))
    font = pygame.font.Font(font_path, 32)
    fps_text = font.render(fps, 1, pygame.Color("coral"))
    return fps_text


def day_with_suffix() -> str:
    """
    Returns the current day of the month with the appropriate suffix (st, nd, rd, or th).

    Returns:
        str: The current day of the month with the appropriate suffix (st, nd, rd, or th).
    """
    dic = {"1": "st", "2": "nd", "3": "rd"}
    if os.name == "nt":
        x = time.strftime("%#d")
    else:
        x = time.strftime("%-d")
    return x + ("th" if len(x) == 2 and x[0] == "1" else dic.get(x[-1], "th"))


def live_energy_time_reading(readings_csv_filename: str, blinks_per_kilowatt: int) -> float:
    """
    Calculates the live energy reading based on the time difference between the last two readings in the CSV file.

    Args:
        readings_csv_filename (str): The path to the CSV file containing the energy readings.
        blinks_per_kilowatt (int): The number of blinks per kilowatt-hour for the energy meter.

    Returns:
        float: The live energy reading in kilowatts.
    """
    reading = 0
    try:
        with FileReadBackwards(readings_csv_filename, encoding="utf-8") as f:
            live_energy_times = []
            index = 0
            for row in f:
                strip_and_split_row = row.strip().split(",")
                if len(strip_and_split_row) > 1:
                    live_energy_times.append(strip_and_split_row[1])
                else:
                    break

                index += 1
                if index == 2:
                    break

            if len(live_energy_times) == 2:
                reading = (
                    3600 * (1000.0 / blinks_per_kilowatt) / (float(live_energy_times[0]) - float(live_energy_times[1]))
                )
    except Exception:
        logging.error(f"Error in live_energy_time_reading: {traceback.format_exc()}")

    return reading


def get_power_stats_from_past(from_time: datetime, readings_csv_filename: str, blinks_per_kilowatt: str) -> dict:
    """
    Returns a dictionary containing the power statistics for the last 5, 30, and 60 minutes based on the given CSV file
    of energy readings.

    Parameters:
        from_time (datetime): The current time.
        readings_csv_filename (str): The filename of the CSV file containing the energy readings.
        blinks_per_kilowatt (str): The number of blinks per kilowatt-hour for the energy meter.

    Returns:
        dict: A dictionary containing the power statistics for the last 5, 30, and 60 minutes.
    """
    stats = {"power_last_five_minutes": 0, "power_last_thirty_minutes": 0, "power_last_sixty_minutes": 0}

    last_five_time = datetime.timestamp(from_time) - 300
    last_half_time = datetime.timestamp(from_time) - 1800
    last_hour_time = datetime.timestamp(from_time) - 3600

    with FileReadBackwards(readings_csv_filename, encoding="utf-8") as f:
        for line in f:
            split_line = line.split(",")
            if len(split_line) > 1:
                current_timestamp = float(line.split(",")[1])
            else:
                break

            if current_timestamp > last_five_time:
                stats["power_last_five_minutes"] += 1.0 / blinks_per_kilowatt

            if current_timestamp > last_half_time:
                stats["power_last_thirty_minutes"] += 1.0 / blinks_per_kilowatt

            if current_timestamp > last_hour_time:
                stats["power_last_sixty_minutes"] += 1.0 / blinks_per_kilowatt

            if current_timestamp < last_hour_time:
                break
    return stats


def get_time_to_price_map_for_day(prices_directory: str, config: dict, target_date: datetime) -> dict:
    """
    Returns a dictionary mapping datetime objects to energy prices for a given day.

    Args:
    - prices_directory (str): The directory where energy prices are stored.
    - config (dict): A dictionary containing configuration settings.
    - target_date (datetime): The target date for which to retrieve energy prices.

    Returns:
    - time_to_price_map (dict): A dictionary mapping datetime objects to energy prices.
    """
    time_to_price_map = dict()
    target_day = target_date.strftime("%Y-%m-%d")
    prices_csv_filename = os.path.join(prices_directory, config["OCTOPUS_TARIFF"], f"{target_day}.csv")
    if not os.path.exists(prices_csv_filename):
        start_of_day_datetime = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day_datetime = target_date.replace(hour=23, minute=59, second=59, microsecond=0)
        time_to_price_map = get_energy_prices(
            start_date=start_of_day_datetime,
            end_date=end_of_day_datetime,
            config=config,
            prices_directory=prices_directory,
        )
    else:
        time_to_price_map = convert_price_csv_to_dict(prices_csv_filename)
    return time_to_price_map


def get_readings_df_from_path(readings_csv_filename: str) -> pd.DataFrame:
    """
    Returns a pandas DataFrame containing energy monitor readings from a given CSV file.

    Args:
    - readings_csv_filename (str): The path to the CSV file containing the energy monitor readings.

    Returns:
    - readings_df (pd.DataFrame): A pandas DataFrame containing energy monitor readings from the given CSV file.
    """
    readings_df = None

    if os.path.exists(readings_csv_filename):
        readings_df = pd.read_csv(
            readings_csv_filename,
            header=None,
            names=["Lux", "Epoch Time", "Time", "Datetime", "Origin"],
            dtype={
                "Lux": "float32",
                "Epoch Time": "float64",
                "Time": "str",
                "Datetime": "str",
                "Origin": "str",
            },
        )

    return readings_df


def get_readings_df_from_date(monitor_data_directory: str, target_date: datetime) -> pd.DataFrame:
    """
    Returns a pandas DataFrame containing energy monitor readings for a given date.

    Args:
    - monitor_data_directory (str): The directory where the monitor data is stored.
    - target_date (datetime): The date for which the readings are required.

    Returns:
    - readings_df (pd.DataFrame): A pandas DataFrame containing energy monitor readings for the given date.
    """

    target_day = target_date.strftime("%Y-%m-%d")
    readings_csv_filename = os.path.join(monitor_data_directory, f"{target_day}.csv")
    readings_df = get_readings_df_from_path(readings_csv_filename)

    return readings_df


def calculate_total_cost(
    target_date: datetime, config: dict, monitor_data_directory: str, prices_directory: str
) -> tuple:
    """
    Calculates the total cost and power consumption for a given date, tariff, and energy monitor data.

    Args:
        target_date (datetime): The target date for which to calculate the cost and power consumption.
        config (dict): A dictionary containing the configuration parameters.
        monitor_data_directory (str): The directory containing the energy monitor data.
        prices_directory (str): The directory containing the energy prices data.

    Returns:
        tuple: A tuple containing the total cost and power consumption for the given date.
    """
    cost = 0
    power = 0

    readings_df = get_readings_df_from_date(monitor_data_directory=monitor_data_directory, target_date=target_date)
    if readings_df is None or len(readings_df) < 2:
        return cost, power

    time_to_price_map = get_time_to_price_map_for_day(
        prices_directory=prices_directory, config=config, target_date=target_date
    )

    time_to_watts_map = {}
    for time_str in TIMES:
        time_to_watts_map[time_str] = 0

    for index, row in readings_df.iterrows():
        current_datetime = datetime.strptime(row["Datetime"], "%Y-%m-%d %H:%M:%S")
        current_date = current_datetime.strftime("%Y-%m-%d")
        current_time = current_datetime.strftime("%H:%M")

        if current_date == target_date.strftime("%Y-%m-%d"):
            time_to_watts_map[current_time] += 1

    for time_str in TIMES:
        power += time_to_watts_map[time_str] * (1.0 / config["BLINKS_PER_KILOWATT"])
        try:
            if time_str in time_to_price_map:
                cost += (
                    time_to_watts_map[time_str]
                    * time_to_price_map[time_str]
                    * (1000.0 / config["BLINKS_PER_KILOWATT"])
                    / 100000
                )
        except Exception:
            logging.error(f"Error in calculate_total_cost: {traceback.format_exc()}")

    return cost, power


def calculate_cost_and_power_after_five_thirty_sixty_minutes(
    current_timestamp: int,
    target_date: datetime,
    config: dict,
    monitor_data_directory: str,
    prices_directory: str,
    return_data: dict,
) -> None:
    """
    Calculates the cost and power consumption for the last 5, 30, and 60 minutes based on the given parameters.

    Args:
        current_timestamp (int): The current timestamp in seconds.
        target_date (datetime): The target date to calculate the cost and power consumption for.
        config (dict): A dictionary containing the configuration parameters.
        monitor_data_directory (str): The directory where the energy monitor data is stored.
        prices_directory (str): The directory where the energy prices are stored.
        return_data (dict): A dictionary to store the calculated cost and power consumption.
    """

    readings_df = get_readings_df_from_date(monitor_data_directory=monitor_data_directory, target_date=target_date)
    if readings_df is None or len(readings_df) < 2:
        return_data["five_mins_cost"] = 0
        return_data["five_mins_power"] = 0
        return_data["thirty_mins_cost"] = 0
        return_data["thirty_mins_power"] = 0
        return_data["sixty_mins_cost"] = 0
        return_data["sixty_mins_power"] = 0
        return_data["readings_df"] = None
        return_data["time_to_price_map"] = None

    return_data["readings_df"] = readings_df

    time_to_price_map = get_time_to_price_map_for_day(
        prices_directory=prices_directory, config=config, target_date=target_date
    )
    return_data["time_to_price_map"] = time_to_price_map

    # Note, this must be in order of oldest to newest timestamp.
    # This is because we filter the readings_df everytime in the following loop to make each iteration faster
    timestamps = OrderedDict(
        {
            "sixty_mins": current_timestamp - 3600,
            "thirty_mins": current_timestamp - 1800,
            "five_mins": current_timestamp - 300,
        }
    )

    filtered_readings_df = readings_df
    for timestamp_str, after_timestamp in timestamps.items():
        time_to_watts_map = {}
        for time_str in TIMES:
            time_to_watts_map[time_str] = 0

        filtered_readings_df = filtered_readings_df.loc[filtered_readings_df["Epoch Time"] > after_timestamp]
        filtered_readings_df.reset_index(drop=True, inplace=True)
        if len(filtered_readings_df) < 2:
            return_data[timestamp_str + "_cost"] = 0
            return_data[timestamp_str + "_power"] = 0
            continue

        for index, row in filtered_readings_df.iterrows():
            current_datetime = datetime.strptime(row["Datetime"], "%Y-%m-%d %H:%M:%S")
            current_date = current_datetime.strftime("%Y-%m-%d")
            current_time = current_datetime.strftime("%H:%M")

            if current_date == target_date.strftime("%Y-%m-%d"):
                time_to_watts_map[current_time] += 1

        cost = 0
        power = 0
        for time_str in TIMES:
            power += time_to_watts_map[time_str] * (1000.0 / config["BLINKS_PER_KILOWATT"]) / 1000
            try:
                if time_str in time_to_price_map:
                    cost += (
                        time_to_watts_map[time_str]
                        * time_to_price_map[time_str]
                        * (1000.0 / config["BLINKS_PER_KILOWATT"])
                        / 100000
                    )
            except Exception:
                logging.error(
                    f"Error in calculate_cost_and_power_after_five_thirty_sixty_minutes: {traceback.format_exc()}"
                )

        return_data[timestamp_str + "_cost"] = cost
        return_data[timestamp_str + "_power"] = power


def calculate_total_cost_and_power_faster(
    config: dict,
    target_date: datetime,
    readings_df: pd.DataFrame,
    previous_time_watts_map: dict,
    time_to_price_map: dict,
) -> dict:
    """
    Calculates the total cost and power for a given target date using the provided readings and configuration.

    Args:
        config (dict): A dictionary containing the configuration parameters.
        target_date (datetime): The target date for which the total cost and power should be calculated.
        readings_df (pd.DataFrame): A pandas DataFrame containing the readings data.
        previous_time_watts_map (dict): A dictionary containing the previous time to watts mapping.
        time_to_price_map (dict): A dictionary containing the time to price mapping.

    Returns:
        dict: A dictionary containing the calculated total cost, power, and time to watts mapping.
    """

    calculated_data = {"cost": 0, "power": 0, "average_cost_in_pence": 0, "time_to_watts_map": None}

    if readings_df is None or time_to_price_map is None:
        return calculated_data

    if previous_time_watts_map is None:
        time_to_watts_map = {}
        for time_str in TIMES:
            time_to_watts_map[time_str] = 0
        current_readings_df = readings_df
    else:
        previous_wattage = 0
        for watts in previous_time_watts_map.values():
            previous_wattage += watts
        time_to_watts_map = previous_time_watts_map
        if previous_wattage == 0:
            current_readings_df = readings_df.tail(0)
        else:
            current_readings_df = readings_df.tail(max(0, len(readings_df) - previous_wattage))
            current_readings_df.reset_index(drop=True, inplace=True)

    for index, row in current_readings_df.iterrows():
        current_datetime = datetime.strptime(row["Datetime"], "%Y-%m-%d %H:%M:%S")
        current_date = current_datetime.strftime("%Y-%m-%d")
        current_time = current_datetime.strftime("%H:%M")

        if current_date == target_date.strftime("%Y-%m-%d"):
            time_to_watts_map[current_time] += 1

    # Save the time_to_watts_map to return
    calculated_data["time_to_watts_map"] = time_to_watts_map

    for time_str in TIMES:
        try:
            current_power = time_to_watts_map[time_str] / config["BLINKS_PER_KILOWATT"]
            calculated_data["power"] += current_power

            if time_str in time_to_price_map:
                calculated_data["cost"] += current_power * time_to_price_map[time_str] / 100

        except Exception:
            logging.error(f"Error in calculate_total_cost_and_power_faster: {traceback.format_exc()}")

    if calculated_data["power"] == 0:
        calculated_data["average_cost_in_pence"] = 0
    else:
        calculated_data["average_cost_in_pence"] = 100 * calculated_data["cost"] / calculated_data["power"]

    return calculated_data


def daily_cost_thread(
    date_today: datetime,
    cost_values: list,
    config: dict,
    monitor_data_directory: str,
    prices_directory: str,
    cache_directory: str,
):
    """
    Calculates the daily, weekly, and monthly energy costs and power usage based on the monitor data and prices.

    Args:
        date_today (datetime): The current date and time.
        cost_values (list): A list to store the calculated energy costs and power usage.
        config (dict): A dictionary containing the configuration parameters.
        monitor_data_directory (str): The directory path where the monitor data is stored.
        prices_directory (str): The directory path where the prices are stored.
        cache_directory (str): The directory path where the cached data is stored.

    Returns:
        None
    """
    try:
        yesterday = date_today.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        yesterday_txt_filename = os.path.join(cache_directory, "{}.txt".format(yesterday.strftime("%Y-%m-%d")))
        if os.path.exists(yesterday_txt_filename):
            values = [float(current_line.rstrip()) for current_line in open(yesterday_txt_filename)]
            yesterday_cost = values[0]
            yesterday_power = values[1]
        else:
            yesterday_cost, yesterday_power = calculate_total_cost(
                target_date=yesterday,
                config=config,
                monitor_data_directory=monitor_data_directory,
                prices_directory=prices_directory,
            )
            with open(yesterday_txt_filename, "w") as f:
                f.write(str(yesterday_cost))
                f.write("\n")
                f.write(str(yesterday_power))

        exist_week_readings = True
        week_cost = 0
        week_power = 0
        for i in reversed(range(1, 8)):
            current_date = date_today.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=i)
            readings_csv_filename = os.path.join(
                monitor_data_directory, "{}.csv".format(current_date.strftime("%Y-%m-%d"))
            )
            if not os.path.exists(readings_csv_filename):
                exist_week_readings = False
                break
        if exist_week_readings:
            week_cost += yesterday_cost
            week_power += yesterday_power
            for i in reversed(range(2, 8)):
                current_date = date_today.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=i)

                current_date_txt_filename = os.path.join(
                    cache_directory, "{}.txt".format(current_date.strftime("%Y-%m-%d"))
                )
                if os.path.exists(current_date_txt_filename):
                    values = [float(current_line.rstrip()) for current_line in open(current_date_txt_filename)]
                    current_cost = values[0]
                    current_power = values[1]
                else:
                    current_cost, current_power = calculate_total_cost(
                        target_date=current_date,
                        config=config,
                        monitor_data_directory=monitor_data_directory,
                        prices_directory=prices_directory,
                    )
                    with open(current_date_txt_filename, "w") as f:
                        f.write(str(current_cost))
                        f.write("\n")
                        f.write(str(current_power))

                week_cost += current_cost
                week_power += current_power

        exist_month_readings = True
        month_cost = 0
        month_power = 0
        for i in reversed(range(1, 32)):
            current_date = date_today.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=i)
            readings_csv_filename = os.path.join(
                monitor_data_directory, "{}.csv".format(current_date.strftime("%Y-%m-%d"))
            )
            if not os.path.exists(readings_csv_filename):
                exist_month_readings = False
                break
        if exist_month_readings:
            month_cost += week_cost
            month_power += week_power
            for i in reversed(range(8, 32)):
                current_date = date_today.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=i)

                current_date_txt_filename = os.path.join(
                    cache_directory, "{}.txt".format(current_date.strftime("%Y-%m-%d"))
                )
                if os.path.exists(current_date_txt_filename):
                    values = [float(current_line.rstrip()) for current_line in open(current_date_txt_filename)]
                    current_cost = values[0]
                    current_power = values[1]
                else:
                    current_cost, current_power = calculate_total_cost(
                        target_date=current_date,
                        config=config,
                        monitor_data_directory=monitor_data_directory,
                        prices_directory=prices_directory,
                    )
                    with open(current_date_txt_filename, "w") as f:
                        f.write(str(current_cost))
                        f.write("\n")
                        f.write(str(current_power))

                month_cost += current_cost
                month_power += current_power

        cost_values[0] = yesterday_cost
        cost_values[1] = yesterday_power
        cost_values[2] = week_cost
        cost_values[3] = week_power
        cost_values[4] = month_cost
        cost_values[5] = month_power
    except Exception:
        logging.error(f"Error in daily_cost_thread: {traceback.format_exc()}")


def init_pygame(config: dict) -> tuple:
    """
    Initialises Pygame and sets up the game window according to the given configuration.

    Args:
        config (dict): A dictionary containing configuration parameters for the game window.

    Returns:
        tuple: A tuple containing the Pygame screen object and the Pygame clock object.
    """
    pygame.init()
    if os.name == "nt" or config["DEBUG"]:
        screen = pygame.display.set_mode((config["SCREEN_WIDTH"], config["SCREEN_HEIGHT"]), pygame.RESIZABLE)
    else:
        screen = pygame.display.set_mode((config["SCREEN_WIDTH"], config["SCREEN_HEIGHT"]), pygame.FULLSCREEN)
        pygame.mouse.set_visible(False)

    # Set the window title
    pygame.display.set_caption("Energy Monitor")
    # Used to manage how fast the screen updates
    clock = pygame.time.Clock()

    return screen, clock


def get_pygame_fonts(font_path: str) -> dict:
    """
    Returns a dictionary containing various pygame fonts used in the energy monitor application.

    Args:
        font_path (str): The path to the font file to be used for the FPS count.

    Returns:
        fonts (dict): A dictionary containing various pygame fonts used in the energy monitor application.
    """
    fonts = dict()

    fonts["heading_font"] = pygame.font.Font(font_path, 22)
    fonts["summary_font"] = pygame.font.Font(font_path, 18)
    fonts["number_small_font"] = pygame.font.Font(font_path, 20)
    fonts["number_smaller_font"] = pygame.font.Font(font_path, 18)
    fonts["number_minor_font"] = pygame.font.Font(font_path, 36)
    fonts["number_font"] = pygame.font.Font(font_path, 72)
    fonts["number_major_font"] = pygame.font.Font(font_path, 68)
    fonts["price_font"] = pygame.font.Font(font_path, 64)
    fonts["price_small_font"] = pygame.font.Font(font_path, 36)
    fonts["tomorrow_price_font"] = pygame.font.Font(font_path, 18)
    fonts["price_major_font"] = pygame.font.Font(font_path, 84)
    fonts["time_font"] = pygame.font.Font(font_path, 24)

    return fonts


def get_yesterdays_prices(config: dict, prices_directory: str) -> dict:
    """
    Retrieves energy prices for the previous day.

    Args:
        config (dict): A dictionary containing configuration information.
        prices_directory (str): The directory where energy prices are stored.

    Returns:
        dict: A dictionary containing energy prices for the previous day.
    """
    start_of_day_datetime = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    end_of_day_datetime = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0) - timedelta(days=1)
    return get_energy_prices(
        start_date=start_of_day_datetime, end_date=end_of_day_datetime, config=config, prices_directory=prices_directory
    )


def get_todays_prices(config: dict, prices_directory: str) -> dict:
    """
    Retrieves energy prices for today.

    Args:
        config (dict): A dictionary containing configuration information.
        prices_directory (str): The directory where energy prices are stored.

    Returns:
        dict: A dictionary containing energy prices for today.
    """
    start_of_day_datetime = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day_datetime = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0)
    return get_energy_prices(
        start_date=start_of_day_datetime, end_date=end_of_day_datetime, config=config, prices_directory=prices_directory
    )


def get_tomorrows_prices(config: dict, prices_directory: str) -> dict:
    """
    Retrieves energy prices for tomorrow.

    Args:
        config (dict): A dictionary containing configuration information.
        prices_directory (str): The directory where energy prices are stored.

    Returns:
        dict: A dictionary containing energy prices for tomorrow.
    """
    start_of_day_datetime = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    end_of_day_datetime = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0) + timedelta(days=1)
    return get_energy_prices(
        start_date=start_of_day_datetime, end_date=end_of_day_datetime, config=config, prices_directory=prices_directory
    )


def get_todays_gas_price(config: dict, gas_prices_directory: str) -> float:
    """
    Retrieves gas price for today.

    Args:
        config (dict): A dictionary containing configuration information.
        prices_directory (str): The directory where energy prices are stored.

    Returns:
        dfloatict: A float representing gas price for today.
    """
    start_of_day_datetime = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day_datetime = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0)
    return get_gas_price(
        start_date=start_of_day_datetime,
        end_date=end_of_day_datetime,
        config=config,
        gas_prices_directory=gas_prices_directory,
    )


def get_tomorrows_gas_price(config: dict, gas_prices_directory: str) -> float:
    """
    Retrieves gas price for tomorrow.

    Args:
        config (dict): A dictionary containing configuration information.
        prices_directory (str): The directory where energy prices are stored.

    Returns:
        dfloatict: A float representing gas price for tomorrow.
    """
    start_of_day_datetime = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    end_of_day_datetime = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0) + timedelta(days=1)
    return get_gas_price(
        start_date=start_of_day_datetime,
        end_date=end_of_day_datetime,
        config=config,
        gas_prices_directory=gas_prices_directory,
    )


def compress_single_file_into_zip(input_filename: str, output_filename: str) -> None:
    """
    Compresses a text file in a zip archive.

    Args:
        input_filename (str): The name of the input file to compress.
        output_filename (str): The name of the output zip archive to write the compressed data to.
    """
    # When you use the ZipFile.write() method to add a file to a zip archive,
    # it includes the file's full path in the archive by default. This means
    # that if the file is located in a directory, the directory structure
    # will also be included in the archive. So, if you want to add only the
    # file to the archive without including its directory structure, you can
    # use the arcname parameter of the write() method to specify a different
    # name for the file in the archive.
    with zipfile.ZipFile(output_filename, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.write(input_filename, arcname=os.path.basename(input_filename))


def parse_date_from_text(text: str, date_format: str = "%Y-%m-%d.csv") -> datetime:
    """
    Parses a date from a string using the specified date format.

    Args:
        text (str): The string to parse the date from.
        date_format (str, optional): The format of the date string. Defaults to "%Y-%m-%d".

    Returns:
        datetime: The parsed datetime object, or None if the string could not be parsed.
    """
    try:
        return datetime.strptime(text, date_format)
    except ValueError:
        return None


def compress_and_archive_old_readings(
    monitor_data_directory: str, archive_data_directory: str, input_date: str, days_after_input_date_to_compress: int
) -> None:
    """
    Compresses and archives readings from a given date.

    Args:
        monitor_data_directory (str): The directory where the monitor data is stored.
        archive_data_directory (str): The directory where the archive data is stored.
        input_date (str): The date to compress and archive readings from.
        days_after_input_date_to_compress (int): The no. of days after the input date to compress and archive readings.
    """
    newest_date_to_compress = input_date - timedelta(days=days_after_input_date_to_compress)
    readings_csv_paths = sorted(glob.glob(os.path.join(monitor_data_directory, "*.csv")))
    for readings_csv_filename in readings_csv_paths:
        current_readings_date = parse_date_from_text(
            os.path.basename(readings_csv_filename), date_format="%Y-%m-%d.csv"
        ).date()

        if current_readings_date is None:
            continue

        if current_readings_date >= newest_date_to_compress:
            continue

        archive_filename = os.path.join(archive_data_directory, f"{current_readings_date}.zip")
        if os.path.exists(archive_filename):
            logging.info(f"Archive already exists: {archive_filename}")
            logging.info(f"Deleting: {readings_csv_filename}")
            os.remove(readings_csv_filename)
            logging.info(f"Deleted: {readings_csv_filename}")
            continue

        logging.info(f"Compressing and archiving: {readings_csv_filename}")

        with tempfile.TemporaryDirectory() as temp_dir:
            readings_zip_filename = os.path.join(temp_dir, f"{current_readings_date}.zip")
            compress_single_file_into_zip(input_filename=readings_csv_filename, output_filename=readings_zip_filename)

            # shutil.move() will overwrite the file if it already exists
            shutil.move(readings_zip_filename, archive_filename)
            logging.info(f"Archived: {archive_filename}")

            os.remove(readings_csv_filename)
            logging.info(f"Deleted: {readings_csv_filename}")


def main():
    # Set up the directories
    data_directory = os.path.join(SCRIPT_DIR, "data")
    os.makedirs(data_directory, exist_ok=True)
    monitor_data_directory = os.path.join(data_directory, "monitor")
    os.makedirs(monitor_data_directory, exist_ok=True)
    archive_data_directory = os.path.join(data_directory, "archive")
    os.makedirs(archive_data_directory, exist_ok=True)
    prices_directory = os.path.join(data_directory, "prices")
    os.makedirs(prices_directory, exist_ok=True)
    gas_prices_directory = os.path.join(data_directory, "prices", "gas")
    os.makedirs(gas_prices_directory, exist_ok=True)
    cache_directory = os.path.join(data_directory, "cache")
    os.makedirs(cache_directory, exist_ok=True)

    # Set up logging
    logger_path = os.path.join(SCRIPT_DIR, "energy_monitor.log")
    setup_logging(logger_path, log_level=logging.INFO)

    # Get the configuration
    utils_directory = os.path.join(SCRIPT_DIR, "utils")
    config_path = os.path.join(utils_directory, "config.yaml")
    if not os.path.exists(config_path):
        config_path = os.path.join(utils_directory, "config.template.yaml")
    config = get_config_from_yaml(config_path)

    # Start the energy monitor thread
    energy_loggger_thread = EnergyMonitor(config=config, save_directory=monitor_data_directory)
    energy_loggger_thread.run()

    # Hide the Pygame support prompt and detect AVX2
    os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "hide"

    # Set up the Pygame window
    screen, clock = init_pygame(config=config)

    # Used to indicate if we are done so we exit the program
    done = False

    # In case of a previous bad restart or power cut, fix any text corruption in the latest two energy log files
    fix_data_corruption_of_latest_two_files(monitor_data_directory)

    # Get the fonts used, e.g. to reference them: fonts["time_font"]
    font_path = os.path.join(data_directory, "Roboto-Bold.ttf")
    fonts = get_pygame_fonts(font_path=font_path)

    # Get prices for today and yesterday
    get_yesterdays_prices(config=config, prices_directory=prices_directory)
    time_to_price_map = get_todays_prices(config=config, prices_directory=prices_directory)
    todays_gas_price = get_todays_gas_price(config=config, gas_prices_directory=gas_prices_directory)

    # Used to determine if we go to the next day whilst running
    tomorrow = date.today() + timedelta(days=1)

    previous_time_watts_map = None
    tomorrows_average_unit_price = None
    tomorrows_gas_price = None

    week_cost = 0
    week_power = 0

    month_cost = 0
    month_power = 0

    yesterday = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    yesterday_cost, yesterday_power = calculate_total_cost(
        target_date=yesterday,
        config=config,
        monitor_data_directory=monitor_data_directory,
        prices_directory=prices_directory,
    )

    # Gray Colour for headings, white for default
    heading_colour = (220, 220, 220)
    default_colour = (255, 255, 255)

    first_run = True
    prices_file_exists = False
    gas_price_file_exists = False
    cost_thread = None
    past_cost_and_power_thread = None
    past_cost_and_power_thread_first_run = True
    cost_values = [0] * 6
    while not done:
        try:
            # Handle key press events to quit
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    done = True
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_q:
                        done = True
                    elif event.key == pygame.K_ESCAPE:
                        done = True

            # Clear screen to black before drawing
            screen.fill((0, 0, 0))

            # Draw FPS Counter if enabled
            if config["SHOW_FPS"]:
                screen.blit(update_fps(clock=clock, font_path=font_path), (755, 440))

            # Reset readings, costs and download new prices for next day
            if date.today() == tomorrow or first_run:
                first_run = False

                previous_time_watts_map = None
                tomorrows_average_unit_price = None
                tomorrows_gas_price = None

                past_cost_and_power_thread_first_run = True
                if past_cost_and_power_thread is not None:
                    past_cost_and_power_thread.join()
                    past_cost_and_power_thread = None

                # Compress and archive old readings
                compress_and_archive_old_readings(
                    monitor_data_directory=monitor_data_directory,
                    archive_data_directory=archive_data_directory,
                    input_date=date.today(),
                    days_after_input_date_to_compress=32,
                )

                # Get prices for today and set new tomorrow
                time_to_price_map = get_todays_prices(config=config, prices_directory=prices_directory)
                todays_gas_price = get_todays_gas_price(config=config, gas_prices_directory=gas_prices_directory)

                tomorrow = date.today() + timedelta(days=1)

                # Check files exists
                prices_file_exists = check_prices_file_exists(
                    config=config, prices_directory=prices_directory, current_date=datetime.now()
                )
                gas_price_file_exists = check_gas_price_file_exists(
                    config=config, gas_prices_directory=gas_prices_directory, current_date=datetime.now()
                )

                # Start the thread to calculate the past cost/power
                cost_values = [0] * 6
                cost_thread = threading.Thread(
                    target=daily_cost_thread,
                    args=(
                        datetime.now(),
                        cost_values,
                        config,
                        monitor_data_directory,
                        prices_directory,
                        cache_directory,
                    ),
                )
                cost_thread.start()

                # Set the past costs/power to default values
                yesterday_cost = cost_values[0]
                yesterday_power = cost_values[1]
                week_cost = cost_values[2]
                week_power = cost_values[3]
                month_cost = cost_values[4]
                month_power = cost_values[5]

            # If the cost thread has finished, update the values for past costs/power
            if cost_thread is not None and not cost_thread.is_alive():
                yesterday_cost = cost_values[0]
                yesterday_power = cost_values[1]
                week_cost = cost_values[2]
                week_power = cost_values[3]
                month_cost = cost_values[4]
                month_power = cost_values[5]
                cost_thread = None

            # Get unit prices
            current_time = datetime.now()
            if int(current_time.strftime("%M")) < 30:
                unit_price_now_start = datetime.combine(
                    date.today(), datetime_time(int(current_time.strftime("%H")), 0)
                )
            else:
                unit_price_now_start = datetime.combine(
                    date.today(), datetime_time(int(current_time.strftime("%H")), 30)
                )
            unit_price_now_end = unit_price_now_start + timedelta(minutes=30)
            unit_price_future_start = unit_price_now_end
            unit_price_future_end = unit_price_future_start + timedelta(minutes=30)

            unit_price_now_start = unit_price_now_start.strftime("%H:%M")
            unit_price_now_end = unit_price_now_end.strftime("%H:%M")

            # If not offline and we do not have the correct prices, try to get them again every 10 minutes
            if config["OFFLINE"] is not True and not prices_file_exists and datetime.now().minute % 10 == 0:
                time_to_price_map = get_todays_prices(config=config, prices_directory=prices_directory)
                prices_file_exists = check_prices_file_exists(
                    config=config, prices_directory=prices_directory, current_date=datetime.now()
                )

            # If not offline and we do not have today's gas price, try to get them again every 10 minutes
            if config["OFFLINE"] is not True and not gas_price_file_exists and datetime.now().minute % 10 == 0:
                todays_gas_price = get_todays_gas_price(config=config, gas_prices_directory=gas_prices_directory)
                gas_price_file_exists = check_gas_price_file_exists(
                    config=config, gas_prices_directory=gas_prices_directory, current_date=datetime.now()
                )

            # After 4pm, if on Agile, if we still do not have all the prices for today, try to get them again
            if (
                len(time_to_price_map) < 48
                and config["OCTOPUS_TARIFF"] == "AGILE"
                and datetime.now().hour > 16
                and datetime.now().minute % 10 == 0
            ):
                time_to_price_map = get_todays_prices(config=config, prices_directory=prices_directory)

            # If online and we do not have this period's price try to get it again from the API
            if config["OFFLINE"] is not True and unit_price_now_start not in time_to_price_map:
                time_to_price_map = get_todays_prices(config=config, prices_directory=prices_directory)

            # Get the unit price for this period, if it does not exist we use the config'sdefault price
            if unit_price_now_start in time_to_price_map:
                unit_price_now = time_to_price_map[unit_price_now_start]
            else:
                unit_price_now = config["DEFAULT_UNIT_PRICE"]

            # Get the average unit price for today
            average_unit_price = sum(time_to_price_map.values()) / float(len(time_to_price_map))

            # After 8 AM, if not offline, get tomorrow's average unit price for electricity
            if (
                config["OFFLINE"] is not True
                and len(time_to_price_map) == 48
                and datetime.now().hour > 8
                and datetime.now().minute % 10 == 0
                and tomorrows_average_unit_price is None
            ):
                tomorrows_time_to_price_map = get_tomorrows_prices(config=config, prices_directory=prices_directory)
                tomorrows_average_unit_price = sum(tomorrows_time_to_price_map.values()) / float(
                    len(tomorrows_time_to_price_map)
                )

            # After 4 PM, if not offline, get tomorrow's unit price for gas
            if (
                config["OFFLINE"] is not True
                and len(time_to_price_map) == 48
                and datetime.now().hour > 16
                and datetime.now().minute % 30 == 0
                and tomorrows_gas_price is None
            ):
                tomorrows_gas_price = get_tomorrows_gas_price(config=config, gas_prices_directory=gas_prices_directory)

            # Get the unit price for the next period, if it does not exist we use the config's default price
            unit_price_future_start = unit_price_future_start.strftime("%H:%M")
            unit_price_future_end = unit_price_future_end.strftime("%H:%M")
            if unit_price_future_start in time_to_price_map and unit_price_future_start != "00:00":
                unit_price_future = time_to_price_map[unit_price_future_start]
            else:
                # Either we need the future price for tomorrow
                if unit_price_future_start == "00:00":
                    start_of_day_datetime = datetime.combine(tomorrow, datetime_time(0, 0))
                    end_of_day_datetime = datetime.combine(tomorrow, datetime_time(23, 59))
                    future_time_to_price_map = get_energy_prices(
                        start_date=start_of_day_datetime,
                        end_date=end_of_day_datetime,
                        config=config,
                        prices_directory=prices_directory,
                    )
                    if unit_price_future_start in future_time_to_price_map:
                        unit_price_future = future_time_to_price_map[unit_price_future_start]
                    else:
                        unit_price_future = config["DEFAULT_UNIT_PRICE"]
                else:
                    # or we are missing data for today
                    time_to_price_map = get_todays_prices(config=config, prices_directory=prices_directory)
                    if unit_price_future_start in time_to_price_map:
                        unit_price_future = time_to_price_map[unit_price_future_start]
                    else:
                        unit_price_future = config["DEFAULT_UNIT_PRICE"]

            # Get the readings filename for today
            readings_csv_filename = os.path.join(
                monitor_data_directory,
                "{}.csv".format(datetime.now().strftime("%Y-%m-%d")),
            )

            # Check if current day has readings, otherwise sleep for 1 second and check again, ad infinitum
            while not os.path.exists(readings_csv_filename) or not has_readings(readings_csv_filename):
                time.sleep(1)

            power_now = live_energy_time_reading(
                readings_csv_filename=readings_csv_filename, blinks_per_kilowatt=config["BLINKS_PER_KILOWATT"]
            )
            cost_now = unit_price_now * power_now / 1000

            power_total = line_count(readings_csv_filename) / config["BLINKS_PER_KILOWATT"]

            cost_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

            # Run to get initial cost and power data
            if past_cost_and_power_thread_first_run:
                cost_and_power_data = dict()
                calculate_cost_and_power_after_five_thirty_sixty_minutes(
                    current_timestamp=time.time(),
                    target_date=cost_date,
                    config=config,
                    monitor_data_directory=monitor_data_directory,
                    prices_directory=prices_directory,
                    return_data=cost_and_power_data,
                )
                cost_five = cost_and_power_data["five_mins_cost"]
                cost_half = cost_and_power_data["thirty_mins_cost"]
                cost_hour = cost_and_power_data["sixty_mins_cost"]
                readings_df = cost_and_power_data["readings_df"]
                time_to_price_map = cost_and_power_data["time_to_price_map"]
                past_cost_and_power_thread_first_run = False

            if past_cost_and_power_thread is None and not past_cost_and_power_thread_first_run:
                cost_and_power_data = dict()
                past_cost_and_power_thread = threading.Thread(
                    target=calculate_cost_and_power_after_five_thirty_sixty_minutes,
                    args=(
                        time.time(),
                        cost_date,
                        config,
                        monitor_data_directory,
                        prices_directory,
                        cost_and_power_data,
                    ),
                )
                past_cost_and_power_thread.start()

            if past_cost_and_power_thread is not None and not past_cost_and_power_thread.is_alive():
                cost_five = cost_and_power_data["five_mins_cost"]
                cost_half = cost_and_power_data["thirty_mins_cost"]
                cost_hour = cost_and_power_data["sixty_mins_cost"]
                readings_df = cost_and_power_data["readings_df"]
                time_to_price_map = cost_and_power_data["time_to_price_map"]
                past_cost_and_power_thread = None

            total_cost_power_data_dict = calculate_total_cost_and_power_faster(
                config=config,
                target_date=cost_date,
                readings_df=readings_df,
                previous_time_watts_map=previous_time_watts_map,
                time_to_price_map=time_to_price_map,
            )
            cost_total = total_cost_power_data_dict["cost"]
            average_cost_in_pence = total_cost_power_data_dict["average_cost_in_pence"]
            previous_time_watts_map = total_cost_power_data_dict["time_to_watts_map"]

            # Costs
            text = fonts["heading_font"].render("Current Cost:", True, heading_colour)
            screen.blit(text, (8, 50))

            text = fonts["price_major_font"].render("{:4.1f}p".format(cost_now), True, default_colour)
            screen.blit(text, (25, 75))

            text = fonts["heading_font"].render("Total Cost (5 min / 30 min / 60 min / Daily):", True, heading_colour)
            screen.blit(text, (260, 48))

            text = fonts["number_small_font"].render(
                "£{:4.2f} / £{:4.2f} / £{:4.2f}".format(cost_five, cost_half, cost_hour),
                True,
                default_colour,
            )
            screen.blit(text, (280, 90))

            text = fonts["price_major_font"].render("/ £{:4.2f}".format(cost_total), True, default_colour)
            screen.blit(text, (480, 75))

            # Power
            text = fonts["heading_font"].render("Current Power:", True, heading_colour)
            screen.blit(text, (8, 180))

            if len(str(int(np.round(power_now)))) < 4:
                text = fonts["number_font"].render("{:4.0f}".format(power_now), True, default_colour)
                screen.blit(text, (15, 210))
                text = fonts["number_minor_font"].render("W", True, default_colour)
                screen.blit(text, (170, 243))
            else:
                if len(str(int(np.round(power_now)))) < 6:
                    text = fonts["number_font"].render("{:>5.2f}".format(power_now / 1000), True, default_colour)
                elif len(str(int(np.round(power_now)))) == 6:
                    text = fonts["number_font"].render("{:>5.1f}".format(power_now / 1000), True, default_colour)
                else:
                    text = fonts["number_font"].render("{:>5.0f}".format(power_now / 1000), True, default_colour)
                screen.blit(text, (15, 210))
                text = fonts["number_minor_font"].render("kW", True, default_colour)
                if len(str(int(np.round(power_now)))) == 4:
                    screen.blit(text, (190, 243))
                else:
                    screen.blit(text, (210, 243))

            text = fonts["heading_font"].render("Used Power:", True, heading_colour)
            screen.blit(text, (298, 180))

            if len("{:d}".format(int(np.round(power_total, decimals=2)))) < 3:
                text = fonts["number_major_font"].render("{:5.2f}".format(power_total), True, default_colour)
                screen.blit(text, (306, 212))
            else:
                text = fonts["number_major_font"].render("{:5.1f}".format(power_total), True, default_colour)
                screen.blit(text, (306, 212))

            if len("{:d}".format(int(np.round(power_total, decimals=2)))) == 1:
                text = fonts["number_minor_font"].render("kW", True, default_colour)
                screen.blit(text, (473, 242))
            else:
                text = fonts["number_minor_font"].render("kW", True, default_colour)
                screen.blit(text, (491, 242))

            if config["OCTOPUS_TARIFF"] == "TRACKER" or config["OCTOPUS_TARIFF"] == "FLEXIBLE":
                # Show fixed Unit Price if on Tracker
                text = fonts["heading_font"].render("Today's Unit Price:", True, heading_colour)
                screen.blit(text, (588, 180))

                text = fonts["number_major_font"].render("{:4.1f}p".format(average_unit_price), True, default_colour)
                screen.blit(text, (600, 212))

                # Gas Unit Price Present/Future
                text = fonts["heading_font"].render("Today's Gas Price (p/kWh or £/unit):", True, heading_colour)
                screen.blit(text, (8, 310))
                if todays_gas_price is not None:
                    kw_per_gas_unit = (2.83 * 1.02264 * 38.7) / 3.6
                    text = fonts["price_font"].render(
                        "{:4.1f}p / £{:4.2f}".format(todays_gas_price, todays_gas_price * kw_per_gas_unit / 100),
                        True,
                        default_colour,
                    )
                    screen.blit(text, (30, 335))
                else:
                    text = fonts["price_font"].render("N/A", True, default_colour)
                    screen.blit(text, (120, 335))

                # Show tomorrow's average unit price if available
                text = fonts["heading_font"].render("Tomorrow's Elec/Gas kWh Price:", True, heading_colour)
                screen.blit(text, (440, 310))

                # Show N/A if tomorrow's average unit price is not available
                if tomorrows_average_unit_price is None and tomorrows_gas_price is None:
                    text = fonts["price_font"].render("N/A", True, default_colour)
                    screen.blit(text, (545, 335))
                elif tomorrows_average_unit_price is not None and tomorrows_gas_price is None:
                    text = fonts["price_font"].render(
                        "{:4.1f}p / -".format(tomorrows_average_unit_price), True, default_colour
                    )
                    screen.blit(text, (470, 335))
                elif tomorrows_average_unit_price is None and tomorrows_gas_price is not None:
                    text = fonts["price_font"].render("- / {:4.1f}p".format(tomorrows_gas_price), True, default_colour)
                    screen.blit(text, (480, 335))
                else:
                    text = fonts["price_font"].render(
                        "{:2.0f}p / {:2.0f}p".format(tomorrows_average_unit_price, tomorrows_gas_price),
                        True,
                        default_colour,
                    )
                    screen.blit(text, (470, 335))
            else:
                # Average Unit Cost
                text = fonts["heading_font"].render("Average Unit Cost:", True, heading_colour)
                screen.blit(text, (589, 180))
                text = fonts["number_major_font"].render("{:4.1f}p".format(average_cost_in_pence), True, default_colour)
                screen.blit(text, (600, 212))

                # Current Unit Price
                text = fonts["heading_font"].render(
                    "Unit Price ({} - {}):".format(unit_price_now_start, unit_price_now_end),
                    True,
                    heading_colour,
                )
                screen.blit(text, (8, 310))

                text = fonts["price_font"].render("{:4.1f}p".format(unit_price_now), True, default_colour)
                screen.blit(text, (60, 335))

                # Future Unit Price
                text = fonts["heading_font"].render(
                    "Unit Price ({} - {}):".format(unit_price_future_start, unit_price_future_end),
                    True,
                    heading_colour,
                )
                screen.blit(text, (298, 310))

                text = fonts["price_font"].render("{:4.1f}p".format(unit_price_future), True, default_colour)
                screen.blit(text, (350, 335))

                # Show current average Unit Price, and tomorrow's average unit price if available
                text = fonts["heading_font"].render("Average Unit Price:", True, heading_colour)
                screen.blit(text, (587, 310))

                if tomorrows_average_unit_price is None:
                    text = fonts["price_font"].render("{:4.1f}p".format(average_unit_price), True, default_colour)
                    screen.blit(text, (600, 335))
                else:
                    text = fonts["price_small_font"].render("{:4.1f}p".format(average_unit_price), True, default_colour)
                    screen.blit(text, (635, 339))

                    text = fonts["tomorrow_price_font"].render(
                        "Tomorrow: {:4.1f}p".format(tomorrows_average_unit_price),
                        True,
                        default_colour,
                    )
                    screen.blit(text, (613, 385))

            yesterday_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
            last_week_start_date = yesterday_date - timedelta(days=6)
            last_month_start_date = yesterday_date - timedelta(days=30)

            if yesterday_cost > 0 and yesterday_power > 0:
                # Yesterday Cost
                text = fonts["summary_font"].render(
                    "Yesterday [{}]:".format(yesterday_date.strftime("%d/%m")),
                    True,
                    heading_colour,
                )
                screen.blit(text, (8, 428))

                text = fonts["summary_font"].render(
                    "£{:.2f} ({:.1f} kW @ {:.1f}p)".format(
                        yesterday_cost,
                        yesterday_power,
                        100 * yesterday_cost / yesterday_power,
                    ),
                    True,
                    heading_colour,
                )
                screen.blit(text, (8, 450))

            if week_cost > 0 and week_power > 0:
                # Week Cost
                text = fonts["summary_font"].render(
                    "Past Week [{} - {}]:".format(
                        last_week_start_date.strftime("%d/%m"),
                        yesterday_date.strftime("%d/%m"),
                    ),
                    True,
                    heading_colour,
                )
                screen.blit(text, (258, 428))

                text = fonts["summary_font"].render(
                    "£{:.2f} ({:.1f} kW @ {:.1f}p)".format(week_cost, week_power, 100 * week_cost / week_power),
                    True,
                    heading_colour,
                )
                screen.blit(text, (258, 450))

            if month_cost > 0 and month_power > 0:
                # Month Cost
                text = fonts["summary_font"].render(
                    "Past Month [{} - {}]:".format(
                        last_month_start_date.strftime("%d/%m"),
                        yesterday_date.strftime("%d/%m"),
                    ),
                    True,
                    heading_colour,
                )
                screen.blit(text, (523, 428))

                text = fonts["summary_font"].render(
                    "£{:.2f} ({:.1f} kW @ {:.1f}p)".format(month_cost, month_power, 100 * month_cost / month_power),
                    True,
                    heading_colour,
                )
                screen.blit(text, (523, 450))

            # Display date and time
            text = fonts["time_font"].render(
                "{} {} {}".format(
                    datetime.now().strftime("%A"),
                    day_with_suffix(),
                    datetime.now().strftime("%B %Y"),
                ),
                True,
                heading_colour,
            )
            screen.blit(text, (8, 8))

            text = fonts["time_font"].render("{}".format(datetime.now().strftime("%H:%M:%S")), True, heading_colour)
            screen.blit(text, (693, 8))

            pygame.display.flip()
            clock.tick(5)
        except Exception:
            logging.error(f"Exception in main loop: {traceback.format_exc()}")

    energy_loggger_thread.stop()


if __name__ == "__main__":
    main()
