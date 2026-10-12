# Cyber-Incognito — Tema Kılavuzu

**Konsept:** Cyberpunk Minimalism · **Atmosfer:** odak artıran, gizlilik hissi veren,
neon dokunuşlarla zengin ama gözü yormayan karanlık mod (**Dark Mode Default**).

Kaynak dosyalar:

- `secretchat/theme.py` — renk token'ları, CSS/theme dict, tipografi, duyarlı spacing
- `secretchat/components.py` — hazır arayüz şablonu (durum çubuğu, balonlar, giriş alanı)
- `tools/smoke_theme.py` — çalışan duman testi (`PYTHONPATH=. python tools/smoke_theme.py`)

---

## 1. Renk Paleti (Color Tokens)

`theme.PALETTE` — çerçevenizden bağımsız saf değer sözlüğü.

| Token | Hex | Kullanım |
|---|---|---|
| `background` | `#0B0E14` | Ana zemin (derin, hafif maviye çalan siyah) |
| `surface` | `#151B26` | Sohbet pencereleri, kartlar, üst/alt çubuk |
| `surface_alt` | `#1E293B` | Gelen mesaj balonu, iç kutular |
| `surface_input` | `#10161F` | Girdi kutusu (zeminden ayrışır) |
| `primary` | `#00F5D4` | Neon turkuaz — şifreli vurgu, aktif buton |
| `primary_hover` | `#00D9BD` | Buton hover/pressed |
| `on_primary` | `#0B0E14` | Primary üzerinde metin |
| `secondary` | `#7B2CBF` | Derin mor — kendi mesajların, gizli rozet |
| `secondary_deep` | `#2E1065` | Giden balon gradient sonu |
| `text` | `#F1F5F9` | Ana metin (17.63:1) |
| `text_muted` | `#64748B` | Zaman damgası, ikincil bilgi + **placeholder** (spec) |
| `text_dim` | `#475569` | Pasif/devre dışı metin (placeholder değil) |
| `on_secondary` | `#F5F3FF` | Mor üzerinde metin (6.48:1) |
| `success` | `#10B981` | Çevrimiçi / şifreleme aktif |
| `warning` | `#F59E0B` | Bağlanıyor / uyarı |
| `error` | `#EF4444` | Bağlantı koptu / mesaj silindi |
| `border` | `#1F2A3A` | Kart kenarlığı |
| `focus` | `#00F5D4` | Odak halkası / parıltı |

### Erişilebilirlik (WCAG AA ≥ 4.5:1)

| Çift | Oran |
|---|---|
| `text` / `background` | **17.63:1** |
| `text` / `surface` | **15.76:1** |
| `on_primary` / `primary` | **13.81:1** |
| `primary` / `background` | **13.81:1** |
| `on_secondary` / `secondary` | **6.48:1** |
| `success` / `surface` | **6.80:1** |
| `warning` / `surface` | **8.04:1** |
| `error` / `surface` | **4.59:1** |
| `text_muted` / `surface` | 3.63:1 — *yalnız dekoratif meta/rozet; gövde metni `text` kullanır* |

