import struct

with open('d:\\sliver\\extensions\\sandbox-detect\\sandbox_detect.dll', 'rb') as f:
    data = f.read()

pe_offset = struct.unpack('<I', data[0x3c:0x40])[0]
coff = data[pe_offset+4:pe_offset+24]
machine = struct.unpack('<H', coff[0:2])[0]
print(f'Machine: 0x{machine:04x}')
num_sections = struct.unpack('<H', coff[2:4])[0]
print(f'Number of sections: {num_sections}')

opt_header_offset = pe_offset + 24
magic = struct.unpack('<H', data[opt_header_offset:opt_header_offset+2])[0]
print(f'Optional header magic: 0x{magic:04x}')

if magic == 0x20b:
    data_dir_offset = opt_header_offset + 112
else:
    data_dir_offset = opt_header_offset + 96

export_rva = struct.unpack('<I', data[data_dir_offset:data_dir_offset+4])[0]
export_size = struct.unpack('<I', data[data_dir_offset+4:data_dir_offset+8])[0]
print(f'Export directory RVA: 0x{export_rva:08x}, Size: {export_size}')

if export_rva == 0:
    print('No exports!')
else:
    section_offset = opt_header_offset + (240 if magic == 0x20b else 224)
    for i in range(num_sections):
        sec = data[section_offset:section_offset+40]
        name = sec[0:8].rstrip(b'\x00').decode('ascii', errors='replace')
        virtual_size = struct.unpack('<I', sec[8:12])[0]
        virtual_addr = struct.unpack('<I', sec[12:16])[0]
        raw_size = struct.unpack('<I', sec[16:20])[0]
        raw_offset = struct.unpack('<I', sec[20:24])[0]
        
        if virtual_addr <= export_rva < virtual_addr + max(virtual_size, raw_size):
            file_offset = export_rva - virtual_addr + raw_offset
            print(f'Export in section: {name} (file offset: 0x{file_offset:08x})')
            
            num_functions = struct.unpack('<I', data[file_offset+20:file_offset+24])[0]
            num_names = struct.unpack('<I', data[file_offset+24:file_offset+28])[0]
            print(f'Number of functions: {num_functions}')
            print(f'Number of names: {num_names}')
            
            name_ptr_rva = struct.unpack('<I', data[file_offset+32:file_offset+36])[0]
            name_ptr_offset = name_ptr_rva - virtual_addr + raw_offset
            for j in range(min(num_names, 20)):
                name_rva_entry = struct.unpack('<I', data[name_ptr_offset + j*4:name_ptr_offset + j*4 + 4])[0]
                name_offset = name_rva_entry - virtual_addr + raw_offset
                name_end = data.find(b'\x00', name_offset)
                func_name = data[name_offset:name_end].decode('ascii', errors='replace')
                print(f'  Export[{j}]: {func_name}')
            break
        section_offset += 40
