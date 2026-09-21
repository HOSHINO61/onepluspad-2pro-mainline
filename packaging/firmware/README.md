# Device firmware

The 72 binaries under this directory are the firmware closure this tablet's
mainline drivers ask for by name, laid out exactly as they install under
`/usr/lib/firmware`. `tools/build-debs.py` packs them into `erhai-firmware`
after checking each one against the sha256 and size recorded in
[`../firmware-manifest.json`](../firmware-manifest.json), which is the per-file
provenance record: the input every file came from and its path inside it.

## Origin

| Files | From | What |
|---|---|---|
| 59 | the OnePlus Pad 2 Pro official ColorOS OTA `OPD2413_11.C.34_1340_202607031844`: 58 out of `modem.img`, one out of `dtbo.img` | the ADSP PIL set under `qcom/sm8750/erhai/`, and the NT36536 touch application firmware, which the vendor keeps as an overlay property rather than as a file |
| 9 | ROCKNIX `extra-firmware`, commit `2b7207cf` | WCN7860 Wi-Fi (`ath12k/`) and Bluetooth (`qca/`), which upstream linux-firmware does not carry |
| 4 | linux-firmware | Adreno 830 SQE/GMU/AQE microcode and the SM8750 zap shader |

Nothing here is modified, recompiled or repacked: each file is the bytes its
input holds, copied out and given mode 0644. `tools/build-debs.py
--refresh-from-rom` extracts the closure from those inputs again and diffs it
against this directory, which is how a later ROM version gets in.

## License

These are proprietary Qualcomm and OnePlus binaries. The project claims no
copyright and grants no license over them, and the repository's GPL-2.0-only
does not reach them; they are redistributed here as they came, unmodified, so
that this device's port builds from one tree. The four linux-firmware files
carry that project's `LICENSE.qcom` redistribution terms, and ROCKNIX
redistributes its nine under the terms it received them.

The 59 files taken out of the stock OTA are the ones to be careful with: this
project has **not** established any redistribution permission for them from
OnePlus or Qualcomm, and the OTA ships no license text granting one. They are
here because the port needs them and the owner of this unit decided to publish
them; anyone who redistributes this tree further stands in the same place.
Dropping them from the manifest and from this directory is all it takes to
build without them, at the cost of the ADSP and the touchscreen.
