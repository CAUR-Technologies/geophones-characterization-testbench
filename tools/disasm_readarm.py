"""
Desassemblage detaille de PHI_ReadARM_ADC_Data pour comprendre :
  - le role de chaque argument ([ebp+8], [ebp+0xC], [ebp+0x10])
  - les fonctions appelees en interne (notamment si GetEvents y est appele)
"""

import pefile
import capstone

DLL = r"C:\Program Files (x86)\Texas Instruments\ADS1285 EVM\Library\tiPHIChar.dll"
FUNC = "PHI_ReadARM_ADC_Data"

pe = pefile.PE(DLL, fast_load=True)
pe.parse_data_directories([pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_EXPORT"]])
base = pe.OPTIONAL_HEADER.ImageBase

# Map RVA -> nom d'export (pour resoudre les call internes)
rva_to_name = {}
for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols:
    if exp.name:
        rva_to_name[exp.address] = exp.name.decode()

func_rva = next(e.address for e in pe.DIRECTORY_ENTRY_EXPORT.symbols
                if e.name and e.name.decode() == FUNC)
off = pe.get_offset_from_rva(func_rva)
code = pe.__data__[off:off + 600]

md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
md.detail = True

print(f"=== {FUNC} @ RVA {hex(func_rva)} ===\n")
for ins in md.disasm(code, base + func_rva):
    annot = ""
    if ins.mnemonic == "call":
        # tenter de resoudre la cible si c'est un call direct relatif
        try:
            tgt = int(ins.op_str, 16)
            tgt_rva = tgt - base
            if tgt_rva in rva_to_name:
                annot = f"   ; -> {rva_to_name[tgt_rva]}"
        except ValueError:
            pass
    # annoter les acces aux arguments
    if "ebp + 8" in ins.op_str:
        annot += "   ; arg1"
    elif "ebp + 0xc" in ins.op_str:
        annot += "   ; arg2"
    elif "ebp + 0x10" in ins.op_str:
        annot += "   ; arg3"
    print(f"{ins.address:#010x}  {ins.mnemonic:7s} {ins.op_str}{annot}")
    if ins.mnemonic == "ret":
        break
