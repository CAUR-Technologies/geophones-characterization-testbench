"""
Spy CIBLE sur la sequence d'acquisition de tiPHIChar.dll.

But : comprendre PHI_GetEvents et la boucle de polling qui suit PHI_RunPSM,
afin de pouvoir la reproduire dans bridge32.py (les donnees reviennent a zero
parce que le bridge ne pompe jamais les evenements via PHI_GetEvents).

Contrairement a spy_phi_dll.py, ce script :
  - ne hooke que les fonctions de la phase d'acquisition
  - capture le CONTENU des buffers pointes par PHI_GetEvents AVANT et APRES
    l'appel (pour voir ce que la fonction lit / ecrit)
  - capture les valeurs lues par les PHI_Read de statut (registres 514/4108/4144)
  - n'ecrase AUCUN fichier .bin existant (sauvegarde seulement un JSON dedie)

Usage :
  1. Lancer la GUI TI : ADS1285 EVM.exe
  2. venv\\Scripts\\python.exe tools\\spy_getevents.py
  3. Dans la GUI : connecter l'EVM PUIS lancer une ACQUISITION de donnees
     (c'est l'acquisition qui declenche RunPSM + GetEvents)
  4. Ctrl+C pour arreter et ecrire la capture
"""

import frida
import sys
import json
import time
import os

DLL_NAME = "tiPHIChar.dll"

# On ne surveille que la phase d'acquisition / lecture.
FUNCTIONS = [
    "PHI_Enable_PipeOut",
    "PHI_RunPSM",
    "PHI_GetEvents",
    "PHI_Read",
    "PHI_Write",
    "PHI_Process",
    "PHI_Read_PipeOut",
    "PHI_GetPSMScriptStatus",
    "PHI_GetStatus_PipeOut",
]

hook_calls = "\n        ".join([f'hookFn(mod, "{f}");' for f in FUNCTIONS])

js_code = (
    "(function() {\n"
    "    var dll = '" + DLL_NAME + "';\n"
    "    var hooksInstalled = false;\n"
    "\n"
    "    function readBuf(p, len) {\n"
    "        try {\n"
    "            if (p.isNull()) return null;\n"
    "            var bytes = [];\n"
    "            for (var i = 0; i < len && i < 256; i++)\n"
    "                bytes.push(p.add(i).readU8());\n"
    "            return bytes;\n"
    "        } catch(e) { return null; }\n"
    "    }\n"
    "\n"
    "    function hookFn(mod, name) {\n"
    "        try {\n"
    "            var addr = mod.findExportByName(name);\n"
    "            if (!addr) return;\n"
    "            Interceptor.attach(addr, {\n"
    "                onEnter: function(args) {\n"
    "                    this.fnName = name;\n"
    "                    this.a = [args[0].toInt32(), args[1].toInt32(),\n"
    "                              args[2].toInt32(), args[3].toInt32(),\n"
    "                              args[4].toInt32()];\n"
    "                    this.p = [args[1], args[2], args[3], args[4]];\n"
    "                    this.before = null;\n"
    "                    // GetEvents : lire les 4 arguments-pointeurs avant l'appel\n"
    "                    if (name === 'PHI_GetEvents') {\n"
    "                        this.before = [readBuf(args[1],64), readBuf(args[2],64),\n"
    "                                       readBuf(args[3],64), readBuf(args[4],64)];\n"
    "                    }\n"
    "                },\n"
    "                onLeave: function(retval) {\n"
    "                    var after = null;\n"
    "                    if (this.fnName === 'PHI_GetEvents') {\n"
    "                        after = [readBuf(this.p[0],64), readBuf(this.p[1],64),\n"
    "                                 readBuf(this.p[2],64), readBuf(this.p[3],64)];\n"
    "                    }\n"
    "                    // PHI_Read : capturer la valeur lue si c'est un petit registre\n"
    "                    var rdval = null;\n"
    "                    if (this.fnName === 'PHI_Read' && this.a[3] <= 16) {\n"
    "                        rdval = readBuf(this.p[3], this.a[3]);\n"
    "                    }\n"
    "                    send({\n"
    "                        fn: this.fnName,\n"
    "                        args: this.a,\n"
    "                        ret: retval.toInt32(),\n"
    "                        before: this.before,\n"
    "                        after: after,\n"
    "                        rdval: rdval\n"
    "                    });\n"
    "                }\n"
    "            });\n"
    "        } catch(e) {}\n"
    "    }\n"
    "\n"
    "    function installHooks() {\n"
    "        if (hooksInstalled) return;\n"
    "        var mod = Process.findModuleByName(dll);\n"
    "        if (!mod) return;\n"
    "        hooksInstalled = true;\n"
    "        send({type:'info', msg:'DLL trouvee a ' + mod.base + ' - hooks actifs'});\n"
    "        " + hook_calls + "\n"
    "    }\n"
    "\n"
    "    installHooks();\n"
    "    setInterval(function() { if (!hooksInstalled) installHooks(); }, 300);\n"
    "})();\n"
)

call_log = []


def on_message(message, data):
    if message["type"] == "send":
        payload = message["payload"]
        if payload.get("type") == "info":
            print(f"[INFO] {payload['msg']}")
            return
        call_log.append(payload)
        fn = payload["fn"]
        args = payload["args"]
        ret = payload["ret"]
        extra = ""
        if payload.get("rdval") is not None:
            extra = f"  rdval={payload['rdval']}"
        if fn == "PHI_GetEvents":
            extra = "  [GetEvents - before/after captures]"
        print(f"  {fn:24s} args={args} ret={ret}{extra}")
    elif message["type"] == "error":
        print(f"[FRIDA ERREUR] {message.get('stack')}")


def find_target_pid():
    device = frida.get_local_device()
    for proc in device.enumerate_processes():
        if "ADS1285" in proc.name or "ads1285" in proc.name.lower():
            return proc.pid
    return None


print("Attente de la GUI TI (ADS1285 EVM.exe)... Lancez-la maintenant.")
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

print(f"Surveillance active sur {DLL_NAME}.")
print("Dans la GUI : connectez l'EVM, puis LANCEZ UNE ACQUISITION. Ctrl+C ensuite.\n")
print(f"{'Fonction':<24}  Args  Ret")
print("-" * 80)

try:
    sys.stdin.read()
except KeyboardInterrupt:
    pass

out_path = os.path.join(os.path.dirname(__file__), "getevents_capture.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(call_log, f, indent=2)

# Resume : isoler le dernier bloc d'acquisition (du dernier RunPSM jusqu'au
# premier Read_PipeOut/Read(3,...) qui suit) pour faciliter l'analyse.
run_idx = [i for i, c in enumerate(call_log) if c["fn"] == "PHI_RunPSM"]
print(f"\n\n=== {len(call_log)} appels captures, {len(run_idx)} RunPSM ===")
if run_idx:
    start = run_idx[-1]
    print(f"Dernier bloc d'acquisition a partir de l'appel #{start}:")
    ge_count = sum(1 for c in call_log[start:] if c["fn"] == "PHI_GetEvents")
    print(f"  -> {ge_count} appels PHI_GetEvents dans ce bloc")
print(f"\nCapture complete sauvegardee : {out_path}")
session.detach()
