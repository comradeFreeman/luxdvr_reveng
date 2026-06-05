import socket
import sys
import threading
import time
import argparse
import functools
import random
from credentials import HOST, PORT
import uuid

from protocol import LuxDVR_Proto

print = functools.partial(print, file=sys.stderr)

parser = argparse.ArgumentParser(description="LuxDVR Pro 04-fx2 RTSP Streamer")
parser.add_argument("-H", "--host", type=str, default=HOST, help="IP address")
parser.add_argument("-p", "--port", type=int, default=PORT, help="Port")
parser.add_argument("-c", "--cam", type=int, default=1, help="Camera ID (default: 1)")
parser.add_argument("-m", "--mac", type=str, help="MAC-address (example: AA:BB:CC:DD:EE:FF), 'random' to generate new, 'real' to use your real MAC")
parser.add_argument("-n", "--name", type=str, help="PC Name / Client ID (example: Viewer-1)")
args = parser.parse_args()

def send_keepalive(sock, dvr, interval, stop_event):
    while not stop_event.is_set():
        if stop_event.wait(interval):
            break
        try:
            sock.sendall(dvr.gen_keepalive_req())
        except Exception:
            # The main stream catches errors of the socket, here we just exit silently
            break


def run_stream():
    """Single loop for connection and streaming. In case of the socket failure throws an exception"""

    kwargs = {}
    if args.name:
        kwargs['client'] = args.name

    if args.mac:
        if args.mac.lower() == 'random':
            # Generate safe random MAC-address
            mac_bytes = [0x02] + [random.randint(0x00, 0xff) for _ in range(5)]
            kwargs['mac'] = ':'.join(f'{b:02x}' for b in mac_bytes)
            print(f"[*] Using a new random MAC for this session: {kwargs['mac']}")
        elif args.mac.lower() == "real":
            kwargs['mac'] = ':'.join([f'{(uuid.getnode() >> i) & 0xff:02x}' for i in reversed(range(0, 48, 8))])
            print(f"[*] Using the real MAC for this session: {kwargs['mac']}")
        else:
            kwargs['mac'] = args.mac

    # Create a new object for each connection (this ensures that stream buffer will be empty)
    dvr = LuxDVR_Proto(**kwargs)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # Setting timeout during connection
        s.settimeout(5.0)
        print(f"[*] Connecting to the DVR {args.host}:{args.port}...")
        s.connect((args.host, args.port))

        # Here we got greeting - skip
        s.recv(128)

        # Authorisation
        s.sendall(dvr.gen_auth_req())
        s.settimeout(1.0)
        try:
            auth_reply = s.recv(1024)
            info = dvr.parse_dvr_info(auth_reply)
            if info.get("success"):
                print(f"[+] Authorisation OK: {info.get('name')} - SW{info.get('sw_ver')}")
            else:
                print("[-] Authorisation failed! Possibly wrong login/password")
                sys.exit(1)  # In this case exit
        except socket.timeout:
            pass

        # We need to request parameters despite we don't need them
        # 20580 bytes ☠️
        s.settimeout(None)
        s.sendall(dvr.gen_pref_req())
        s.settimeout(1.5)
        try:
            while True:
                chunk = s.recv(4096)
                if not chunk: break
        except socket.timeout:
            pass

        # Start streaming
        s.settimeout(None)
        s.sendall(dvr.gen_stream_req(args.cam))
        print(f"[!] Request for stream from the camera #{args.cam} sent. Streaming...")

        # "Heartbeat" thread to keep-alive session
        stop_keepalive = threading.Event()
        ka_thread = threading.Thread(target=send_keepalive, args=(s, dvr, 10, stop_keepalive))
        ka_thread.start()

        bytes_received = 0
        try:
            while True:
                # If network crashes, recv throws ConnectionResetError
                raw_data = s.recv(8192)
                if not raw_data:
                    print("[-] DVR correctly closed a streaming pipe")
                    break

                for clean_chunk in dvr.parse_stream(raw_data):
                    # If ffmpeg crashes, write throws BrokenPipeError
                    bytes_received += sys.stdout.buffer.write(clean_chunk)
                    sys.stdout.buffer.flush()

        finally:
            stop_keepalive.set()
            ka_thread.join()


def main():
    """Watchdog that monitors the main thread and restarts it"""
    while True:
        try:
            run_stream()

        except BrokenPipeError:
            # Arises when receiving program (ffmpeg) was closed
            print("[!] FFmpeg BrokenPipe. Stopping...")
            # If ffmpeg crashes we better close too - Systemd will restart full chain
            sys.exit(0)

        except (ConnectionError, socket.timeout, socket.error) as e:
            # Arises when network problems occur, the router/DVR restarts
            print(f"[!] Network error: {e}. Reconnecting in 5 second...")
            time.sleep(5)

        except KeyboardInterrupt:
            # Ctrl + C
            print("[+] Stream stopped by user")
            break

        except Exception as e:
            # Other unforeseen errors
            print(f"[!] Error: {e}. Reconnecting in 5 second...")
            time.sleep(5)


if __name__ == "__main__":
    main()