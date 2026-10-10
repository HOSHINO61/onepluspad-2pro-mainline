# Ubuntu for OnePlus Pad 2 Pro

在一加平板 2 Pro 上运行 Ubuntu Desktop 26.04，采用 GNOME 桌面与基于上游 Linux
的设备适配内核。[English](README.md)

## 📮 关注与交流

项目进展、使用记录与技术交流会在以下渠道更新，欢迎反馈使用中遇到的问题。

| 公众号：熵减矩阵 | 小红书：yzddmr6 |
|:---:|:---:|
| <img src="docs/assets/gzh-qr.png" width="200" alt="公众号：熵减矩阵"> | <img src="docs/assets/xhs-qr.jpg" width="200" alt="小红书：yzddmr6"> |
| 项目进展 · 技术记录 | 使用分享 · 问题交流 |

## ⚠️ 安装前请阅读

- **适用设备**：一加平板 2 Pro，**OPD2413 / erhai / SM8750P**。已测设备为
  **16 GB 内存、512 GB 存储**；OnePlus Pad 3、其他容量、其他固件及分区布局尚未验证。
- **安装范围**：双系统切换已在现有安装布局下验证，尚不提供通用首次安装流程。
  请先阅读[安装与恢复说明](docs/FLASHING.zh-CN.md)，不要直接将切换工具用于未安装的设备。
- **充电与续航**：Linux 下可靠净充电尚未解决，需要返回 Android 充电；Fastboot
  不能作为充电方案。当前日用熄屏只关闭背光，耗电高于正常待机。
- **数据与恢复**：解锁 Bootloader 会清除用户数据。操作前请备份个人文件，准备
  匹配的原厂固件；出厂校准与设备地址必须来自本机，不可跨设备复制。
- **调试访问**：USB 调试通道仅供开发使用，启用后提供免认证 root shell 和 HTTP
  服务。请仅连接可信电脑，不要将其开放到公共网络。

## 🚀 获取与使用

