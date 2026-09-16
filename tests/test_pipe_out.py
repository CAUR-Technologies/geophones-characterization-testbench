"""
Test direct du read_pipe_out pour vérifier les données.
"""

import json
import socket
import os
import time

def test_pipe_out():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(("127.0.0.1", 9500))
    sock.settimeout(30.0)

    # Paramètres
    num_samples = 256
    n_bytes = num_samples * 4

    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    phi_binaries = os.path.join(_root, "bridge", "phi_binaries")
    psm_acq = os.path.join(phi_binaries, "psm_04_40B.bin")
    psm_seq = os.path.join(phi_binaries, "psm_05_200B.bin")

    print(f"Acquisition de {num_samples} samples...")

    # Acquérir les données
    req = {
        "id": 1,
        "cmd": "acquire_samples",
        "args": [num_samples, os.path.abspath(psm_acq), os.path.abspath(psm_seq), 4000],
        "kwargs": {}
    }

    sock.sendall((json.dumps(req) + "\n").encode())

    # Lire la réponse
    resp_data = b""
    while b"\n" not in resp_data:
        chunk = sock.recv(65536)
        if not chunk:
            break
        resp_data += chunk

    resp = json.loads(resp_data.split(b"\n")[0].decode())

    print(f"\n=== Réponse du bridge ===")
    if "error" in resp and resp["error"]:
        print(f"ERREUR: {resp['error']}")
    else:
        result = resp.get("result", {})
        print(f"Return code: {result.get('ret')}")

        raw_data = result.get("data", [])
        print(f"Octets reçus: {len(raw_data)}")

        if raw_data:
            # Afficher les premiers bytes
            print(f"Premiers 32 bytes: {raw_data[:32]}")
            print(f"Derniers 32 bytes: {raw_data[-32:]}")

            # Convertir en samples 32-bit
            samples = []
            for i in range(0, min(len(raw_data) - 3, len(raw_data)), 4):
                word = (raw_data[i] << 24) | (raw_data[i+1] << 16) | (raw_data[i+2] << 8) | raw_data[i+3]
                if word >= 0x80000000:
                    word -= 0x100000000
                samples.append(word)

            print(f"\n=== Données converties ===")
            print(f"Samples: {len(samples)}")
            if samples:
                print(f"Premiers 8 samples: {samples[:8]}")
                print(f"Derniers 8 samples: {samples[-8:]}")
                print(f"Min: {min(samples)}")
                print(f"Max: {max(samples)}")
                print(f"Moyenne: {sum(samples)/len(samples):.1f}")

                # Compter les zéros
                zero_count = sum(1 for s in samples if s == 0)
                print(f"Samples à zéro: {zero_count}/{len(samples)}")
            else:
                print("PROBLÈME: Aucun sample converti!")
        else:
            print("PROBLÈME: Aucune donnée reçue!")

    sock.close()

if __name__ == "__main__":
    test_pipe_out()
