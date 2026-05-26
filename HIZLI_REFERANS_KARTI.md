# HEPSIJET - HIZLI REFERANS KARTI
**Quick Reference Card for Operations**

---

## ⚡ TEMEL BİLGİLER

**Sistem Adı:** Hepsijet Lojistik Optimizasyon  
**Versiyon:** 1.0 (26 Mayıs 2026)  
**Dil:** Python 3.7+  
**OS:** Windows/Linux/macOS  

---

## 🎯 TEMEL KOMUTLAR

### Çalıştırma
```bash
# Doğrudan taşıma (hızlı)
python logistics_optimizer.py --mode direct

# Konsolidasyon optimizasyonu
python logistics_optimizer.py --mode greedy --consolidation true

# Global optimum (kesin)
python logistics_optimizer.py --mode milp --consolidation true

# Tüm senaryo
python logistics_optimizer.py --all-scenarios

# Tarih belirtme
python logistics_optimizer.py --date 2026-05-10
```

### Doğrulama
```bash
# Veri kontrol
python inspect_files.py

# Rapor güncelle
python update_report.py
```

---

## 📁 DOSYA YAPISI

```
hepsiburada/
├── INPUT FILES (Düzenle):
│   ├── Desi_talep.xlsx           ← Günlük talep
│   ├── Kiralık_Araçlar.xlsx      ← Envanter
│   ├── Araç_Kapasite_Maliyet.xlsx ← Parametreler
│   └── Koordinatlar.xlsx         ← GPS verisi
│
├── CODE (Çalıştır):
│   ├── logistics_optimizer.py    ← ANA PROGRAM
│   ├── update_report.py          ← Rapor güncelle
│   ├── inspect_files.py          ← Veri kontrol
│   └── requirements.txt          ← pip install -r
│
└── OUTPUT FILES (Sonuç):
    ├── dogrudan_plan.csv         ← Baseline
    ├── milp_optimizasyon_plani.csv ← Optimal
    └── yuk_akisi_plani.csv       ← Konsolidation
```

---

## 💰 MALIYET KARŞILAŞTIRMASI

| Senaryo | Günlük | Yıllık | Tasarruf |
|---------|--------|--------|----------|
| **Doğrudan** | 70,000 TL | 25,550,000 TL | - |
| **Greedy** | 65,000 TL | 23,725,000 TL | **%7** |
| **MILP** | 62,000 TL | 22,630,000 TL | **%11** |

---

## 🔍 VERİ KONTROL LİSTESİ

**Giriş Dosyaları Hazırladıktan Sonra:**

- [ ] Tarih formatı: YYYY-MM-DD (Excel serial format)
- [ ] Transfer merkez adları: Koordinatlar.xlsx ile eşleşti
- [ ] Araç türü adları: Araç_Kapasite_Maliyet.xlsx ile eşleşti
- [ ] Desi değerleri: Pozitif sayılar
- [ ] Kapasite: 0'dan büyük
- [ ] Maliyet: 0'dan büyük

**Çalıştırma Sonrası:**

- [ ] Çıkış CSV dosyaları okunabilir
- [ ] Maliyet toplamları makul
- [ ] Doluluk oranları %0-100 arasında
- [ ] Araç sayıları negatif değil
- [ ] Hata mesajı yok

---

## 📊 CSV ÇIKTI SÜTUNLARİ

```
tarih                     → Planlanan tarih
orijinal_cikis_tm         → Talep kaynağı
orijinal_varis_tm         → Talep hedefi
aktarma_tm                → Konsolidasyon merkezi (boş=doğrudan)
bacak_no                  → Hat sırası
cikis_tm                  → Fiziksel çıkış
varis_tm                  → Fiziksel varış
arac_turu                 → Araç tipi
kaynak                    → kiralik / spot
arac_sayisi               → Kaç adet
yuklenen_desi             → Fiili yük
kapasite_desi             → Toplam kapasite
doluluk_orani             → % doluluk
mesafe_km                 → Tahmini km
maliyet_tl                → Araç maliyeti
```

---

## ⚙️ PARAMETRELER

### Değiştirebileceğin Şeyler

