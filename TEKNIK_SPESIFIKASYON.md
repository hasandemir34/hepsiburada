# HEPSIJET LOJISTIK OPTIMIZASYON SISTEMI
## Teknik Spesifikasyon ve Uygulama Kılavuzu

**Sürüm:** 1.0  
**Son Güncelleme:** 26 Mayıs 2026  
**Durum:** Production Ready

---

## 1. GENEL BAKIŞ

### 1.1 Sistem Tanımı
Hepsijet, Hepsiburada lojistik operasyonları için **matematiksel optimizasyon tabanlı araç planlama sistemi**dir. Sistem, günlük yük taleplerini, mevcut araç envanterini ve maliyet parametrelerini kullanarak, en düşük maliyetli taşıma planı oluşturur.

### 1.2 Temel Özellikler
- **Multi-mod Optimizasyon**: Kiralik + Spot araçlar
- **Konsolidasyon Desteği**: Opsiyonel ara transfer merkezleri
- **Global Optimum Hesaplama**: MILP (Integer Linear Programming)
- **Greedy Alternatifi**: Hızlı çözüm için yaklaşık mod
- **Karayolu Mesafe Tahmini**: Koordinat tabanlı Haversine formülü

---

## 2. GİRİŞ VERİLERİ (INPUT)

### 2.1 Desi Talep Dosyası (Desi_talep.xlsx)

**Yapı:**
```
Sütun A: Tarih (Excel tarih formatı)
Sütun B: Çıkış Transfer Merkezi (metin, örn: "Kocaeli")
Sütun C: Varış Transfer Merkezi (metin, örn: "İstanbul")
Sütun D: Toplam Desi (ondalık sayı)
```

**Örnek:**
```
Tarih          | Çıkış TM  | Varış TM  | Toplam Desi
2026-05-10     | Kocaeli   | İstanbul  | 3199.68
2026-05-10     | Kocaeli   | Manisa    | 3366.48
2026-05-10     | Manisa    | Tekirdağ  | 72.6
```

**Gereksinimler:**
- En az 1 satır başlık
- Tarih: Excel serial format (1900 tabanlı)
- Transfer merkez adları: Koordinatlar.xlsx'te bulunmalı
- Desi: Pozitif ondalık sayı

### 2.2 Araç Kapasite & Maliyet Dosyası (Araç_Kapasite_Maliyet.xlsx)

**Yapı:**
```
Sütun A: Araç Adı
Sütun B: Kapasite (desi)
Sütun C: Kiralık Araç Günlük Kira (TL)
Sütun D: Kiralık Araç Kilometre Başına Maliyet (TL)
Sütun E: Spot Araç Sabit Günlük Maliyet (TL)
Sütun F: Spot Kilometre Başına Maliyet (TL)
```

**Örnek:**
```
Araç Adı | Kapasite | Kiralik Gün | Kiralik /km | Spot Gün | Spot /km
Tır      | 22400    | 4500        | 15          | 2000     | 50
Kamyon   | 12000    | 3000        | 12          | 1500     | 40
Kamyonet | 5600     | 1500        | 8           | 1000     | 30
```

**Gereksinimler:**
- En az 3 araç tipi
- Kapasite sırasından bağımsız (sistem otomatik sıralar)
- Maliyetler: Pozitif ondalık sayı
- Kiralik ve Spot değerleri her ikisi de verilmeli

### 2.3 Kiralık Araçlar Envanteri (Kiralık_Araçlar.xlsx)

**Yapı:**
```
Sütun A: Çıkış Transfer Merkezi
Sütun B: Varış Transfer Merkezi
Sütun C: Araç Türü
Sütun D: Araç sayısı
```

**Örnek:**
```
Çıkış TM  | Varış TM  | Araç Türü | Araç sayısı
Kocaeli   | Balıkesir | Kamyon    | 1
Kocaeli   | İstanbul  | Tır       | 2
Manisa    | Yalova    | Kamyonet  | 1
```

**Gereksinimler:**
- Her satır = 1 (çıkış, varış, araç tipi) kombinasyonu
- Araç türü: Araç_Kapasite_Maliyet.xlsx'te bulunmalı
- Araç sayısı: Pozitif tam sayı

### 2.4 Transfer Merkezi Koordinatları (Koordinatlar.xlsx)

