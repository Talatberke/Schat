# 🔐 SecretChat

Farklı şehirlerdeki / ağlardaki kullanıcıların **modemden port açmadan**, **VPN kurmadan**,
uçtan uca şifreli (E2EE) sohbet etmesini sağlayan, koyu temalı masaüstü uygulaması.

> Aktarıcı sunucular (broker) yalnızca **şifreli zarfları** taşır; mesaj içeriklerini
> asla göremez. Kayıt kapalıyken mesajlar yalnızca RAM'de tutulur.

---

## Özellikler

| Özellik | Nasıl |
|---|---|
| Sıfır modem ayarı | TLS'li MQTT sinyal/relay kanalı (herkese açık broker'lar) + STUN/UDP P2P katmanı |
| Oda Kur / Katıl | "Oda Kur" → 5 haneli kısa kod (örn. `3K7QX`), karşı taraf kodu yapıştırır |
| E2EE | X25519 (ECDH) el sıkışma → HKDF-SHA256 → AES-256-GCM |
| MITM kontrolü | 6 haneli SAS doğrulama kodu (iki tarafta aynı görünür) |
| Grup sohbeti | Host, grup anahtarını her üyeye ECIES ile sarıp dağıtır |
| Gizlilik | Mesajlar varsayılan RAM'de; "Geçmişi Kaydet" ile isteğe bağlı .log/.txt |
| Gizli rumuz | Kullanıcı adı boş bırakılırsa otomatik `sıfat nesne sayı` rumuzu (örn. `mavi bulut 1923`) |
| Fotoğraf gönderimi | Sohbet içinden JPEG/PNG/GIF seçimi, E2EE şifreli aktarım, balon içi önizleme |
| Emoji paneli | Giriş kutusu yanında kategorili emoji seçici (açık/koyu tema uyumlu) |
| Kopyala / Düzenle / Sil | Balona sağ tık menüsü; kendi mesajında düzenleme/silme karşı tarafa şifreli yayınlanır |
| Yazı tipi + boyutu | ⚙ Ayarlar'dan Google Fonts bağlantısı/adıyla font indirme, 9–18 pt boyut kaydırıcısı |
| Duyarlı arayüz | Dar pencerede sadeleşen üst bar, taşınca kayan karşılama kartı, font değişiminde bozulmayan akış |
| Modern GUI | Tkinter, açık/koyu mod, tek pencere, tek tıkla çalışır |

## Mimari

```
┌─────────────┐   şifreli zarflar   ┌──────────────────┐   şifreli zarflar   ┌─────────────┐
│   Host GUI  │ ───────────────────▶│  MQTT broker(TLS)│───────────────────▶ │  Client GUI │
│             │◀─────────────────── │  (aktarıcı; içerik│◀────────────────── │             │
└─────────────┘                     │   GÖREMEZ)        │                    └─────────────┘
     │        X25519 el sıkışma     └──────────────────┘        X25519 el sıkışma │
     └───────────────────────────────────────────────────────────────────────────┘
                    Ortak AES-256 anahtarı (HKDF) — broker bilmez
```

**El sıkışma akışı**

1. **Katılan → Host:** `HELLO` — geçici X25519 pub + Ed25519 kimlik pub + nonce
2. **Host → Katılan:** `HELLO_BACK` — host pub + nonce'un oturum anahtarıyla şifreli kanıtı
3. **Katılan → Host:** `HB_ACK` — anahtar onayı
4. **Host → Katılan:** `MEMBER_JOIN` — grup anahtarı, katılanın kimlik pub'ıyla ECIES sarmalı
5. **Herkes:** `DATA` — grup anahtarıyla AES-256-GCM şifreli sohbet

Katılan, nonce'u ancak host'un ECDH sırrıyla çözebildiyse doğrulama geçer; ortadaki adam
(MITM) anahtarı değiştirirse iki tarafta görünen **SAS kodu** farklılaşır.

## Kurulum (kaynaktan)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Gereksinim: Python 3.10+ (`requirements.txt` içinde `Pillow` da bulunur — fotoğraf önizlemeleri için)

## .exe / tek dosya derleme

```bash
# Windows
build_exe.bat          # → dist\SecretChat.exe

# Linux / macOS
chmod +x build_exe.sh && ./build_exe.sh   # → dist/SecretChat
```

Çıkan tek dosyayı herkese dağıtabilirsiniz; karşı taraf Python kurmadan çift tıklar.

## Kullanım

1. **Oda Kur** → ekranda oda kodu görünür → "📋 Kopyala" ile paylaş (telefon/mesaj ile).
2. Karşı taraf: takma ad + kodu yapıştır → **Katıl**.
3. (Önerilir) UI'daki 6 haneli **doğrulama kodunu** karşı tarafla telefonla karşılaştırın.
4. "Geçmişi Kaydet" işaretlenirse şifresi çözülmüş metin seçtiğiniz dosyaya yazılır;
   işaretli değilse her şey RAM'de kalır, kapanınca silinir.

## Testler

```bash
python -m pytest tests -q            # tamamı (ağ testi dahil, ~1 dk)
SKIP_NET=1 python -m pytest tests -q # yalnızca çevrimdışı birim testler
```

## Proje yapısı

```
main.py                  # giriş noktası
secretchat/
  config.py              # sabitler (broker, kod uzunluğu, zaman aşımları, medya limitleri)
  crypto.py              # X25519, HKDF, AES-GCM, ECIES, Ed25519, SAS
  messages.py            # tel protokolü (JSON zarfları: chat/image/edit/delete)
  signaling.py           # MQTT/TLS kanal + kuyruklu dağıtım
  stun.py                # STUN istemcisi (P2P dış adres keşfi)
  p2p.py                 # UDP hole-punching taşıma katmanı
  room.py                # Host/Client oturum mantığı, grup anahtarı dağıtımı
  storage.py             # RAM modu / dosya kaydı
  theme.py               # açık/koyu palet + tema/font kalıcılığı
  fonts.py               # Google Fonts indirme + sisteme font tanıtma
  media.py               # fotoğraf doğrulama/yeniden boyutlandırma/base64
  emoji_picker.py        # kategorili emoji seçici
  nicknames.py           # otomatik gizli rumuz üretimi
  ui.py                  # Tkinter GUI
tests/                   # birim + entegrasyon + responsive testleri
tools/debug_handshake.py # el sıkışma izleme aracı
```

## Sınırlar ve notlar

- **Post-quantum değil**: X25519 kuantum bilgisayarlara karşı değildir (ulusal ölçekte
  tehdit değildir, ama not edilmeli).
- **Mesaj ileri gizliliği (PFS)**: geçici anahtarlar oturum sonunda RAM'den silinir; ancak
  anahtar rotasyonu yoktur (çift ratchet değildir).
- Herkese açık MQTT broker'lar kullanılır; broker trafiği göremez ama **meta veriyi**
  (zamanlama, boyut, topic) görür. Tam meta-gizlilik için kendi broker'ınızı işletin
  (`config.py` → `DEFAULT_BROKER`).
- P2P katmanı (STUN/hole-punch) mevcuttur; iletişim halihazırda TLS'li relay üzerinden
  yürür, P2P düşük gecikme isteyenler için temeldir.
