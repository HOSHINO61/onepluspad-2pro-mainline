# 构建指南

[English](BUILD.md) · [项目首页](../README.zh-CN.md)

在 Linux 主机上构建内核、设备包与 Ubuntu 根系统。内核源码由
[linux-sm8750-erhai](https://github.com/yzddmr6/linux-sm8750-erhai) 单独维护，
必须使用输入清单指定的项目提交和原始输入。

## 主机与源码

使用 Linux 主机，准备 Git、Python 3、GNU make、AArch64 GCC/binutils、bc、bison、flex、
OpenSSL/ELF 开发头文件与 kmod；ccache 可选。音频构建另需 m4 和 alsa-utils。
内核版本、配置位置和工具输入见 [kernel/source.json](../kernel/source.json)。

独立 checkout 使用以下布局，命令均从集成仓库根目录执行：

```text
onepluspad-2pro-mainline/
  kernel/linux/     匹配 source.json 中提交的独立内核 checkout
  cache/           已校验的原始输入
  out/             构建输出，不进源码仓库
```

`ERHAI_WORKSPACE` 可指定另一个包含 `kernel/linux`、`cache` 和 `out` 的工作区。
Python 入口可用 `--help` 查看参数；shell 入口采用下文的环境变量。

## 内核与 RAM 启动镜像

```sh
kernel_out="$PWD/out/kernel"
OUT_DIR="$kernel_out" tools/build-kernel.sh
```

输出包括 Image、设备树、模块、最终配置及构建身份。重复构建复用兼容的 OUT 与 ccache，
不需要每次全量重编。正式候选必须保持内核和模块匹配。

构建 NCM initramfs 还需要 `cache/busybox-arm64` 和内核生成的 `gen_init_cpio`；
BusyBox 必须匹配 source.json 中的 SHA-256。启动镜像封装需要同一清单对应的 AOSP
`mkbootimg.py`，默认位于 `cache/tools/mkbootimg.py`。

```sh
PROFILE=ncm OUT_DIR="$PWD/out/initramfs" \
  GEN_INIT_CPIO="$kernel_out/usr/gen_init_cpio" tools/build-initramfs.sh
python3 tools/build-erhai-abl-symbols.py --output out/abl-dtb \
  --mainline-dtb "$kernel_out/arch/arm64/boot/dts/qcom/sm8750-erhai.dtb" \
  --dtc "$kernel_out/scripts/dtc/dtc" \
  --vendor-boot /path/to/stock/vendor_boot.img --dtbo-img /path/to/stock/dtbo.img
python3 tools/build-mainline-boot.py --output out/mainline-boot \
  --kernel-out "$kernel_out" --dtb out/abl-dtb/erhai-abl.dtb \
  --initramfs out/initramfs/initramfs-ncm.cpio.gz
```

原厂输入必须匹配目标固件。当前封装逻辑根据已核对的 ColorOS C.34 输入选择原厂
身份条目，不能假定其他版本相同。这些命令只生成开发镜像，不能据此认定已经可以
刷写或得到 Ubuntu 桌面；设备使用范围见[试用与恢复](FLASHING.zh-CN.md)。

## 设备包与图形组件

设备内容分为内核、固件、音频、显示电源、设备支持和可选调试包，分别更新。
`erhai-kernel` 选择器精确依赖匹配的版本化镜像/模块包；音频和固件不要求所有包版本相同。

`tools/build-debs.py --help` 列出构建参数。包含启动三件套的构建需要自己的 AVB 签名密钥
与 AOSP avbtool；密钥不进入软件包。固件从仓库读取，来源与分发边界见
[固件说明](../packaging/firmware/README.md)。音频原始源码由
[packaging/audio/source.json](../packaging/audio/source.json)锁定，使用 `--audio-source` 指定。

Mesa 的构建、安装和回退见[图形专项](GRAPHICS.md)。传感器入口为
`tools/build-sensors.py --help`。组件构建的输入、依赖与包行为详见
[英文构建参考](BUILD.md#device-packages)。

沿用上面的内核、DTB 和 initramfs 输出，完整设备包的构建示例为：

```sh
python3 tools/build-debs.py --output out/device-packages \
  --kernel-out "$kernel_out" --dtb out/abl-dtb/erhai-abl.dtb \
  --initramfs out/initramfs/initramfs-ncm.cpio.gz \
  --stock /path/to/stock/images \
  --avb-key /path/to/signing-key.pem --avbtool /path/to/avbtool.py \
  --audio-source /path/to/audioreach-topology-993a17dc.tar.gz
```

所有 `/path/to/` 都需替换为自己的实际输入路径。密钥为 RSA-4096 PEM；原厂目录应包含
构建器要求的匹配启动镜像，不能使用另一个设备或固件版本的备份。


## Ubuntu Desktop 根系统

使用官方 Ubuntu Desktop 26.04 ARM64 ISO 中原始的 `minimal.squashfs` 与
`minimal.standard.squashfs`。装配器按
[packaging/desktop/source.json](../packaging/desktop/source.json)校验输入。

当前装配需要 amd64 主机、rootful Docker、已配置的 ARM64 binfmt、Python 3.11+ 与
dpkg-dev。先拉取清单固定的容器镜像。装配期间容器需要额外的挂载能力；这是可信
本机构建操作，不用于运行未审阅的外部代码。

把同一候选选定的设备 deb 放在独立目录，每个组件只放一个版本：

```sh
args=()
for deb in /path/to/selected-device-packages/*.deb; do
  args+=(--device-deb "$deb")
done
python3 tools/build-desktop-rootfs.py --layers /path/to/iso/casper \
  --output out/desktop-root "${args[@]}"
```

上述命令使用 Bash。输出包括 `rootfs.squashfs`、输入/文件/软件包清单和扩展属性记录。
装配通过官方 APT 包加入运行依赖和设备组件，保留 Ubuntu 正常的软件源。
账户、校准、无线地址与 Android 回退镜像需要在后续安装阶段处理，不进入通用根树。

当前根树装配已经完成离线检查，新的 RAM 桌面启动路径尚未在平板验证。
构建产物不是完整安装包；不要使用旧实验根树或上一版镜像拼接新版本。
