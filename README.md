# Rich4 browser port

Public game hosting: https://wqx-txdsyl.github.io/rich4-play/

The original Rich4.exe is unchanged. All seven MKF packages and 25 MIDI files must match the local installation SHA-256 hashes. The 21 complete original cutscenes are restored from the verified Time Travel disc image. Personal saves and uninstall records are excluded from public builds.

Original disc storage format: for byte position i, encoded = ROL8((original + i % 71) % 256, 2) XOR 0xD5. The decoder reverses the installer format and verifies every resulting full file against the local SHA-256 inventory. The original disc image is also checked against its catalog SHA-1 and exact size.

The browser uses official Boxedwine 26R1 single-threaded JS/WASM with the Wine 11 root filesystem, plus a pinned Noto Sans CJK TC font. Original MIDI output from Wine is translated into browser audio through TinySynth. Music selection, note events and tempo remain controlled by the original game.

Browser gameplay, fonts, sound, cutscene decoding and save/load require validation; restored media does not by itself prove complete gameplay parity.

## Build

Python 3.11, Node.js and an internet connection are required.

    python build_cloud.py

Build output is dist/. GitHub Actions deploys this folder to Pages after the preservation and archive integrity checks pass.

Game artwork/audio belong to SOFTSTAR. Boxedwine and its shell are GPL; Wine is LGPL; Noto Sans CJK is SIL OFL; TinySynth is Apache-2.0. Licenses are included in the site output. Upstream sources: https://github.com/danoon2/Boxedwine/tree/26R1.0, https://www.winehq.org/, https://github.com/notofonts/noto-cjk, https://github.com/g200kg/webaudio-tinysynth.
