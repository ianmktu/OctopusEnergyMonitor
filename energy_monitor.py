#!/usr/bin/python3

import time
import traceback
import threading
import os
import csv
import random
import requests

os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import pygame

import numpy as np
import pandas as pd

from ltr559 import LTR559

from dateutil import parser
from datetime import date, datetime, timedelta
from datetime import time as datetime_time

from pathlib import Path

from file_read_backwards import FileReadBackwards

from tzlocal import get_localzone

LOCAL_TIMEZONE = get_localzone() 

API_KEY = ''
API_PASS = ''
AGILE_PRICES_URL = 'https://api.octopus.energy/v1/products/AGILE-18-02-21/electricity-tariffs/E-1R-AGILE-18-02-21-C/standard-unit-rates/'
GO_PRICES_URL = 'https://api.octopus.energy/v1/products/GO-21-05-13/electricity-tariffs/E-1R-GO-21-05-13-C/standard-unit-rates/'

ON_OCTOPUS_GO = True

SHOW_FPS = False
WIDTH = 800
HEIGHT = 480

BLINKS_PER_KILOWATT = 1000 + 5
MULTIPLIER = 1000.0 / BLINKS_PER_KILOWATT

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
    "23:30"
]

PRICES = [
    9.324,
    9.576,
    10.017,
    9.45,
    8.946,
    8.568,
    8.736,
    8.4,
    7.56,
    6.3,
    8.673,
    8.82,
    10.08,
    9.45,
    8.484,
    11.13,
    10.29,
    10.248,
    10.5,
    9.492,
    10.101,
    9.45,
    9.576,
    9.576,
    9.639,
    9.576,
    10.08,
    9.597,
    9.765,
    9.765,
    9.933,
    10.92,
    23.52,
    31.5,
    29.652,
    29.736,
    25.2,
    21.42,
    10.5,
    8.736,
    9.387,
    9.177,
    11.34,
    7.896,
    7.56,
    7.56,
    9.03,
    9.03,
]

GO_TIME_PRICES_MAP = {
    "00:00":15.9,
    "00:30":5.00,
    "01:00":5.00,
    "01:30":5.00,
    "02:00":5.00,
    "02:30":5.00,
    "03:00":5.00,
    "03:30":5.00,
    "04:00":5.00,
    "04:30":15.9,
    "05:00":15.9,
    "05:30":15.9,
    "06:00":15.9,
    "06:30":15.9,
    "07:00":15.9,
    "07:30":15.9,
    "08:00":15.9,
    "08:30":15.9,
    "09:00":15.9,
    "09:30":15.9,
    "10:00":15.9,
    "10:30":15.9,
    "11:00":15.9,
    "11:30":15.9,
    "12:00":15.9,
    "12:30":15.9,
    "13:00":15.9,
    "13:30":15.9,
    "14:00":15.9,
    "14:30":15.9,
    "15:00":15.9,
    "15:30":15.9,
    "16:00":15.9,
    "16:30":15.9,
    "17:00":15.9,
    "17:30":15.9,
    "18:00":15.9,
    "18:30":15.9,
    "19:00":15.9,
    "19:30":15.9,
    "20:00":15.9,
    "20:30":15.9,
    "21:00":15.9,
    "21:30":15.9,
    "22:00":15.9,
    "22:30":15.9,
    "23:00":15.9,
    "23:30":15.9
}


