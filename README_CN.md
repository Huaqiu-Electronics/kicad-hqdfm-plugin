# HQ DFM

<p>
    中文 |<a href="README.md">English<a/>
</p>

### 在 KiCad 中 HQ DFM 实现一键分析 PCB 设计隐患

HQ DFM 插件将帮助您：

- 一键分析开短路、断头线、线距线宽等 20 余项设计风险问题
- 自动分析 PCB 设计隐患，排除生产难点、设计缺陷

检查完设计隐患后，您可以使用 HQPCB 插件将其直接添加到您的华秋购物车。
![华秋插件](dfm-screen.gif)

## 功能

### 设计参数分析

HQ DFM 将从您的 KiCad 设计中分析 PCB 中的以下参数：

- 板子层数
- 板子尺寸
- 电气信号
- 最小线宽
- 最小间距
- 最小焊盘
- SMD 间距
- 网格铺铜
- 孔大小
- 孔环
- 孔到孔
- 孔到线
- 板边距离
- 特殊孔
- 孔上焊盘
- 阻焊开窗
- 孔密度
- 沉金面积
- 飞针点数

注意：这些参数从您的 KiCad 设计的 gerber 文件中提取分析。

## 安装

安装最新版本的插件，从主窗口打开“插件和内容管理器”，在插件栏中找到“HQ DFM”。最后，点击“安装”和“应用挂起的更改”
![图片](kicad_dfm/picture/HQDFM.png)

### 关于华秋 DFM

[华秋 DFM](https://dfm.elecfans.com/) 是一款高效的 PCB 设计软件，一键分析设计隐患，提供优化方案，输出 Gerber、BOM、坐标文件，让设计和制造更简单。

您可以使用华秋 DFM 仔细检查您的制造文件，调整电路板参数，然后通过 HQ PCB / NextPCB 将其直接添加到您的华秋购物车。

### 关于华秋 PCB / NextPCB

华秋专注于可靠的多层 PCB 制造和组装，与 KiCad 一样，我们的目标是帮助工程师构建未来的电子产品。 华秋 PCB 正在与 KiCad 合作提供智能工具来简化从设计到物理产品的流程。华秋拥有 3 家主要从事原型设计、批量生产和 PCB 组装的工厂，并拥有超过 15 年的工程专业知识，相信我们的行业经验对于 KiCad 用户和 PCB 设计社区来说将是无价的。

我们是 [KiCad 白金赞助商](https://www.nextpcb.com/blog/kicad-nextpcb-platinum-sponsorship)。



## Kicad-HQ 安装

### Windows

Windows 安装包可以直接使用以下链接下载：
https://www.eda.cn/data/kicad-release/kicad-huaqiu-8.0.6-x86_64.exe.zip

### Linux
Linux 版本需要使用 Flatpak 下载

#### 1，安装 flatpak

`sudo apt install flatpak`

#### 2，将域名映射为特定的 IP 地址

`sudo vim /etc/hosts`

用 vim 去 etc/host 中，加上这行：
`175.6.14.183 kicad.huaqiu.com`

测试是否连接成功：
`ping kicad.huaqiu.com`

#### 3，添加远程kicad仓库

`flatpak remote-add --user repo https://kicad.huaqiu.com/kicadhuaqiu`

查看是否添加成功：
`flatpak remote-ls repo`

如果报错GPG verification,执行步骤 4 ，否则跳过

#### 4，忽略包没签名认证,用 vim 编辑器修改配置

`vim ~/.local/share/flatpak/repo/config`

在文件中修改: `gpg-verify=false`

`flatpak remote-modify --no-gpg-verify repo`

查看是否添加成功：
`flatpak remote-ls repo`

#### 5，安装kicad

`flatpak install repo org.kicad.KiCad`

如果报错缺少依赖，进行下一步“6”。

#### 6，缺少 SDK 依赖，用国内 flathub 镜像仓库，先添加远程仓库，然后安装缺少的依赖：

`sudo flatpak remote-modify flathub --url=https://mirror.sjtu.edu.cn/flathub`

如果缺少org.freedesktop.Sdk/x86_64/23.08：
`flatpak install flathub org.freedesktop.Sdk/x86_64/23.08`

如果缺少org.freedesktop.Sdk//23.08：
`flatpak install flathub org.freedesktop.Sdk//23.08`
