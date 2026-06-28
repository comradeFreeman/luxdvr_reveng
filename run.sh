#!/bin/bash
CAM=$1
PIPE="/tmp/luxdvr_pipe_$CAM"
NOSIGNAL="/tmp/luxdvr/nosignal_${CAM}.h264"
sleep $(($1*3))

echo "=== [cam$CAM] Initializing seamless pipeline ==="

# 1. Create the named pipe (FIFO buffer)
rm -f "$PIPE"
mkfifo "$PIPE"

# 2. Generate the raw H.264 test card file ONCE (Duration: 60 seconds).
# Using the built-in SMPTE color bars generator (no external fonts required)
if [ ! -f "$NOSIGNAL" ]; then
    echo "=== [cam$CAM] Generating SMPTE test card... ==="
    /usr/bin/ffmpeg -hide_banner -loglevel error -f lavfi -i "smptebars=size=960x576:rate=25" -t 60 \
    -c:v libx264 -preset ultrafast -profile:v baseline -x264opts keyint=25 -b:v 500k \
    -f h264 "$NOSIGNAL"
fi

# 3. UNIX MAGIC: Open the pipe for both reading and writing on FD3.
# This prevents the pipe from ever sending an EOF (End Of File) signal, even when idle.
exec 3<> "$PIPE"

# 4. Launch the "Eternal" background FFmpeg. It reads the pipe and holds the RTSP connection to MediaMTX.
# Mode A: Zero transcoding (CPU copy)
/usr/bin/ffmpeg -hide_banner -loglevel error -fflags +genpts -use_wallclock_as_timestamps 1 -f h264 -i "$PIPE" -c:v copy -rtsp_transport tcp -f rtsp rtsp://127.0.0.1:8554/cam$CAM &
FFMPEG_PID=$!

# Mode B: Software H.264 transcoding (Uncomment if needed)
# /usr/bin/ffmpeg -hide_banner -loglevel warning -f h264 -i "$PIPE" -vf 'setpts=N/(25*TB)' -r 25 -c:v libx264 -preset ultrafast -tune zerolatency -crf 23 -rtsp_transport tcp -f rtsp rtsp://127.0.0.1:8554/cam$CAM & FFMPEG_PID=$!

(
    while kill -0 $FFMPEG_PID 2>/dev/null; do
        sleep 1
    done
    echo "=== [cam$CAM] FATAL ERROR: background FFmpeg died! ==="
    echo "=== [cam$CAM] Restarting unit... ==="
    kill -TERM $$
) &

# Graceful cleanup on service termination: kill background FFmpeg and close FD 3
trap "kill -9 $FFMPEG_PID; exec 3>&-; rm -f $PIPE" EXIT

# 5. Main Hot-Swap Loop
while true; do
    echo "=== [cam$CAM] Streaming live DVR feed... ==="
    # Python pipes raw H.264 directly into File Descriptor 3
    /usr/bin/python3 main.py -c $CAM --mac random --name "LuxDVR CamReader-$CAM" >&3

    echo "=== [cam$CAM] CONNECTION LOST! Seamlessly injecting test card... ==="
    # If we reached this line, Python crashed.
    # Instantly push the 60-second fallback file into the same FD3.
    # Flag -re streams it at 1x real-time speed. Duration: exactly 60 seconds.
    /usr/bin/ffmpeg -hide_banner -loglevel error -re -i "$NOSIGNAL" -c:v copy -f h264 pipe:1 >&3

    echo "=== [cam$CAM] Reconnecting to the DVR... ==="
    sleep 1
done
