"""
Rapordaki elleçleme maliyeti referanslarını kaldırır/günceller.
Veri setinde elleçleme birim maliyeti olmadığı için amaç fonksiyonundan çıkarılır.
"""
from docx import Document

doc = Document(r"c:\Users\HASAN\Desktop\hepsiburada\Teknofest_Rapor_Gelismis.docx")

# Replacement map: old text -> new text
replacements = {
    # Bölüm 2.1 - Amaç fonksiyonu açıklaması: "üç ana maliyet" -> "iki ana maliyet"
    "Amaç fonksiyonu üç ana maliyet kaleminin toplamından oluşur:":
        "Amaç fonksiyonu iki ana maliyet kaleminin toplamından oluşur:",

    # Elleçleme maliyet kalemini kaldır (tam paragraf)
    "Elleçleme ve Konsolidasyon Maliyetleri: Paketlerin Transfer Merkezlerinde (TM) indirilmesi, gruplanması ve tekrar yük-lenmesi sırasında oluşan operasyonel maliyetler.":
        "",

    # Konsolidasyon CSND motoru - elleçleme maliyet referansını güncelle
    "Bir ara TM kullanımının elleçleme maliyet artışını araç doluluk tasarrufunun karşılayıp karşılamadığı her senaryo için dinamik olarak hesaplanır; bu denge MILP modelinin amaç fonksiyonuna doğrudan dahil edilmiştir.":
        "Bir ara TM kullanımının operasyonel yükünü araç doluluk tasarrufunun karşılayıp karşılamadığı her senaryo için dinamik olarak değerlendirilir; bu denge MILP modelinin amaç fonksiyonunda araç maliyetleri üzerinden dolaylı olarak yansıtılmıştır.",
}

count = 0
for para in doc.paragraphs:
    for old_text, new_text in replacements.items():
        if old_text in para.text:
            # Handle empty replacement (delete paragraph content)
            if new_text == "":
                # Clear all runs
                for run in para.runs:
                    run.text = ""
                print(f"SILINDI: '{old_text[:60]}...'")
            else:
                # Replace text preserving formatting of first run
                full = para.text
                new_full = full.replace(old_text, new_text)
                # Rebuild runs
                if para.runs:
                    para.runs[0].text = new_full
                    for run in para.runs[1:]:
                        run.text = ""
                print(f"GUNCELLENDI: '{old_text[:60]}...'")
            count += 1

doc.save(r"c:\Users\HASAN\Desktop\hepsiburada\Teknofest_Rapor_Gelismis.docx")
print(f"\nToplam {count} değişiklik yapıldı ve dosya kaydedildi.")
