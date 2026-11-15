#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sg003a_read.py — читання даних із калібратора SG-003A по MODBUS RTU.

Автор: спільна робота sydenko + Lumo.
Призначення: демо-клієнт для репозиторію SG-003A.
Значення виводяться СИРІМИ (в "попугаях") — без конверсії у фізичні
одиниці. Розбір полів — окреме завдання після збору статистики.

Використання:
    python sg003a_read.py                # читати за замовчуванням
    python sg003a_read.py COM9           # вказати порт
    python sg003a_read.py COM9 009 115200

Залежність: pip install pyserial
"""

import sys
import serial

# --- Налаштування за замовчуванням (перекриваються аргументами) ---
DEFAULT_PORT = "COM9"       # CH343 (вдома), віртуальний COM калібратора
DEFAULT_ADDR = 0x09         # slave address 009, як налаштовано в приладі
DEFAULT_BAUD = 115200

TIMEOUT_S = 1.0             # таймаут відповіді, с
REG_FIRST = 0x0000          # початковий регістр читання
REG_COUNT = 8               # скільки регістрів читати за раз


def crc16_modbus(data: bytes) -> int:
    """CRC-16/MODBUS: поліном 0xA001 (реверс 0x8005), старт 0xFFFF."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def build_request(addr: int, func: int, first: int, count: int) -> bytes:
    """Зібрати валідний MODBUS RTU кадр з CRC."""
    req = bytes([addr, func, first >> 8, first & 0xFF,
                 count >> 8, count & 0xFF])
    crc = crc16_modbus(req)
    return req + bytes([crc & 0xFF, crc >> 8])


def read_registers(ser, addr: int, first: int, count: int) -> bytes:
    """Функція 0x04 (Read Input Registers). Повертає сирі байти даних."""
    ser.reset_input_buffer()                      # дренаж зайвих кадрів
    ser.write(build_request(addr, 0x04, first, count))
    # очікувана відповідь: addr(1) + func(1) + bytecount(1) + data + crc(2)
    expected = 5 + 2 * count
    resp = ser.read(expected)
    if len(resp) < 5:
        raise IOError(
            f"Прилад не відповів (одержано {len(resp)} байт): {resp.hex(' ')}"
        )
    # перевірка адреси та ознаки винятку
    if resp[0] != addr:
        raise IOError(f"Невідповідність адреси: {resp.hex(' ')}")
    if resp[1] & 0x80:
        exc = resp[2] if len(resp) > 2 else -1
        raise IOError(f"MODBUS exception {exc}: {resp.hex(' ')}")
    # перевірка CRC відповіді
    if crc16_modbus(resp[:-2]) != (resp[-2] | (resp[-1] << 8)):
        raise IOError(f"CRC не зійшовся: {resp.hex(' ')}")
    return resp[3:3 + 2 * count]


def main() -> None:
    port = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PORT
    addr = int(sys.argv[2], 0) if len(sys.argv) > 2 else DEFAULT_ADDR
    baud = int(sys.argv[3], 0) if len(sys.argv) > 3 else DEFAULT_BAUD

    print(f"SG-003A  port={port}  addr={addr:03d}  baud={baud}")

    try:
        with serial.Serial(port, baud, bytesize=8, parity='N',
                           stopbits=1, timeout=TIMEOUT_S) as ser:
            print("Запит :", build_request(addr, 0x04,
                                           REG_FIRST, REG_COUNT).hex(' '))
            data = read_registers(ser, addr, REG_FIRST, REG_COUNT)
            print("Дані  :", data.hex(' '))
            # сирі регістри, без тлумачення — "попугаї"
            for i in range(0, len(data), 2):
                reg_no = REG_FIRST + i // 2
                value = (data[i] << 8) | data[i + 1]
                print(f"  регістр {reg_no:#06x}: {value:5d}  "
                      f"(0x{value:04X})")
    except serial.SerialException as e:
        sys.exit(f"Помилка порту: {e}")
    except IOError as e:
        sys.exit(f"Помилка обміну: {e}")


if __name__ == "__main__":
    main()