**Yapı:**
```
Sütun A: Transfer Merkezi
Sütun B: Enlem (Latitude)
Sütun C: Boylam (Longitude)
```

**Örnek:**
```
Transfer Merkezi | Enlem    | Boylam
İstanbul         | 41.0082  | 28.9784
Kocaeli          | 40.7667  | 29.9333
Ankara           | 39.9334  | 32.8597
```

**Gereksinimler:**
- WGS84 koordinat sistemi (standart GPS)
- Ondalık derece formatı (DMS değil)
- Enlem: -90 ile +90 arasında
- Boylam: -180 ile +180 arasında

---

## 3. ÇIKTI VERİLERİ (OUTPUT)

### 3.1 Çıkış CSV Dosyaları

Tüm çıkış dosyaları aşağıdaki sütunları içerir:

```
tarih: Planlanan tarih (YYYY-MM-DD)
orijinal_cikis_tm: Talep kaynağı
orijinal_varis_tm: Talep hedefi
aktarma_tm: Konsolidasyon merkezi (boş ise doğrudan)
bacak_no: Hattın sırası (1=ilk, 2=ikinci vb.)
cikis_tm: Fiziksel hattın çıkış noktası
varis_tm: Fiziksel hattın varış noktası
arac_turu: Araç tipi (Tır/Kamyon/Kamyonet)
kaynak: Araç kaynağı (kiralik/spot)
arac_sayisi: Kaç adet araç
yuklenen_desi: Fiilen yüklü desi
kapasite_desi: Toplam araç kapasitesi
doluluk_orani: yuklenen_desi / kapasite_desi
mesafe_km: Hat mesafesi (tahmini)
maliyet_tl: Toplam maliyet (TL)
```

### 3.2 Senaryo Dosyaları

#### A. dogrudan_plan.csv
- **Tanım**: Tüm taleplerin doğrudan taşınması
- **Algoritma**: Greedy, kiralik önceliği
- **Konsolidasyon**: Hayır
- **Hız**: Çok hızlı
- **Kullanım**: Temel karşılaştırma, baseline

#### B. milp_optimizasyon_plani.csv
- **Tanım**: Global optimum araç atanması
- **Algoritma**: MILP (Mixed Integer Linear Programming)
- **Konsolidasyon**: Evet, optimal
- **Hız**: 5-30 saniye
- **Kullanım**: Stratejik planlama, en düşük maliyet

#### C. yuk_akisi_plani.csv
- **Tanım**: Konsolidasyon fırsatlarını gösteren yük akışı
- **Algoritma**: Greedy konsolidasyon
- **Konsolidasyon**: Evet, dinamik
- **Hız**: Hızlı (2-5 saniye)
- **Kullanım**: Operasyonel planlama, dengeli çözüm

#### D. milp_yuk_akisi_plani.csv
- **Tanım**: MILP'nin yük akış kararları
- **Algoritma**: MILP'den flow decisions
- **Konsolidasyon**: Evet, optimal akış
- **Hız**: 5-30 saniye
- **Kullanım**: Detaylı analiz

---

## 4. ALGORİTMA DETAYLARI

### 4.1 Matematiksel Model (MILP)

**Karar Değişkenleri:**
```
x[i,p] ∈ {0,1}  : Talep i, yol p seçilsin mi?
y[l,v,s] ∈ ℤ≥0  : Leg l'de, araç v, kaynak s'den kaç tane?
```

Burada:
- i = talep indeksi
- p = yol (path) indeksi
- l = fiziksel hat (leg)
- v = araç tipi
- s = kaynak (kiralik/spot)

**Kısıtlar:**
```
1) Tek Yol Seçimi:
   ∑_p x[i,p] = 1, ∀i ∈ D

2) Hat Kapasitesi:
   ∑_i demand[i] × ∑_p (l ∈ path[p]) × x[i,p] ≤ ∑_v,s capacity[v] × y[l,v,s]

3) Kiralik Envanteri:
   y[l,v,"kiralik"] ≤ rental_inventory[l,v], ∀l,v

4) Negatif Olmayan Koşul:
   y[l,v,s] ≥ 0, ∀l,v,s
```

**Amaç Fonksiyonu:**
```
Minimize:
  ∑_l,v,s cost[v,s,l] × y[l,v,s]
  
Burada cost[v,s,l] = daily_cost + km_cost × distance[l]
```