class EnergyMonitor:
    def __init__(self):
        self.thread = None
        self.started = True

        if os.name == 'nt':
            self.ltr559 = None
        else:
            self.ltr559 = LTR559()
            self.ltr559.set_light_integration_time_ms(50)
            self.ltr559.set_light_repeat_rate_ms(50)
        self.sleep_time_seconds = 0.02

        self.script_directory = os.path.dirname(os.path.realpath(__file__))
        self.log_directory = os.path.join(self.script_directory, "log")
        if not os.path.exists(self.log_directory):
            os.makedirs(self.log_directory)

    def monitor(self):
        previous_lux = 0
        previous_previous_time = -1
        previous_time = -1
        previous_time_origin = "fixed"
        current_time = -1
        fix_counter = 0
        while self.started:
            try:
                if os.name == 'nt':
                    current_lux = random.randint(0, 2)
                    time.sleep(random.randint(4, 10))
                else:
                    self.ltr559.update_sensor()
                    current_lux = self.ltr559.get_lux()

                if current_lux > 0.0:
                    if abs(previous_lux - current_lux) < 1e-2:
                        time.sleep(self.sleep_time_seconds)
                        continue

                    previous_previous_time = previous_time
                    previous_time = current_time
                    previous_time_origin = "original"
                    current_time = time.time()

                    if previous_previous_time > 0 and previous_time > 0:
                        if ((current_time - previous_time) > (previous_time - previous_previous_time) * 1.7) and fix_counter <= 2:
                            fix_counter += 1

                            num_segments = np.round((current_time - previous_time) / (previous_time - previous_previous_time)).astype(int)

                            original_previous_time = previous_time
                            original_previous_lux = previous_lux
                            for index in range(max(0, num_segments - 1)):
                                current_lux_fixed = ((current_lux + original_previous_lux) / 2) + 1 * index
                                current_time_fixed = original_previous_time + ((current_time - original_previous_time) / num_segments) * (index + 1)
                                unit_price_start_time = get_unit_datetime(current_time_fixed)

                                csv_filename = os.path.join(self.log_directory, "{}.csv".format(datetime.fromtimestamp(current_time_fixed).strftime("%Y-%m-%d")))
                                if not os.path.exists(csv_filename):
                                    with open(csv_filename, "a") as f:
                                        f.write("{:06.2f},{:.6f},{},{},{}".format(
                                            previous_lux, previous_time, datetime.fromtimestamp(previous_time).strftime("%H:%M:%S.%f"), get_unit_datetime(previous_time),
                                            previous_time_origin))
                                        f.write("\n")

                                with open(csv_filename, "a") as f:
                                    f.write("{:06.2f},{:.6f},{},{},{}".format(
                                        current_lux_fixed, current_time_fixed, datetime.fromtimestamp(current_time_fixed).strftime("%H:%M:%S.%f"), unit_price_start_time, "fixed"))
                                    f.write("\n")

                                if is_first_input_to_csv(csv_filename):
                                    yesterday = datetime.fromtimestamp(current_time_fixed) - timedelta(days=1)
                                    csv_filename = os.path.join(self.log_directory, "{}.csv".format(yesterday.strftime("%Y-%m-%d")))
                                    with open(csv_filename, "a") as f:
                                        f.write("{:06.2f},{:.6f},{},{},{}".format(
                                            current_lux_fixed, current_time_fixed, datetime.fromtimestamp(current_time_fixed).strftime("%H:%M:%S.%f"), unit_price_start_time, "fixed"))
                                        f.write("\n")

                                previous_previous_time = previous_time
                                previous_lux = current_lux_fixed
                                previous_time = current_time_fixed
                                previous_time_origin = "fixed"
                        else:
                            fix_counter = 0

                    csv_filename = os.path.join(self.log_directory, "{}.csv".format(datetime.fromtimestamp(current_time).strftime("%Y-%m-%d")))
                    if previous_previous_time > 0 and previous_time > 0:
                        if not os.path.exists(csv_filename):
                            with open(csv_filename, "a") as f:
                                f.write("{:06.2f},{:.6f},{},{},{}".format(
                                    previous_lux, previous_time, datetime.fromtimestamp(previous_time).strftime("%H:%M:%S.%f"), get_unit_datetime(previous_time), previous_time_origin))
                                f.write("\n")

                    unit_price_start_time = get_unit_datetime(current_time)
                    with open(csv_filename, "a") as f:
                        f.write("{:06.2f},{:.6f},{},{},{}".format(
                            current_lux, current_time, datetime.fromtimestamp(current_time).strftime("%H:%M:%S.%f"), unit_price_start_time, "original"))
                        f.write("\n")

                    if is_first_input_to_csv(csv_filename) and previous_time > 0:
                        yesterday = datetime.fromtimestamp(current_time) - timedelta(days=1)
                        csv_filename = os.path.join(self.log_directory, "{}.csv".format(yesterday.strftime("%Y-%m-%d")))
                        if os.path.exists(csv_filename):
                            with open(csv_filename, "a") as f:
                                f.write("{:06.2f},{:.6f},{},{},{}".format(
                                    current_lux, current_time, datetime.fromtimestamp(current_time).strftime("%H:%M:%S.%f"), unit_price_start_time, "original"))
                                f.write("\n")

                    previous_lux = current_lux
                time.sleep(self.sleep_time_seconds)
            except:
                traceback.print_exc()
                if os.name == 'nt':
                    self.ltr559 = None
                else:
                    self.ltr559 = LTR559()
                    self.ltr559.set_light_integration_time_ms(50)
                    self.ltr559.set_light_repeat_rate_ms(50)
                time.sleep(self.sleep_time_seconds)

    def run(self):
        self.thread = threading.Thread(target=self.monitor, args=())
        self.thread.start()

    def stop(self):
        self.started = False
        self.thread.join()


def get_unit_datetime(epoch_time):
    if int(datetime.fromtimestamp(epoch_time).strftime("%M")) < 30:
        unit_price_start_time = datetime.combine(
            date.today(),
            datetime_time(int(datetime.fromtimestamp(epoch_time).strftime("%H")), 0)
        )
    else:
        unit_price_start_time = datetime.combine(
            date.today(),
            datetime_time(int(datetime.fromtimestamp(epoch_time).strftime("%H")), 30)
        )

    return unit_price_start_time


def is_first_input_to_csv(filename):
    with open(filename) as f:
        line_count = 0
        for _ in f:
            line_count += 1
            if line_count > 2:
                return False
    return True


def has_readings(filename):
    with open(filename) as f:
        line_count = 0
        for _ in f:
            line_count += 1
            if line_count > 2:
                return True
    return False


def update_fps():
    fps = str(int(clock.get_fps()))
    font = pygame.font.Font("Roboto-Bold.ttf", 32)
    fps_text = font.render(fps, 1, pygame.Color("coral"))
    return fps_text


def day_with_suffix():
    dic = {'1': 'st', '2': 'nd', '3': 'rd'}
    if os.name == 'nt':
        x = time.strftime('%#d')
    else:
        x = time.strftime('%-d')
    return x + ('th' if len(x) == 2 and x[0] == '1' else dic.get(x[-1], 'th'))


