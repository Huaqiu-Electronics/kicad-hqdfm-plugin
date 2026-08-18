# HQ DFM KiCad 插件文档

本文档只保留当前代码仍在维护和验证的内容。历史重构计划、旧 KiCad 5/6 核查和已完成的兼容修复草案已移除，避免和实际实现互相打架。

## 文档索引

- [功能总览](./功能总览.md)：用户入口、主流程、规则组、详情定位和 I18N 资源。
- [架构与运行流程](./架构与运行流程.md)：插件启动、KiCad/Gerber 本地分析、规则生效、可见层恢复和定位高亮流程。
- [模块说明](./模块说明.md)：按源码目录说明核心模块职责。
- [数据、接口与规则说明](./数据接口与规则说明.md)：制造文件输出、远端兼容接口、内部结果结构、规则阈值和颜色判定。
- [离线 DFM 规则目录](./离线DFM规则目录.md)：内置规则目录和当前离线检查实现状态。
- [兼容矩阵测试记录](./兼容矩阵测试记录.md)：历史自动验证快照、KiCad 6.0-10.0 结果和发布前检查项。
- [代码审核报告（2026-08-02）](./代码审核报告-2026-08-02.md)：完整仓库审核范围、13 个类目/54 条规则逐项结论、修复和实测记录。
- [代码审核与发布报告（2026-08-12）](./代码审核报告-2026-08-12.md)：当前工作树的完整复审、修复项、KiCad 6/7/10 实测和精简 Release 清单。
- [设计评审报告（2026-08-09）](./设计评审报告-2026-08-09.md)：快速/综合双入口、分析契约、性能优化、缓存边界、风险和验收证据。
- [KiCad API 文档](https://github.com/AskStr/kicad-api-doc)：KiCad `pcbnew` / IPC API、跨版本符号矩阵和迁移参考。

## 当前产品状态

插件在 KiCad PCB Editor 中注册 `HQ DFM` 入口，主窗口提供显式的“快速 DFM 检查”和“综合 DFM 检查”；远端分析代码仅作为兼容路径保留。当前重点保障 KiCad 6.0-10.0 的 SWIG `pcbnew` 兼容。

当前主线能力：

- 快速 DFM 检查只读取当前 KiCad PCB 对象，适合布局迭代；综合 DFM 检查顺序执行 Native、Gerber/Excellon 导出扫描和结果合并，适合生产前确认。
- 分析进度条实时显示当前工作内容，并可用 `Stop Analysis` 停止剩余检查。
- 导出 Gerber 并本地分析，输出到 `HQDMF/Gerber_<PCB文件名>`，并把可量化 Gerber/Drill 结果合并到对应原生检查项。
- Gerber Export 只保留制造文件交付完整性问题，如缺文件、空文件、ZIP、铜层数量、钻孔/map 和板框异常。
- 三组可编辑制造规则：`Basic`、`Standard`、`Advanced`，默认 `Standard`。
- 规则组在主界面用单选按钮选择，分析前即可切换。
- 规则管理窗口可快速编辑规则值，并显示对应语言的规则提示图。
- KiCad 本地实现的检查项覆盖信号完整性、线宽/线距、焊盘尺寸/间距、孔径、孔环、孔距、孔到铜、铜到板边、特殊孔、SMD 焊盘上孔、阻焊少开窗，以及阻焊桥/盖线/覆盖多个网络分析。
- 详情窗口支持按层/问题类型筛选、列表导航、定位和高亮。
- 大批量问题定位会限制选择和标记数量，避免 KiCad 卡死。
- KiCad 6/7 分析完成后自动把 UUID-backed DFM 结果同步为临时原生 DRC marker；KiCad 8+ 不启用该 marker 路线，主界面不显示手动 marker 按钮。
- 主界面提供 `Reset Layers`，可一键显示全部 PCB 层和可见元素；关闭主窗口时恢复进入插件时的可见状态。
- IPC backend 目前是预留能力，主线仍使用 SWIG `pcbnew` backend。
- 简体中文/英文 gettext 文案和语言无关规则图示资源。

## 维护原则

- 以 KiCad 6.0-10.0 自动 smoke test 为当前兼容基线。
- 新增 UI 文案必须进入 `kicad_dfm/language/locale/zh_CN/LC_MESSAGES/kicad_hqdfm_plugin.po`，并运行 `tools/i18n_compile.py`。
- 新增规则说明图只需提供 `kicad_dfm/picture/diagram/<picture_name>.png` 无文字底图，并在 `diagram_catalog.py` 增加标注锚点和说明翻译 key。
- 规则阈值优先级为：当前规则组 > 分析结果内规则 > 内置默认规则。
- 跨平台路径使用 `pathlib/os/tempfile`，不要硬编码 Windows-only 路径到运行时代码。

## 常用验证

```powershell
python -m pytest -q
python tools/verify_i18n.py
python tools/verify_combined_assets.py --assets video --gerber-source existing --compact --fail-fast
python tools/verify_analysis_kicad_versions.py --kicad-root D:\KiCad --board D:\KiCad\6.0\share\kicad\demos\video\video.kicad_pcb --check-profiles
python tools/verify_native_drc_marker_kicad_versions.py --kicad-root D:\KiCad --board D:\KiCad\6.0\share\kicad\demos\video\video.kicad_pcb --versions 6.0 7.0 8.0 9.0 10.0
python tools/verify_detail_locate_kicad_versions.py --kicad-root D:\KiCad --board D:\KiCad\6.0\share\kicad\demos\video\video.kicad_pcb --versions 6.0 7.0 8.0 9.0 10.0 --max-rows-total 8 --max-rows-per-category 2
python tools/verify_locate_ui_windows.py --kicad-root D:\KiCad --board D:\KiCad\6.0\share\kicad\demos\video\video.kicad_pcb --versions 6.0 7.0 8.0 9.0 10.0 --max-categories 2 --max-rows-per-category 2
foreach ($v in '6.0','7.0','8.0','9.0','10.0') {
  python tools/verify_ui_windows.py --kicad-python "D:\KiCad\$v\bin\python.exe" --board D:\KiCad\6.0\share\kicad\demos\video\video.kicad_pcb
}
```

## Release 打包

```powershell
.\script\package_plugin.ps1 -PackageName HQ_DFM_kicad_plugin
```

默认输出 `dist/HQ_DFM_kicad_plugin.zip`。Release 仅包含插件入口、运行时代码、编译后的翻译、规则 JSON 与图片资源；`docs/`、`tests/`、`tools/`、`script/`、wxFormBuilder 源文件、gettext 源文件和 Python 缓存不会进入压缩包。打包脚本会在完成前再次检查这些禁止项。
