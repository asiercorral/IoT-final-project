import unittest
from grove.grove_moisture_sensor import GroveMoistureSensor

class TestSoilMoistureSensor(unittest.TestCase):
    def setUp(self):
        # Canal 0 corresponde al puerto A0
        self.sensor = GroveMoistureSensor(0)

    def test_read_moisture(self):
        value = self.sensor.moisture
        self.assertIsNotNone(value, "No se pudo obtener lectura del sensor")
        self.assertIsInstance(value, (int, float))
        # Rango válido del ADC (0 a 1023)
        self.assertGreaterEqual(value, 0)
        self.assertLessEqual(value, 1023)

if __name__ == '__main__':
    unittest.main()