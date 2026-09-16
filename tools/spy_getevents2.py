"""
Spy sur PHI_GetEvents pour capturer la structure du buffer d'evenements.

Usage:
  1. Lancer la GUI TI (ADS1285 EVM.exe) et connecter l'EVM
  2. Dans un autre terminal (venv 64-bit):
       venv\Scripts\python.exe tools\spy_getevents2.py
  3. Observer quelques captures dans la GUI TI
  4. Ctrl+C pour voir les resultats

Sauvegarde les buffers bruts dans tools/getevents_buffers/
"""

import frida
import sys
import json
import time
import os

DLL_NAME = "tiPHIChar.dll"

# Taille du dump de chaque buffer d'evenements (bytes)
BUF_DUMP_SIZE = 512

js_code = """
(function() {
    var dll = '""" + DLL_NAME + """';
    var hooksInstalled = false;
    var callCount = 0;

    function readBuf(ptr, len) {
        try {
            if (ptr.isNull()) return null;
            return Array.from(ptr.readByteArray(len));
        } catch(e) { return null; }
    }

    function hookGetEvents(mod) {
        var addr = mod.findExportByName('PHI_GetEvents');
        if (!addr) { send({type:'error', msg:'PHI_GetEvents non trouve'}); return; }

        Interceptor.attach(addr, {
            onEnter: function(args) {
                this.handle = args[0].toInt32();
                this.evBuf  = args[1];          // pointeur vers event buffer
                this.p2     = args[2].toInt32();
                this.p3     = args[3].toInt32();
            },
            onLeave: function(retval) {
                callCount++;
                if (callCount > 200) return;  // limiter a 200 captures
                var buf = readBuf(this.evBuf, """ + str(BUF_DUMP_SIZE) + """);
                send({
                    type: 'event',
                    n: callCount,
                    handle: this.handle,
                    evBufAddr: this.evBuf.toInt32(),
                    p2: this.p2,
                    p3: this.p3,
                    ret: retval.toInt32(),
                    buf: buf
                });
            }
        });
        send({type:'info', msg:'PHI_GetEvents hooke'});
    }

    function hookFPGALoad(mod) {
        // Capturer le buffer de PHILoadFPGA (bitfile FPGA)
        var addr = mod.findExportByName('PHILoadFPGA');
        if (!addr) return;
        Interceptor.attach(addr, {
            onEnter: function(args) {
                this.handle = args[0].toInt32();
                this.bufPtr = args[1];
                this.size   = args[2].toInt32();
                send({type:'fpga_start', size: this.size});
            },
            onLeave: function(retval) {
                send({type:'fpga_ret', ret: retval.toInt32()});
                // Tenter de lire le buffer (peut etre lent pour 464KB)
                if (!this.bufPtr.isNull() && this.size > 0 && this.size < 1000000) {
                    try {
                        var bytes = Array.from(this.bufPtr.readByteArray(this.size));
                        send({type:'fpga_buf', size: this.size, buf: bytes});
                    } catch(e) {
                        send({type:'fpga_err', msg: e.message});
                    }
                }
            }
        });
        send({type:'info', msg:'PHILoadFPGA hooke'});
    }

    function installHooks() {
        if (hooksInstalled) return;
        var mod = Process.findModuleByName(dll);
        if (!mod) return;
        hooksInstalled = true;
        send({type:'info', msg:'DLL trouvee a ' + mod.base});
        hookGetEvents(mod);
        hookFPGALoad(mod);
    }

    installHooks();
    setInterval(function() { if (!hooksInstalled) installHooks(); }, 300);
})();
"""

event_bufs = []
fpga_buf_data = None
out_dir = os.path.join(os.path.dirname(__file__), "getevents_buffers")
os.makedirs(out_dir, exist_ok=True)


