# translated from: bm1370.c
import struct
import serial
import time
import logging
import binascii

from .crc_functions import crc5, crc16_false

TYPE_JOB = 0x20
TYPE_CMD = 0x40

GROUP_SINGLE = 0x00
GROUP_ALL = 0x10

CMD_JOB = 0x01
CMD_SETADDRESS = 0x00
CMD_WRITE = 0x01
CMD_READ = 0x02
CMD_INACTIVE = 0x03

RESPONSE_CMD = 0x00
RESPONSE_JOB = 0x80

MISC_CONTROL = 0x18

class BM1370:
    def __init__(self):
        self.chip_id_response = "aa5513700000"

    def ll_init(self, serial_tx_func, serial_rx_func, reset_func):
        self.serial_tx_func = serial_tx_func
        self.serial_rx_func = serial_rx_func
        self.reset_func = reset_func

    def send(self, header, data):
        packet_type = TYPE_JOB if header & TYPE_JOB else TYPE_CMD
        data_len = len(data)
        total_length = data_len + 6 if packet_type == TYPE_JOB else data_len + 5

        buf = bytearray(total_length)
        buf[0] = 0x55
        buf[1] = 0xAA
        buf[2] = header
        buf[3] = data_len + 4 if packet_type == TYPE_JOB else data_len + 3
        buf[4:4+data_len] = data

        if packet_type == TYPE_JOB:
            crc16_total = crc16_false(buf[2:4+data_len])
            buf[4 + data_len] = (crc16_total >> 8) & 0xFF
            buf[5 + data_len] = crc16_total & 0xFF
        else:
            buf[4 + data_len] = crc5(buf[2:4+data_len])

        self.serial_tx_func(buf)

    def send_simple(self, data):
        self.serial_tx_func(bytearray(data))

    def send_chain_inactive(self):
        self.send(TYPE_CMD | GROUP_ALL | CMD_INACTIVE, [0x00, 0x00])

    def set_chip_address(self, chipAddr):
        self.send(TYPE_CMD | GROUP_SINGLE | CMD_SETADDRESS, [chipAddr, 0x00])

    def set_version_mask(self, version_mask):
        versions_to_roll = version_mask >> 13
        version_byte0 = (versions_to_roll >> 8) & 0xFF
        version_byte1 = versions_to_roll & 0xFF
        version_cmd = [0x00, 0xA4, 0x90, 0x00, version_byte0, version_byte1]
        self.send(TYPE_CMD | GROUP_ALL | CMD_WRITE, version_cmd)

    def send_hash_frequency(self, target_freq):
        freqbuf = [0x00, 0x08, 0x40, 0xA0, 0x02, 0x41]
        fb_divider = 0
        post_divider1 = 0
        post_divider2 = 0
        ref_divider = 0
        min_difference = 10
        max_diff = 1.0
        newf = 200.0

        for refdiv in range(2, 0, -1):
            for postdiv1 in range(7, 0, -1):
                for postdiv2 in range(7, 0, -1):
                    if postdiv1 >= postdiv2:
                        temp_fb_divider = round((postdiv1 * postdiv2 * target_freq * refdiv) / 25.0)
                        if 0xa0 <= temp_fb_divider <= 0xef:
                            temp_freq = 25.0 * temp_fb_divider / (refdiv * postdiv2 * postdiv1)
                            freq_diff = abs(target_freq - temp_freq)
                            if freq_diff < min_difference and freq_diff < max_diff:
                                fb_divider = temp_fb_divider
                                post_divider1 = postdiv1
                                post_divider2 = postdiv2
                                ref_divider = refdiv
                                min_difference = freq_diff
                                newf = temp_freq

        if fb_divider == 0:
            logging.error(f"Failed to find PLL settings for target frequency {target_freq:.2f}")
            return

        freqbuf[3] = fb_divider
        freqbuf[4] = ref_divider
        freqbuf[5] = (((post_divider1 - 1) & 0xf) << 4) + ((post_divider2 - 1) & 0xf)
        if fb_divider * 25 / float(ref_divider) >= 2400:
            freqbuf[2] = 0x50

        self.send(TYPE_CMD | GROUP_ALL | CMD_WRITE, freqbuf)
        logging.info(f"Setting Frequency to {target_freq:.2f}MHz ({newf:.2f})")

    def count_asic_chips(self, expected_count, chip_id_response_length=11):
        self.send(TYPE_CMD | GROUP_ALL | CMD_READ, [0x00, 0x00])
        chip_counter = 0
        while True:
            data = self.serial_rx_func(chip_id_response_length, 5000)
            if data is None:
                break
            if self.chip_id_response not in binascii.hexlify(data).decode('utf8'):
                continue
            chip_counter += 1
        self.send_chain_inactive()
        return chip_counter

    def send_init(self, frequency, expected, difficulty, chips_enabled=None):
        for _ in range(3):
            self.set_version_mask(0xFFFFFFFF)

        self.send_simple([0x55, 0xAA, 0x52, 0x05, 0x00, 0x00, 0x0A])
        chip_counter = self.count_asic_chips(expected)
        if chip_counter == 0:
            raise Exception("No ASIC chips found")

        self.set_version_mask(0xFFFFFFFF)
        self.send(TYPE_CMD | GROUP_ALL | CMD_WRITE, [0x00, 0xA8, 0x00, 0x07, 0x00, 0x00])
        self.send(TYPE_CMD | GROUP_ALL | CMD_WRITE, [0x00, 0x18, 0xF0, 0x00, 0xC1, 0x00])
        self.send_chain_inactive()

        address_interval = int(256 / chip_counter)
        for i in range(chip_counter):
            self.set_chip_address(i * address_interval)

        self.send(TYPE_CMD | GROUP_ALL | CMD_WRITE, [0x00, 0x3C, 0x80, 0x00, 0x8B, 0x00])
        self.send(TYPE_CMD | GROUP_ALL | CMD_WRITE, [0x00, 0x3C, 0x80, 0x00, 0x80, 0x0C])

        # Set difficulty mask
        difficulty_mask = self.get_difficulty_mask(difficulty)
        self.send(TYPE_CMD | GROUP_ALL | CMD_WRITE, difficulty_mask)

        self.send(TYPE_CMD | GROUP_ALL | CMD_WRITE, [0x00, 0x58, 0x00, 0x01, 0x11, 0x11])

        for i in range(chip_counter):
            addr = i * address_interval
            self.send(TYPE_CMD | GROUP_SINGLE | CMD_WRITE, [addr, 0xA8, 0x00, 0x07, 0x01, 0xF0])
            self.send(TYPE_CMD | GROUP_SINGLE | CMD_WRITE, [addr, 0x18, 0xF0, 0x00, 0xC1, 0x00])
            self.send(TYPE_CMD | GROUP_SINGLE | CMD_WRITE, [addr, 0x3C, 0x80, 0x00, 0x8B, 0x00])
            self.send(TYPE_CMD | GROUP_SINGLE | CMD_WRITE, [addr, 0x3C, 0x80, 0x00, 0x80, 0x0C])
            self.send(TYPE_CMD | GROUP_SINGLE | CMD_WRITE, [addr, 0x3C, 0x80, 0x00, 0x82, 0xAA])

        self.send(TYPE_CMD | GROUP_ALL | CMD_WRITE, [0x00, 0xB9, 0x00, 0x00, 0x44, 0x80])
        self.send(TYPE_CMD | GROUP_ALL | CMD_WRITE, [0x00, 0x54, 0x00, 0x00, 0x00, 0x02])
        self.send(TYPE_CMD | GROUP_ALL | CMD_WRITE, [0x00, 0xB9, 0x00, 0x00, 0x44, 0x80])
        self.send(TYPE_CMD | GROUP_ALL | CMD_WRITE, [0x00, 0x3C, 0x80, 0x00, 0x8D, 0xEE])

        self.send_hash_frequency(frequency)

        self.send(TYPE_CMD | GROUP_ALL | CMD_WRITE, [0x00, 0x10, 0x00, 0x00, 0x1E, 0xB5])
        return chip_counter

    def get_difficulty_mask(self, difficulty):
        # This should match the C function get_difficulty_mask
        mask = [0x00, 0x14, 0x00, 0x00, 0x00, 0xFF]
        difficulty = self._largest_power_of_two(difficulty) - 1
        for i in range(4):
            value = (difficulty >> (8 * i)) & 0xFF
            mask[5 - i] = self._reverse_bits(value)
        return mask

    def _largest_power_of_two(self, n):
        p = 1
        while p * 2 <= n:
            p *= 2
        return p

    def _reverse_bits(self, byte):
        return int('{:08b}'.format(byte)[::-1], 2)

    def set_default_baud(self):
        baudrate = [0x00, MISC_CONTROL, 0x00, 0x00, 0b01111010, 0b00110001]
        self.send(TYPE_CMD | GROUP_ALL | CMD_WRITE, baudrate)
        return 115749

    def set_max_baud(self):
        self.send_simple([0x55, 0xAA, 0x51, 0x09, 0x00, 0x28, 0x11, 0x30, 0x02, 0x00, 0x03])
        return 1000000

    def reset(self):
        self.reset_func()

    # Add more methods