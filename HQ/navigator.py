from enum import Enum
import numpy as np
from EOS import EOS
from gevent import sleep
import logging


class Phase(Enum):
    SETUP = "setup"
    EXPLORE = "explore"
    OPTIMIZE = "optimize"
    COMPLETE = "complete"
    FAILED = "failed"

class Navigator:
    def __init__(self, eos_ip="192.168.1.105", eos_port=8000, gui=None, sensor_data=None, lock=None):
        self.gui = gui
        self.eos = EOS(eos_ip, eos_port)
        self.current_phase = Phase.SETUP
        self.pan = 0.0
        self.tilt = 0.0
        self.best_intensity = -1
        self.target_sensor = 1
        self.target_sensor_previous_intensity = -1
        self.sensor_baselines = {}
        self.sensor_data = sensor_data
        self.lock = lock

    def send_light_command(self, pan_move, tilt_move, use_degrees=True):
        # Send pan/tilt updates to EOS
        self.eos.set_pan(1, self.pan, pan_move, "r1", use_degrees)
        self.eos.set_tilt(1, self.tilt, tilt_move, "r1", use_degrees)
        self.pan += pan_move
        self.tilt += tilt_move
        logging.debug(f"Sent pan_move: {pan_move}, tilt_move: {tilt_move}. New pan: {self.pan}, New tilt: {self.tilt}")

    def setup_phase(self):
        logging.info("Entering SETUP phase.")
        self.eos.set_pan(1, 0, 0, "r1", use_degrees=True)
        self.eos.set_tilt(1, 0, 0, "r1", use_degrees=True)
        self.eos.set_intensity(1, 100)
        sleep(5)  # Reduced sleep for quicker updates
        # set baselines
        self.sensor_baselines = self.get_new_data()
        logging.info(f"Sensor baselines: {self.sensor_baselines}")

        self.best_intensity = self.get_new_data().get(self.target_sensor, {}).get("intensity", 0)
        logging.debug(f"Setup complete. Baseline intensity: {self.best_intensity}")

        return Phase.EXPLORE

    def explore_phase(self):
        # move in expanding concentric circles until the taret sensor picks up significant changes
        logging.info("Entering EXPLORE phase.")

        # Move the light in a spiral pattern
        max_tilt = self.eos.get_tilt_range("r1")[1]
        min_pan, max_pan = self.eos.get_pan_range("r1")
        pan_move_step = 5
        tilt_move_step = 10



        if self.target_sensor_previous_intensity == -1:
            self.target_sensor_previous_intensity = self.get_new_data().get(self.target_sensor, {}).get("intensity", 0)

        self.send_light_command(min_pan, 0, use_degrees=True)


        scan_pan = min_pan
        scan_tilt = 0
        direction = 1
        give_up_tilt = 85
        found = False
        while not found:
            # set tilt
            for i in range(0, max_pan, pan_move_step):
                self.eos.set_pan(1,0,scan_pan, "r1", use_degrees=True)
                self.eos.set_tilt(1,0,scan_tilt, "r1", use_degrees=True)
                self.pan = scan_pan
                self.tilt = scan_tilt
                sleep(0.2)
                intensity = self.get_new_data().get(self.target_sensor, {}).get("intensity", 0)
                logging.info(f"Intensity: {intensity}")
                logging.info(f"Previous Intensity: {self.target_sensor_previous_intensity}")
                if intensity > self.sensor_baselines.get(self.target_sensor, {}).get("intensity", 0) + 10000000:
                    return Phase.COMPLETE

                self.target_sensor_previous_intensity = intensity
                scan_pan += pan_move_step * direction


            if direction == 1 and scan_pan >= max_pan:
                direction = -1
                scan_pan = max_pan
                scan_tilt += tilt_move_step
                if scan_tilt > max_tilt:
                    break
            elif direction == -1 and scan_pan <= min_pan:
                direction = 1
                scan_pan = min_pan
                scan_tilt += tilt_move_step
                if scan_tilt > max_tilt:
                    break
            if (abs(scan_tilt) > give_up_tilt):
                logging.info("Giving up")
                self.eos.set_intensity(1, 0)
                self.eos.set_pan(1, 0, 0, "r1", use_degrees=True)
                self.eos.set_tilt(1, 0, 0, "r1", use_degrees=True)
                return Phase.FAILED

        return Phase.COMPLETE






    def optimize_phase(self):
        logging.info("Entering OPTIMIZE phase.")


        initial_intensity = self.get_new_data().get(self.target_sensor, {}).get("intensity", 0)

        self.send_light_command(pan_move=5, tilt_move=5)  # Example move
        self.eos.set_intensity(1, 0)
        logging.debug("Light intensity set to 0.")
        sleep(0.5)  # Adjust based on sensor response time

        updated_intensity = self.get_new_data().get(self.target_sensor, {}).get("intensity", 0)

        if initial_intensity != updated_intensity:
            logging.info("They are not equal")
            logging.info(f"Initial intensity: {initial_intensity}, Updated intensity: {updated_intensity}")
            return Phase.COMPLETE
        else:
            logging.info("They are equal")
            return Phase.COMPLETE  # Or return Phase.OPTIMIZE to continue optimizing

    def get_new_data(self):
        new_sensor_data = {}

        with self.lock:
            new_sensor_data = self.sensor_data.copy()

        # now, combine it with the GUI coords
        # right now, the sensor data is in {sensor_id: intensity} format. it needs to be in {sensor_id: {intensity: intensity, x: x, y: y}} format
        if self.gui is not None:
            sensor_positions = self.gui.get_sensor_positions()
            for sensor_id, intensity in new_sensor_data.items():
                new_sensor_data[sensor_id] = {
                    "intensity": intensity,
                    "x": sensor_positions[sensor_id][0],
                    "y": sensor_positions[sensor_id][1],
                }
        return new_sensor_data

    def execute(self):
        logging.debug(f"Executing phase: {self.current_phase}")
        if self.current_phase == Phase.SETUP:
            self.current_phase = self.setup_phase()
        elif self.current_phase == Phase.EXPLORE:
            self.current_phase = self.explore_phase()
        elif self.current_phase == Phase.OPTIMIZE:
            self.current_phase = self.optimize_phase()

        return {
            "current_phase": self.current_phase.name,
            "pan": self.pan,
            "tilt": self.tilt,
            "target_sensor": self.target_sensor,
        }
