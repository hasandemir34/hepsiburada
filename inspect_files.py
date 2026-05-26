import os
import sys
import zipfile
import xml.etree.ElementTree as ET

# Ensure stdout is set to utf-8 for Windows
sys.stdout.reconfigure(encoding='utf-8')

class Logger:
    def __init__(self, filename):
        self.terminal = sys.stdout
        self.log = open(filename, "w", encoding="utf-8")

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)

    def flush(self):
        self.terminal.flush()
        self.log.flush()

def parse_xlsx_pure_python(file_path):
    namespaces = {
        'main': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
        'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    }
    
    with zipfile.ZipFile(file_path) as z:
        # 1. Read shared strings
        shared_strings = []
        ss_file = [f for f in z.namelist() if f.lower().endswith('sharedstrings.xml')]
        if ss_file:
            ss_content = z.read(ss_file[0])
            ss_root = ET.fromstring(ss_content)
            for si in ss_root.findall('.//main:si', namespaces):
                t_texts = [t.text for t in si.findall('.//main:t', namespaces) if t.text]
                shared_strings.append("".join(t_texts) if t_texts else "")
        
        # 2. Read sheets names from workbook
        wb_file = [f for f in z.namelist() if f.lower().endswith('workbook.xml')]
        if not wb_file:
            raise Exception("Workbook.xml not found")
        wb_content = z.read(wb_file[0])
        wb_root = ET.fromstring(wb_content)
        
        sheets = []
        for s in wb_root.findall('.//main:sheet', namespaces):
            name = s.attrib.get('name')
            sheet_id = s.attrib.get('sheetId')
            sheets.append({'name': name, 'id': sheet_id})
            
        # 3. Read worksheets
        # Let's map worksheets by listing files in xl/worksheets/
        ws_files = sorted([f for f in z.namelist() if f.startswith('xl/worksheets/sheet') and f.endswith('.xml')])
        
        results = {}
        for idx, s_info in enumerate(sheets):
            sheet_name = s_info['name']
            if idx < len(ws_files):
                file_name = ws_files[idx]
            else:
                continue
                
            try:
                ws_content = z.read(file_name)
                ws_root = ET.fromstring(ws_content)
                
                rows_data = {}
                for row_el in ws_root.findall('.//main:row', namespaces):
                    r_attr = row_el.attrib.get('r')
                    if r_attr is None:
                        continue
                    row_num = int(r_attr)
                    row_cells = []
                    for c_el in row_el.findall('.//main:c', namespaces):
                        cell_ref = c_el.attrib.get('r')
                        if cell_ref is None:
                            continue
                        col_letters = ''.join([char for char in cell_ref if char.isalpha()])
                        col_idx = 0
                        for char in col_letters:
                            col_idx = col_idx * 26 + (ord(char.upper()) - 64)
                        
                        v_el = c_el.find('main:v', namespaces)
                        val = None
                        if v_el is not None and v_el.text is not None:
                            val = v_el.text
                            cell_type = c_el.attrib.get('t')
                            if cell_type == 's':
                                idx_str = int(val)
                                if idx_str < len(shared_strings):
                                    val = shared_strings[idx_str]
                            elif cell_type == 'b':
                                val = (val == '1')
                            else:
                                try:
                                    if '.' in val:
                                        val = float(val)
                                    else:
                                        val = int(val)
                                except ValueError:
                                    pass
                        row_cells.append((col_idx, val))
                    row_cells.sort()
                    rows_data[row_num] = row_cells
                
                if not rows_data:
                    results[sheet_name] = []
                    continue
                
                max_col = max(c[0] for r in rows_data.values() for c in r) if rows_data else 0
                max_row = max(rows_data.keys()) if rows_data else 0
                
                matrix = []
                for r in range(1, max_row + 1):
                    row_cells = rows_data.get(r, [])
                    row_dict = {c[0]: c[1] for c in row_cells}
                    row_list = [row_dict.get(col, None) for col in range(1, max_col + 1)]
                    matrix.append(row_list)
                results[sheet_name] = matrix
            except Exception as e:
                print(f"Error parsing sheet {sheet_name}: {e}")
                
        return results

def inspect_excel_pure(file_path):
    print(f"\n=========================================\nDOSYA: {os.path.basename(file_path)}\n=========================================")
    try:
        data = parse_xlsx_pure_python(file_path)
        print(f"Sayfa İsimleri: {list(data.keys())}")
        for sheet_name, rows in data.items():
            print(f"  Sayfa: {sheet_name}")
            if not rows:
                print("    Sayfa boş veya okunamadı.")
                continue
            
            # Sütun sayısı ve satır sayısı
            num_rows = len(rows)
            headers = rows[0]
            num_cols = len(headers)
            print(f"    Boyut: {num_rows} satır x {num_cols} sütun")
            print(f"    Başlıklar (Sütun İsimleri): {headers}")
            
            # Örnek veriler
            print("    Örnek Satırlar:")
            limit = min(num_rows, 11) # Header dahil ilk 10 veri satırı
            for i in range(1, limit):
                if i < len(rows):
                    print(f"      Satır {i}: {rows[i]}")
                
            # Eğer dosya küçükse ve tüm satırları yazdırmak anlamlıysa
            basename = os.path.basename(file_path).lower()
            if num_rows <= 100 and any(x in basename for x in ['kapasite', 'maliyet', 'kiralik', 'kiralık', 'koordinat']):
                print("    Tüm Satırlar:")
                for i in range(1, num_rows):
                    if i < len(rows):
                        print(f"      {rows[i]}")
    except Exception as e:
        print(f"Excel okuma hatası: {e}")

def inspect_docx_pure(file_path):
    print(f"\n=========================================\nDOSYA: {os.path.basename(file_path)}\n=========================================")
    try:
        with zipfile.ZipFile(file_path) as docx_zip:
            xml_content = docx_zip.read('word/document.xml')
            root = ET.fromstring(xml_content)
            namespaces = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            paragraphs = []
            for p in root.findall('.//w:p', namespaces):
                texts = [t.text for t in p.findall('.//w:t', namespaces) if t.text]
                if texts:
                    paragraphs.append("".join(texts))
            print(f"Bulunan paragraf sayısı: {len(paragraphs)}")
            print("Belge İçeriği (Tamamı):")
            for i, p in enumerate(paragraphs):
                if len(p.strip()) > 0:
                    print(f"[{i+1}] {p}")
    except Exception as e:
        print(f"DOCX okuma hatası: {e}")

def main():
    workspace = r"c:\Users\HASAN\Desktop\hepsiburada"
    log_file = os.path.join(workspace, "inspection_output.txt")
    sys.stdout = Logger(log_file)
    sys.stderr = sys.stdout
    
    files = [
        "Araç_Kapasite_Maliyet.xlsx",
        "Desi_talep.xlsx",
        "EDA_Temiz_Veri.xlsx",
        "Kiralık_Araçlar.xlsx",
        "Koordinatlar.xlsx",
        "Teknofest_Rapor_Gelismis.docx"
    ]
    for f in files:
        full_path = os.path.join(workspace, f)
        if not os.path.exists(full_path):
            print(f"Dosya bulunamadı: {full_path}")
            continue
        if f.endswith('.xlsx'):
            inspect_excel_pure(full_path)
        elif f.endswith('.docx'):
            inspect_docx_pure(full_path)

if __name__ == "__main__":
    main()
