import struct
import uuid
import credentials



HEADER = b'1111'

class LuxDVR_Proto:
    def __init__(self, *args, **kwargs):
        self.login = kwargs.get('login', credentials.login).encode('ascii')
        self.password = kwargs.get('password', credentials.password).encode('ascii')
        self.client = kwargs.get('client', credentials.client).encode('ascii')
        self.mac = kwargs.get('mac', credentials.mac)

        # If MAC comes in str "aa:bb:cc...", translating to bytes
        if isinstance(self.mac, str):
            self.mac = bytes.fromhex(self.mac.replace(':', ''))

        # Buffer for data from TCP-socket
        self._stream_buffer = bytearray()

    def gen_auth_req(self):
        """
        |  header  |  payload_len |  service? |  login   |  password  |   client   |   MAC   |  service? |
        |    4s    |      I       |    24s    |   36s    |    36s     |     28s    |   6s    |     6s    |
        | 4 bytes  |   4 bytes    |  24 bytes | 36 bytes |  36 bytes  |  28 bytes  | 6 bytes |  6 bytes  |
                                  |                           136 bytes = 0x88                            |
        """
        payload_len = 136
        service = bytes.fromhex("01 01 00 00 78 01 fb 03 \
                                 00 00 00 00 78 00 00 00 \
                                 03 00 00 00 00 00 00 00")
        tail = bytes.fromhex(   "00 00 04 00 00 00")

        return bytearray(struct.pack(
            '< 4s I 24s 36s 36s 28s 6s 6s',
            HEADER, payload_len, service,
            self.login, self.password, self.client,
            self.mac, tail
        ))

    def gen_pref_req(self):
        """
        |  header  |  payload_len | opcodes? | broadcast? | service? | get sysinfo?  | get caminfo?  |
        |    4s    |      I       |    4s    |     8s     |   12s    |      3s       |      4s       |
        | 4 bytes  |   4 bytes    | 4 bytes  |  8 bytes   | 12 bytes |  3 * 8 bytes  |  4 * 8 bytes  |
                                  |                         80 bytes = 0x50                          |
        """
        payload_len = 80
        opcodes = bytes.fromhex("03 04 00 00")
        broadcast = bytes.fromhex("ff") * 8
        service = bytes.fromhex("40 00 00 00 \
                                 00 f8 59 05 \
                                 04 00 00 00")

        codes = [bytes.fromhex(code + "f8 00 00 00 00 00 00")
                     for code in "01 02 03 40 41 42 43".split()]

        return bytearray(struct.pack(
            '< 4s I 4s 8s 12s' + ('8s' * 7),
            HEADER, payload_len, opcodes, broadcast, service,
            *codes
        ))

    def gen_stream_req(self, cam=1):
        """
        |  header  |  payload_len | opcodes? | padding? | struct_len? |  camera number?  |
        |    4s    |       I      |    4s    |    8s    |      I      |  12s + I + 23s   |
        | 4 bytes  |   4 bytes    | 4 bytes  | 8 bytes  |   4 bytes   |     36 bytes     |
                                  |                    52 bytes = 0x34                   |
        """
        payload_len = 52
        opcodes = bytes.fromhex("01 02 00 00")
        pad1 = bytes(8)
        struct_len = 36
        offset = bytes(12)
        pad2 = bytes(23)

        return bytearray(struct.pack(
            '< 4s I 4s 8s I 12s I 20s',
            HEADER, payload_len, opcodes, pad1, struct_len, offset, 2**(cam - 1), pad2
                                                                      # Chinese magic :)
        ))

    def gen_keepalive_req(self):
        pad = bytes(8)

        return bytearray(struct.pack(
            '< 4s 8s',
            HEADER, pad
        ))

    def parse_dvr_info(self, data):
        if len(data) < 340:
            return {}
        fmt = '< H 2x I I 64x 4B 76x 32s 32s 64s 48s'
        st, sess, ch, v, a, in_, out, dev, hw, sn, bld = struct.unpack(fmt, data[8:340])

        return {
            "success": st == 1,
            "sess_id": hex(sess),
            "channels": ch,
            "name": dev.rstrip(b'\x00').decode(), # errors='ignore'
            "sw_ver": hw.rstrip(b'\x00').decode(),
            "kernel": sn.rstrip(b'\x00').decode(),
            "hw_ver": bld.rstrip(b'\x00').decode(),
        }

    def parse_stream(self, raw_chunk):
        """
        Receives raw data from the socket, collects entire packets,
        cuts PACK/Frame Headers at hard offsets
        and gives away (yield) pure H.264 NAL units.
        """
        # Extend the stream buffer with a new portion of data from the network
        self._stream_buffer.extend(raw_chunk)

        # Processing the stream buffer while it has full b'1111' envelopes
        while True:
            idx = self._stream_buffer.find(HEADER)  # HEADER = b'1111'
            if idx == -1:
                # If there is no HEADER leave a tail (if H264 marker was in previous packet)
                if len(self._stream_buffer) > 3:
                    self._stream_buffer = self._stream_buffer[-3:]
                break

            # Cleaning trash before H264 marker
            if idx > 0:
                del self._stream_buffer[:idx]

            # Waiting at least one H264 marker + length (8 bytes)
            if len(self._stream_buffer) < 8:
                break

            try:
                payload_len = struct.unpack('<I', self._stream_buffer[4:8])[0]
            except struct.error:
                del self._stream_buffer[:4]
                continue

            # Protection
            if payload_len == 0 or payload_len > 5 * 1024 * 1024:
                del self._stream_buffer[:4]
                continue

            # Checking whether it's full envelope
            total_packet_size = 8 + payload_len
            if len(self._stream_buffer) < total_packet_size:
                break  # Waiting for the next recv

            # We've got full envelope!
            payload = self._stream_buffer[8: total_packet_size]

            # Preparing - purging envelope to be processed
            del self._stream_buffer[:total_packet_size]

            # Ignoring the starting packet of the video initialisation
            if b'H264' in payload[:128]:
                continue

            # Huge I-frames (cutted into several pieces and wrapped in a PACK)
            if payload.startswith(b'PACK'):
                if len(payload) >= 28:
                    chunk_idx = struct.unpack('<I', payload[16:20])[0]
                    if chunk_idx == 1:
                        # First part of I-frame: PACK (28) + Header (76) = 104 bytes
                        if len(payload) > 104:
                            yield payload[104:]
                    elif chunk_idx > 1:
                        # Pieces-continuations of I-frame: only PACK (28)
                        if len(payload) > 28:
                            yield payload[28:]

            # 2. P-frame (Small motion frames. Without PACK)
            # Check whether the first byte is 0x01 (Video)
            elif len(payload) > 76 and payload[0] == 1:
                # Cutting off exactly 76 bytes
                yield payload[76:]