| 我想要 | 入口 |
|---|---|
| 了解目前能用哪些功能 | [硬件支持](#硬件支持) |
| 了解 Android 与 Ubuntu 如何切换 | [双系统切换](#双系统切换) |
| 编译内核与设备组件 | [构建指南](docs/BUILD.zh-CN.md) |
| 查看安装条件与恢复方式 | [安装与恢复说明](docs/FLASHING.zh-CN.md) |
| 开发或调整图形组件 | [图形集成说明](docs/GRAPHICS.md) |
| 贡献代码或反馈问题 | [参与贡献](CONTRIBUTING.md) |

## 双系统切换

在已安装双系统的设备上，Ubuntu 使用独立的 Linux 根分区，Android 保留自己的系统
和数据。日常切换需要重启，不重新安装系统或清空用户文件。

| 当前系统 | 切换方式 |
|---|---|
| Ubuntu → Android | 打开应用列表中的 **Switch to Android（切换到 Android）**，输入管理员密码，等待自动重启。 |
| Android → Ubuntu | 在 KernelSU 中打开 `erhai dual boot switch` 模块的 WebUI，选择 **Reboot to Ubuntu**。 |

两个系统共用同一活动启动槽；已验证的布局使用 A 槽。切换器将目标系统的
`boot`、`init_boot`、`vendor_boot` 三张启动镜像作为一组写入，读回校验后再重启；
另一套系统的镜像保存在 Linux 分区的切换存储区中。日常切换不改变活动槽。

切换过程中会写入启动分区，请勿断电或强制重启。操作条件与恢复方式见
[安装与恢复说明](docs/FLASHING.zh-CN.md)，实现细节见[切换器说明](switch/README.md)。

## 硬件支持

下表列出当前硬件支持与已知限制。“可用”表示已完成所述范围的真机测试；
开发中的功能不计入已支持范围。

✅ 可用 · 🟡 部分支持 · 🔧 开发中／待实测 · ❌ 尚不支持

### 平台、显示与输入

| 功能 | 器件 / 实现 | 状态 | 范围与限制 |
|---|---|---|---|
| 启动与存储 | SM8750P / UFS | ✅ | Ubuntu 启动与存储读写可用；双系统切换限上述已验证布局。 |
| 内置显示 | 双 DSI / DSC | ✅ | 3392 × 2400、120 Hz；其他刷新率待实测。 |
| 触控 | Novatek NT36536 | ✅ | 手指触控、桌面操作与登录已验证；手写笔单独列项。 |
| GPU 与桌面 | Adreno 830 / Freedreno / Mesa | 🟡 | GNOME 桌面已使用 GPU 加速，OpenGL 渲染通过；Vulkan、沙箱应用和持续负载待验。 |
| 手动亮度 | 双 KTZ8868 / 统一背光接口 | 🟡 | 已接入统一亮度接口并验证熄屏联动；桌面滑块的实际亮度范围待验。 |
| 磁吸键盘 | Pogo 键盘 / 触控板 | 🟡 | 键盘输入可用；完整键位、触控板手势及拔下重吸待实测。 |
| 手写笔 | NT36536 笔输入 | 🔧 | 笔输入代码已具备；坐标、压感与按键待实测。 |
| 笔充电 | CPS8601 | ❌ | 充电、电量显示与自动控制笔扫描尚未实现。 |

### 无线与 USB

| 功能 | 器件 / 实现 | 状态 | 范围与限制 |
|---|---|---|---|
| Wi-Fi | WCN7860 / ath12k | ✅ | 联网、开机自动连接及短时传输可用；漫游、热点与长时间传输待实测。 |
| 蓝牙 | WCN7860 / BlueZ | 🟡 | 控制器、固件、扫描与本机地址已验证；键鼠和耳机业务尚未验收。 |
| USB 设备模式 | USB-C / NCM | ✅ | 与电脑的 USB 网络及调试连接已验证；接过外设后重新连接电脑的恢复待实测。 |
| USB 主机外设 | 键鼠、存储、网卡、数字音频 | 🔧 | 常见外设驱动已配置，模拟环境下存储和音频测试通过；平板供电与实物外设待验。 |
| USB 存储格式 | UAS、exFAT、NTFS3 | 🔧 | 模拟环境下读写与 NTFS 中文文件名检查通过；实盘与桌面挂载待验。 |
| 外接显示 | USB-C DisplayPort Alt Mode | 🔧 | 显示输出代码已具备；尚未完成外接显示器实测。 |
| 外屏声音 | DisplayPort / ALSA / PipeWire | 🔧 | 已配置 48 kHz、24 位立体声；识别、播放和热插拔待实测。 |

### 音视频与传感器

| 功能 | 器件 / 实现 | 状态 | 范围与限制 |
|---|---|---|---|
| 内置麦克风 | WCD939x / ALSA / PipeWire | 🟡 | 双通道采集与重复录音通过；语音清晰度、增益和底噪待听音验收。 |
| 扬声器 | 六颗 AW88261 功放 / AudioReach | 🔧 | 播放默认关闭；底层信号测试通过，实际听音、音量和杂音待实测。 |
| USB-C 模拟音频 | WCD939x 耳机通路 | ❌ | 模拟转接头与耳麦检测未实现；数字 USB 音频见上表。 |
| H.264 软件播放 | Ubuntu GStreamer 软件包 | 🔧 | 模拟环境下软件解码通过；平板上的播放器画面和声音待验。 |
| 视频硬件编解码 | Qualcomm Iris | 🔧 | 驱动与固件已接入；硬解、硬编待真机验证。 |
| 前后摄像头 | SC820CS / SC1300CS | ❌ | 摄像、拍照与视频通话尚未实现。 |
| 自动旋转 | SSC / iio-sensor-proxy | 🟡 | 方向传感器已接入桌面；实际横竖屏切换与触控方向待验证。 |
| 自动亮度 | SSC 光感 / GNOME | 🔧 | 光感与桌面接入代码已具备；实际光照响应及亮度变化待验。 |
| 其他传感器 | 陀螺仪、磁力计、接近、霍尔 | ❌ | 完整应用接入尚未实现。 |

### 电源、时间与应用

| 功能 | 器件 / 实现 | 状态 | 范围与限制 |
|---|---|---|---|
| 电源键 | Linux input / GNOME | 🟡 | 实体键熄屏、亮屏已验证；目前只关闭背光，锁屏后再次输入密码的流程待验。 |
| 调频与测温 | SCMI / IIO / thermal | 🟡 | 调频和温度读取可用；持续负载下的温控与机身温度管理仍不完整。 |
| 电池信息 | qcom_battmgr / UPower | ✅ | 可读电量、容量与估计剩余时间；充电能力另列。 |
| Linux 充电 | USB 供电 / 厂商固件 | ❌ | 尚不提供可靠净充电，需要返回 Android 充电。 |
| 挂起与恢复 | Linux 电源管理 | 🟡 | 连接 USB 时定时唤醒通过；电源键唤醒、拔线待机续航及外设恢复待验。 |
| RTC | Qualcomm PMIC RTC | ✅ | 时间读写与已测重启过程中的保持已验证。 |
| Snap 应用 | AppArmor / snapd / 图形运行库 | 🔧 | 兼容适配进行中；完整沙箱与浏览器运行待验。 |
| Android 应用 | Android 运行时 | ❌ | 尚未集成 Waydroid。 |

## 使用与维护

基础系统来自官方 Ubuntu Desktop，设备适配通过独立的 `erhai-*` 软件包交付，Ubuntu
软件包继续由 APT 管理。当前显示电源适配针对 GNOME Settings Daemon 50，桌面大版本
升级需先核对兼容性。

反馈问题时，请提供型号、固件与软件包版本、复现步骤及相关日志。分享前删除凭据、
序列号和个人信息；使用交流可通过顶部的公众号与小红书进行。

## 开发与贡献

| 仓库 | 内容 |
|---|---|
| [onepluspad-2pro-mainline](https://github.com/yzddmr6/onepluspad-2pro-mainline) | 设备包、用户态适配、构建工具与文档 |
| [linux-sm8750-erhai](https://github.com/yzddmr6/linux-sm8750-erhai) | Linux 内核源码、驱动、设备树与内核配置 |

构建使用的内核提交记录在 [kernel/source.json](kernel/source.json)。
构建步骤见[构建指南](docs/BUILD.zh-CN.md)，提交与反馈方式见[参与贡献](CONTRIBUTING.md)。

## 致谢与许可证

本项目基于 Linux、Ubuntu、GNOME、Freedreno/Mesa 和 Linux Qualcomm 社区的成果。
设备适配参考了 [ROCKNIX](https://github.com/ROCKNIX/distribution)、OnePlus 与 LineageOS
的相关工作，并复用了 AudioReach 和 SSC 传感器栈的实现。

除文件另有声明外，项目原创集成代码采用 **GPL-2.0-only**。Linux 内核与第三方组件
保留各自许可证和作者声明。详见 [LICENSE](LICENSE)、[NOTICE](NOTICE) 与
[固件来源及分发限制](packaging/firmware/README.md)。
