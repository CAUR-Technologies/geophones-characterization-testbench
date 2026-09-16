"""
Script de debug pour ver exactamente lo que retorna el bridge.
"""

import json
import socket
import time

def test_bridge():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(("127.0.0.1", 9500))
    sock.settimeout(20.0)

    # 1. Check devices
    print("\n=== Checking devices ===")
    req = {"id": 1, "cmd": "check_devices", "args": [], "kwargs": {}}
    sock.sendall((json.dumps(req) + "\n").encode())
    resp = json.loads(sock.recv(4096).decode())
    print(f"Devices found: {resp['result']}")

    # 2. Get version
    print("\n=== Getting version ===")
    req = {"id": 2, "cmd": "get_version", "args": [], "kwargs": {}}
    sock.sendall((json.dumps(req) + "\n").encode())
    resp = json.loads(sock.recv(4096).decode())
    print(f"Version: {resp['result']}")

    # 3. Acquire samples (small test)
    print("\n=== Acquiring 256 samples @ 4000 Hz ===")
    import os
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    phi_binaries = os.path.join(_root, "bridge", "phi_binaries")
    psm_acq = os.path.join(phi_binaries, "psm_04_40B.bin")
    psm_seq = os.path.join(phi_binaries, "psm_05_200B.bin")

    req = {
        "id": 3,
        "cmd": "acquire_samples",
        "args": [256, os.path.abspath(psm_acq), os.path.abspath(psm_seq), 4000],
        "kwargs": {}
    }
    print(f"Sending: {req}")
    sock.sendall((json.dumps(req) + "\n").encode())

    # Wait for response (longer timeout for acquisition)
    sock.settimeout(20.0)
    resp_data = b""
    while b"\n" not in resp_data:
        chunk = sock.recv(65536)
        if not chunk:
            break
        resp_data += chunk

    resp = json.loads(resp_data.split(b"\n")[0].decode())

    print(f"\n=== Response structure ===")
    print(f"Keys in response: {list(resp.keys())}")
    if "result" in resp:
        print(f"Keys in result: {list(resp['result'].keys())}")
        result = resp['result']
        if "data" in result:
            raw_data = result["data"]
            print(f"Raw data type: {type(raw_data)}")
            print(f"Raw data length: {len(raw_data)}")
            print(f"First 16 bytes (raw): {raw_data[:16]}")
            print(f"Last 16 bytes (raw): {raw_data[-16:]}")

            # Convert to 32-bit samples
            samples = []
            for i in range(0, min(len(raw_data) - 3, 32), 4):
                word = (raw_data[i] << 24) | (raw_data[i+1] << 16) | (raw_data[i+2] << 8) | raw_data[i+3]
                if word >= 0x80000000:
                    word -= 0x100000000
                samples.append(word)

            print(f"\nFirst 8 converted samples: {samples[:8]}")
            print(f"Last 8 converted samples: {samples[-8:]}")
            print(f"Min: {min(samples) if samples else 'N/A'}")
            print(f"Max: {max(samples) if samples else 'N/A'}")

    sock.close()

if __name__ == "__main__":
    test_bridge()
