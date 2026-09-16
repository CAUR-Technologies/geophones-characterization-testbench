"""
Test PHI_LoadPSM ctx candidates in isolated subprocesses.
Each candidate is tested by launching a subprocess that calls PHI_LoadPSM
with that ctx. A clean exit (0) = success, non-zero or crash = failure.
"""
import subprocess, sys, os, ctypes, struct

DLL_PATH    = r'C:\Program Files (x86)\Texas Instruments\ADS1285 EVM\Library\tiPHIChar.dll'
SHARED_PATH = r'C:\Program Files (x86)\Texas Instruments\ADS1285 EVM\Shared Library'

PY32 = r'C:\Python311-32\python.exe'
THIS_DIR = os.path.dirname(os.path.abspath(__file__))

TESTER_SCRIPT = os.path.join(THIS_DIR, '_loadpsm_inner.py')

# Write the inner test script
with open(TESTER_SCRIPT, 'w') as f:
    f.write('''
import sys, ctypes, os, struct

OFFSET = int(sys.argv[1], 16)

DLL_PATH    = r"C:\\Program Files (x86)\\Texas Instruments\\ADS1285 EVM\\Library\\tiPHIChar.dll"
SHARED_PATH = r"C:\\Program Files (x86)\\Texas Instruments\\ADS1285 EVM\\Shared Library"
os.add_dll_directory(os.path.dirname(DLL_PATH))
os.add_dll_directory(SHARED_PATH)
dll = ctypes.WinDLL(DLL_PATH)
P = ctypes.POINTER(ctypes.c_int32)

dll.PHI_CheckforDevices.restype  = ctypes.c_int32
dll.PHI_CheckforDevices.argtypes = [P]
dll.PHI_Initialize.restype  = ctypes.c_int32
dll.PHI_Initialize.argtypes = [ctypes.c_int32, P]
dll.PHI_InitializePSM.restype  = ctypes.c_int32
dll.PHI_InitializePSM.argtypes = [ctypes.c_int32, ctypes.c_int32, ctypes.c_char_p]
dll.PHI_LoadPSM.restype  = ctypes.c_int32
dll.PHI_LoadPSM.argtypes = [ctypes.c_int32, ctypes.c_int32, ctypes.c_int32]
dll.PHI_UpdateWireIn.restype  = ctypes.c_int32
dll.PHI_UpdateWireIn.argtypes = [ctypes.c_int32, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32]
dll.PHI_Load_PipeIn.restype  = ctypes.c_int32
dll.PHI_Load_PipeIn.argtypes = [ctypes.c_int32, ctypes.c_int32, ctypes.c_char_p, ctypes.c_int32]
dll.PHI_Play_PipeIn.restype  = ctypes.c_int32
dll.PHI_Play_PipeIn.argtypes = [ctypes.c_int32, ctypes.c_int32, ctypes.c_int32]
dll.PHI_Write.restype  = ctypes.c_int32
dll.PHI_Write.argtypes = [ctypes.c_int32, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32, ctypes.c_char_p]
dll.PHI_Process.restype  = ctypes.c_int32
dll.PHI_Process.argtypes = [ctypes.c_int32, ctypes.c_int32, P]

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PSM_ACQ = os.path.join(_root, "bridge", "phi_binaries", "psm_04_40B.bin")
PSM_SEQ = os.path.join(_root, "bridge", "phi_binaries", "psm_05_200B.bin")

c = ctypes.c_int32(0)
dll.PHI_CheckforDevices(ctypes.byref(c))
h = ctypes.c_int32(0)
dll.PHI_Initialize(0, ctypes.byref(h))
handle = h.value
dummy = ctypes.create_string_buffer(512)
dll.PHI_InitializePSM(h, ctypes.c_int32(0), dummy)

with open(PSM_ACQ,"rb") as f: psm_acq=f.read()
with open(PSM_SEQ,"rb") as f: psm_seq=f.read()

def wi(ep,val,mask): dll.PHI_UpdateWireIn(h,ctypes.c_int32(ep),ctypes.c_int32(val),ctypes.c_int32(mask))
def pw(ch,addr,db):
    buf=ctypes.create_string_buffer(bytes(db),len(db))
    dll.PHI_Write(h,ctypes.c_int32(ch),ctypes.c_int32(addr),ctypes.c_int32(len(db)),buf)
def proc(cmd):
    r=ctypes.c_int32(0)
    dll.PHI_Process(h,ctypes.c_int32(cmd),ctypes.byref(r))
def lp(ep,db):
    buf=ctypes.create_string_buffer(bytes(db),len(db))
    dll.PHI_Load_PipeIn(h,ctypes.c_int32(ep),buf,ctypes.c_int32(len(db)))

wi(20,1,0xFFFF); wi(21,1,0xFFFF); wi(3,1,0x000F)
n=len(psm_acq); pw(1,12288,list(n.to_bytes(4,"little"))); pw(1,2304,[1,0,0,0]); proc(2304)
lp(0,psm_acq); pw(1,16388,[0]); pw(1,16384,[1,0,0,0]); pw(1,2308,[1,0,0,0]); proc(2308)
dll.PHI_Play_PipeIn(h,ctypes.c_int32(0),ctypes.c_int32(0)); wi(3,2,0x000F)
n2=len(psm_seq); pw(1,12288,list(n2.to_bytes(4,"little"))); pw(1,2304,[1,0,0,0]); proc(2304)
lp(0,psm_seq); pw(1,16388,[0]); pw(1,16384,[1,0,0,0]); pw(1,2308,[1,0,0,0]); proc(2308)
dll.PHI_Play_PipeIn(h,ctypes.c_int32(0),ctypes.c_int32(0)); wi(3,19,0x001F); wi(3,0,0x0010)

ctx = ctypes.c_int32.from_address(handle + OFFSET).value
print(f"ctx=0x{ctx:08X}", flush=True)
ret = dll.PHI_LoadPSM(h, ctypes.c_int32(0), ctypes.c_int32(ctx))
print(f"ret={ret}", flush=True)
sys.exit(0)
''')

# Test each offset
offsets = [0x44, 0x50, 0x5C, 0x60, 0x84, 0x88, 0x8C, 0x90]

for offset in offsets:
    try:
        result = subprocess.run(
            [PY32, TESTER_SCRIPT, f'{offset:X}'],
            capture_output=True,
            text=True,
            timeout=10
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        code = result.returncode
        status = "OK (no crash)" if code == 0 else f"CRASHED (exit={code})"
        print(f"handle+0x{offset:02X}: {status}")
        if stdout:
            print(f"  stdout: {stdout}")
        if stderr and 'Error' in stderr:
            print(f"  stderr: {stderr[:100]}")
    except subprocess.TimeoutExpired:
        print(f"handle+0x{offset:02X}: TIMEOUT")
    except Exception as e:
        print(f"handle+0x{offset:02X}: ERROR {e}")

os.unlink(TESTER_SCRIPT)
