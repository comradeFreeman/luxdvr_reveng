# LuxDVR Pro 04-fx2 to RTSP Bridge

A lightweight, zero-transcoding Python proxy for legacy Chinese CCTV DVRs (specifically **LuxDVR Pro 04-fx2**). 

Many older DVRs use a proprietary, undocumented transport protocol that modern NVRs cannot read. This script acts as a surgical bridge: it connects to the DVR, strips away the proprietary headers (`1111` / `PACK`), and pipes the pure, raw `H.264 Annex B` NAL units directly into `FFmpeg`. 

By piping this clean stream to an RTSP server like MediaMTX, you can easily integrate your old DVR cameras into modern smart home systems (Shinobi, Frigate, Home Assistant) with ~0.1% CPU load.

### Key Features:
* 🚀 **Zero Transcoding:** Uses FFmpeg's `-c:v copy` for zero-latency, CPU-free streaming.
* 🛡️ **Auto-Recovery:** Built-in watchdog handles network drops and broken pipes gracefully.
* 🎭 **Client Spoofing:** Generates random MACs and Client IDs to prevent stream conflicts when running multiple cameras streams simultaneously.
* 🐧 **Systemd Ready:** Designed to run 24/7 as template daemon processes in Linux (see [luxdvr@.service](luxdvr@.service)).

### Files
1. `protocol.py` — The core protocol parser. Handles the partially reverse-engineered proprietary communication (DVR to IE+WebClient), strips away custom transport wrappers and extracts pure H.264 Annex B frames. Details about the reverse engineering are provided below.
2. `main.py` — The main entry point and network client. Manages CLI arguments, maintains the TCP socket, runs the keep-alive watchdog with auto-reconnect capabilities, and pipes the raw binary video stream to `stdout`.
3. `ref.py` — Experimental reference script used during the initial reverse-engineering phase.
4. `credentials.py` — Default configuration file (Host IP, login, password, MAC). These values act as fallbacks and can be overridden via CLI arguments.
5. `stream_copy.sh` / `stream_h264.sh` — Example shell scripts demonstrating the FFmpeg pipeline. Shows how to repack the raw stream into RTSP with zero-CPU usage (`copy`) or with full software transcoding (`h264`).
6. `luxdvr@.service` — A `systemd` template unit file for deploying the bridge as a resilient 24/7 background daemon on Linux. It allows managing multiple cameras independently, handles automatic crash recovery, and ensures the correct startup sequence alongside the local RTSP server (e.g., MediaMTX).

# LuxDVR Pro 04-Fx2 Reverse Engineering
### In this part the milestones of reverse engineering of the protocol are provided
> Main goal was to drop the bunch of Windows XP + Internet Explorer + ActiveX proprietary plugin (known as "WebClient.exe") 
> by creation of the client-side application, that will act as genuine software and grab a videostream

