"""
Test pas-a-pas du bridge32 (supposant qu'il tourne deja sur localhost:9500).
"""
import socket, json, time

HOST, PORT = "127.0.0.1", 9500
req_id = 0

def call(cmd, args=None):
    global req_id
    req_id += 1
    req = {"id": req_id, "cmd": cmd, "args": args or [], "kwargs": {}}
    payload = (json.dumps(req) + "\n").encode()
    print(f"  >> {cmd}  ({len(payload)} octets)")
    sock.sendall(payload)
    buf = b""
    while b"\n" not in buf:
        buf += sock.recv(65536)
    resp = json.loads(buf.split(b"\n")[0].decode())
    if resp.get("error"):
        print(f"  ERREUR:\n{resp['error']}")
        return None
    print(f"  OK: {resp['result']}")
    return resp["result"]

sock = socket.create_connection((HOST, PORT), timeout=15)
sock.settimeout(30)
print("Connecte au bridge32\n")

print("=== 1. check_devices ===")
call("check_devices")

print("\n=== 2. get_serial_numbers ===")
call("get_serial_numbers")

print("\n=== 3. initialize ===")
call("initialize", [0])

print("\n=== 4. initialize_full (chemins seulement) ===")
import os
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
base = os.path.join(_root, "bridge", "phi_binaries")
fpga = os.path.join(base, "fpga_189956B.bin")
psms = sorted(os.path.join(base, f) for f in os.listdir(base)
              if f.startswith("psm_") and f.endswith(".bin"))
xml  = r"C:\Program Files (x86)\Texas Instruments\ADS1285 EVM\Register Map.xml"
log  = os.path.join(base, "call_log.json")

call("initialize_full", [fpga, psms, xml, log])

sock.close()