def get_agile_prices(start_date, end_date):
    start_date_localized = start_date.astimezone(LOCAL_TIMEZONE)
    end_date_localized = end_date.astimezone(LOCAL_TIMEZONE)

    period_from_and_to_params = {
        'period_from': start_date_localized.isoformat(),
        'period_to': end_date_localized.isoformat()
    }

    try:
        script_directory = os.path.dirname(os.path.realpath(__file__))
        price_directory = os.path.join(script_directory, "prices")
        if not os.path.exists(price_directory):
            os.makedirs(price_directory)

        price_csv_filename = os.path.join(price_directory, "{}-agile-prices.csv".format(start_date.strftime("%Y-%m-%d")))        
        if os.path.exists(price_csv_filename):
            if ON_OCTOPUS_GO:
                price_csv_filename = os.path.join(price_directory, "octopus-go-prices.csv")
            prices_df = pd.read_csv(price_csv_filename, dtype={'Date': 'str', 'Time': 'str', 'Price': 'float16'})
            if len(prices_df) == 48:
                time_to_price_map = {}
                for i in range(len(prices_df)):
                    time_to_price_map[TIMES[i]] = prices_df.loc[prices_df['Time'] == TIMES[i]]['Price'].values[0]
                return time_to_price_map

        if API_KEY is not '':
            r = requests.get(
                AGILE_PRICES_URL,
                auth=requests.auth.HTTPBasicAuth(API_KEY, API_PASS),
                params=period_from_and_to_params
            )
        else:
            r = requests.get(
                AGILE_PRICES_URL,
                params=period_from_and_to_params
            )

        agile_prices_json_data = r.json()

        agile_prices = agile_prices_json_data['results']
        time_to_price_map = {}

        for price in agile_prices:
            interval_start_string = parser.isoparse(price['valid_from']).astimezone(LOCAL_TIMEZONE).strftime('%H:%M')
            price = price['value_inc_vat']
            time_to_price_map[interval_start_string] = float(price)

        with open(price_csv_filename, 'w', newline='\n') as f:
            csv_writer = csv.writer(f, delimiter=',', quotechar='|', quoting=csv.QUOTE_MINIMAL)
            csv_writer.writerow(['Date', 'Time', 'Price'])
            for time_key in sorted(time_to_price_map.keys()):
                csv_writer.writerow([start_date.strftime('%Y-%m-%d'), time_key, time_to_price_map[time_key]])

        if ON_OCTOPUS_GO:
            price_csv_filename = os.path.join(price_directory, "octopus-go-prices.csv")
            prices_df = pd.read_csv(price_csv_filename, dtype={'Date': 'str', 'Time': 'str', 'Price': 'float16'})
            time_to_price_map = {}
            for i in range(len(prices_df)):
                time_to_price_map[TIMES[i]] = prices_df.loc[prices_df['Time'] == TIMES[i]]['Price'].values[0]
    except:
        script_directory = os.path.dirname(os.path.realpath(__file__))
        price_directory = os.path.join(script_directory, "prices")

        if ON_OCTOPUS_GO:
            price_csv_filename = os.path.join(price_directory, "octopus-go-prices.csv")
        else:
            price_csv_filename = os.path.join(price_directory, "{}-agile-prices.csv".format(start_date.strftime("%Y-%m-%d")))

        if os.path.exists(price_csv_filename):
            prices_df = pd.read_csv(price_csv_filename, dtype={'Date': 'str', 'Time': 'str', 'Price': 'float16'})
            time_to_price_map = {}
            for i in range(len(prices_df)):
                time_to_price_map[TIMES[i]] = prices_df.loc[prices_df['Time'] == TIMES[i]]['Price'].values[0]
            return time_to_price_map

        time_to_price_map = {}
        for i in range(48):
            time_to_price_map[TIMES[i]] = PRICES[i]

    return time_to_price_map


def live_energy_time_reading(filename):
    reading = 0
    try:
        with FileReadBackwards(filename, encoding="utf-8") as f:
            live_energy_times = []
            index = 0
            for row in f:
                strip_and_split_row = row.strip().split(',')
                if len(strip_and_split_row) > 1:
                    live_energy_times.append(strip_and_split_row[1])
                else:
                    break

                index += 1
                if index == 2:
                    break

            if len(live_energy_times) == 2:
                reading = 3600 * MULTIPLIER / (float(live_energy_times[0]) - float(live_energy_times[1]))
    except:
        traceback.print_exc()
        pass

    return reading


def line_count(filename):
    with open(filename) as f:
        i = -1
        for i, _ in enumerate(f):
            pass
    return i + 1


