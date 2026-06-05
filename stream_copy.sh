#!/bin/sh
/usr/bin/python3 main.py -H 192.168.1.3 -c 1 -m random  | /usr/bin/ffmpeg -hide_banner -loglevel warning -fflags +genpts -use_wallclock_as_timestamps 1 -f h264 -i - -c:v copy -rtsp_transport tcp -f rtsp rtsp://127.0.0.1:8554/cam1
