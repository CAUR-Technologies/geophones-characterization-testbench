"""
Desassemble une fonction de tiPHIChar.dll par nom d'export ou par RVA hex.
Usage: python tools/disasm_any.py <nom_ou_0xRVA> [nb_octets]
Resout les call directs vers des exports connus.
"""

import sys
import pefile
import capstone

DLL = r"C:\Program Files (x86)\Texas Instruments\ADS1285 EVM\Library\tiPHIChar.dll"

pe = pefile.PE(DLL, fast_load=True)
pe.parse_data_directories([pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_EXPORT"]])
base = pe.OPTIONAL_HEADER.ImageBase

rva_to_name = {}
name_to_rva = {}
for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols:
    if exp.name:
        rva_to_name[exp.address] = exp.name.decode()
        name_to_rva[exp.name.decode()] = exp.address

target = sys.argv[1]
nbytes = int(sys.argv[2]) if len(sys.argv) > 2 else 400

if target.startswith("0x"):
    rva = int(target, 16) - base if int(target, 16) > base else int(target, 16)
    label = target
else:
    rva = name_to_rva[target]
    label = target

off = pe.get_offset_from_rva(rva)
code = pe.__data__[off:off + nbytes]

md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
md.detail = True

print(f"=== {label} @ RVA {hex(rva)} ===\n")
for ins in md.disasm(code, base + rva):
    annot = ""
    if ins.mnemonic == "call":
        try:
            tgt = int(ins.op_str, 16)
            tgt_rva = tgt - base
            if tgt_rva in rva_to_name:
                annot = f"   ; -> {rva_to_name[tgt_rva]}"
            else:
                annot = f"   ; -> sub_{tgt_rva:x}"
        except ValueError:
            pass
    for tok, lbl in (("ebp + 8", "arg1"), ("ebp + 0xc", "arg2"),
                     ("ebp + 0x10", "arg3"), ("ebp + 0x14", "arg4"),
                     ("ebp + 0x18", "arg5")):
        if tok in ins.op_str:
            annot += f"   ; {lbl}"
    print(f"{ins.address:#010x}  {ins.mnemonic:7s} {ins.op_str}{annot}")
    if ins.mnemonic == "ret":
        break
