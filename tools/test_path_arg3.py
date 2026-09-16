"""
Test PHI_InitializePSM with a real directory path as arg3.
The path directory contains DataMem.bin and CMdMem.bin.
Then test PHI_LoadPSM with 4 args (ctx, psm_id, arg3, arg4=1).
"""
import ctypes, ctypes.wintypes, struct, os, sys

DLL_PATH    = r'C:\Program Files (x86)\Texas Instruments\ADS1285 EVM\Library\tiPHIChar.dll'
SHARED_PATH = r'C:\Program Files (x86)\Texas Instruments\ADS1285 EVM\Shared Library'
os.add_dll_directory(os.path.dirname(DLL_PATH))
os.add_dll_directory(SHARED_PATH)
dll = ctypes.WinDLL(DLL_PATH)
P = ctypes.POINTER(ctypes.c_int32)
dll.PHI_CheckforDevices.restype  = ctypes.c_int32
dll.PHI_CheckforDevices.argtypes = [P]
dll.PHI_Initialize.restype  = ctypes.c_int32
dll.PHI_Initialize.argtypes  = [ctypes.c_int32, P]
dll.PHI_InitializePSM.restype  = ctypes.c_int32
dll.PHI_InitializePSM.argtypes = [ctypes.c_int32, ctypes.c_int32, ctypes.c_char_p]
dll.PHI_LoadPSM.restype  = ctypes.c_int32
dll.PHI_LoadPSM.argtypes = [ctypes.c_int32, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32]
dll.PHI_ClosePSM.restype  = ctypes.c_int32
dll.PHI_ClosePSM.argtypes = [ctypes.c_int32, ctypes.c_int32]

GetModuleHandle = ctypes.windll.kernel32.GetModuleHandleW
GetModuleHandle.restype = ctypes.wintypes.HMODULE
dll_base = GetModuleHandle('tiPHIChar.dll')

def read_bytes_safe(addr, n):
    try:
        buf = ctypes.create_string_buffer(n)
        nread = ctypes.c_size_t(0)
        ctypes.windll.kernel32.ReadProcessMemory(
            ctypes.windll.kernel32.GetCurrentProcess(),
            ctypes.c_void_p(addr), buf, n, ctypes.byref(nread))
        return buf.raw[:nread.value]
    except:
        return b''

c = ctypes.c_int32(0); dll.PHI_CheckforDevices(ctypes.byref(c))
print(f'devices={c.value}', flush=True)
h = ctypes.c_int32(0); dll.PHI_Initialize(0, ctypes.byref(h))
handle = h.value
print(f'handle=0x{handle:08X}  dll_base=0x{dll_base:08X}', flush=True)

# Directory containing DataMem.bin and CMdMem.bin
PSM_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'bridge', 'phi_binaries', 'psm0')
print(f'PSM_DIR={PSM_DIR}', flush=True)
print(f'Files: {os.listdir(PSM_DIR)}', flush=True)

# Pass the directory path as arg3
arg3 = ctypes.create_string_buffer(PSM_DIR.encode('ascii') + b'\x00')
print(f'arg3 = "{PSM_DIR}" ({len(PSM_DIR)} chars)', flush=True)

ret = dll.PHI_InitializePSM(h, ctypes.c_int32(0), arg3)
print(f'PHI_InitializePSM -> ret={ret}', flush=True)

# Check handle+0x94 (fn_C destination) and handle+0x90 (heap ptr)
val_94 = ctypes.c_uint32.from_address(handle + 0x94).value
ptr_90 = ctypes.c_uint32.from_address(handle + 0x90).value
print(f'handle+0x94 = 0x{val_94:08X}', flush=True)
print(f'handle+0x90 = 0x{ptr_90:08X}', flush=True)

if ptr_90 > 0x1000:
    heap_raw = read_bytes_safe(ptr_90, 64)
    print(f'heap[0:64] = {heap_raw[:64]}', flush=True)
    # Try to decode as string
    end = heap_raw.find(b'\x00')
    path_str = heap_raw[:end].decode('ascii', errors='replace') if end >= 0 else '?'
    print(f'heap as string: "{path_str}"', flush=True)

# Also check handle+0x94 content
raw_94 = read_bytes_safe(handle + 0x94, 64)
end94 = raw_94.find(b'\x00')
str_94 = raw_94[:end94].decode('ascii', errors='replace') if end94 >= 0 else '?'
print(f'handle+0x94 as string: "{str_94}" (first 8 bytes: {raw_94[:8].hex()})', flush=True)

# Now call PHI_LoadPSM with ctx = handle+0x90 value, arg4=1
ctx = ptr_90
print(f'\nCalling PHI_LoadPSM(handle, 0, ctx=0x{ctx:08X}, 1)...', flush=True)
sys.stdout.flush()
ret2 = dll.PHI_LoadPSM(h, ctypes.c_int32(0), ctypes.c_int32(ctx), ctypes.c_int32(1))
print(f'PHI_LoadPSM -> ret={ret2}', flush=True)
