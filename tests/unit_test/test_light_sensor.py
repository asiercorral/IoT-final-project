import unittest
from grove.grove_light_sensor_v1_2 import GroveLightSensor

class TestLightSensor(unittest.TestCase):
    def setUp(self):
        # Canal 2 corresponde al puerto A2
        self.sensor = GroveLightSensor(2)

    def test_read_light_level(self):
        light_value = self.sensor.light
        self.assertIsNotNone(light_value, "La lectura del sensor de luz devolvió None")
        self.assertIsInstance(light_value, (int, float))
        self.assertGreaterEqual(light_value, 0)

if __name__ == '__main__':
    unittest.main()
