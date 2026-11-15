#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sg003a_console.py — переговорник із прихованою консоллю SG-003A.

Відкриття дня: регістри 0x9C4C/0x9C4F відповідають ТЕКСТОМ
("The message you sent is:7" + ехо запиту) — у прошивці 0x0040
живе забутий тестовий обробник. Цей скрипт пробує поговорити з ним
по-людськи: надсилає текстову команду і показує відповідь
у байтах і в ASCII.

Використання:
    python sg003a_console.py COM6            # батч: пробує список команд
    python sg003a_console.py COM6 help        # одна команда
"""

import sys
import time
import serial

TIMEOUT_S = 2.0
PAUSE_S = 0.5

# команди для батча — класика забутих консолей
CANDIDATES = ["help", "?", "ver", "version", "test", "AT"]


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def modbus_frame(addr: int, reg: int) -> bytes:
    """Вхід у текстовий режим: запит до 0x9C4C — прилад заговорить."""
    req = bytes([addr, 0x64, reg >> 8, reg & 0xFF, 0x00, 0x01])
    crc = crc16_modbus(req)
    return req + bytes([crc & 0xFF, crc >> 8])


def show(tag: str, data: bytes) -> None:
    print(f"{tag} hex : {data.hex(' ')}")
    printable = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
    print(f"{tag} ascii: {printable}\n")


def talk(ser, payload: bytes, label: str) -> None:
    print(f"=== {label} ===")
    ser.reset_input_buffer()
    ser.write(payload)
    resp = ser.read(256)
    if resp:
        show("RX", resp)
    else:
        print("RX: (тишина)\n")
    time.sleep(PAUSE_S)


def main() -> None:
    port = sys.argv[1] if len(sys.argv) > 1 else "COM6"

    with serial.Serial(port, 115200, bytesize=8, parity='N',
                       stopbits=1, timeout=TIMEOUT_S) as ser:
        # контроль: MODBUS-вхід у текстовий режим
        talk(ser, modbus_frame(0x09, 0x9C4C), "ключ: запит до 0x9C4C")

        if len(sys.argv) >= 3:
            commands = [" ".join(sys.argv[2:])]
        else:
            commands = CANDIDATES

        # текстові команди — прямо в порт
        for cmd in commands:
            talk(ser, (cmd + "\r\n").encode("ascii"),
                 f'команда "{cmd}"')

        # ще один ключ: адреси, що давали "тишину" (0x9C0D, 0x000D)
        for reg in (0x9C0D, 0x000D):
            talk(ser, modbus_frame(0x09, reg), f"підозра: запит до 0x{reg:04X}")


if __name__ == "__main__":
    main()
