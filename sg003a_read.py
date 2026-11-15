#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sg003a_read.py — читання даних із калібратора SG-003A по MODBUS RTU.

Автор: спільна робота sydenko + Lumo.
Призначення: клієнт-сканер для репозиторію SG-003A.
Діалект фірмовий: функція читання 0x64 (деталі — MODBUS_PROTOCOL.md).
Значення виводяться СИРІМИ (в "попугаях") — без конверсії у фізичні
одиниці. Привиди (запізнілі відповіді) лікуться retry + дренажем.

Використання:
    python sg003a_read.py                # скан за замовчуванням
    python sg003a_read.py COM6 009 115200
"""

import struct
import sys
import serial
import time

# --- Налаштування за замовчуванням (перекриваються аргументами) ---
DEFAULT_PORT = "COM6"       # віртуальний COM калібратора
DEFAULT_ADDR = 0x09         # slave address 009, як налаштовано в приладі
DEFAULT_BAUD = 115200

TIMEOUT_S = 2.0             # таймаут відповіді, с (піднятий: прилад повільний)
RETRY_TRIES = 3             # скільки разів питати регістр перед капітуляцією
PAUSE_S = 0.05              # пауза між регістрами, щоб прилад продихав

# --- Фірмовий діалект SG-003A (не стандартні 03/04!) ---
FUNC_READ = 0x64            # 100 = читання регістрів
FUNC_WRITE = 0x65           # 101 = запис регістрів

# --- Карта регістрів (MODBUS_PROTOCOL.md, Таблиця 2 мануала) ---
REG_VERSION  = 0x9C41       # uint16 — версія прошивки
REG_IN_TYPE  = 0x9C42       # uint16 — тип вхідного сигналу
REG_OUT_TYPE = 0x9C43       # uint16 — тип вихідного сигналу

# --- Вікна сканування: (від, до) ---
# Основне вікно — підтверджена зона. Решта — полювання за живим
# регістром вхідного значення (вхід прилада працює ЗАВЖДИ, значить
# десь його видно). Зайві вікна можна закоментувати.
WINDOWS = [
    (0x9C41, 0x9C61),   # основна карта, перевірена
    (0x9C61, 0x9CA1),   # продовження фірмової зони
    (0x9C00, 0x9C41),   # зона нижче карти мануала
    (0x0000, 0x0021),   # типова база "простих" прошивок
]


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


def build_read_request(addr: int, first: int, count: int) -> bytes:
    """Зібрати фірмовий кадр читання (ф. 0x64) з CRC."""
    req = bytes([addr, FUNC_READ, first >> 8, first & 0xFF,
                 count >> 8, count & 0xFF])
    crc = crc16_modbus(req)
    return req + bytes([crc & 0xFF, crc >> 8])


def read_registers(ser, addr: int, first: int, count: int) -> bytes:
    """Функція 0x64. Повертає сирі байти даних (1 регістр!)."""
    ser.reset_input_buffer()                      # дренаж зайвих кадрів
    req = build_read_request(addr, first, count)
    ser.write(req)
    # очікувана відповідь: addr(1) + func(1) + bytecount(1) + data + crc(2)
    expected = 5 + 2 * count
    resp = ser.read(expected)
    if len(resp) < 5:
        raise IOError(
            f"Прилад не відповів (одержано {len(resp)} байт): {resp.hex(' ')}"
        )
    if resp[0] != addr:
        raise IOError(f"Невідповідність адреси: {resp.hex(' ')}")
    if resp[1] & 0x80:
        exc = resp[2] if len(resp) > 2 else -1
        raise IOError(f"MODBUS exception {exc}: {resp.hex(' ')}")
    if crc16_modbus(resp[:-2]) != (resp[-2] | (resp[-1] << 8)):
        raise IOError(f"CRC не зійшовся: {resp.hex(' ')}")
    return resp[3:3 + 2 * count]


def read_retry(ser, addr, reg, tries=RETRY_TRIES):
    """Читання з повтором: таймаут → пауза, дренаж, спроба знову.
    Після успіху теж дренаж — щоб запізніла відповідь не стала
    привидом для наступного регістра."""
    for i in range(tries):
        try:
            data = read_registers(ser, addr, reg, 1)
            ser.reset_input_buffer()   # змести запізнілі хвости
            return data
        except IOError as e:
            if "не відповів" not in str(e) or i == tries - 1:
                raise
            time.sleep(0.3)


def to_u16(data: bytes) -> int:
    return (data[0] << 8) | data[1]


def to_float(data: bytes) -> float:
    """IEEE-754 float з 4 байт (порядок байт — як у відповіді прилада)."""
    return struct.unpack(">f", data)[0]


def short_error(e: IOError) -> str:
    """Стисла мітка помилки для таблиці скана."""
    msg = str(e)
    if "не відповів" in msg:
        return "тишина"          # таймаут — мабуть, привид/повільність
    if "MODBUS exception" in msg:
        return msg.split("MODBUS exception ")[1][:1]
    return "?"


def scan_window(ser, addr, lo: int, hi: int) -> int:
    """Просканувати діапазон регістрів, друк 4 на рядок. OK → лічильник."""
    ok_count = 0
    for reg in range(lo, hi):
        try:
            v = to_u16(read_retry(ser, addr, reg))
            print(f"0x{reg:04X}: OK  {v:5d}  (0x{v:04X})", end="")
            if True:
                print()
            ok_count += 1
        except IOError as e:
            mark = short_error(e)
            print(f"0x{reg:04X}:{mark:<8}", end="  ")
            if (reg - lo) % 4 == 3:
                print()
        time.sleep(PAUSE_S)
    # довушка: якщо рядок не заповнений до 4 — закрити його
    if (hi - lo) % 4 != 0:
        print()
    return ok_count


def main() -> None:
    port = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PORT
    addr = int(sys.argv[2], 0) if len(sys.argv) > 2 else DEFAULT_ADDR
    baud = int(sys.argv[3], 0) if len(sys.argv) > 3 else DEFAULT_BAUD

    print(f"SG-003A  port={port}  addr={addr:03d}  baud={baud}")

    try:
        with serial.Serial(port, baud, bytesize=8, parity='N',
                           stopbits=1, timeout=TIMEOUT_S) as ser:
            # 1. Версія прошивки (перший робочий запит з протоколу)
            print("Запит :", build_read_request(addr, REG_VERSION, 1).hex(' '))
            fw = to_u16(read_retry(ser, addr, REG_VERSION))
            print(f"Версія прошивки: {fw}  (0x{fw:04X})")

            # 2. Тип входу / виходу (вхід прилада невимиканний —
            #    ці регістри мають бути читабельні завжди)
            in_type = to_u16(read_retry(ser, addr, REG_IN_TYPE))
            out_type = to_u16(read_retry(ser, addr, REG_OUT_TYPE))
            print(f"Тип входу : 0x{in_type:04X}")
            print(f"Тип виходу: 0x{out_type:04X}")

            # 3. Скани по вікнах
            total_ok = 0
            for lo, hi in WINDOWS:
                print(f"--- скан 0x{lo:04X}..0x{hi-1:04X} ---")
                total_ok += scan_window(ser, addr, lo, hi)
                print()
            print(f"читабельних регістрів: {total_ok}")
    except serial.SerialException as e:
        sys.exit(f"Помилка порту: {e}")
    except IOError as e:
        sys.exit(f"Помилка обміну: {e}")


if __name__ == "__main__":
    main()
