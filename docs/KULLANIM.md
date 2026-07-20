# cryptobot_v4 — Kullanım Kılavuzu

Bu belge botun kurulumu, konfigürasyonu ve üç çalışma modunun (kağıt / geriye
dönük test / canlı) ayrıntılı kullanımını anlatır. Strateji kuralları sabittir ve
değiştirilmez; bu kılavuz o kuralları **nasıl çalıştıracağını** ve
**konfigüre edeceğini** gösterir.

> **Uyarı:** Bu bir gerçek para ile işlem yapabilen araçtır. Canlı moda geçmeden
> önce mutlaka `--testnet` üzerinde dene ve küçük sermaye ile başla. Kripto
> alım-satımı risklidir; sorumluluk tamamen kullanıcıya aittir.

---

## İçindekiler

1. [Genel bakış](#1-genel-bakış)
2. [Kurulum](#2-kurulum)
3. [Konfigürasyon dosyası](#3-konfigürasyon-dosyası)
4. [Çalıştırma modları](#4-çalıştırma-modları)
5. [İzleme (monitoring)](#5-izleme-monitoring)
6. [Strateji kuralları (özet)](#6-strateji-kuralları-özet)
7. [Sermaye ve slot mantığı](#7-sermaye-ve-slot-mantığı)
8. [Parametre referansı](#8-parametre-referansı)
9. [Önemli notlar ve uyarılar](#9-önemli-notlar-ve-uyarılar)
10. [Sık sorulan sorular](#10-sık-sorulan-sorular)

---

## 1. Genel bakış

Bot, her coin için bağımsız parametrelerle çalışan deterministik bir RSI /
RSI-VWMA / ADX / ADR stratejisidir. Üç modu vardır:

| Mod | Ne yapar | Gerçek emir? | API anahtarı? |
|-----|----------|:---:|:---:|
| **Kağıt (paper)** | Gerçek (salt-okunur) piyasa verisiyle çalışır, dolumları simüle eder | Hayır | Gerekmez |
| **Geriye dönük test (backtest)** | Geçmiş mumları aynı motordan geçirir | Hayır | Gerekmez |
| **Canlı (live)** | Binance'te gerçek emir gönderir | **Evet** | Gerekir |

Her üç mod da **aynı strateji motorunu** kullanır — yani kağıt modunda ya da
backtest'te gördüğün davranış, canlıda da birebir aynıdır.

---

## 2. Kurulum

Gereksinim: **Python 3.10+**. Harici bağımlılık yoktur (yalnızca standart
kütüphane); test için `pytest` gerekir.

```bash
git clone https://github.com/aricansoft2022/cryptobot_v4
cd cryptobot_v4

# Seçenek A — paket olarak kur (önerilir): sonrasında "python -m cryptobot" çalışır
pip install -e .

# Seçenek B — kurmadan çalıştır
export PYTHONPATH=src
python -m cryptobot --help
```

Testleri çalıştırmak (isteğe bağlı ama önerilir):

```bash
pip install pytest
pytest            # tüm testler geçmeli
```

---

## 3. Konfigürasyon dosyası

Bot tek bir JSON dosyasıyla yapılandırılır (`--config` ile verilir). İki bölümü
vardır: `coins` (coin başına strateji ayarları) ve global ayarlar (`cost_model`,
`candle_buffer`).

### Örnek

`examples/config.example.json`:

```json
{
  "coins": {
    "BTCUSDT": {
      "rsi_oversold": 30,
      "rsi_overbought": 70,
      "adx_low": 20,
      "adx_high": 50,
      "min_net_profit_pct": "0.5",
      "rsi_period": 14,
      "rsi_ma_period": 14,
      "adx_period": 14,
      "adr_period": 14,
      "capital_limit_usdt": "1000",
      "slot_count": 3
    },
    "ETHUSDT": {
      "rsi_oversold": 28,
      "rsi_overbought": 72,
      "adx_low": 18,
      "adx_high": 55,
      "min_net_profit_pct": "0.6",
      "rsi_period": 14,
      "rsi_ma_period": 20,
      "adx_period": 14,
      "adr_period": 14,
      "capital_pct": 30,
      "slot_count": 2
    }
  },
  "cost_model": {
    "exit_fee_rate": "0.001",
    "safety_buffer_frac": "0.0005"
  },
  "candle_buffer": 200
}
```

### Coin ekleme / çıkarma

`coins` altındaki her sembol bağımsızdır. **Coin eklemek** için yeni bir sembol
girdisi ekle; **çıkarmak** için sil. Değişiklikten sonra **botu yeniden başlat**
(çalışırken canlı ekle/çıkar özelliği yoktur).

### Sermaye: iki seçenekten biri

Her coin için sermayeyi **iki yoldan biriyle** belirtirsin — ikisini birden değil:

- **`capital_limit_usdt`** — sabit mutlak üst sınır (örn. `"1000"` = en fazla
  1000 USDT).
- **`capital_pct`** — toplam USDT bakiyenin yüzdesi (örn. `30` = %30). Bu değer
  **başlangıçta bir kez**, **toplam USDT bakiyene** (serbest + kilitli) göre
  mutlak bir USDT limitine çevrilir ve oturum boyunca sabit kalır. Yeniden
  hesaplamak için botu yeniden başlat.
  - Canlı modda: gerçek Binance USDT bakiyen okunur.
  - Kağıt / backtest modunda: `--quote-balance` değeri kullanılır.

İkisini birden yazarsan, hiçbirini yazmazsan veya `capital_pct` 0–100 dışındaysa
bot açılışta hata verir.

---

## 4. Çalıştırma modları

### 4.1. Kağıt modu (paper)

Gerçek Binance piyasa verisini **salt-okunur** kullanır; hiçbir emir göndermez,
dolumları en iyi alış/satış fiyatından simüle eder. API anahtarı gerekmez.

```bash
python -m cryptobot --config examples/config.example.json
```

Faydalı bayraklarla (tek satır — kopyala-yapıştır güvenli):

```bash
python -m cryptobot --config config.json --quote-balance 5000 --ticks 100 --interval 60 --status-port 8787
```

- `--quote-balance 5000` — başlangıç kağıt bakiyesi (`capital_pct` tabanı da bu)
- `--ticks 100` — 100 tur sonra dur (`0` = sonsuz, Ctrl+C ile durdur)
- `--interval 60` — turlar arası saniye (1 dakikalık mumlar için `60`)
- `--status-port 8787` — JSON durum sayfası (bkz. İzleme)

### 4.2. Geriye dönük test (backtest)

Bir JSON mum (klines) dosyasını aynı motordan geçirir ve coin başına bir rapor
(işlem sayısı, net PnL, kazanma oranı, son bakiye) yazar.

```bash
python -m cryptobot --config config.json --backtest klines.json --quote-per-order 100 --quote-balance 1000
```

- `--backtest klines.json` — backtest edilecek mum dosyası
- `--quote-per-order 100` — işlem başına sabit USDT (opsiyonel; yoksa `capital / slot_count`)
- `--quote-balance 1000` — başlangıç bakiyesi (`capital_pct` tabanı)

> **Not:** Komutları **tek satır** yaz. Çok satırlı `\` kullanacaksan, `\`
> karakterinden **sonra boşluk veya yorum bırakma** — zsh/bash satır
> birleştirmeyi bozar ("command not found" / "unrecognized arguments").

**Mum dosyası biçimi** — `{ "SEMBOL": [ <binance kline dizisi>, ... ] }`. Birden
çok sembol **tek dosyada** olabilir; o zaman tek koşuda hepsi test edilir.

**Önerilen — dahili indirici (çok sembollü + sayfalamalı).** Binance tek istekte
en fazla **1000 mum** verir; daha uzun geçmiş için sayfalama (pagination) gerekir.
Dahili araç bunu yapıp tek dosyaya yazar:

```bash
python -m cryptobot.fetch BTCUSDT,ETHUSDT --total 5000 --output klines.json
python -m cryptobot --config config.json --backtest klines.json --quote-per-order 100
```

`--total` sembol başına mum sayısıdır (5000 ≈ 3,5 günlük 1m veri). Her iki sembol
de aynı dosyada olduğu için tek koşu ikisini de backtest eder.

**Hızlı yol (tek istek, en fazla 1000 mum)** — küçük bir deneme için:

```bash
curl -s "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&limit=1000" > btc.json
python -c "import json;print(json.dumps({'BTCUSDT': json.load(open('btc.json'))}))" > klines.json
python -m cryptobot --config config.json --backtest klines.json --quote-per-order 100
```

> **Uyarı:** Binance'te `limit` en fazla **1000**'dir; `limit=100000000` gibi büyük
> değerler işe yaramaz (yine ~1000 mum gelir). Uzun geçmiş için yukarıdaki
> `python -m cryptobot.fetch` aracını kullan.

> Backtest, göstergelerin tam oturması için varsayılan olarak **tüm geçmişi**
> ısınma (warmup) verisi olarak kullanır. Canlıda buna denk davranış için
> `candle_buffer` değerini yüksek tut (bkz. Önemli notlar).

### 4.3. Canlı mod (live)

Binance'te **gerçek emir** gönderir. Güvenlik katmanlıdır:

- API anahtarları yalnızca ortam değişkeninden okunur (kodda saklanmaz, loglanmaz):
  `BINANCE_API_KEY`, `BINANCE_API_SECRET`.
- Anahtarlar yoksa `--live` çalışmaz.
- **Gerçek para** için açıkça `--yes-trade-real-money` gerekir; aksi halde
  `--testnet` (sahte para, Binance testnet) kullanılır.

**Anahtarları `.env` dosyasından okutmak (önerilir).** Depodaki `.env.example`'ı
`.env` olarak kopyala ve doldur. `.env` `.gitignore`'dadır — asla commit edilmez.
Bot her çalıştığında `.env`'i otomatik yükler (kabukta zaten tanımlı bir değişken
varsa o öncelikli olur).

```bash
cp .env.example .env
# .env içeriği:
#   BINANCE_API_KEY=xxxx
#   BINANCE_API_SECRET=yyyy

# 1) ÖNCE testnet (sahte para) — testnet anahtarları https://testnet.binance.vision
python -m cryptobot --config config.json --live --testnet --status-port 8787

# 2) Gerçek para (bilerek onayla)
python -m cryptobot --config config.json --live --yes-trade-real-money --status-port 8787
```

Alternatif olarak anahtarları kabukta da verebilirsin
(`export BINANCE_API_KEY=...`), veya başka bir dosya için `--env-file yol/.env`
kullanabilirsin.

Canlı modda her turda: gerçek USDT bakiyen yenilenir, **mutabakat (reconciliation)**
yapılır (borsadaki gerçek bakiye ile botun beklediği pozisyonlar karşılaştırılır) ve
uyumsuzluk varsa yeni emir gönderilmez.

---

## 5. İzleme (monitoring)

Herhangi bir kağıt/canlı çalıştırmaya `--status-port N` eklersen, salt-okunur bir
JSON durum sayfası açılır:

```bash
python -m cryptobot --config config.json --status-port 8787
curl http://127.0.0.1:8787/status
curl http://127.0.0.1:8787/health      # {"ok": true}
```

`/status` örneği:

```json
{
  "available_quote": "900",
  "open_positions": [
    {"symbol": "BTCUSDT", "state": "OPEN", "qty": "1", "invested_quote": "100",
     "estimated_net_pnl": "-1"}
  ],
  "open_invested_quote": "100",
  "estimated_unrealized_net_pnl": "-1",
  "realized_trades": 0,
  "realized_net_pnl": "0",
  "wins": 0, "losses": 0, "win_rate": 0.0
}
```

Alanlar: `available_quote` müsait USDT; `open_positions` açık pozisyonlar (`state`
= `OPEN` veya `EXIT_ARMED`, `estimated_net_pnl` = muhafazakâr tahmini net PnL);
`realized_*` kapanan işlemlerin gerçekleşmiş istatistikleri.

---

## 6. Strateji kuralları (özet)

Bu kurallar sabittir; bot bunları değiştirmez.

**Giriş (BUY)** — son kapanmış mumda **beş koşulun tamamı** sağlanmalı:

1. `RSI[t] < rsi_oversold` (kesin küçük)
2. `RSI[t-1] <= RSI_VWMA[t-1]`
3. `RSI[t] > RSI_VWMA[t]` (2 ve 3 birlikte: RSI, VWMA'yı aşağıdan yukarı keser)
4. `adx_low <= ADX[t] <= adx_high` (sınırlar dahil)
5. `ADR[t] > ADR[t-1]` (kesin artış)

Teknik sinyal tek başına yetmez; **tüm operasyonel kapılar** açık olmalı (runtime
çalışıyor, işlem açık, coin aktif, veri taze ve boşluksuz, göstergeler hazır, slot
ve sermaye limiti uygun, USDT yeterli, Binance filtreleri kabul ediyor, mutabakat
temiz vb.). Aynı coin + aynı mum ikinci kez asla alım üretmez.

**Normal çıkış** — iki aşamalı, **stop-loss yoktur**:

1. `RSI[t] > rsi_overbought` olduğunda pozisyon **kalıcı olarak** `EXIT_ARMED`
   olur (RSI sonradan düşse de geri alınmaz).
2. `EXIT_ARMED` sonrası, muhafazakâr **tahmini net kâr** hedefe ulaşınca satılır:
   `tahmini_net_pnl >= yatırılan_maliyet * min_net_profit_pct / 100`.

**Çekim modu (withdrawal)** — global durum `WITHDRAWAL_REQUESTED` iken: yeni giriş
olmaz, RSI/arming aranmaz, her pozisyon tahmini net kâr **%0,20**'ye ulaşınca
satılır (altındaysa zararına satılmaz).

Ayrıntılı formüller ve gerekçeler için ana `README.md`'ye bak.

---

## 7. Sermaye ve slot mantığı

- **`capital_limit_usdt`** (veya `capital_pct`'ten çözülen değer) = coin'in
  kullanabileceği **toplam** sermaye tavanı.
- **`slot_count`** = bu sermayenin kaç parçaya bölüneceği. Her emir
  `sermaye / slot_count` kadar USDT kullanır ve aynı anda **en fazla `slot_count`**
  açık pozisyon olur.

**Örnek:** `capital_pct: 30`, toplam USDT bakiye 2000 → sermaye = 600 USDT.
`slot_count: 3` → her işlem 200 USDT, en fazla 3 eşzamanlı pozisyon.

**Örnek (sabit):** `capital_limit_usdt: "1000"`, `slot_count: 4` → her işlem
250 USDT, en fazla 4 pozisyon.

Emir büyüklüğü ayrıca Binance sembol filtrelerine (minimum notional, lot adımı)
göre doğrulanır/yuvarlanır.

---

## 8. Parametre referansı

### Coin başına (`coins` içindeki her girdi)

| Alan | Tip | Anlamı |
|------|-----|--------|
| `rsi_oversold` | sayı (0–100) | Giriş: `RSI < bu değer` olmalı |
| `rsi_overbought` | sayı (0–100) | Çıkış tetiği: `RSI > bu değer` → `EXIT_ARMED` |
| `adx_low` | sayı | İzin verilen ADX bandının alt sınırı (dahil) |
| `adx_high` | sayı | İzin verilen ADX bandının üst sınırı (dahil) |
| `min_net_profit_pct` | metin (ondalık) | Normal çıkış için minimum net kâr yüzdesi (örn. `"0.5"`) |
| `rsi_period` | tam sayı ≥ 1 | RSI Wilder periyodu |
| `rsi_ma_period` | tam sayı ≥ 1 | RSI-VWMA pencere uzunluğu |
| `adx_period` | tam sayı ≥ 1 | ADX Wilder periyodu |
| `adr_period` | tam sayı ≥ 1 | ADR pencere uzunluğu (mevcut mum hariç) |
| `capital_limit_usdt` | metin (ondalık) | Sabit sermaye tavanı — `capital_pct` ile birlikte kullanılamaz |
| `capital_pct` | sayı (0–100] | Toplam USDT'nin yüzdesi — `capital_limit_usdt` ile birlikte kullanılamaz |
| `slot_count` | tam sayı ≥ 1 | Sermayenin kaç parçaya bölüneceği / maks. eşzamanlı pozisyon |

### Global

| Alan | Tip | Varsayılan | Anlamı |
|------|-----|:---:|--------|
| `cost_model.exit_fee_rate` | metin (ondalık) | `"0"` | Çıkış komisyon oranı (örn. `"0.001"` = %0,1) |
| `cost_model.safety_buffer_frac` | metin (ondalık) | `"0"` | Çıkış kararında ek muhafazakârlık payı (getirinin oranı) |
| `candle_buffer` | tam sayı | `5` | Strateji minimumunun üstüne çekilen ekstra mum (ısınma için) |

### Komut satırı bayrakları

| Bayrak | Varsayılan | Anlamı |
|--------|:---:|--------|
| `--config PATH` | (zorunlu) | JSON konfigürasyon dosyası |
| `--quote-balance N` | `1000` | Kağıt/backtest başlangıç bakiyesi (paper/backtest'te `capital_pct` tabanı) |
| `--ticks N` | `0` | Tur sayısı (0 = sonsuz) |
| `--interval S` | `60` | Turlar arası saniye |
| `--base-url URL` | Binance ana | REST taban adresi |
| `--backtest PATH` | — | Backtest için klines JSON dosyası |
| `--quote-per-order N` | — | Backtest'te işlem başına sabit USDT |
| `--live` | kapalı | Canlı işlem (API anahtarı + onay gerekir) |
| `--testnet` | kapalı | Binance testnet (sahte para) |
| `--yes-trade-real-money` | kapalı | Gerçek parayla işlem için zorunlu onay |
| `--status-port N` | — | JSON durum sunucusu portu |
| `--env-file YOL` | `.env` | Ortam değişkenlerinin okunacağı `.env` dosyası |

### Ortam değişkenleri (yalnızca canlı)

Bunlar `.env` dosyasına yazılabilir (bkz. 4.3) ya da kabukta `export` ile
verilebilir. Kabukta zaten tanımlıysa `.env`'i geçersiz kılar (kabuk önceliklidir).

| Değişken | Anlamı |
|----------|--------|
| `BINANCE_API_KEY` | Binance API anahtarı |
| `BINANCE_API_SECRET` | Binance API gizli anahtarı |

---

## 9. Önemli notlar ve uyarılar

- **Gösterge ısınması (warmup):** Wilder RSI/ADX özyinelemelidir; sağlıklı
  değerler için yeterli geçmiş gerekir. Bot her turda
  `min_gerekli_mum + candle_buffer` kadar mum çeker. Canlı/kağıt modda
  göstergelerin iyi oturması için `candle_buffer` değerini **yüksek tut**
  (örn. `200`). Backtest zaten tüm geçmişi ısınma olarak kullanır.
- **Önce testnet:** Canlı gerçek paraya geçmeden önce mutlaka `--testnet` ile dene
  ve küçük `capital_limit_usdt` / `capital_pct` ile başla.
- **Mutabakat kapısı:** Borsadaki gerçek bakiye botun beklediğinden azsa (elle
  satış, beklenmedik dolum, çökme sonrası) mutabakat "kirli" olur ve düzelene
  kadar yeni emir gönderilmez.
- **Tek süreç varsayımı:** Bot tek süreç için tasarlanmıştır (worker lease her
  zaman elde varsayılır). Aynı hesap için **aynı anda birden fazla kopya
  çalıştırma** — çoklu örnek için dağıtık kilit gerekir (henüz yok).
- **`capital_pct` sabittir:** Başlangıçtaki toplam USDT'ye göre bir kez hesaplanır.
  Bakiyen değişince yeniden hesaplanması için botu yeniden başlat.
- **Kalıcılık yok:** Açık pozisyonlar/işlem geçmişi bellekte tutulur; süreç
  yeniden başlarsa bu durum korunmaz (kalıcı depolama henüz yok).
- **Stop-loss yok:** Strateji gereği zarar durdurma yoktur. Bunu bilerek kullan.

---

## 10. Sık sorulan sorular

**Her coin için RSI/ADX eşiklerini ayrı ayrı verebilir miyim?**
Evet — `coins` altında her sembolün kendi `rsi_oversold`, `rsi_overbought`,
`adx_low`, `adx_high` (ve tüm diğer) değerleri vardır.

**Coin ekleyip çıkarabilir miyim?**
Evet — config dosyasındaki `coins` listesini düzenleyip botu yeniden başlatarak.
Çalışırken canlı ekle/çıkar yoktur.

**Her coin'e USDT bakiyemin yüzdesini sermaye olarak verebilir miyim?**
Evet — `capital_pct` ile (başlangıçta toplam USDT'ye göre sabitlenir).

**Sermayeyi işlem başına kaça böleceğini söyleyebilir miyim?**
Evet — `slot_count`. Her emir `sermaye / slot_count` kadar kullanır.

**Kağıt modu gerçek veriye mi bakıyor?**
Evet, gerçek Binance verisini salt-okunur kullanır; yalnızca dolumları simüle eder.

**Config değişikliği açık pozisyonu etkiler mi?**
Hayır. Her pozisyon açıldığı andaki parametrelerin değişmez kopyasıyla yönetilir.

---

Ayrıntılı mimari ve strateji formülleri için depo kökündeki `README.md` dosyasına
bakabilirsin.