### 4.2 Greedy Konsolidasyon Algoritması

```
ADIM 1: Tüm talepleri başlangıçta doğrudan al
        flow_decisions = [(origin, destination) for each demand]

ADIM 2: Döngü:
        improved = True
        while improved:
            improved = False
            for her talep i in flow_decisions:
                for her aktarma merkezi c:
                    if c not in (origin, destination):
                        yeni_yol = (origin, c, destination)
                        yeni_maliyet = total_cost(modified_flows)
                        if yeni_maliyet < eski_maliyet:
                            flow_decisions[i] = yeni_yol
                            improved = True
                            break  # En iyi değişikliği uyguladıktan sonra çık
```

### 4.3 Spot Araç Seçimi (Kombinasyon Arama)

```
PROBLEM: Kalan 'desi' için minimum maliyetli araç kombinasyonu

ÇÖZÜM: Rekursif ekshaustif arama

def search(araç_indeksi, kullanılan_desi, toplam_maliyet):
    if araç_indeksi == son:
        if toplam_kapasite ≥ talep_desi:
            if toplam_maliyet < en_iyi_maliyet:
                en_iyi = (kombinasyon, maliyet)
        return
    
    for k in range(max_adet):
        search(araç_indeksi+1, ...)

Fitness Sırası:
1. Minimum maliyet
2. Minimum fazla kapasite (waste)
3. Minimum araç sayısı
```

### 4.4 Mesafe Tahmini

**Haversine Formülü:**
```
a = sin²(Δφ/2) + cos(φ1)×cos(φ2)×sin²(Δλ/2)
c = 2×atan2(√a, √(1−a))
d = R×c  (R = 6371 km)

Karayolu Tahmini:
road_distance = d × 1.25  (ortalama katsayı)
```

---

## 5. KURULUM VE ÇALIŞTURMA

### 5.1 Ön Koşullar
```
Python: 3.7+
OS: Windows 10+, Linux, macOS
RAM: 512 MB minimum
Disk: 100 MB
```

### 5.2 Paket Kurulumu

```bash
# Gerekli paketler
pip install -r requirements.txt

# requirements.txt içeriği:
# pulp==3.3.2
```

### 5.3 Kullanım

```bash
# Doğrudan plan
python logistics_optimizer.py \
    --mode direct \
    --date 2026-05-10

# Konsolidasyon planı
python logistics_optimizer.py \
    --mode greedy \
    --consolidation true \
    --date 2026-05-10

# MILP Global Optimum
python logistics_optimizer.py \
    --mode milp \
    --consolidation true \
    --date 2026-05-10

# Tüm senaryo
python logistics_optimizer.py \
    --all-scenarios \
    --date 2026-05-10
```

### 5.4 Parametre Açıklamaları

| Parametre | Değer | Açıklama |
|-----------|-------|---------|
| --mode | direct/greedy/milp | Algoritma seçimi |
| --consolidation | true/false | Konsolidasyon açık/kapalı |
| --date | YYYY-MM-DD | Planlama tarihi |
| --road-factor | 1.0-1.5 | Karayolu mesafe katsayısı |
| --all-scenarios | - | Tüm 3 senaryo çalıştır |
| --output-dir | path | Çıkış dizini |

---

## 6. PERFORMANS VE SCALABILITY

### 6.1 Zaman Karmaşıklığı

| Yöntem | Zaman Karmaşıklığı | Pratik Süresi |
|--------|-------------------|--------------|
| Doğrudan | O(n) | < 0.1 saniye |
| Greedy Konsolidasyon | O(n × m × c) | 0.5-2 saniye |
| MILP | Üstel (NP-zor) | 5-30 saniye* |

*n = talep sayısı, m = aktarma merkezi, c = araç tipi

### 6.2 Makine Gereksinimleri (Talep Sayısına Göre)

| Talep Sayısı | RAM | CPU | Sürü |
|-------------|-----|-----|------|
| 10-20 | 512 MB | Dual Core | 1-5 sn |
| 50-100 | 1 GB | Quad Core | 5-15 sn |
| 200-500 | 2 GB | Quad Core | 15-60 sn |
| 1000+ | 4 GB | Octa Core | 60+ sn |

### 6.3 Optimization Tavsiyeleri