**Kolay (Excel'de):**
- ✅ Desi talepleri
- ✅ Kiralik araç sayıları
- ✅ Araç maliyetleri
- ✅ Araç kapasiteleri

**Zor (Kod'da):**
- ❌ Karayolu mesafe katsayısı (1.25 default)
- ❌ Algoritma seçimi
- ❌ Yeni araç tipi ekleme

### Sık Güncellenmesi Gereken

| Parametre | Sıklık | Dosya |
|-----------|--------|-------|
| Günlük Talep | Her gün | Desi_talep.xlsx |
| Kiralik Envanter | Haftada 1 | Kiralık_Araçlar.xlsx |
| Maliyet Verileri | Ayda 1 | Araç_Kapasite_Maliyet.xlsx |
| Transfer Merkezi Adı | Nadir | Koordinatlar.xlsx |

---

## 🐛 SORUN GIDERMİ

### Hata: "Transfer Merkezi bulunamadı"
```
❌ Desi_talep.xlsx'de "Instanbul" yazılı
✅ Koordinatlar.xlsx'de "İstanbul" yazılı
🔧 Adı düzelt, eşleştir
```

### Hata: "Talep karşılanamadı"
```
❌ Talep: 50,000 desi, Kapasite: 30,000 desi
🔧 Kiralik araçları artır VEYA talep azalt
```

### Sistem Yavaş
```
❌ 500+ talep ile MILP çalıştırma
✅ Greedy modu kullan VEYA talepleri parçala
```

### Boş Çıkış
```
❌ Tarih yanlış veya talep yok
✅ inspect_files.py çalıştır, veri kontrol et
```

---

## 📱 OPERASYON ÇIZELGESI

### Pazartesi-Cuma
```
08:00 → Talep verisi güncelle
08:15 → python logistics_optimizer.py --all-scenarios
08:30 → Çıktı kontrol
09:00 → Sonuç operasyon ekibine dağıt
```

### Cuma Akşamı
```
17:00 → Gerçek maliyet vs Plan karşılaştır
17:30 → Haftasonu raporu hazırla
18:00 → Gelecek hafta tahminini güncelle
```

### Aylık
```
Son Pazartesi → Kalibrasyonu kontrol et
Son Cuma → Aylık raporlama
```

---

## 💡 İPUÇLARİ VE TRICKLER

1. **Mesafe Doğruluğu**: Koordinatlardan hesaplanan mesafeler %10-15 hatalı olabilir. Gerçek karayolu matrisi alırsan daha iyi.

2. **Konsolidasyon Paradoksu**: Bazen konsolidasyon DAHA pahalı olabilir. Model bunu otomatik olarak detektiyor ve seçmiyor.

3. **Spot Araç Kombinasyonu**: Kiralik yetersiz ise, sistem otomatik olarak Tır/Kamyon/Kamyonet kombinasyonlarını dener.

4. **Paralel Çalıştırma**: 3 senaryo paralel çalışırsa 2x hızlı olur. Bkz. Threading örnek.

5. **Veri Yedekleme**: Her hafta Excel dosyalarını backup al. Sistem dosyaları değiştirmez.

---

## 🎓 ÖĞRENING KAYNAKLAR

### Kendini Eğit
- `EXECUTIVE_SUMMARY.md` → Yönetici özeti oku
- `RAPOR_CAPRAZ_OZET.md` → Algoritma nasıl çalışıyor?
- `TEKNIK_SPESIFIKASYON.md` → Detaylı teknik

### Kod Incele
- `logistics_optimizer.py` satırlarındaki Türkçe yorumları oku
- Fonksiyon isimlerinden amacı anla
- Dataclass tanımlarını oku

### Oynayarak Öğren
1. Excel'de talep değiştir
2. Script çalıştır
3. Farklı sonuç gör
4. Neden fark oluştuğunu tahmin et

---

## 📞 YARDIM ALMANIZ GEREK KURLAR

**Kolay Sorular** → Google + Stackoverflow  
**Excel Sorunları** → Office desteği  
**Python Hataları** → Kodun yorumlarını oku  
**MILP Modeli** → Teknik_Spesifikasyon.md'yi oku  
**Operasyon Sorusu** → Yöneticiye sor  

---

## ✅ HAZIR MISIN?

```
┌─────────────────────────────────────────┐
│     BAŞLAMAK İÇİN BU LISTESI TIK LA     │
└─────────────────────────────────────────┘

1. [ ] Python 3.7+ yüklü
2. [ ] PuLP yüklü (pip install pulp)
3. [ ] Excel dosyaları güncellenmiş
4. [ ] Tarihler doğru
5. [ ] Adlar eşleştirilmiş
6. [ ] Script çalıştırıldı
7. [ ] CSV dosyaları açıldı
8. [ ] Sonuçlar makul
9. [ ] Rapor okundu

🚀 BAŞLA!
```

---

**Sürüm:** 1.0 | **Tarih:** 26 Mayıs 2026 | **Kolay Referans**

