# Decisions

One entry per judgment call made while working unattended. Newest at the bottom.

1. **Build on the community work, then verify it against the official binary.** About 20
   open-source F75 Max projects already exist, and several include USB captures of AULA's
   own app. Reverse-engineering from scratch would be slower and no more reliable. Every
   fact the app depends on is checked against the decompiled `DeviceDriver.exe` or an
   official-app capture, and PROTOCOL.md cites which one.

2. **Official software source:** Epomaker's download page links
   `AULA_F75_Max_Gasket_Mechanical_Keyboard_Driver_1.0.0.5.zip` (sha256
   `98dd00c6e3d1717fcbaeb6ab9829d2c9d3359361d17476891a4e801461144581`). The Epomaker x
   AULA F75 Max is the co-branded version of this keyboard. Its `config.xml` lists exactly
   our dongle (05AC:024F), so it is the right binary.

3. **Tools without root:** innoextract was unpacked from the Arch package into the
   scratchpad instead of being installed. Ghidra lives in `~/.cache/aula-re/` because
   `/tmp` is a RAM-backed tmpfs and the machine has about 3 GB free. Neither tool touches
   the system.