def on_message(message, data):
    global fpga_buf_data
    if message["type"] == "send":
        payload = message["payload"]
        t = payload.get("type")
        if t == "info":
            print(f"[INFO] {payload['msg']}")
        elif t == "error":
            print(f"[ERREUR] {payload['msg']}")
        elif t == "event":
            n = payload["n"]
            buf = payload.get("buf") or []
            ret = payload["ret"]
            # Afficher les premiers bytes en hex
            hex_str = " ".join(f"{b:02x}" for b in buf[:32])
            print(f"[{n:3d}] ret={ret:8d}  buf32: {hex_str}")
            event_bufs.append(payload)
        elif t == "fpga_start":
            print(f"[FPGA] PHILoadFPGA appele: size={payload['size']:,} bytes")
        elif t == "fpga_ret":
            print(f"[FPGA] PHILoadFPGA ret={payload['ret']}")
        elif t == "fpga_buf":
            fpga_buf_data = bytes(payload["buf"])
            path = os.path.join(out_dir, f"fpga_bitfile_{payload['size']}B.bin")
            with open(path, "wb") as f:
                f.write(fpga_buf_data)
            print(f"[FPGA] Bitfile sauvegarde: {path}")
        elif t == "fpga_err":
            print(f"[FPGA] Erreur lecture: {payload['msg']}")
    elif message["type"] == "error":
        print(f"[FRIDA ERREUR] {message['stack']}")


def find_target_pid():
    device = frida.get_local_device()
    for proc in device.enumerate_processes():
        if "ADS1285" in proc.name or "ads1285" in proc.name.lower():
            return proc.pid
    return None


print("Attente de la GUI TI (ADS1285 EVM.exe)...")
pid = None
while pid is None:
    pid = find_target_pid()
    if pid is None:
        time.sleep(0.5)

print(f"GUI trouvee (PID {pid}). Attachement Frida...")
session = frida.attach(pid)
script = session.create_script(js_code)
script.on("message", on_message)
script.load()

print("Surveillance active. Faites quelques captures dans la GUI TI. Ctrl+C pour arreter.\n")

try:
    sys.stdin.read()
except KeyboardInterrupt:
    pass

# Analyser les buffers captures
print(f"\n\n=== ANALYSE DES BUFFERS PHI_GetEvents ({len(event_bufs)} captures) ===")

if event_bufs:
    # Trouver les bytes qui varient entre captures
    min_len = min(len(e.get("buf") or []) for e in event_bufs)
    print(f"Taille du buffer: {min_len} bytes captures (sur {BUF_DUMP_SIZE} max)")

    if min_len > 0:
        # Pour chaque offset, afficher min/max/variance des valeurs
        print("\nOffsets avec variation (possible donnee ADC):")
        bufs = [bytes(e.get("buf") or []) for e in event_bufs if e.get("buf")]

        varied_offsets = []
        for off in range(min(min_len, 512)):
            vals = [b[off] for b in bufs if len(b) > off]
            if min(vals) != max(vals):
                varied_offsets.append(off)

        print(f"  {len(varied_offsets)} offsets avec variation: {varied_offsets[:40]}")

        # Analyser les int32 qui varient (pour trouver les samples ADC)
        print("\nInt32 big-endian qui varient (x offset 4-aligne):")
        for off in range(0, min(min_len - 3, 512), 4):
            import struct
            vals32 = [struct.unpack_from(">I", bytes(b[off:off+4]))[0]
                      for b in bufs if len(b) >= off+4]
            if len(vals32) > 1 and min(vals32) != max(vals32):
                print(f"  @{off:3d}: range [{min(vals32):10d}..{max(vals32):10d}]  "
                      f"ex=[{vals32[0]:10d}, {vals32[1]:10d}, {vals32[2]:10d}]")

        # Sauvegarder tous les buffers
        log_path = os.path.join(out_dir, "getevents_buffers.json")
        with open(log_path, "w") as f:
            json.dump(event_bufs, f)
        print(f"\nBuffers sauvegardes: {log_path}")

        # Sauvegarder aussi en binaire brut (premier buffer)
        raw_path = os.path.join(out_dir, "event_buf_sample.bin")
        with open(raw_path, "wb") as f:
            f.write(bufs[0])
        print(f"Premier buffer brut: {raw_path}")

session.detach()
