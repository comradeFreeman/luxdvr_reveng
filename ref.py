import socket
import binascii
import sys
import threading
import time

HOST = '192.168.1.8'
PORT = 6036

first = bytes.fromhex('3131313188000000010100007801fb030000000078000000030000000000000061646d696e0000000000000000000000000000000000000000000000000000000000000031323334353600000000000000000000000000000000000000000000000000000000000073797370726f62732d64613161363100000000000000000000000000080027639734000004000000')
second = bytes.fromhex('313131315000000003040000ffffffffffffffff4000000000f859050400000001f800000000000002f800000000000003f800000000000040f800000000000041f800000000000042f800000000000043f8000000000000')
third = bytes.fromhex('313131313400000001020000000000000000000024000000000000000000000000000000010000000000000000000000000000000000000000000000')
four = bytes.fromhex('3131313100000000')


def send_heartbeat(sock):
    """Тихо шлет 8 байт каждые 10 секунд"""
    while True:
        time.sleep(10)
        try:
            sock.sendall(four)
        except:
            break


with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    print(f"[*] Подключение к медиа-порту {HOST}:{PORT}...")
    s.connect((HOST, PORT))

    data = s.recv(128)
    print("HEX:", binascii.hexlify(data, " ").decode("utf-8"))
    print("TXT:", data)
    print("[+] Приветствие получено.")

    s.sendall(first)
    print("[+] Авторизация отправлена.")
    s.settimeout(1.0)
    try:
        data = s.recv(1024)
    except socket.timeout:
        pass
    print("HEX:", binascii.hexlify(data, " ").decode("utf-8"))
    print("TXT:", data)

    s.settimeout(None)
    s.sendall(second)
    print("[!] Команда 2 отправлена. Ожидание большого ответа...")
    s.settimeout(1.5)

    full_response = bytearray()
    try:
        while True:
            chunk = s.recv(4096)
            if not chunk:
                print("[*] Сервер закрыл соединение.")
                break
            full_response.extend(chunk)
    except socket.timeout:
        print(f"[+] Данные успешно собраны по таймауту. Всего байт: {len(full_response)}")
    finally:
        s.settimeout(None)

    s.sendall(third)
    print("[!] Запрос 3 отправлен")

    # Запускаем сердцебиение ровно перед началом скачивания видео
    threading.Thread(target=send_heartbeat, args=(s,), daemon=True).start()

    bytes_received = 0
    with open('cam1_raw.bin', 'wb') as f:
        while True:
            data = s.recv(8192)
            if not data:
                print("\n[-] Регистратор закрыл видеоканал.")
                break
            f.write(data)
            bytes_received += len(data)
            print(f"\rСкачано: {bytes_received / 1024:.2f} KB", end='', flush=True)