def calculate_total_cost(target_date, log_directory, prices_directory):
    readings_csv_filename = os.path.join(log_directory, "{}.csv".format(target_date.strftime("%Y-%m-%d")))
    if os.path.exists(readings_csv_filename):
        readings_df = pd.read_csv(readings_csv_filename, header=None, names=['Lux', 'Epoch Time', 'Time', 'Datetime', 'Origin'],
                                  dtype={'Lux': 'float32', 'Epoch Time': 'float64', 'Time': 'str', 'Datetime': 'str', 'Origin': 'str'})
        if len(readings_df) < 2:
            return 0, 0
    else:
        return 0, 0

    if ON_OCTOPUS_GO:
        prices_csv_filename = os.path.join(prices_directory, "octopus-go-prices.csv")
    else:
        prices_csv_filename = os.path.join(prices_directory, "{}-agile-prices.csv".format(target_date.strftime("%Y-%m-%d")))
        if not os.path.exists(prices_csv_filename) or line_count(prices_csv_filename) != 49:
            start_of_day_datetime = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day_datetime = target_date.replace(hour=23, minute=59, second=59, microsecond=0)
            get_agile_prices(start_of_day_datetime, end_of_day_datetime)
            if not os.path.exists(prices_csv_filename):
                prices_csv_filename = os.path.join(prices_directory, "example-agile-prices.csv")

    prices_df = pd.read_csv(prices_csv_filename, dtype={'Date': 'str', 'Time': 'str', 'Price': 'float16'})        

    time_to_watts_map = {}
    for i in range(48):
        time_to_watts_map[TIMES[i]] = 0

    for index, row in readings_df.iterrows():
        current_datetime = datetime.strptime(row['Datetime'], '%Y-%m-%d %H:%M:%S')
        current_date = current_datetime.strftime("%Y-%m-%d")
        current_time = current_datetime.strftime("%H:%M")

        if current_date == target_date.strftime("%Y-%m-%d"):
            time_to_watts_map[current_time] += 1

    cost = 0
    power = 0
    for i in range(48):
        power += time_to_watts_map[TIMES[i]] * MULTIPLIER / 1000
        try:
            if TIMES[i] in prices_df['Time'].values:
                cost += time_to_watts_map[TIMES[i]] * prices_df.loc[prices_df['Time'] == TIMES[i]]['Price'].values[0] * MULTIPLIER / 100000
            elif ON_OCTOPUS_GO:
                cost += time_to_watts_map[TIMES[i]] * GO_TIME_PRICES_MAP[TIMES.index(TIMES[i])] * MULTIPLIER / 100000
            else:
                cost += time_to_watts_map[TIMES[i]] * PRICES[TIMES.index(TIMES[i])] * MULTIPLIER / 100000
        except:
            traceback.print_exc()
            pass

    return cost, power


def calculate_cost_and_power_after_five_thirty_sixty_minutes(current_timestamp, target_date, log_directory, prices_directory):
    readings_csv_filename = os.path.join(log_directory, "{}.csv".format(target_date.strftime("%Y-%m-%d")))
    if os.path.exists(readings_csv_filename):
        readings_df = pd.read_csv(
            readings_csv_filename, header=None, names=['Lux', 'Epoch Time', 'Time', 'Datetime', 'Origin'],
            dtype={'Lux': 'float32', 'Epoch Time': 'float64', 'Time': 'str', 'Datetime': 'str', 'Origin': 'str'}
        )
        if len(readings_df) < 2:
            return 0, 0, 0, 0, 0, 0, None, None
    else:
        return 0, 0, 0, 0, 0, 0, None, None

    if ON_OCTOPUS_GO:
        prices_csv_filename = os.path.join(prices_directory, "octopus-go-prices.csv")
    else:
        prices_csv_filename = os.path.join(prices_directory, "{}-agile-prices.csv".format(target_date.strftime("%Y-%m-%d")))
        if not os.path.exists(prices_csv_filename):
            start_of_day_datetime = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day_datetime = target_date.replace(hour=23, minute=59, second=59, microsecond=0)
            get_agile_prices(start_of_day_datetime, end_of_day_datetime)
            if not os.path.exists(prices_csv_filename):
                prices_csv_filename = os.path.join(prices_directory, "example-agile-prices.csv")
    prices_df = pd.read_csv(prices_csv_filename, dtype={'Date': 'str', 'Time': 'str', 'Price': 'float16'})

    five = current_timestamp - 300
    thirty = current_timestamp - 1800
    sixty = current_timestamp - 3600

    cost_power_list = []
    filtered_readings_df = readings_df   

    for after_timestamp in [sixty, thirty, five]:
        time_to_watts_map = {}
        for i in range(48):
            time_to_watts_map[TIMES[i]] = 0

        filtered_readings_df = filtered_readings_df.loc[filtered_readings_df['Epoch Time'] > after_timestamp]
        filtered_readings_df.reset_index(drop=True, inplace=True)
        if len(filtered_readings_df) < 2:
            cost_power_list.append((0, 0))
            continue

        for index, row in filtered_readings_df.iterrows():
            current_datetime = datetime.strptime(row['Datetime'], '%Y-%m-%d %H:%M:%S')
            current_date = current_datetime.strftime("%Y-%m-%d")
            current_time = current_datetime.strftime("%H:%M")

            if current_date == target_date.strftime("%Y-%m-%d"):
                time_to_watts_map[current_time] += 1

        cost = 0
        power = 0
        for i in range(48):
            power += time_to_watts_map[TIMES[i]] * MULTIPLIER / 1000
            try:
                if TIMES[i] in prices_df['Time'].values:
                    cost += time_to_watts_map[TIMES[i]] * prices_df.loc[prices_df['Time'] == TIMES[i]]['Price'].values[0] * MULTIPLIER / 100000
                elif ON_OCTOPUS_GO:
                    cost += time_to_watts_map[TIMES[i]] * GO_TIME_PRICES_MAP[TIMES.index(TIMES[i])] * MULTIPLIER / 100000
                else:
                    cost += time_to_watts_map[TIMES[i]] * PRICES[TIMES.index(TIMES[i])] * MULTIPLIER / 100000
            except:
                traceback.print_exc()
                pass

        cost_power_list.append((cost, power))

    return cost_power_list[2][0], cost_power_list[2][1], \
           cost_power_list[1][0], cost_power_list[1][1], \
           cost_power_list[0][0], cost_power_list[0][1], \
           readings_df, prices_df


