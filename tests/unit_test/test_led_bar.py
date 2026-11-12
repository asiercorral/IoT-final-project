import unittest
import time
from grove.gpio import GPIO

class GroveLedBar:
    """
    Controlador autónomo para Grove - LED Bar (Chip MY9221).
    Al conectar al puerto D5, usa GPIO 5 (Datos) y GPIO 6 (Reloj).
    """
    def __init__(self, pin_data=5, pin_clk=6):
        self.data_pin = GPIO(pin_data, GPIO.OUT)
        self.clk_pin = GPIO(pin_clk, GPIO.OUT)

    def _send_16bit(self, data):
        for i in range(16):
            state = (data & (1 << (15 - i))) != 0
            self.data_pin.write(1 if state else 0)
            self.clk_pin.write(1)
            self.clk_pin.write(0)

    def _latch(self):
        self.data_pin.write(0)
        time.sleep(0.0001)
        for _ in range(8):
            self.data_pin.write(1)
            self.data_pin.write(0)

    def set_level(self, level):
        # Nivel de 0 (todos apagados) a 10 (todos encendidos)
        level = max(0, min(10, level))
        # Enviar comando de control MY9221
        self._send_16bit(0x0000)
        # Enviar estado de los 10 LEDs
        for i in range(10):
            self._send_16bit(0x00FF if i < level else 0x0000)
        # Relleno de tramas del chip MY9221
        self._send_16bit(0x0000)
        self._send_16bit(0x0000)
        self._latch()

class TestLedBar(unittest.TestCase):
    def setUp(self):
        # Puerto digital D5 (GPIO 5 Datos, GPIO 6 Reloj)
        self.led_bar = GroveLedBar(pin_data=5, pin_clk=6)

    def test_led_bar_levels(self):
        # Prueba encendido progresivo de niveles 0 a 10
        for level in range(11):
            self.led_bar.set_level(level)
            time.sleep(0.05)
        self.led_bar.set_level(0)
        self.assertTrue(True)

    def tearDown(self):
        if hasattr(self, 'led_bar'):
            self.led_bar.set_level(0)

if __name__ == '__main__':
    unittest.main()