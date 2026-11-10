#!/usr/bin/env python3
"""Customise the native projects that `npx cap add ios|android` generates.

The ios/ and android/ folders are generated (not committed), so everything
CheetahClaws needs on top of Capacitor's template lives here:

* App icon + splash from desktop/assets/icon.png, rendered at whatever sizes
  the template ships (so a newer Capacitor template keeps working).
* Plain-http to the user's own computer on the LAN / Tailscale
  (iOS App Transport Security, Android cleartext + mixed content).
* iOS permission strings: local network (required on iOS 14+ to reach a
  LAN address) and camera (QR scanning).
* Android minSdk 26, required by @capacitor/barcode-scanner.

Usage:  python3 scripts/patch_native.py ios|android     (from mobile/)
Needs:  Pillow
"""
from __future__ import annotations

import plistlib
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
MOBILE = HERE.parent
SRC_ICON = MOBILE.parent / "desktop" / "assets" / "icon.png"
TOP, BOTTOM = (26, 34, 50), (10, 14, 20)   # icon gradient (make_icon.py)
BG_HEX = "#0B0F14"


def _gradient(w: int, h: int) -> Image.Image:
    img = Image.new("RGB", (w, h))
    px = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(h - 1, 1)
        px.line([(0, y), (w, y)],
                fill=tuple(int(a * (1 - t) + b * t) for a, b in zip(TOP, BOTTOM)))
    return img


def full_bleed(size: int, scale: float = 1.13) -> Image.Image:
    """Square icon with no transparent corners (the OS applies its own mask)."""
    src = Image.open(SRC_ICON).convert("RGBA")
    base = _gradient(size, size).convert("RGBA")
    n = int(size * scale)
    ic = src.resize((n, n), Image.LANCZOS)
    base.alpha_composite(ic, ((size - n) // 2, (size - n) // 2))
    return base.convert("RGB")


def round_icon(size: int) -> Image.Image:
    img = full_bleed(size).convert("RGBA")
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    img.putalpha(mask)
    return img


def splash(w: int, h: int) -> Image.Image:
    img = Image.new("RGB", (w, h), (11, 15, 20))
    n = max(int(min(w, h) * 0.28), 16)
    ic = Image.open(SRC_ICON).convert("RGBA").resize((n, n), Image.LANCZOS)
    img.paste(ic, ((w - n) // 2, (h - n) // 2), ic)
    return img


def _replace(path: Path, render) -> None:
    w, h = Image.open(path).size
    render(w, h).save(path, optimize=True)


# ── Android ─────────────────────────────────────────────────────────────

def patch_android(root: Path) -> None:
    res = root / "app" / "src" / "main" / "res"
    for png in res.rglob("*.png"):
        name = png.name
        if name == "ic_launcher.png":
            _replace(png, lambda w, h: full_bleed(w))
        elif name == "ic_launcher_round.png":
            _replace(png, lambda w, h: round_icon(w))
        elif name == "ic_launcher_foreground.png":
            # Adaptive icon: the launcher shows only the middle ~66%, so the
            # claws are drawn smaller on a full-bleed backdrop.
            _replace(png, lambda w, h: full_bleed(w, scale=0.86))
        elif name.startswith("splash"):
            _replace(png, splash)

    bg = res / "values" / "ic_launcher_background.xml"
    if bg.exists():
        bg.write_text(re.sub(r"#[0-9A-Fa-f]{6,8}", BG_HEX, bg.read_text()))

    manifest = root / "app" / "src" / "main" / "AndroidManifest.xml"
    text = manifest.read_text()
    if "usesCleartextTraffic" not in text:
        text = text.replace("<application",
                            '<application\n        android:usesCleartextTraffic="true"', 1)
    manifest.write_text(text)

    variables = root / "variables.gradle"
    text = variables.read_text()
    m = re.search(r"minSdkVersion\s*=\s*(\d+)", text)
    if m and int(m.group(1)) < 26:
        text = text.replace(m.group(0), "minSdkVersion = 26")
    variables.write_text(text)
    print("patched android/: icons, splash, cleartext, minSdk>=26")


# ── iOS ─────────────────────────────────────────────────────────────────

def patch_ios(root: Path) -> None:
    app = root / "App" / "App"
    assets = app / "Assets.xcassets"
    for png in (assets / "AppIcon.appiconset").glob("*.png"):
        _replace(png, lambda w, h: full_bleed(w))     # RGB: App Store rejects alpha
    for png in (assets / "Splash.imageset").glob("*.png"):
        _replace(png, splash)

    plist_path = app / "Info.plist"
    with plist_path.open("rb") as fh:
        plist = plistlib.load(fh)
    ats = plist.setdefault("NSAppTransportSecurity", {})
    # The agent server is the user's own computer over plain http on the LAN
    # or Tailscale (100.x) — ATS would otherwise block every connection.
    ats["NSAllowsArbitraryLoads"] = True
    ats["NSAllowsLocalNetworking"] = True
    plist["NSLocalNetworkUsageDescription"] = (
        "CheetahClaws connects to the agent running on your computer "
        "over your local network.")
    plist["NSCameraUsageDescription"] = (
        "Scan the pairing QR code shown on your computer.")
    plist["CFBundleDisplayName"] = "CheetahClaws"
    with plist_path.open("wb") as fh:
        plistlib.dump(plist, fh)
    print("patched ios/: icon, splash, ATS, local-network + camera strings")


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in ("ios", "android"):
        print(__doc__)
        return 2
    plat = argv[1]
    root = MOBILE / plat
    if not root.is_dir():
        print(f"{root} not found — run `npx cap add {plat}` first", file=sys.stderr)
        return 1
    (patch_ios if plat == "ios" else patch_android)(root)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