def calculate_total_cost_and_power_faster(target_date, readings_df, prices_df, previous_time_watts_map):
    if readings_df is None or prices_df is None:
        return 0, 0, 0

    if previous_time_watts_map is None:
        time_to_watts_map = {}
        for i in range(48):
            time_to_watts_map[TIMES[i]] = 0
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
        current_datetime = datetime.strptime(row['Datetime'], '%Y-%m-%d %H:%M:%S')
        current_date = current_datetime.strftime("%Y-%m-%d")
        current_time = current_datetime.strftime("%H:%M")

        if current_date == target_date.strftime("%Y-%m-%d"):
            time_to_watts_map[current_time] += 1

    cost = 0
    power = 0
    for i in range(48):
        power += time_to_watts_map[TIMES[i]] * MULTIPLIER / 1000
        try:
            if TIMES[i] in prices_df['Time'].values:
                cost += time_to_watts_map[TIMES[i]] * prices_df.loc[prices_df['Time'] == TIMES[i]]['Price'].values[0] * MULTIPLIER / 100000
            else:
                cost += time_to_watts_map[TIMES[i]] * PRICES[TIMES.index(TIMES[i])] * MULTIPLIER / 100000
        except:
            traceback.print_exc()
            pass

    return cost, power, time_to_watts_map


def is_ascii(s):
    """Check if the characters in string s are in ASCII, U+0-U+7F."""
    return len(s) == len(s.encode())


def check_and_fix_log_corruption(log_directory):
    paths = [str(path) for path in sorted(Path(log_directory).iterdir(), key=os.path.getmtime)]
    paths.reverse()

    for i in range(min(2, len(paths))):
        with open(paths[i], "r") as f:
            lines = f.readlines()

        with open(paths[i], "w") as f:
            for line in lines:
                if len(line.split(",")) == 5 and is_ascii(line):
                    f.write(line)


def daily_cost_thread(date_today, cost_values):
    try:
        script_directory = os.path.dirname(os.path.realpath(__file__))
        cache_directory = os.path.join(script_directory, "cache")
        if not os.path.exists(cache_directory):
            os.makedirs(cache_directory)

        yesterday = date_today.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        yesterday_txt_filename = os.path.join(cache_directory, "{}.txt".format(yesterday.strftime("%Y-%m-%d")))
        if os.path.exists(yesterday_txt_filename):
            values = [float(current_line.rstrip()) for current_line in open(yesterday_txt_filename)]
            yesterday_cost = values[0]
            yesterday_power = values[1]
        else:
            yesterday_cost, yesterday_power = calculate_total_cost(yesterday, log_directory, prices_directory)
            with open(yesterday_txt_filename, "w") as f:
                f.write(str(yesterday_cost))
                f.write('\n')
                f.write(str(yesterday_power))

        exist_week_readings = True
        week_cost = 0
        week_power = 0
        for i in reversed(range(1, 8)):
            current_date = date_today.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=i)
            readings_csv_filename = os.path.join(log_directory, "{}.csv".format(current_date.strftime("%Y-%m-%d")))
            if not os.path.exists(readings_csv_filename):
                exist_week_readings = False
                break
        if exist_week_readings:
            week_cost += yesterday_cost
            week_power += yesterday_power
            for i in reversed(range(2, 8)):
                current_date = date_today.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=i)

                current_date_txt_filename = os.path.join(cache_directory, "{}.txt".format(current_date.strftime("%Y-%m-%d")))
                if os.path.exists(current_date_txt_filename):
                    values = [float(current_line.rstrip()) for current_line in open(current_date_txt_filename)]
                    current_cost = values[0]
                    current_power = values[1]
                else:
                    current_cost, current_power = calculate_total_cost(current_date, log_directory, prices_directory)
                    with open(current_date_txt_filename, "w") as f:
                        f.write(str(current_cost))
                        f.write('\n')
                        f.write(str(current_power))

                week_cost += current_cost
                week_power += current_power

        exist_month_readings = True
        month_cost = 0
        month_power = 0
        for i in reversed(range(1, 32)):
            current_date = date_today.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=i)
            readings_csv_filename = os.path.join(log_directory, "{}.csv".format(current_date.strftime("%Y-%m-%d")))
            if not os.path.exists(readings_csv_filename):
                exist_month_readings = False
                break
        if exist_month_readings:
            month_cost += week_cost
            month_power += week_power
            for i in reversed(range(8, 32)):
                current_date = date_today.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=i)

                current_date_txt_filename = os.path.join(cache_directory, "{}.txt".format(current_date.strftime("%Y-%m-%d")))
                if os.path.exists(current_date_txt_filename):
                    values = [float(current_line.rstrip()) for current_line in open(current_date_txt_filename)]
                    current_cost = values[0]
                    current_power = values[1]
                else:
                    current_cost, current_power = calculate_total_cost(current_date, log_directory, prices_directory)
                    with open(current_date_txt_filename, "w") as f:
                        f.write(str(current_cost))
                        f.write('\n')
                        f.write(str(current_power))

                month_cost += current_cost
                month_power += current_power

        cost_values[0] = yesterday_cost
        cost_values[1] = yesterday_power
        cost_values[2] = week_cost
        cost_values[3] = week_power
        cost_values[4] = month_cost
        cost_values[5] = month_power
    except:
        traceback.print_exc()


