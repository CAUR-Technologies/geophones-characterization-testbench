"""
Determine le nombre d'arguments des fonctions de tiPHIChar.dll par desassemblage.

- stdcall : la fonction se termine par `ret N` (0xC2) -> nb_args = N/4
- cdecl   : se termine par `ret` (0xC3) -> on deduit nb_args du plus grand
            offset [ebp+X] (X>=8) ou [esp+X] accede pour lire les arguments.
"""

import pefile
import capstone

DLL = r"C:\Program Files (x86)\Texas Instruments\ADS1285 EVM\Library\tiPHIChar.dll"

# Candidates haut-niveau + temoins connus pour valider la methode
TARGETS = [
    "PHI_Read",            # connu : 5 args
    "PHI_RunPSM",          # connu : 3 args (handle, psm_id, num_samples)
    "PHI_Read_PipeOut",    # connu : ~4 args
    "PHI_StartCapture",
    "PHI_StartFiniteCapture",
    "PHI_ReadARM_ADC_Data",
    "PHI_GetStatus_PipeOut",
    "PHI_ModeSet_PipeOut",
    "PHI_BufferReinitialise",
    "PHI_GetEvents",
]

pe = pefile.PE(DLL, fast_load=True)
pe.parse_data_directories([pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_EXPORT"]])
image_base = pe.OPTIONAL_HEADER.ImageBase

exports = {}
for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols:
    if exp.name:
        exports[exp.name.decode()] = exp.address  # RVA

md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
md.detail = True


def analyze(name):
    rva = exports.get(name)
    if rva is None:
        return f"{name}: EXPORT INTROUVABLE"
    off = pe.get_offset_from_rva(rva)
    code = pe.__data__[off:off + 1024]
    max_arg_off = 0          # plus grand [ebp+X] lu (args)
    saw_ebp_frame = False
    for ins in md.disasm(code, image_base + rva):
        m = ins.mnemonic
        # Detecter prologue standard (push ebp; mov ebp, esp)
        if m == "mov" and ins.op_str.startswith("ebp, esp"):
            saw_ebp_frame = True
        # Inspecter les operandes memoire base=ebp, disp>=8 (arguments)
        for op in ins.operands:
            if op.type == capstone.x86.X86_OP_MEM:
                base = op.mem.base
                disp = op.mem.disp
                if md.reg_name(base) == "ebp" and 8 <= disp <= 0x100:
                    max_arg_off = max(max_arg_off, disp)
        if m == "ret":
            if ins.op_str.strip():
                n = int(ins.op_str, 16)
                return f"{name}: stdcall ret {n} -> {n//4} args"
            else:
                # cdecl : deduire des offsets ebp
                if saw_ebp_frame and max_arg_off >= 8:
                    nargs = (max_arg_off - 8) // 4 + 1
                    return f"{name}: cdecl ret (max [ebp+{hex(max_arg_off)}]) -> >= {nargs} args"
                return f"{name}: cdecl ret (pas de frame ebp clair, args indetermine)"
    return f"{name}: pas de ret dans les 1024 premiers octets"


for t in TARGETS:
    print(analyze(t))
