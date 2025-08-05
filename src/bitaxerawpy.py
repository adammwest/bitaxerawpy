from __future__ import annotations
import serial  # type: ignore
import bm1370

RESET_N_HIGH_PACKET: bytes = bytes([0x07, 0x00, 0x00, 0x00, 0x06, 0x01, 0x01])

class SerialInterface:
    def __init__(self, port: str, baud: int = 115200):
        self._port = port
        self._baud = baud
        self._ser: serial.Serial | None = None

    def open(self):
        self._ser = serial.Serial(self._port, self._baud, timeout=0.1)

    def close(self):
        if self._ser:
            self._ser.close()
            self._ser = None

    def readline(self, timeout: float = 1.0) -> str:
        if not self._ser:
            raise RuntimeError("Serial not open")
        self._ser.timeout = timeout
        return self._ser.readline().decode(errors="ignore").rstrip()
    

def create_connection_with_ASIC(control_port: str, baud: int = 115200) -> SerialInterface:
    """
    Opens the control serial port and sets RST_N High to enable the ASIC.

    Args:
        control_port: The serial port for control (first serial port).
        baud: Baud rate for the control serial port (default 115200).

    Returns:
        SerialInterface: The opened SerialInterface instance.
    """
    # Open the control serial port
    ctrl_serial = SerialInterface(control_port, baud)
    ctrl_serial.open()    
    ctrl_serial._ser.write(RESET_N_HIGH_PACKET)
    return ctrl_serial


def send_init_bm1370(ctrl_serial: SerialInterface, asic:bm1370.BM1370, frequency: float = 200.0, expected_chips: int = 1, difficulty: int = 0x1FFFFF):
    """
    Uses bm1370.py to send the init sequence to the chip via the ctrl_serial interface.

    Args:
        ctrl_serial: The SerialInterface instance for control serial.
        frequency: Target frequency in MHz for the ASIC initialization.
        asic: The asic
        expected_chips: Number of expected ASIC chips.
        difficulty: Mining difficulty mask.
    """
    # Define TX and RX functions for BM1370
    def serial_tx_func(data: bytes):
        if not ctrl_serial._ser:
            raise RuntimeError("Serial port not open")
        ctrl_serial._ser.write(data)

    def serial_rx_func(length: int, timeout_ms: int = 1000):
        if not ctrl_serial._ser:
            raise RuntimeError("Serial port not open")
        ctrl_serial._ser.timeout = timeout_ms / 1000.0
        return ctrl_serial._ser.read(length)

    def reset_func():
        # Optionally implement hardware reset if needed
        pass

    
    asic.ll_init(serial_tx_func, serial_rx_func, reset_func)
    asic.send_init(frequency, expected_chips, difficulty)
    return asic

def main():
    ctrl_serial: SerialInterface = create_connection_with_ASIC(control_port="ACM0")
    asic = bm1370.BM1370()
    send_init_bm1370(ctrl_serial,asic,frequency=400,difficulty=16)




if __name__ == "__main__":
    pass