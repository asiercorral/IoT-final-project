import unittest
from grove.grove_temperature_humidity_sensor import DHT

class TestTempHumiditySensor(unittest.TestCase):
    def setUp(self):
        # Tipo de sensor '11' en puerto digital 5
        self.sensor = DHT('11', 5)

    def test_read_temperature_and_humidity(self):
        humi, temp = self.sensor.read()

        self.assertIsNotNone(temp, "Error al leer la temperatura")
        self.assertIsNotNone(humi, "Error al leer la humedad")

        # Validación dentro de rangos ambientales lógicos
        self.assertTrue(-10 <= temp <= 60, f"Temperatura fuera de rango: {temp}°C")
        self.assertTrue(0 <= humi <= 100, f"Humedad fuera de rango: {humi}%")

if __name__ == '__main__':
    unittest.main()