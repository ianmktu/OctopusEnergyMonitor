import logging
import os
import random
import threading
import time
import traceback
from datetime import date, datetime, timedelta
from datetime import time as datetime_time
from typing import Optional

import numpy as np
from ltr559 import LTR559


class EnergyMonitor:
    """
    A class that monitors energy usage by reading light levels from an LTR559 sensor and logging the data to a CSV file.

    Args:
        config (dict): A dictionary containing configuration parameters for the monitor.

    Attributes:
        thread (Thread): A thread object for running the monitor.
        started (bool): A boolean indicating whether the monitor has started.
        config (dict): A dictionary containing configuration parameters for the monitor.
        ltr559 (LTR559): An LTR559 object representing the light and proximity sensor.
        reading_sleep_time (float): A float representing the time to sleep between sensor readings.
        save_directory (str): The path to the directory where the CSV data files are saved.
    """

    def __init__(self, config: dict, save_directory: str):
        self.thread = None
        self.started = True
        self.config = config
        self.ltr559 = self.init_sensor(self.config)
        self.reading_sleep_time = config["LTR559_SLEEP_TIME_BETWEEN_READINGS_IN_MILLISECONDS"] / 1000
        self.save_directory = save_directory

    @staticmethod
    def init_sensor(config: dict) -> Optional[LTR559]:
        """
        Initializes the light and proximity sensor (LTR559) if not in debug mode.

        Args:
            config (dict): A dictionary containing configuration parameters.

        Returns:
            Optional[LTR559]: An instance of the LTR559 class if not in debug mode, otherwise None.
        """
        if os.name == "nt" or config["DEBUG"]:
            ltr559 = None
        else:
            ltr559 = LTR559()
            ltr559.set_light_integration_time_ms(config["LTR559_LIGHT_INTEGRATION_TIME_MILLISECONDS"])
            ltr559.set_light_repeat_rate_ms(config["LTR559_LIGHT_REPEAT_RATE_MILLISECONDS"])
        return ltr559

    @staticmethod
    def is_first_input_to_csv(filename: str) -> bool:
        """
        Checks if the given CSV file has only one or two lines of data.

        Args:
            filename (str): The path to the CSV file.

        Returns:
            bool: True if the file has only one or two lines of data, False otherwise.
        """
        with open(filename, "r") as f:
            line_count = 0
            for _ in f:
                line_count += 1
                if line_count > 2:
                    return False
        return True

    @staticmethod
    def get_unit_datetime(epoch_time: float) -> datetime:
        """
        Returns the datetime object for the start of the unit price interval, either XX:00 or XX:30,
        corresponding to the given epoch time.

        Args:
            epoch_time (float): The epoch time for which to calculate the unit price interval.

        Returns:
            datetime: The datetime object for the start of the unit price interval.
        """
        if int(datetime.fromtimestamp(epoch_time).strftime("%M")) < 30:
            unit_price_start_time = datetime.combine(
                date.today(),
                datetime_time(int(datetime.fromtimestamp(epoch_time).strftime("%H")), 0),
            )
        else:
            unit_price_start_time = datetime.combine(
                date.today(),
                datetime_time(int(datetime.fromtimestamp(epoch_time).strftime("%H")), 30),
            )

        return unit_price_start_time

    def write_energy_reading_to_file(
        self,
        csv_filename: str,
        lux: float,
        epoch_time: float,
        unit_price_start_time: str,
        record_type: str,
    ) -> None:
        """
        Writes energy reading to a CSV file.

        Args:
            csv_filename (str): The name of the CSV file to write to.
            lux (float): The lux value to write to the CSV file.
            epoch_time (float): The epoch time to write to the CSV file.
            unit_price_start_time (str): The unit price start time to write to the CSV file.
            record_type (str): The record type to write to the CSV file.
        """
        with open(csv_filename, "a") as f:
            f.write(
                "{:06.2f},{:.6f},{},{},{}".format(
                    lux,
                    epoch_time,
                    datetime.fromtimestamp(epoch_time).strftime("%H:%M:%S.%f"),
                    unit_price_start_time,
                    record_type,
                )
            )
            f.write("\n")

    def monitor(self) -> None:
        """
        Continuously monitors the light sensor and writes energy readings to a CSV file.
        """
        previous_lux = 0
        previous_previous_time = -1
        previous_time = -1
        previous_time_origin = "fixed"
        current_time = -1
        fix_counter = 0

        while self.started:
            try:
                if os.name == "nt" or self.config["DEBUG"]:
                    current_lux = random.randint(0, 2)
                    time.sleep(random.randint(4, 10))
                else:
                    self.ltr559.update_sensor()
                    current_lux = self.ltr559.get_lux()

                if current_lux > 0.0:
                    if abs(previous_lux - current_lux) < self.config["LTR559_MIN_LUX_DIFFERENCE_FOR_READING"]:
                        time.sleep(self.reading_sleep_time)
                        continue

                    previous_previous_time = previous_time
                    previous_time = current_time
                    previous_time_origin = "original"
                    current_time = time.time()

                    # Smooth out intervals that are too large
                    if previous_previous_time > 0 and previous_time > 0:
                        current_interval = current_time - previous_time
                        previous_interval = previous_time - previous_previous_time
                        outlier_multiplier = self.config["LTR559_SMOOTHING_INTERVAL_MULTIPLIER"]
                        smooth_limit = self.config["LTR559_SMOOTHING_LIMIT"]
                        if (current_interval > previous_interval * outlier_multiplier) and fix_counter < smooth_limit:
                            fix_counter += 1

                            num_segments = np.round(current_interval / previous_interval).astype(int)

                            original_previous_time = previous_time
                            original_previous_lux = previous_lux
                            for index in range(max(0, num_segments - 1)):
                                current_lux_fixed = ((current_lux + original_previous_lux) / 2) + 1 * index
                                current_time_fixed = original_previous_time + (
                                    (current_time - original_previous_time) / num_segments
                                ) * (index + 1)
                                unit_price_start_time = self.get_unit_datetime(current_time_fixed)

                                current_day = datetime.fromtimestamp(current_time_fixed).strftime("%Y-%m-%d")
                                csv_filename = os.path.join(self.save_directory, f"{current_day}.csv")

                                # Save the first reading of a file as the previous reading
                                if not os.path.exists(csv_filename):
                                    self.write_energy_reading_to_file(
                                        csv_filename=csv_filename,
                                        lux=previous_lux,
                                        epoch_time=previous_time,
                                        unit_price_start_time=self.get_unit_datetime(previous_time),
                                        record_type=previous_time_origin,
                                    )

                                # Save reading
                                self.write_energy_reading_to_file(
                                    csv_filename=csv_filename,
                                    lux=current_lux_fixed,
                                    epoch_time=current_time_fixed,
                                    unit_price_start_time=unit_price_start_time,
                                    record_type="fixed",
                                )

                                # Save first reading of the day to yesterday's CSV file
                                if self.is_first_input_to_csv(csv_filename):
                                    yesterday = (
                                        datetime.fromtimestamp(current_time_fixed) - timedelta(days=1)
                                    ).strftime("%Y-%m-%d")
                                    yesterday_csv_filename = os.path.join(self.save_directory, f"{yesterday}.csv")
                                    self.write_energy_reading_to_file(
                                        csv_filename=yesterday_csv_filename,
                                        lux=current_lux_fixed,
                                        epoch_time=current_time_fixed,
                                        unit_price_start_time=unit_price_start_time,
                                        record_type="fixed",
                                    )

                                previous_previous_time = previous_time
                                previous_lux = current_lux_fixed
                                previous_time = current_time_fixed
                                previous_time_origin = "fixed"
                        else:
                            fix_counter = 0

                    current_day = datetime.fromtimestamp(current_time).strftime("%Y-%m-%d")
                    csv_filename = os.path.join(self.save_directory, f"{current_day}.csv")

                    # Save the first reading of a file as the previous reading
                    if previous_previous_time > 0 and previous_time > 0:
                        if not os.path.exists(csv_filename):
                            self.write_energy_reading_to_file(
                                csv_filename=csv_filename,
                                lux=previous_lux,
                                epoch_time=previous_time,
                                unit_price_start_time=self.get_unit_datetime(previous_time),
                                record_type=previous_time_origin,
                            )

                    # Save reading
                    unit_price_start_time = self.get_unit_datetime(current_time)
                    self.write_energy_reading_to_file(
                        csv_filename=csv_filename,
                        lux=current_lux,
                        epoch_time=current_time,
                        unit_price_start_time=unit_price_start_time,
                        record_type="original",
                    )

                    # Save first reading of the day to yesterday's CSV file
                    if self.is_first_input_to_csv(csv_filename) and previous_time > 0:
                        yesterday = (datetime.fromtimestamp(current_time) - timedelta(days=1)).strftime("%Y-%m-%d")
                        yesterday_csv_filename = os.path.join(self.save_directory, f"{yesterday}.csv")
                        self.write_energy_reading_to_file(
                            csv_filename=yesterday_csv_filename,
                            lux=current_lux,
                            epoch_time=current_time,
                            unit_price_start_time=unit_price_start_time,
                            record_type="original",
                        )

                    previous_lux = current_lux
                time.sleep(self.reading_sleep_time)
            except Exception:
                logging.error(f"EnergyMonitor Error: {traceback.format_exc()}")
                logging.info("Restarting LTR559 sensor...")
                self.init_sensor(config=self.config)
                logging.info("Restarted LTR559 sensor")
                time.sleep(self.reading_sleep_time)

    def run(self) -> None:
        """
        Starts the monitor thread.
        """
        self.thread = threading.Thread(target=self.monitor, args=())
        self.thread.start()

    def stop(self) -> None:
        """
        Stops the monitor thread.
        """
        self.started = False
        self.thread.join()
