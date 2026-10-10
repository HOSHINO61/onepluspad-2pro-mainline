# Stock boot build inputs

`stock-boot-inputs.tar.gz` contains the unmodified `boot.img`, `init_boot.img`,
`vendor_boot.img` and `dtbo.img` from the official OPD2413 ColorOS C.34 OTA.
[source.json](source.json) records the OTA source and SHA-256, every image's
SHA-256, and the archive checksum.

The build reads the device trees from `vendor_boot` and `dtbo`, and the original
partition sizes and rollback indices from the three boot images. Keeping these
original inputs together avoids requiring a full ROM download or a separate
extraction tool. They contain no per-device calibration or project signing key.

Run `python3 tools/prepare-inputs.py` from the project root to unpack them into
the build cache. That command performs no device operations. These files are
build references, not the project's Android recovery or installation package.
Other stock firmware versions require separately verified inputs.

The stock images retain their original vendor and third-party licensing terms.
The project's GPL license does not cover them. Redistribution permission for
the vendor content has not been established; see the related
[firmware distribution notes](../firmware/README.md).
