# MystX DEX — Custom Logo Placement Guide

To replace the placeholder branding with your final custom **MystX DEX** logo, place your assets into the designated resource locations listed below:

---

## 1. Android Launcher Icons (Adaptive & Legacy)

| Screen Density | Target Location | Dimensions (px) |
|---|---|---|
| **Adaptive Vector (Default)** | `app/src/main/res/drawable/ic_foreground.xml` | Vector (108x108dp) |
| **mdpi** | `app/src/main/res/mipmap-mdpi/ic_launcher.png`<br>`app/src/main/res/mipmap-mdpi/ic_launcher_round.png` | 48 × 48 |
| **hdpi** | `app/src/main/res/mipmap-hdpi/ic_launcher.png`<br>`app/src/main/res/mipmap-hdpi/ic_launcher_round.png` | 72 × 72 |
| **xhdpi** | `app/src/main/res/mipmap-xhdpi/ic_launcher.png`<br>`app/src/main/res/mipmap-xhdpi/ic_launcher_round.png` | 96 × 96 |
| **xxhdpi** | `app/src/main/res/mipmap-xxhdpi/ic_launcher.png`<br>`app/src/main/res/mipmap-xxhdpi/ic_launcher_round.png` | 144 × 144 |
| **xxxhdpi** | `app/src/main/res/mipmap-xxxhdpi/ic_launcher.png`<br>`app/src/main/res/mipmap-xxxhdpi/ic_launcher_round.png` | 192 × 192 |

---

## 2. Android TV & App Banner

- **Banner Image**: `app/src/main/res/drawable/banner.png` (320 × 180 px)

---

## 3. Web GUI Logo

The MystX DEX Web GUI loads its branding from:
- **Vector Logo (Preferred)**: `app/src/main/assets/mystx/web/assets/logo.svg`
- **Fallback PNG**: `app/src/main/assets/mystx/web/assets/logo.png`
- **Runtime User Path**: `~/.mystx/web/assets/logo.svg`

---

## 4. Vector / Source Artworks

- High-resolution or master SVGs can be saved in:
  `art/mystx_logo.svg`