> Not: `#64748B` (istenen palet değeri) 3.63:1; bu yüzden yalnızca küçük meta
> bilgilerde tutuldu, tüm gövde metni `text` (#F1F5F9) ile yazılır.

---

## 2. Tipografi

```python
FONT_SANS_STACK = ["Inter", "Roboto", "Segoe UI", "system-ui", "Helvetica Neue", "Arial"]
FONT_MONO_STACK = ["Fira Code", "JetBrains Mono", "Consolas", "Menlo",
                   "DejaVu Sans Mono", "Courier New"]
```

- **Sans-Serif** → mesaj balonları, menüler, gövde (`Inter`/`Roboto`/System UI)
- **Monospace** → oda kodu, anahtar/hash göstergeleri, durum metinleri, saat
- Satır yüksekliği `1.5`, başlıklarda `1.2` — ferah okunabilirlik
- `theme.TYPE_SCALE`: `caption 10 / body 11 / body_big 12 / label 11 / title 14 / heading 18 / display 26 / code 16`

Tkinter'de kurulu aileyi seçmek için: `theme.resolve_fonts(tkfont.families())`.

---

## 3. UI Bileşenleri

### Mesaj Baloncukları

| | Gelen | Giden |
|---|---|---|
| Hiza | sol (`anchor=w`) | sağ (`anchor=e`) |
| Arka plan | `#1E293B` düz | `#7B2CBF → #2E1065` **gradient** |
| `border-radius` | `12px 12px 12px 2px` | `12px 12px 2px 12px` |
| Metin | `text` (#F1F5F9) | `on_secondary` (#F5F3FF) |
| Meta/saat | `text_muted` | `meta_on_secondary` (#EDE9FE) |

Asimetrik köşe, konuşma yönünü ("kuyruk") gösterir. Tkinter `Text` widget'ı
`border-radius`/gradient desteklemediği için `components.Bubble` balonları
**Canvas** üzerinde poligon + gradyan şeritlerle çizer.

### Giriş Alanı (Input)

Odakta (`<FocusIn>`) dış çerçeve `#00F5D4`'e döner ve nefes alan bir parıltı
başlar — CSS'teki karşılığı:

```css
box-shadow: 0 0 10px rgba(0, 245, 212, 0.3);
```

`theme.GLOW["focus_input"]` bu değeri tutar. Odak kalkınca `border` rengine döner.

### Durum Çubuğu

Çevrimiçi noktası (`success`), `🔒 E2EE` rozeti (`secondary`), oda kodu
(`primary`, monospace) ve tema düğmesi. Hover mikro-etkileşimi 150 ms (`MOTION["fast"]`).

### Mikro-Etkileşimler

- **Hover:** kopyala / çöz / sil butonları balonun üzerine gelince belirir; renk `text_muted → primary` (150 ms)
- **Yazıyor...:** `components.MessageList.show_typing()` — noktalar `MOTION["normal"]` (250 ms) döngüsü
- **Kaybolan mesaj:** `Bubble.fade_out()` — `MOTION["slow"]` (400 ms) opacity geçişi
- **CSS geçişi:** `all 250ms cubic-bezier(0.4, 0, 0.2, 1)`

---

## 4. Duyarlı (Responsive) Spacing

`theme.BREAKPOINTS = {"mobile": 576, "tablet": 768, "desktop": 1024}`

| Kırılım | unit | gutter | card_pad | bubble_pad | gap | bar_h |
|---|---|---|---|---|---|---|
| **mobile** (≤576) | 4 | 12 | 16 | 10 | 6 | 52 |
| **tablet** (≤768) | 6 | 20 | 24 | 12 | 10 | 56 |
| **desktop** (>768) | 8 | 28 | 32 | 14 | 12 | 60 |

Kullanım:

```python
sp = theme.spacing_for(width_px)     # {'unit','gutter','card_pad',...}
name = theme.breakpoint_of(width_px) # 'mobile' | 'tablet' | 'desktop'
```

`ChatTemplate` pencere `<Configure>` olayında `spacing_for()` çağırır; web için
`theme.spacing_css()` aynı değerleri `@media (min-width: ...)` bloğu olarak üretir.

---

## 5. CSS / Stil Sözlüğü (Theme Dict)

```python
from secretchat import theme
print(theme.css_variables())   # :root { --bg: #0B0E14; ... }
print(theme.css_style_sheet()) # tam sayfa (.bubble-in, .bubble-out, .input:focus, ...)
print(theme.spacing_css())     # mobil -> tablet -> masaüstü @media
```

`theme.CSS` sözlüğü bileşen sınıflarını içerir:
`.bubble-in` · `.bubble-out` (gradient) · `.bubble-system` · `.input:focus` (neon glow)
· `.btn-primary` · `.btn-send` · `.chat-body` · `.input-bar` (sticky) · `.status-bar`
· `.meta` · `.typing`.

---

## 6. Yerleşim Mimarisi (Layout — 2 Bölme)

Sohbet ekranı **2 bağımsız bölüme** ayrılır; scroll eden tek alan mesaj listesidir:

```
┌────────────────────────────┐
│ StatusBar / Header  (TOP)  │  sabit
├────────────────────────────┤
│                            │
│ Chat Display Area          │  expand=True (flex:1), kendi içinde scroll
│ (mesaj listesi)            │  içerik altında padding-bottom: 80px
│                            │
├────────────────────────────┤
│ Input Bar (BOTTOM, 72px)   │  sabit — liste uzadıkça ezilmez/kaybolmaz
└────────────────────────────┘
```

**Tkinter (`ui.py` / `components.py`):**

1. `chat_top.pack(side=tk.TOP)` → `chat_bottom.pack(side=tk.BOTTOM, height=72)`
   **önce** yerini ayırır → `chat_mid.pack(fill=BOTH, expand=True)` kalanı kaplar.
2. `chat_bottom.pack_propagate(False)` → yükseklik 72px (spec 60-80) sabit.
3. `tk.Text` varsayılan `height=24` (~870px) talep ediyordu; bu talep pack
   sırasını ezip alt barı `mapped=0` (görünmez) yapıyordu → `height=12` + yukarıdaki
   sıra. Regresyon testi: `tests/test_ui_layout.py`.
4. `MessageList` içinde alt kenara `side=BOTTOM` ile 80px boşluk — son mesaj
   asla barın altında kaybolmaz.

**Web:** `.chat-body { overflow-y:auto; padding-bottom:80px }` +
`.input-bar { position:sticky; bottom:0; z-index:100; height:72px }`.

---

## 7. Çerçeve Uyarlama Notları

| Çerçeve | Nasıl |
|---|---|
| **Tkinter** (bu proje) | `theme.py` + `components.py`; renkler global `theme.BG`, `theme.PRIMARY`... |
| **CustomTkinter** | `CTkButton(fg_color=theme.PRIMARY, text_color=theme.ON_ACCENT)` |
| **Streamlit** | `st.markdown(f"<style>{theme.css_style_sheet()}</style>", True)` |
| **Flet** | `ft.Color(theme.token("primary"))` — `token()` aktif modu izler; sabit koyu palet için `DARK_PALETTE` |
| **PyQt/QSS** | `theme.CSS` sözlüğünü `selector { prop: val; }` QSS'e çevirin |
| **Web** | `css_style_sheet()` + `spacing_css()` doğrudan `.css` dosyası |

---

## 8. Tema Geçişi

```python
theme.set_theme("light")   # Cyber-Incognito -> gündüz karşılığı
theme.toggle_theme()       # tek tuşla dark <-> light
theme.is_dark()            # aktif mod
theme.token("primary")     # semantik anahtarla aktif renk
```

Tercih `~/.secretchat/settings.json`'a yazılır; varsayılan **dark**.