if __name__ == "__main__":
    energy_loggger_thread = EnergyMonitor()
    energy_loggger_thread.run()

    script_directory = os.path.dirname(os.path.realpath(__file__))
    log_directory = os.path.join(script_directory, "log")
    prices_directory = os.path.join(script_directory, "prices")

    pygame.init()
    if os.name == 'nt':
        screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
    else:
        screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.FULLSCREEN)
        pygame.mouse.set_visible(False)
    pygame.display.set_caption("Energy Monitor")
    done = False
    clock = pygame.time.Clock()

    heading_font = pygame.font.Font("Roboto-Bold.ttf", 22)
    summary_font = pygame.font.Font("Roboto-Bold.ttf", 18)
    number_small_font = pygame.font.Font("Roboto-Bold.ttf", 20)
    number_smaller_font = pygame.font.Font("Roboto-Bold.ttf", 18)
    number_minor_font = pygame.font.Font("Roboto-Bold.ttf", 36)
    number_font = pygame.font.Font("Roboto-Bold.ttf", 72)
    number_major_font = pygame.font.Font("Roboto-Bold.ttf", 68)
    price_font = pygame.font.Font("Roboto-Bold.ttf", 64)
    price_font_small = pygame.font.Font("Roboto-Bold.ttf", 36)
    tomorrow_price_font = pygame.font.Font("Roboto-Bold.ttf", 18)
    price_font_major = pygame.font.Font("Roboto-Bold.ttf", 84)
    time_font = pygame.font.Font("Roboto-Bold.ttf", 24)

    check_and_fix_log_corruption(log_directory)

    # Yesterday's agile prices
    start_of_day_datetime = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    end_of_day_datetime = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0) - timedelta(days=1)
    get_agile_prices(start_of_day_datetime, end_of_day_datetime)

    # Today's agile prices
    tomorrow = date.today() + timedelta(days=1)
    start_of_day_datetime = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day_datetime = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0)
    time_to_agile_price_map = get_agile_prices(start_of_day_datetime, end_of_day_datetime)

    previous_time_watts_map = None
    tomorrows_average_unit_price = None

    week_cost = 0
    week_power = 0

    month_cost = 0
    month_power = 0

    yesterday = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    yesterday_cost, yesterday_power = calculate_total_cost(yesterday, log_directory, prices_directory)

    heading_colour = (220, 220, 220)

    first_run = True
    cost_thread = None
    cost_values = [0] * 6
    while not done:
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

        # FPS Counter
        if SHOW_FPS:
            screen.blit(update_fps(), (755, 440))

        # Reset readings, costs and download new prices for next day
        if date.today() == tomorrow or first_run:
            first_run = False

            previous_time_watts_map = None
            tomorrows_average_unit_price = None

            start_of_day_datetime = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day_datetime = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0)
            time_to_agile_price_map = get_agile_prices(start_of_day_datetime, end_of_day_datetime)
            tomorrow = date.today() + timedelta(days=1)

            cost_values = [0] * 6
            cost_thread = threading.Thread(target=daily_cost_thread, args=(datetime.now(), cost_values))
            cost_thread.start()

            yesterday_cost = cost_values[0]
            yesterday_power = cost_values[1]
            week_cost = cost_values[2]
            week_power = cost_values[3]
            month_cost = cost_values[4]
            month_power = cost_values[5]

        if cost_thread is not None and not cost_thread.isAlive():
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
            unit_price_now_start = datetime.combine(date.today(), datetime_time(int(current_time.strftime("%H")), 0))
        else:
            unit_price_now_start = datetime.combine(date.today(), datetime_time(int(current_time.strftime("%H")), 30))
        unit_price_now_end = unit_price_now_start + timedelta(minutes=30)
        unit_price_future_start = unit_price_now_end
        unit_price_future_end = unit_price_future_start + timedelta(minutes=30)

        unit_price_now_start = unit_price_now_start.strftime("%H:%M")
        unit_price_now_end = unit_price_now_end.strftime("%H:%M")

        if len(time_to_agile_price_map) < 48 and datetime.now().hour > 16 and datetime.now().minute % 10 == 0:
            start_of_day_datetime = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day_datetime = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0)
            time_to_agile_price_map = get_agile_prices(start_of_day_datetime, end_of_day_datetime)

        if unit_price_now_start in time_to_agile_price_map:
            unit_price_now = time_to_agile_price_map[unit_price_now_start]
        else:
            start_of_day_datetime = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day_datetime = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0)
            time_to_agile_price_map = get_agile_prices(start_of_day_datetime, end_of_day_datetime)
            if unit_price_future_start in time_to_agile_price_map:
                unit_price_now = time_to_agile_price_map[unit_price_now_start]
            else:
                unit_price_now = 15.0

        if len(time_to_agile_price_map) == 48 and tomorrows_average_unit_price is None:
            start_of_day_datetime = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            end_of_day_datetime = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0) + timedelta(days=1)
            tomorrows_time_to_agile_price_map = get_agile_prices(start_of_day_datetime, end_of_day_datetime)
            if len(tomorrows_time_to_agile_price_map) < 48:
                tomorrows_average_unit_price = 0
                for price in tomorrows_time_to_agile_price_map.values():
                    tomorrows_average_unit_price += price
                tomorrows_average_unit_price /= len(tomorrows_time_to_agile_price_map)

        if len(time_to_agile_price_map) > 0:
            average_unit_price = 0
            for price in time_to_agile_price_map.values():
                average_unit_price += price
            average_unit_price /= len(time_to_agile_price_map)
        else:
            average_unit_price = 15.0

        unit_price_future_start = unit_price_future_start.strftime("%H:%M")
        unit_price_future_end = unit_price_future_end.strftime("%H:%M")
        if unit_price_future_start in time_to_agile_price_map and unit_price_future_start != "00:00":
            unit_price_future = time_to_agile_price_map[unit_price_future_start]
        else:
            if unit_price_future_start == "00:00":
                start_of_day_datetime = datetime.combine(tomorrow, datetime_time(0, 0))
                end_of_day_datetime = datetime.combine(tomorrow, datetime_time(23, 59))
                future_time_to_agile_price_map = get_agile_prices(start_of_day_datetime, end_of_day_datetime)
                if unit_price_future_start in future_time_to_agile_price_map:
                    unit_price_future = future_time_to_agile_price_map[unit_price_future_start]
                else:
                    unit_price_future = 15.0
            else:
                start_of_day_datetime = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                end_of_day_datetime = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0)
                time_to_agile_price_map = get_agile_prices(start_of_day_datetime, end_of_day_datetime)
                if unit_price_future_start in time_to_agile_price_map:
                    unit_price_future = time_to_agile_price_map[unit_price_future_start]
                else:
                    unit_price_future = 15.0

        csv_filename = os.path.join(log_directory, "{}.csv".format(datetime.fromtimestamp(time.time()).strftime("%Y-%m-%d")))
        while not os.path.exists(csv_filename) or not has_readings(csv_filename):
            time.sleep(1)

        power_now = live_energy_time_reading(csv_filename)
        cost_now = unit_price_now * power_now / 1000

        power_total = line_count(csv_filename) * MULTIPLIER / 1000

        last_five_time = datetime.timestamp(current_time) - 300
        last_half_time = datetime.timestamp(current_time) - 1800
        last_hour_time = datetime.timestamp(current_time) - 3600

        power_five = 0.0
        power_half = 0.0
        power_hour = 0.0
        with FileReadBackwards(csv_filename, encoding="utf-8") as f:
            for line in f:
                split_line = line.split(',')
                if len(split_line) > 1:
                    current_timestamp = float(line.split(',')[1])
                else:
                    break
                
                if current_timestamp > last_five_time:
                    power_five += 0.001 * MULTIPLIER

                if current_timestamp > last_half_time:
                    power_half += 0.001 * MULTIPLIER

                if current_timestamp > last_hour_time:
                    power_hour += 0.001 * MULTIPLIER

                if current_timestamp < last_hour_time:
                    break

        cost_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        cost_five, cost_five_power, cost_half, cost_half_power, cost_hour, cost_hour_power, readings_df, prices_df = \
            calculate_cost_and_power_after_five_thirty_sixty_minutes(time.time(), cost_date, log_directory, prices_directory)
        cost_total, _, time_watt_map = calculate_total_cost_and_power_faster(cost_date, readings_df, prices_df,
                                                                             previous_time_watts_map)

        previous_time_watts_map = time_watt_map

        # Costs
        text = heading_font.render('Current Cost:', True, heading_colour)
        screen.blit(text, (8, 50))

        text = price_font_major.render('{:4.1f}p'.format(cost_now), True, (255, 255, 255))
        screen.blit(text, (25, 75))

        text = heading_font.render('Total Cost (5 min / 30 min / 60 min / Daily):', True, heading_colour)
        screen.blit(text, (260, 48))

        text = number_small_font.render('£{:4.2f} / £{:4.2f} / £{:4.2f}'.format(cost_five, cost_half, cost_hour), True, (255, 255, 255))
        screen.blit(text, (280, 90))

        text = price_font_major.render('/ £{:4.2f}'.format(cost_total), True, (255, 255, 255))
        screen.blit(text, (480, 75))

        # Power
        text = heading_font.render('Current Power:', True, heading_colour)
        screen.blit(text, (8, 180))

        if len(str(int(np.round(power_now)))) < 4:
            text = number_font.render('{:4.0f}'.format(power_now), True, (255, 255, 255))
            screen.blit(text, (15, 210))
            text = number_minor_font.render('W', True, (255, 255, 255))
            screen.blit(text, (170, 243))
        else:
            if len(str(int(np.round(power_now)))) < 6:
                text = number_font.render('{:>5.2f}'.format(power_now / 1000), True, (255, 255, 255))
            elif len(str(int(np.round(power_now)))) == 6:
                text = number_font.render('{:>5.1f}'.format(power_now / 1000), True, (255, 255, 255))
            else:
                text = number_font.render('{:>5.0f}'.format(power_now / 1000), True, (255, 255, 255))
            screen.blit(text, (15, 210))
            text = number_minor_font.render('kW', True, (255, 255, 255))
            if len(str(int(np.round(power_now)))) == 4:
                screen.blit(text, (190, 243))
            else:
                screen.blit(text, (210, 243))

        text = heading_font.render('Used Power:', True, heading_colour)
        screen.blit(text, (298, 180))

        if len("{:d}".format(int(np.round(power_total, decimals=2)))) < 3:
            text = number_major_font.render('{:5.2f}'.format(power_total), True, (255, 255, 255))
            screen.blit(text, (306, 212))
        else:
            text = number_major_font.render('{:5.1f}'.format(power_total), True, (255, 255, 255))
            screen.blit(text, (306, 212))

        if len("{:d}".format(int(np.round(power_total, decimals=2)))) == 1:
            text = number_minor_font.render('kW', True, (255, 255, 255))
            screen.blit(text, (473, 242))
        else:
            text = number_minor_font.render('kW', True, (255, 255, 255))
            screen.blit(text, (491, 242))

        # Average Unit Cost
        text = heading_font.render('Average Unit Cost:', True, heading_colour)
        screen.blit(text, (589, 180))

        text = number_major_font.render('{:4.1f}p'.format(100 * cost_total/power_total), True, (255, 255, 255))
        screen.blit(text, (600, 212))

        # Current Unit Price
        text = heading_font.render('Unit Price ({} - {}):'.format(unit_price_now_start, unit_price_now_end), True, heading_colour)
        screen.blit(text, (8, 310))

        text = price_font.render('{:4.1f}p'.format(unit_price_now), True, (255, 255, 255))
        screen.blit(text, (60, 335))

        # Future Unit Price
        text = heading_font.render('Unit Price ({} - {}):'.format(unit_price_future_start, unit_price_future_end), True, heading_colour)
        screen.blit(text, (298, 310))

        text = price_font.render('{:4.1f}p'.format(unit_price_future), True, (255, 255, 255))
        screen.blit(text, (350, 335))

        # Average Unit Price
        text = heading_font.render('Average Unit Price:', True, heading_colour)
        screen.blit(text, (587, 310))

        if tomorrows_average_unit_price is None:
            text = price_font.render('{:4.1f}p'.format(average_unit_price), True, (255, 255, 255))
            screen.blit(text, (600, 335))
        else:
            text = price_font_small.render('{:4.1f}p'.format(average_unit_price), True, (255, 255, 255))
            screen.blit(text, (635, 339))

            text = tomorrow_price_font.render('Tomorrow: {:4.1f}p'.format(tomorrows_average_unit_price), True, (255, 255, 255))
            screen.blit(text, (613, 385))

        yesterday_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        last_week_start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=8)
        last_month_start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=32)

        if yesterday_cost > 0 and yesterday_power > 0:
            # Yesterday Cost
            text = summary_font.render('Yesterday [{}]:'.format(yesterday_date.strftime("%d/%m")), True, heading_colour)
            screen.blit(text, (8, 428))

            text = summary_font.render('£{:.2f} ({:.1f} kW @ {:.1f}p)'.format(
                yesterday_cost, yesterday_power, 100 * yesterday_cost / yesterday_power
            ), True, heading_colour)
            screen.blit(text, (8, 450))

        if week_cost > 0 and week_power > 0:
            # Week Cost
            text = summary_font.render('Past Week [{} - {}]:'.format(
                last_week_start_date.strftime("%d/%m"), yesterday_date.strftime("%d/%m")
            ), True, heading_colour)
            screen.blit(text, (258, 428))

            text = summary_font.render('£{:.2f} ({:.1f} kW @ {:.1f}p)'.format(
                week_cost, week_power, 100 * week_cost / week_power
            ), True, heading_colour)
            screen.blit(text, (258, 450))

        if month_cost > 0 and month_power > 0:
            # Month Cost
            text = summary_font.render('Past Month [{} - {}]:'.format(
                last_month_start_date.strftime("%d/%m"), yesterday_date.strftime("%d/%m")
            ), True, heading_colour)
            screen.blit(text, (523, 428))

            text = summary_font.render('£{:.2f} ({:.1f} kW @ {:.1f}p)'.format(
                month_cost, month_power, 100 * month_cost / month_power
            ), True, heading_colour)
            screen.blit(text, (523, 450))

        # Display date and time
        text = time_font.render('{} {} {}'.format(
            datetime.now().strftime("%A"), day_with_suffix(), datetime.now().strftime("%B %Y")
        ), True, heading_colour)
        screen.blit(text, (8, 8))

        text = time_font.render('{}'.format(datetime.now().strftime("%H:%M:%S")), True, heading_colour)
        screen.blit(text, (693, 8))

        pygame.display.flip()
        clock.tick(1)

    energy_loggger_thread.stop()