**Için 100+ talep varsa:**
1. Talepleri zaman pencereleri ile gruplendirme
2. Greedy yöntemi tercih etme
3. Paralel işleme (multiprocessing)
4. Küme analizi (clustering) ile alt-problemlere bölme

---

## 7. HATA YÖNETİMİ

### 7.1 Ortak Hatalar ve Çözümleri

| Hata | Neden | Çözüm |
|------|-------|------|
| "Transfer Merkezi bulunamadı" | Koordinat dosyasında eksik | Koordinatlar.xlsx'e merkez ekle |
| "Araç Türü tanınmadı" | Yanlış ad yazımı | Adları tam eşleştir (Unicode) |
| "Talep karşılanamadı" | Kapasite yetersiz | Kiralik envanteri artır |
| MILP timeout | Çok fazla talep | Greedy moduna geç |
| Division by zero | Kapasite = 0 | Araç Kapasite_Maliyet.xlsx kontrol et |

### 7.2 Veri Doğrulama

```python
# Çalıştırılması önerilen
python inspect_files.py  # Tüm giriş dosyalarını kontrol et
```

---

## 8. İŞLETME TAVSIYALARI

### 8.1 Günlük Rutin

```
Pazartesi-Cuma 08:00:
1. Talep verilerini güncelle (Desi_talep.xlsx)
2. Kiralik envanter kontrol et (Kiralık_Araçlar.xlsx)
3. Sistem çalıştır:
   python logistics_optimizer.py --all-scenarios
4. Çıkış CSV dosyalarını kontrol et
5. Operasyon ekibine dağıt

Aksam 17:00:
6. Gerçek maliyetleri model tahminleriyle karşılaştır
7. Sapmaları analiz et
8. Raporlama
```

### 8.2 Haftalık Rutin

- Her Pazartesi: Önceki hafta performans analiz
- Her Cuma: Gelecek hafta tahmin ve plan hazırla
- Her 2. hafta: Maliyet parametreleri güncelle

### 8.3 Aylık Rutin

- Koordinat doğrulama (hata > 5 km ise güncelle)
- Yeni araç tipi eklemesi
- KPI raporlama
- Sistem optimizasyon

---

## 9. GÜVENLİK VE VERI KORUMASI

### 9.1 Giriş Dosyaları
- Hassas maliyet verileri içerir
- Erişim: Sadece İç Kullanım
- Yedekleme: Günlük
- Şifreleme: İsteğe bağlı (Windows EFS)

### 9.2 Çıkış Dosyaları
- Operasyonel planlar (operasyon ekibine dağıtılır)
- Hassas sayılmaz (genel maliyetler)
- Ama müşteri bilgileri (TM adları) içeriyor
- Saklı: Şirket genelinde hassas

### 9.3 Kod Deposu
- GitHub: Açık (PII/maliyet kodu çıkarılmış)
- Access: Admin'ler sadece

---

## 10. TROUBLESHOOTING

### 10.1 Sistem Yavaş Çalışıyorsa

1. Talep sayısını kontrol et
2. Greedy moduna geç
3. Konsolidasyon kapalı yap
4. RAM artır
5. MILP timeout süresini azalt

### 10.2 Anormal Sonuçlar

1. Girdi dosyalarını kontrol et (inspect_files.py)
2. Koordinat hataları kontrol et
3. Maliyet parametreleri doğru mu?
4. Kiralik envanteri eksik mi?
5. Tarih formatı doğru mu?

### 10.3 Sistem Kilitlenmesi

```bash
# Süren MILP işini durdur (Windows)
taskkill /F /IM python.exe

# Veya Ctrl+C (seri çalışmada)
```

---

## 11. REFERANSLAR

- **MILP Teorisi**: Boyd, S., Vandenberghe, L. (2004). Convex Optimization.
- **Araç Rotalama**: Toth, P., Vigo, D. (2002). The Vehicle Routing Problem.
- **Haversine Formülü**: https://en.wikipedia.org/wiki/Haversine_formula
- **PuLP Dökümantasyonu**: https://coin-or.github.io/pulp/

---

**Versiyon Tarihi:**
- v1.0: 26 Mayıs 2026 - İlk yayın

**Bakım Sorumlusu:** Yazılım Geliştirme Ekibi
**Son Güncelleme:** 26 Mayıs 2026

