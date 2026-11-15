#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sg003a_probe.py — сирий зонд: надіслати запит і показати БЕЗ ПАРСИНГУ
те, що прилад відповів, байт у байт.

Призначення: розібратися з регістрами 0x9C4C / 0x9C4F, які відповідають
"не таким" кадром (масуються під привидів). Тут жодних перевірок —
лише гола осцилограма кадру.

Використання:
    python sg003a_probe.py COM6 009 9C4C
    python sg003a_probe.py COM6 009 9C4F
"""

import sys
import time
import serial

TIMEOUT_S = 2.0
ATTEMPTS = 5          # скільки кадрів зняти поспіль
PAUSE_S = 0.3


def parse_num(s: str) -> int:
    """Парсер, що не вередує: 9, 009, 0x09, 9C4C, 0x9C4C — все їсть."""
    s = s.strip()
    try:
        return int(s, 0)          # 0x.. hex, 123 dec
    except ValueError:
        pass
    if s.isdigit():
        return int(s, 10)          # 009 — десяткове з нулями спереду
    return int(s, 16)              # 9C4C — hex без префікса


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def main() -> None:
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    port = sys.argv[1]
    addr = parse_num(sys.argv[2])
    reg = parse_num(sys.argv[3])

    req = bytes([addr, 0x64, reg >> 8, reg & 0xFF, 0x00, 0x01])
    crc = crc16_modbus(req)
    req += bytes([crc & 0xFF, crc >> 8])

    print(f"Сирий зонд  0x{reg:04X}  port={port}  addr={addr:03d}")
    print(f"TX       : {req.hex(' ')}\n")

    with serial.Serial(port, 115200, bytesize=8, parity='N',
                       stopbits=1, timeout=TIMEOUT_S) as ser:
        for n in range(ATTEMPTS):
            ser.reset_input_buffer()
            ser.write(req)
            # читаємо щедро: до 64 байт, таймаут сам зупинить
            resp = ser.read(64)
            if resp:
                print(f"RX #{n+1:02d}: {resp.hex(' ')}   ({len(resp)} байт)")
            else:
                print(f"RX #{n+1:02d}: (тишина)")
            time.sleep(PAUSE_S)

    print("\nПорівняй TX-запити і RX-кадри: довжина, адреса, функція.")
    print("Якщо кадр довший 7 байт — регістри віддають нестандартні дані.")


if __name__ == "__main__":
    main()