## 1. Prerequisites
+ Oracle VirtualBox
+ Windows XP VM (you can use the VDI with preinstalled OS to save time, i.e. 
[this](https://sysprobs.com/windows-xp-virtualbox-pre-installed-image) one)
**ATTENTION! Consider setting "Bridge" mode of virtual network interface to simplify the proccess!**
+ Wireshark
+ Python

## 2. Bringing on
1. Connect your PC with VM and DVR to a router
2. Find out the IP address of the DVR
3. On VM run `Internet Explorer` and navigate to `http://<IP of the DVR>`, then press `Internet Explorer`. 
The download of `WebClient.exe` should start.
4. Install the mentioned above file, restart browser
5. Run Wireshark on interface you use to connect to network with filter `ip.addr == <IP of the DVR>`, press `Enter`
6. Navigate to `http://<IP of the DVR>/webcamera.html` - you should see a login page. By default, the login is `admin` and the password is `123456`.

## 3. Protocol
*(Full reference experimental script is located in `ref.py`)*

After logging in you'll be able to watch the video from cameras directly in browser. Meanwhile if you take a look on Wireshark window, you'll see: 
predominantly HTTP-traffic during establishing of the connection and then only TCP during video streaming from port 6036. 

I guess there are at least two sessions for this: the UI one (port 80) and the control one (port 6036, also video streaming).
Let's take a deeper look into the last one
### 1) Greetings (DVR -> Client)
Immediately after establishing to connection to control stream (#367 in my case) the DVR sends the 64 bytes long `hello` packet.
The main distinctive feature is the word `head` (and only it) in `ascii`-dump while viewing in Wireshark:

| Offset   | HEX                                               |                    ASCII-dump                     |
|:---------|:--------------------------------------------------|:-------------------------------------------------:| 
| 00000000 | 68 65 61 64 00 00 00 00&ensp;&ensp;b9 00 00 00 04 00 00 00 | <code style="white-space: pre;">head.... ........</code> |
| 00000010 | 03 00 00 00 00 00 00 00&ensp;&ensp;00 00 00 00 00 00 00 00 | <code style="white-space: pre;">........ ........</code> |
| 00000020 | 00 00 00 00 00 00 00 00&ensp;&ensp;00 00 00 00 00 00 00 00 | <code style="white-space: pre;">........ ........</code> |
| 00000030 | 00 00 00 00 00 00 00 00&ensp;&ensp;00 00 00 00 00 00 00 00 | <code style="white-space: pre;">........ ........</code> |

**Note: you can trace TCP-stream in Wireshark starting from this packet**

### 2) Authentication (Client -> DVR)
#### NOTE: starting from here each packet starts from so-called 4 bytes-long "magic header"- `b'1111'` (`31 31 31 31` in HEX). Next comes the 4 bytes-long length of payload (little-endian)

Client (*here and further I mean IE + WebClient.exe*) sends especially formatted struct with authentication credentials. 
Furthermore, it sends the PC's full name and MAC address. Maybe this information is needed for DVR to distinguish different clients

| Offset   | HEX                                                  | ASCII-dump                                               |
|:---------|:-----------------------------------------------------|:---------------------------------------------------------|
| 00000000 | 31 31 31 31 88 00 00 00&ensp;&ensp;01 01 00 00 78 01 fb 03 | <code style="white-space: pre;">1111.... ....x...</code> |
| 00000010 | 00 00 00 00 78 00 00 00&ensp;&ensp;03 00 00 00 00 00 00 00     | <code style="white-space: pre;">....x... ........</code>  |
| 00000020 | 61 64 6d 69 6e 00 00 00&ensp;&ensp;00 00 00 00 00 00 00 00     | <code style="white-space: pre;">admin... ........</code>  |
| 00000030 | 00 00 00 00 00 00 00 00&ensp;&ensp;00 00 00 00 00 00 00 00     | <code style="white-space: pre;">........ ........</code> |
| 00000040 | 00 00 00 00 31 32 33 34&ensp;&ensp;35 36 00 00 00 00 00 00     | <code style="white-space: pre;">....1234 56......</code>  |
| 00000050 | 00 00 00 00 00 00 00 00&ensp;&ensp;00 00 00 00 00 00 00 00     | <code style="white-space: pre;">........ ........</code>  |
| 00000060 | 00 00 00 00 00 00 00 00&ensp;&ensp;73 79 73 70 72 6f 62 73     | <code style="white-space: pre;">........ sysprobs</code>  |
| 00000070 | 2d 64 61 31 61 36 31 00&ensp;&ensp;00 00 00 00 00 00 00 00     | <code style="white-space: pre;">-da1a61. ........</code>  |
| 00000080 | 00 00 00 00 08 00 27 63&ensp;&ensp;97 34 00 00 04 00 00 00     | <code style="white-space: pre;">......'c .4......</code>  |
Description:

1. Bytes starting from the offset of `0x20` and 36 bytes long - `login`
2. Offset from `0x44` and 36 bytes long - `password`
3. Offset `0x84-0x89` represents MAC address of client, in my case it was a MAC address of VirtualBox bridge network interface: `08:00:27:63:97:34`. 
4. Offset from `0x68` and 28 bytes long represents full computer name.

### 3) DVR info (DVR -> Client)
If authentication was successful, the DVR sends some software and hardware data about itself:

| Offset   | HEX                                                  | ASCII-dump                                                |
|:---------|:-----------------------------------------------------|:----------------------------------------------------------|
| 00000040 | 31 31 31 31 6c 01 00 00&ensp;&ensp;01 00 01 00 50 be ec 00 | <code style="white-space: pre;">1111l... ....P...</code>  |
| 00000050 | 04 00 00 00 5c 01 00 00&ensp;&ensp;ff ff ff ff 0f 00 00 00 | <code style="white-space: pre;">....\\... ........</code> |
| 00000060 | 00 00 00 00 0f 00 00 00&ensp;&ensp;00 00 00 00 0f 00 00 00 | <code style="white-space: pre;">........ ........</code>  |
| 00000070 | 00 00 00 00 0f 00 00 00&ensp;&ensp;00 00 00 00 0f 00 00 00 | <code style="white-space: pre;">........ ........</code>  |
| 00000080 | 00 00 00 00 0f 00 00 00&ensp;&ensp;00 00 00 00 04 04 04 01 | <code style="white-space: pre;">........ ........</code>  |
| 00000090 | c8 00 00 00 04 04 00 00&ensp;&ensp;80 08 10 04 40 12 00 b9 | <code style="white-space: pre;">........ ....@...</code>  |
| 000000A0 | 01 01 01 01 84 78 94 82&ensp;&ensp;04 00 00 00 01 00 00 00 | <code style="white-space: pre;">.....x.. ........</code>  |
| 000000B0 | fc ff c9 03 00 00 00 00&ensp;&ensp;00 00 00 00 00 00 00 00 | <code style="white-space: pre;">........ ........</code>  |
| 000000C0 | 00 00 00 00 00 00 00 00&ensp;&ensp;00 00 00 00 00 00 00 00 | <code style="white-space: pre;">........ ........</code>  |
| 000000D0 | 00 00 00 00 00 18 ae 39&ensp;&ensp;83 9c 00 00 0c 07 dd 07 | <code style="white-space: pre;">.......9 ........</code>  |
| 000000E0 | 28 31 0b 00 45 44 56 52&ensp;&ensp;00 00 00 00 00 00 00 00 | <code style="white-space: pre;">(1..EDVR ........</code>  |
| 000000F0 | 00 00 00 00 00 00 00 00&ensp;&ensp;00 00 00 00 00 00 00 00 | <code style="white-space: pre;">........ ........</code>  |
| 00000100 | 00 00 00 00 00 00 00 00&ensp;&ensp;33 2e 33 2e 30 2e 50 2d | <code style="white-space: pre;">........ 3.3.0.P-</code>  |
| 00000110 | 33 35 32 30 41 2d 30 30&ensp;&ensp;00 00 00 00 00 00 00 00 | <code style="white-space: pre;">3520A-00 ........</code>  |
| 00000120 | 00 00 00 00 00 00 00 00&ensp;&ensp;00 00 00 00 43 39 4b 37 | <code style="white-space: pre;">........ ....C9K7</code>  |
| 00000130 | 2d 44 33 42 33 2d 44 37&ensp;&ensp;42 34 00 00 00 00 00 00 | <code style="white-space: pre;">-D3B3-D7 B4......</code>  |
| 00000140 | 00 00 00 00 00 00 00 00&ensp;&ensp;00 00 00 00 00 00 00 00 | <code style="white-space: pre;">........ ........</code>  |
| 00000150 | 00 00 00 00 00 00 00 00&ensp;&ensp;00 00 00 00 00 00 00 00 | <code style="white-space: pre;">........ ........</code>  |
| 00000160 | 00 00 00 00 00 00 00 00&ensp;&ensp;00 00 00 00 31 38 35 2e | <code style="white-space: pre;">........ ....185.</code>  |
| 00000170 | 30 2e 31 36 2e 51 39 2d&ensp;&ensp;44 4b 43 42 41 2d 74 64 | <code style="white-space: pre;">0.16.Q9- DKCBA-td</code>  |
| 00000180 | 32 30 61 00 00 00 00 00&ensp;&ensp;00 00 00 00 00 00 00 00 | <code style="white-space: pre;">20a..... ........</code>  |
| 00000190 | 2d 2d 2d 00 00 00 00 00&ensp;&ensp;00 00 00 00 00 00 00 00 | <code style="white-space: pre;">---..... ........</code>  |
| 000001A0 | 00 00 00 00 00 00 00 00&ensp;&ensp;00 00 00 00 00 00 00 00 | <code style="white-space: pre;">........ ........</code>  |
| 000001B0 | 00 00 00 00            &ensp;&ensp;                        | <code style="white-space: pre;">....</code>               |

Here we can find out the DVR's hostname, its software, hardware version and lots of unknown data :)

### 4) Cameras? (DVR -> Client)
Immediately after previous packet the DVR sends another one. Meaning of this packet is a bit "foggy". 
Possibly this is enumeration of available cameras with some additional information about each one. 
Interesting part about it is that this packet seems to contain a multiple 'mini'-packets, because the 'magic header' 
(+payload length respectively) appears 5 times: 1 at the start, then for each camera.

### 5) Cameras preferences (set? request?) (Client -> DVR)

| Offset   | HEX                                                  | ASCII-dump                                               |
|:---------|:-----------------------------------------------------|:---------------------------------------------------------|
| 00000090 | 31 31 31 31 50 00 00 00&ensp;&ensp;03 04 00 00 ff ff ff ff | <code style="white-space: pre;">1111P... ........</code> |
| 000000A0 | ff ff ff ff 40 00 00 00&ensp;&ensp;00 f8 59 05 04 00 00 00 | <code style="white-space: pre;">....@... ..Y.....</code> |
| 000000B0 | 01 f8 00 00 00 00 00 00&ensp;&ensp;02 f8 00 00 00 00 00 00 | <code style="white-space: pre;">........ ........</code> |
| 000000C0 | 03 f8 00 00 00 00 00 00&ensp;&ensp;40 f8 00 00 00 00 00 00 | <code style="white-space: pre;">........ @.......</code> |
| 000000D0 | 41 f8 00 00 00 00 00 00&ensp;&ensp;42 f8 00 00 00 00 00 00 | <code style="white-space: pre;">A....... B.......</code> |
| 000000E0 | 43 f8 00 00 00 00 00 00                              | <code style="white-space: pre;">C.......</code>             |

This packet is even more 'foggy' than previous one. Very-very roughly I can assume that this is a kinda 'request' about
each camera settings (maybe not only camera ones) - you can see 8 requests starting at the offset of `0xb0`. 
Before that can be another request (look at `03 04` - reminds `command + subcommand` structure)

#### The only thing I know exactly about this packet - we need to send this request and **necessarily** read full answer (see next pt.)

### 6) Cameras presets (DVR -> Client)
After previous request the DVR response with a few huge packets (**20580** bytes!) and we know absolutely nothing about 
them except repeating `preset001`-`preset128` in `ascii`-dump. 
But we **need** to read out all of them, because otherwise DVR closes connection.

### 7) Stream video (Client -> DVR)
Only now we can ask the DVR to start streaming of video from cameras. As always we need to pass `magic header`, payload length (52 bytes), 
possible `command + subcommand` bunch and camera number at the offset of `0x10c`, everything else is filled up with zeroes:

| Offset   | HEX                                                  | ASCII-dump                                               |
|:---------|:-----------------------------------------------------|:---------------------------------------------------------|
| 000000E8 | 31 31 31 31 34 00 00 00&ensp;&ensp;01 02 00 00 00 00 00 00 | <code style="white-space: pre;">11114... ........</code> |
| 000000F8 | 00 00 00 00 24 00 00 00&ensp;&ensp;00 00 00 00 00 00 00 00 | <code style="white-space: pre;">....$... ........</code> |
| 00000108 | 00 00 00 00 01 00 00 00&ensp;&ensp;00 00 00 00 00 00 00 00 | <code style="white-space: pre;">........ ........</code> |
| 00000118 | 00 00 00 00 00 00 00 00&ensp;&ensp;00 00 00 00            | <code style="white-space: pre;">........ ....</code>     |

### 8) Keep-alive (Client -> DVR)
During experiments I've noticed, that stream is closed by the DVR when the raw file is about to reach a size of 3 Mb.
This behavior was caused by the absence of client-side 'reminder' to the DVR, meaning "I'm still here, please continue streaming".
I found this packet in Wireshark - it's only 8 bytes payload small and been sent every 7-8 seconds.
So at least every 5-10 second we need to send out 'keep-alive' packet:

| Offset   | HEX                     | ASCII-dump                                        |
|:---------|:------------------------|:--------------------------------------------------|
| 0000015C | 31 31 31 31&ensp;&ensp;00 00 00 00 | <code style="white-space: pre;">1111  ....</code> |

Just `magick header` and zero-length payload, but this does trick!

## 4. Dealing with videostream from the DVR

Finally, after fulfillment of all conditions above the DVR will start responding with raw H264 videostream.
But since it's encapsulated into TCP, which itself doesn't care about its contents, just about reliable delivery, 
developers continue using of their protocol. Below is an explanation made by Gemini (he also made for me the `cleaner.py`,
that can transform TCP videostream to clean H264), because I don't understand fully the Magic he'd done 🥲... On the 11th try 😅

In order for the program on the other side (our Python script) to understand where one chunk of data begins and another ends, the DVR engineers came up with their own Transport Layer (Wrapper).
Let's break down this "matryoshka" (nested doll) layer by layer using examples from dumps.

### Layer 1: Transport Envelope (DVR Level)
Every piece of information that the DVR "spits out" into the TCP socket is strictly packed into a standard envelope. It always has the exact same structure:
`Magic header` + `Payload Length` + `Payload Itself`
In your data, it looks like this:
1. Magic header: `31 31 31 31` (`b'1111'` in ASCII). This is a beacon for our script. It means: "Attention, a new packet is about to start!".
2. Payload Length: The next 4 bytes indicate how many bytes follow.

*Example from log (Continuation Packet): b'1111\x1c(\x00\x00PACK...'*

1. Header: `b'1111'`
2. Length: `\x1c(\x00\x00`. In little-endian architecture this is the number `0x0000281c`. In decimal, this is 10,268 bytes.
Our while loop in Python searches for header, reads 10268 bytes, and makes a "cut" (slice) of exactly that length. This is how we extract the inner matryoshka.

### Layer 2: Metadata and Fragmentation (What's inside the envelope?)
The DVR pulls a frame from the camera. If it's an intermediate frame (a P-frame, containing only movements like a hand or shadows), its size is small — say, 500 bytes. The DVR easily stuffs it into a single 1111 envelope.
But once every 2 seconds, the camera outputs an I-frame (Keyframe). This is a full, JPEG-like picture of the entire frame. It weighs, for example, 33100 bytes.
In the RAM of old Chinese DVRs, 10 KB buffers are allocated for network transmission. The DVR physically cannot send 33 KB all at once!
So what does it do? It takes a chainsaw and cuts the I-frame into chunks (fragments it).
So that the client (we) can understand that these are pieces of a single whole, the DVR invents another wrapper — the PACK header.
It takes up exactly 28 bytes and contains the fragment number:
+ `PACK... \x01\x00\x00\x00` — Fragment #1
+ `PACK... \x02\x00\x00\x00` — Fragment #2
+ `PACK... \x03\x00\x00\x00` — Fragment #3

*Example from log (The first chunk of an I-frame)*:
The DVR takes the first 10240 bytes of the video frame, glues 28 bytes of the `PACK` header to them (totaling 10268 bytes), packs this into an `b'1111'` envelope, and sends it into the TCP socket.

### Layer 3: Video Codec (H.264 Annex B)
Finally, we have reached the video itself. Inside the wrappers lie the raw pixels. But the H.264 codec also has its own markers (NAL units).
Absolutely every element in H.264 begins with the sequence: `00 00 00 01` (Start Code).
Immediately following this marker is 1 byte that tells FFmpeg exactly what is coming next:

+ `\x00\x00\x00\x01 \x67` (in ASCII this is `g`) — SPS packet. This is the "passport" of the video, containing the resolution (352x288) and that same crazy frame rate (1,200,000 fps).
+ `\x00\x00\x00\x01 \x68` (in ASCII this is `h`) — PPS packet.
+ `\x00\x00\x00\x01 \x65` (in ASCII this is `e`) — IDR frame. The beginning of the keyframe's actual pixels.
+ `\x00\x00\x00\x01 \x41` (in ASCII this is `A`) — P-frame. The motion frame.

Example from your log (The very beginning of the video!): `b'1111\x1c(\x00\x00 PACK... \x00\x00\x00\x01 g B...'`
We see the codec marker, the letter g (SPS), and FFmpeg understands: "Aha, the picture is 352x288!".

### How It Broke and How We Fixed It (Summary)
Imagine the DVR is sending a large frame. A chain flies across the network:
+ Envelope 1: `b'1111'` `Length` `PACK Fragment 1` `00 00 00 01 (Codec!)` `Video data...`
+ Envelope 2: `b'1111'` `Length` `PACK Fragment 2` `Continuation of video data...`
+ Envelope 3: `b'1111'` `Length` `PACK Fragment 3` `Tail of video data...`

### What does our final script do?
It works with surgical precision:
1. Does it see `00 00 00 01` in `Envelope 1`? It cuts out everything before it and grabs the clean video.
2. It takes `Envelope 2`. It doesn't see the codec marker there, but it sees the fragmentation marker `PACK`. 
The script understands: "Aha! This is the tail of a split frame!". It carefully cuts off the 28 bytes of the `PACK`
header and seamlessly splices the raw pixels right onto `Envelope 1`.
3. It grabs a P-frame. It cuts off the Chinese header (76 bytes) and takes the `00 00 00 01 \x41`.
4. The script strips off the layers of the matryoshka, throws away the transport-layer plastic (`b'1111'` and `PACK`), 
and saves the purest, solid H.264, which FFmpeg swallows with pleasure.