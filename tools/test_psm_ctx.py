"""
Test: try various ctx values for PHI_LoadPSM after full init.
Runs the full initialization sequence up to PHI_LoadPSM and tries
different ctx candidates.
"""
import ctypes, os, sys, json, struct

DLL_PATH    = r'C:\Program Files (x86)\Texas Instruments\ADS1285 EVM\Library\tiPHIChar.dll'
SHARED_PATH = r'C:\Program Files (x86)\Texas Instruments\ADS1285 EVM\Shared Library'
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
dll.PHI_ClosePSM.restype  = ctypes.c_int32
dll.PHI_ClosePSM.argtypes = [ctypes.c_int32, ctypes.c_int32]
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
dll.PHI_WriteFPGARegister.restype  = ctypes.c_int32
dll.PHI_WriteFPGARegister.argtypes = [ctypes.c_int32, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32]

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PSM_ACQ_PATH = os.path.join(_root, 'bridge', 'phi_binaries', 'psm_04_40B.bin')
PSM_SEQ_PATH = os.path.join(_root, 'bridge', 'phi_binaries', 'psm_05_200B.bin')

GetModuleHandle = ctypes.windll.kernel32.GetModuleHandleW
import ctypes.wintypes
GetModuleHandle.restype = ctypes.wintypes.HMODULE

c = ctypes.c_int32(0)
dll.PHI_CheckforDevices(ctypes.byref(c))
print(f'devices={c.value}', flush=True)

h = ctypes.c_int32(0)
dll.PHI_Initialize(0, ctypes.byref(h))
handle = h.value
print(f'handle=0x{handle:08X}', flush=True)

dll_base = GetModuleHandle('tiPHIChar.dll')
print(f'dll_base=0x{dll_base:08X}', flush=True)

# PSM array base (RVA 0x79340)
PSM_ARRAY_BASE = dll_base + 0x79340
print(f'PSM_ARRAY_BASE=0x{PSM_ARRAY_BASE:08X}', flush=True)

# Call InitializePSM
dummy = ctypes.create_string_buffer(512)
ret = dll.PHI_InitializePSM(h, ctypes.c_int32(0), dummy)
print(f'PHI_InitializePSM -> {ret}', flush=True)

ctx_handle_plus_90 = ctypes.c_int32.from_address(handle + 0x90).value
print(f'handle+0x90 = 0x{ctx_handle_plus_90:08X}', flush=True)

# Read 64 bytes at handle+0x90's target
def read_struct(addr, n=64):
    try:
        raw = (ctypes.c_byte * n).from_address(addr)
        return bytes(raw)
    except Exception as e:
        return f'ERROR: {e}'

data = read_struct(ctx_handle_plus_90)
if isinstance(data, bytes):
    dwords = struct.unpack(f'<{len(data)//4}I', data)
    print(f'ctx struct: {["0x{:08X}".format(v) for v in dwords[:8]]}', flush=True)

# Load PSM files
with open(PSM_ACQ_PATH, 'rb') as f:
    psm_acq = f.read()
with open(PSM_SEQ_PATH, 'rb') as f:
    psm_seq = f.read()

# Do the pre-LoadPSM sequence
def wi(ep, val, mask):
    dll.PHI_UpdateWireIn(h, ctypes.c_int32(ep), ctypes.c_int32(val), ctypes.c_int32(mask))

def pw(ch, addr, data_bytes):
    buf = ctypes.create_string_buffer(bytes(data_bytes), len(data_bytes))
    dll.PHI_Write(h, ctypes.c_int32(ch), ctypes.c_int32(addr), ctypes.c_int32(len(data_bytes)), buf)

def proc(cmd):
    r = ctypes.c_int32(0)
    dll.PHI_Process(h, ctypes.c_int32(cmd), ctypes.byref(r))

def load_pipe(ep, data_bytes):
    buf = ctypes.create_string_buffer(bytes(data_bytes), len(data_bytes))
    dll.PHI_Load_PipeIn(h, ctypes.c_int32(ep), buf, ctypes.c_int32(len(data_bytes)))

wi(20, 1, 0xFFFF)
wi(21, 1, 0xFFFF)
wi(3, 1, 0x000F)

n = len(psm_acq)
pw(1, 12288, list(n.to_bytes(4, 'little')))
pw(1, 2304, [1, 0, 0, 0])
proc(2304)
load_pipe(0, psm_acq)
pw(1, 16388, [0])
pw(1, 16384, [1, 0, 0, 0])
pw(1, 2308, [1, 0, 0, 0])
proc(2308)
dll.PHI_Play_PipeIn(h, ctypes.c_int32(0), ctypes.c_int32(0))
wi(3, 2, 0x000F)

n2 = len(psm_seq)
pw(1, 12288, list(n2.to_bytes(4, 'little')))
pw(1, 2304, [1, 0, 0, 0])
proc(2304)
load_pipe(0, psm_seq)
pw(1, 16388, [0])
pw(1, 16384, [1, 0, 0, 0])
pw(1, 2308, [1, 0, 0, 0])
proc(2308)
dll.PHI_Play_PipeIn(h, ctypes.c_int32(0), ctypes.c_int32(0))
wi(3, 19, 0x001F)
wi(3, 0, 0x0010)

print('Pre-LoadPSM sequence done.', flush=True)

# Read struct AFTER the pipe operations
ctx_after_pipe = ctypes.c_int32.from_address(handle + 0x90).value
print(f'handle+0x90 after pipe ops = 0x{ctx_after_pipe:08X}', flush=True)
data2 = read_struct(ctx_after_pipe)
if isinstance(data2, bytes):
    dwords2 = struct.unpack(f'<{len(data2)//4}I', data2)
    print(f'ctx struct after pipe: {["0x{:08X}".format(v) for v in dwords2[:8]]}', flush=True)

# Try various ctx candidates
candidates = {
    'handle+0x90_value': ctx_after_pipe,
    'PSM_ARRAY_BASE': PSM_ARRAY_BASE,
    'PSM_ARRAY_BASE+4': PSM_ARRAY_BASE + 4,  # = handle
    'handle itself': handle,
    'handle+0x44': ctypes.c_int32.from_address(handle + 0x44).value,
    'handle+0x50': ctypes.c_int32.from_address(handle + 0x50).value,
    'handle+0x5C': ctypes.c_int32.from_address(handle + 0x5C).value,
    'handle+0x84': ctypes.c_int32.from_address(handle + 0x84).value,
    'handle+0x88': ctypes.c_int32.from_address(handle + 0x88).value,
}

print('\n--- PSM area after pipe ops ---', flush=True)
for i in range(12):
    v = ctypes.c_int32.from_address(handle + i*4 - 4).value
    print(f'  handle{i*4-4:+d}: 0x{v:08X}', flush=True)

print('\n--- Candidates for ctx ---', flush=True)
for name, val in candidates.items():
    print(f'  {name}: 0x{val:08X} ({val})', flush=True)
    if isinstance(val, int) and val > 0x1000:
        data = read_struct(val, 32)
        if isinstance(data, bytes):
            dw = struct.unpack('<8I', data)
            print(f'    struct: {["0x{:08X}".format(v) for v in dw]}', flush=True)

print('\nAll candidates enumerated. Will NOT call PHI_LoadPSM to avoid crash.', flush=True)
