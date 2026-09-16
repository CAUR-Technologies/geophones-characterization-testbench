"""
End-to-end test: PHI_InitializePSM with directory path + PHI_LoadPSM with 4 args.
Run with: C:\Python311-32\python.exe tools\test_psm_with_path.py
"""
import ctypes, ctypes.wintypes, struct, os, sys

DLL_PATH    = r'C:\Program Files (x86)\Texas Instruments\ADS1285 EVM\Library\tiPHIChar.dll'
SHARED_PATH = r'C:\Program Files (x86)\Texas Instruments\ADS1285 EVM\Shared Library'
PSM_DIR     = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'bridge', 'phi_binaries', 'psm0')

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
# PHI_LoadPSM has 4 args: (handle, psm_id, ctx_heap_ptr, arg4=1)
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

# Check device
c = ctypes.c_int32(0)
dll.PHI_CheckforDevices(ctypes.byref(c))
if c.value == 0:
    print('ERROR: No device found. Please reconnect the EVM USB device.', flush=True)
    sys.exit(1)
print(f'devices={c.value}', flush=True)

# Initialize
h = ctypes.c_int32(0)
dll.PHI_Initialize(0, ctypes.byref(h))
handle = h.value
print(f'handle=0x{handle:08X}', flush=True)

# Verify psm0 dir
print(f'PSM_DIR={PSM_DIR}', flush=True)
print(f'  DataMem.bin: {os.path.isfile(os.path.join(PSM_DIR, "DataMem.bin"))}', flush=True)
print(f'  CMdMem.bin:  {os.path.isfile(os.path.join(PSM_DIR, "CMdMem.bin"))}', flush=True)

# Call InitializePSM with directory path as arg3
path_buf = ctypes.create_string_buffer(PSM_DIR.encode('mbcs') + b'\x00')
ret = dll.PHI_InitializePSM(h, ctypes.c_int32(0), path_buf)
print(f'PHI_InitializePSM -> ret={ret}', flush=True)

# Read ctx from handle+0x90
ctx = ctypes.c_uint32.from_address(handle + 0x90).value
print(f'ctx @ handle+0x90 = 0x{ctx:08X}', flush=True)
if ctx:
    raw = read_bytes_safe(ctx, 64)
    null = raw.find(b'\x00')
    path_str = raw[:null].decode('mbcs', errors='replace') if null >= 0 else '?'
    print(f'ctx path = "{path_str}"', flush=True)

# Check handle+0x94 (fn_C strcpy target)
raw_94 = read_bytes_safe(handle + 0x94, 64)
null_94 = raw_94.find(b'\x00')
str_94 = raw_94[:null_94].decode('mbcs', errors='replace') if null_94 >= 0 else '?'
print(f'handle+0x94 (fn_C dest) = "{str_94}"', flush=True)

# Fix: the heap block at ctx is empty; the path was written to handle+0x94 (inline).
# Manually copy the path into the heap block so PHI_LoadPSM can find it.
if ctx:
    path_bytes = PSM_DIR.encode('mbcs') + b'\x00'
    ctypes.memmove(ctx, path_bytes, len(path_bytes))
    raw2 = read_bytes_safe(ctx, 64)
    null2 = raw2.find(b'\x00')
    print(f'ctx path after fix = "{raw2[:null2].decode("mbcs", errors="replace") if null2 >= 0 else "?"}"', flush=True)

# Also try passing handle+0x94 directly as ctx (the inline path buffer address)
ctx_inline = handle + 0x94
print(f'handle+0x94 addr = 0x{ctx_inline:08X}', flush=True)

# Try 1: heap block (now filled with path)
print(f'\nCalling PHI_LoadPSM(handle, 0, ctx=0x{ctx:08X}, 1)  [heap block]...', flush=True)
sys.stdout.flush()
ret2 = dll.PHI_LoadPSM(h, ctypes.c_int32(0), ctypes.c_int32(ctx), ctypes.c_int32(1))
print(f'PHI_LoadPSM -> ret={ret2}', flush=True)

if ret2 == 0:
    print('SUCCESS: PHI_LoadPSM returned 0!', flush=True)
    ret3 = dll.PHI_ClosePSM(h, ctypes.c_int32(0))
    print(f'PHI_ClosePSM -> ret={ret3}', flush=True)
else:
    print(f'PHI_LoadPSM [heap] returned error: 0x{ret2:08X}  — trying inline ctx...', flush=True)
    # Try 2: inline handle+0x94 address
    print(f'\nCalling PHI_LoadPSM(handle, 0, ctx=0x{ctx_inline:08X}, 1)  [inline handle+0x94]...', flush=True)
    sys.stdout.flush()
    ret2b = dll.PHI_LoadPSM(h, ctypes.c_int32(0), ctypes.c_int32(ctx_inline), ctypes.c_int32(1))
    print(f'PHI_LoadPSM [inline] -> ret={ret2b}', flush=True)
    if ret2b == 0:
        print('SUCCESS with inline ctx!', flush=True)
        dll.PHI_ClosePSM(h, ctypes.c_int32(0))
