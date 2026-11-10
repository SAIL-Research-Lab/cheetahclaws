# CheetahClaws for iPhone / Android

The phone app is a remote control for the CheetahClaws agent **running on your
computer**. The phone does no model calls and runs no tools. It opens your
computer's chat UI, so sessions, files, API keys and running tasks all stay on
the computer. Tasks keep running when the phone locks.

```
┌ phone app ───────────────┐   Wi-Fi / Tailscale   ┌ your computer ───────────────┐
│ computer list, QR scan   │ ────────────────────▶ │ CheetahClaws desktop app or  │
│ → WebView: <ip>/chat     │                       │ `cheetahclaws --web --lan`   │
└──────────────────────────┘                       └──────────────────────────────┘
```

## Use it

1. On the computer, open the desktop app and choose **Phone → Connect Phone…**
   (or run `cheetahclaws --web --no-auth --lan` and open the `/pair` link it
   prints).
2. On the phone, open the app → **Scan QR code** (or paste the link).

The app remembers the computer and reconnects to it on launch. The **⇄**
button in the chat's top bar goes back to the computer list.

The phone must be on the same Wi-Fi as the computer. To use it anywhere,
install [Tailscale](https://tailscale.com) on both devices; the pairing page
then also shows a Tailscale code.

**No app needed on iPhone:** scan the QR code with the Camera, open the link
in Safari, then tap **Share → Add to Home Screen**.

## Get the app

GitHub Actions builds both apps (`.github/workflows/apps.yml`). Run it from
**Actions → Apps → Run workflow**, or push a tag `app-v*` to get a Release.

| Platform | File | Install |
|---|---|---|
| Android | `CheetahClaws-android.apk` | Open it on the phone and allow "install unknown apps". |
| iOS | `CheetahClaws-ios-unsigned.ipa` | Apple only installs signed apps. Sideload it with [AltStore](https://altstore.io) or [Sideloadly](https://sideloadly.io), which sign it with your free Apple ID (re-sign every 7 days). Or use a Mac (next section). |

TestFlight or the App Store needs a paid Apple Developer account ($99/yr). With
one, archive the project in Xcode and upload it.

## Build it yourself

Requires Node 22+ and Python 3 with Pillow (`pip install pillow`).

```bash
cd mobile
npm install
npm test                     # connect-screen unit tests

npm run add:android          # generates android/ and applies scripts/patch_native.py
npx cap sync android
cd android && ./gradlew assembleDebug    # → app/build/outputs/apk/debug/app-debug.apk

npm run add:ios              # macOS: generates ios/ (Swift Package Manager)
npx cap sync ios
open ios/App/App.xcodeproj   # pick your iPhone, set your Team under Signing, press Run
```

`android/` and `ios/` are generated, not committed. `scripts/patch_native.py`
applies everything CheetahClaws changes on top of Capacitor's template:

- **Icon and splash**, rendered from `desktop/assets/icon.png`.
- **Plain-HTTP connections to your own computer**: iOS App Transport Security,
  Android cleartext.
- **iOS permission strings** for the local network (required on iOS 14+) and
  the camera (QR scanning).
- **Android `minSdk 26`**, required by the barcode scanner.

## Layout

| Path | What |
|---|---|
| `www/index.html`, `www/app.mjs` | Connect screen: computer list, add/scan, reachability check |
| `www/connect.mjs` | Pure helpers (link parsing, storage), tested by `test/connect.test.mjs` |
| `capacitor.config.json` | `allowNavigation: ["*"]` lets the WebView open your computer's address; `appendUserAgent` lets the chat page show the ⇄ button |
| `scripts/patch_native.py` | Native-project customisation (see above) |
