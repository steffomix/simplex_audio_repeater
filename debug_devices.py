#!/usr/bin/env python3
"""Debug-Script um Audio-Geräte und ihre Kanäle anzuzeigen"""

import pyaudio

p = pyaudio.PyAudio()

print("=== Audio-Geräte ===\n")

for i in range(p.get_device_count()):
    info = p.get_device_info_by_index(i)
    host_api = p.get_host_api_info_by_index(info['hostApi'])['name']
    print(f"[{i}] Host-API: {host_api}")

    if info['maxInputChannels'] > 0:
        print(f"INPUT {i}: {info['name']}")
        print(f"  Max Input Channels: {info['maxInputChannels']}")
        print(f"  Default Sample Rate: {info['defaultSampleRate']}")
        print()
    
    if info['maxOutputChannels'] > 0:
        print(f"OUTPUT {i}: {info['name']}")
        print(f"  Max Output Channels: {info['maxOutputChannels']}")
        print(f"  Default Sample Rate: {info['defaultSampleRate']}")
        print()

p.terminate()
