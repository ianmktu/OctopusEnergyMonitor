import os
import unittest
from datetime import datetime

import energy_monitor
import utils.config
import utils.prices


class TestEnergyMonitor(unittest.TestCase):
    def test_calculate_total_cost_and_power_faster(self):
        script_dir = os.path.dirname(os.path.realpath(__file__))
        config_path = os.path.join(script_dir, "..", "utils", "config.yaml")
        config = utils.config.get_config_from_yaml(config_path)

        data_dir = os.path.join(script_dir, "data")
        date_str = "2023-10-04"

        readings_path = os.path.join(data_dir, "monitor", f"{date_str}.csv")
        readings_df = energy_monitor.get_readings_df_from_path(readings_path)

        prices_path = os.path.join(data_dir, "prices", "tracker", f"{date_str}.csv")
        time_to_price_map = utils.prices.convert_price_csv_to_dict(prices_path)

        time_to_watts_map = dict()
        for time_str in utils.prices.TIMES:
            time_to_watts_map[time_str] = 0

        for _, row in readings_df.iterrows():
            current_datetime = datetime.strptime(row["Datetime"], "%Y-%m-%d %H:%M:%S")
            current_date = current_datetime.strftime("%Y-%m-%d")
            current_time = current_datetime.strftime("%H:%M")

            if current_date == date_str:
                time_to_watts_map[current_time] += 1

        result = energy_monitor.calculate_total_cost_and_power_faster(
            config=config,
            target_date=datetime.strptime("2023-10-04", "%Y-%m-%d"),
            readings_df=readings_df,
            previous_time_watts_map=None,
            time_to_price_map=time_to_price_map,
        )

        self.assertEqual(len(result), 4)
        self.assertAlmostEqual(result["cost"], 2.5214948852619012, delta=1e-9)
        self.assertAlmostEqual(result["power"], 16.781437125748504, delta=1e-9)
        self.assertAlmostEqual(result["average_cost_in_pence"], 15.025500297546387, delta=1e-9)
        self.assertDictEqual(result["time_to_watts_map"], time_to_watts_map)
