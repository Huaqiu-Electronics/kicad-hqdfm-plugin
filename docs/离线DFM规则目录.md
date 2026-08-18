# 离线 DFM 规则目录

本文档记录插件内置 DFM 规则目录、规则来源和当前本地实现状态。当前主流程已具备 KiCad 对象本地 DFM 和 Gerber/Drill 本地补充分析；远端 JSON 解析仍作为兼容路径保留。

## 来源与优先级

当前规则按以下优先级使用：

1. 主界面当前选择的规则组，默认 `Standard`。
2. 服务端 DFM JSON 返回的 `rule` 字段。
3. 本地 `kicad_dfm/core/rule_catalog.py` 中的离线规则目录。
4. 没有规则的布尔/拓扑检查使用 `-,-,-`，只表示需要专用几何或连通性算法，不表示数值阈值。

规则组默认值由 `kicad_dfm/core/rule_profiles.py` 根据内置规则生成；可随制造能力分档变化的尺寸类规则会按三档系数缩放。`Pad size`、`Drill to Copper` 和 `Solder Mask Analysis` 等具有明确制造语义的规则使用目录中列出的固定三档值；布尔类、拓扑缺陷类、结构上限类、比例范围类和 SMD 焊盘上孔重叠类规则也保持基准值。用户编辑后的规则保存到 `kicad_dfm/settings/rule_profiles.json`。

规则来源标记：

| 标记 | 含义 |
| --- | --- |
| `official_service_sample` | 来自当前仓库样例 `kicad_dfm/temp.json` 的华秋服务端返回规则 |
| `hqpcb_public_capability` | 来自华秋公开 PCB 制程能力资料，可作为常规板能力边界 |
| `plugin_default` | 插件离线实现推导值或保守默认值，后续需要用更多官方样例校准 |

规则格式：

`rule = 红色阈值, 黄色/推荐阈值, 第三参数`

多数最小值类规则为：实际值小于第一阈值报错，介于第一和第二阈值之间警告，大于等于第二阈值正常。

多数最大值类规则为：实际值大于第一阈值报错，介于第二和第一阈值之间警告，小于等于第二阈值正常。

## 当前离线实现状态

| 类目 | 离线状态 | 说明 |
| --- | --- | --- |
| Signal Integrity | 已实现 | KiCad 本地检查 Trace Mssing、锐角、浮铜、dangling track 端点和未连接 via；Gerber 本地在所有规则组检查 X2 同网断开分量、外层铜锐角、孤立铜、悬空端点、未连接 ViaPad 及 FS 缺失 |
| Smallest Trace Width | 已实现 | KiCad 遍历 track 宽度；Gerber 铜层 aperture 宽度可补充 |
| Smallest Trace Spacing | 已实现 | 同层 track-track、track-pad、pad-pad 距离；Gerber primitive 按对象组合分类补充 |
| SMD Spacing | 已实现 | 独立检查非 BGA 的同层 SMD-SMD 铜外形间距；NetTie 仅按声明组和局部几何附着关系豁免 |
| Pad size | 已实现 | 遍历 pad，直接使用焊盘外形较短一边；长宽比大于 1.2 时归入 Long Pads |
| Hole Size | 已实现 | KiCad PTH/via、盲埋孔/微孔孔径，PTH 孔厚径比及槽孔宽度/长度/长宽比；Excellon 补充最小/最大圆孔、PTH 孔径，并可从 PCB 读取板厚计算孔厚径比；不再执行方孔尺寸子项 |
| RingHole | 已实现 | 遍历 via/PTH，计算孔环；Gerber X2 ViaPad/普通 pad + Excellon 圆孔分别补充 Via/PTH 孔环 |
| Drill Hole Spacing | 已实现 | 孔边到孔边距离；同网/异网 via 分开检查，PTH 仅使用异网 PTH 规则，盲埋孔使用专用规则 |
| Drill to Copper | 已实现 | 外/内层 PTH/via 仅检查到 trace；NPTH 检查全部铜层的 trace、pad 和铺铜，但每个物理孔只输出一条 Drl 层最小结果 |
| Copper-to-Board Edge | 已实现 | 走线、SMD 焊盘、铜皮/zone 到板边；Gerber 铜 primitive 到 EdgeCuts、EdgeCuts 开口可补充 |
| Hole-to-Board Edge | 已实现 | PTH、Via、螺丝孔、NPTH 的真实孔壁到 Edge.Cuts；Gerber/Excellon 可补充，螺丝孔由 PCB footprint 语义识别 |
| Special Drill Holes | 已实现 | 正/长方形孔、半孔；Gerber/Excellon 交叉扫描补充半孔 |
| Holes on SMD Pads | 已实现 | via on SMD/BGA pad、NPTH/PTH on SMD pad |
| Missing SMask Openings | 已实现 | 检查应开窗的 SMD pad 阻焊属性，并检查外层铜区是否存在对应的同侧 F/B.Mask 开窗；不再把正常 pad 开窗误报为缺失 |
| Solder Mask Analysis | 已实现 | 分别检查阻焊桥、阻焊盖线和单个阻焊开窗覆盖多个网络；支持 KiCad PCB 与 Gerber 阻焊层几何 |

## 规则明细

### Signal Integrity

| 子项 | 规则 | 单位 | 来源 | 离线状态 | 实现要点 |
| --- | --- | --- | --- | --- | --- |
| Trace Mssing（网络断连） | `39.370079,39.370079,78.740157` | mm | official_service_sample | implemented | 服务端样例名称疑似拼写为 `Trace Mssing`。KiCad 本地按同网铜对象接触关系构建连通分量，分裂网络按分量间 bbox 距离套用规则；Gerber 分析不把纯 ViaPad 孤岛重复归为网络断连，该情况只报告为未连接过孔。 |
| Acute Angle Traces | `-,-,-` |  | official_service_sample | implemented | 同层同网 track 端点连接且夹角小于 90 度时报错。 |
| Dangling Tracks（悬空端点） | `-,-,-` |  | official_service_sample | implemented | KiCad 本地检查 track 两端是否接触同网 pad、via、track 或铜区；Gerber 本地利用 X2 网络属性检查 Conductor 两端是否接触同网铜对象。缺少网络属性时不猜测，以避免误报。 |
| Floating Copper | `-,-,-` |  | official_service_sample | implemented | KiCad zone 未接触同网 track、pad、via 时判为浮铜；当前以 zone bbox 近似铜区外形。 |
| Unconnected Vias | `-,-,-` |  | official_service_sample | implemented | KiCad 本地检查 via 是否接触同网 track、pad 或铜区；Gerber 本地按位置和网络合并各铜层 ViaPad，并检查是否在任一导出铜层连接同网铜对象。缺少 X2 网络属性时不猜测。 |

### Smallest Trace Width

| 子项 | 规则 | 单位 | 来源 | 离线状态 | 实现要点 |
| --- | --- | --- | --- | --- | --- |
| Smallest Trace Width | `0.127000,0.150000,999.000000` | mm | hqpcb_public_capability | implemented | KiCad 遍历所有 track，Gerber DFM 可从铜层 aperture 宽度补充。 |

### Smallest Trace Spacing

| 子项 | 规则 | 单位 | 来源 | 离线状态 | 实现要点 |
| --- | --- | --- | --- | --- | --- |
| Trace Spacing | `0.127000,0.150000,999.000000` | mm | hqpcb_public_capability | implemented | 同层真实 track 间最短距离；Gerber 仅接受 segment primitive 对，zone/region 不归入此项。 |
| Trace-to-Pad Spacing | `0.127000,0.150000,999.000000` | mm | hqpcb_public_capability | implemented | 同层 track 到 pad 外形最短距离；Gerber trace/pad primitive 间距可补充。 |
| Pad-to-Pad Spacing | `0.127000,0.150000,999.000000` | mm | hqpcb_public_capability | implemented | 同层普通 pad 铜外形边缘到边缘的最短距离；不是中心距。 |
| BGA Pads | `0.100000,0.127000,999.000000` | mm | plugin_default | implemented | BGA pad 铜外形边缘到边缘的最短距离。 |

### SMD Spacing

| 子项 | 规则 | 单位 | 来源 | 离线状态 | 实现要点 |
| --- | --- | --- | --- | --- | --- |
| SMD Pad Spacing | `0.152400,0.203200,0.254000` | mm | plugin_default | implemented | 非 BGA 的同层 SMD pad 铜外形边缘到边缘距离，默认三档为 6/8/10 mil。NetTie 成员只在同一声明组内豁免；普通焊盘必须与同网成员共享铜层，且直接间隙不超过该成员的局部 clearance，才视为局部附着，不会把相关网络全板等价。 |

### Pad size

| 子项 | 规则 | 单位 | 来源 | 离线状态 | 实现要点 |
| --- | --- | --- | --- | --- | --- |
| Short Pads | `0.203200,0.304800,0.508000` | mm | official_service_sample | implemented | 直接计算焊盘外形较短一边 `min(size_x,size_y)`，不扣除钻孔；长宽比不大于 1.2。Gerber flash pad 同样使用外形短边。 |
| Long Pads | `0.152400,0.177800,0.254000` | mm | official_service_sample | implemented | 长宽比大于 1.2 的长条焊盘直接使用外形较短一边，不扣除钻孔；Gerber flash pad 使用相同定义。 |

### Hole Size

| 子项 | 规则 | 单位 | 来源 | 离线状态 | 实现要点 |
| --- | --- | --- | --- | --- | --- |
| Smallest Drill Size | `0.190000,0.250000,0.300000` | mm | hqpcb_public_capability | implemented | 最小Via（过孔），仅检查普通通孔 Via，不包含器件 PTH 与 NPTH Pad；Via通孔过小会影响生产效率和品质良率，建议直径≥0.3 mm。 |
| Smallest PTH | `0.290000,0.450000,999.000000` | mm | official_service_sample | implemented | 最小插件孔，仅检查器件 PTH Pad，不包含 Via 与 NPTH Pad。 |
| Largest Drill Size | `999.000000,6.300000,6.000000` | mm | hqpcb_public_capability | implemented | 远端兼容及 Excellon 通用最大孔径规则。 |
| Largest PTH Size | `999.000000,6.300000,6.000000` | mm | official_service_sample | implemented | 最大 PTH 孔径。 |
| Aspect Ratio | `12.000000,10.000000,8.000000` | ratio | official_service_sample | implemented | 板厚 / PTH 孔径；钻咀直径越小，螺纹长度越短，微小钻刀可能无法钻穿较厚PCB。 |
| Smallest Via [mec] | `0.190000,0.250000,999.000000` | mm | official_service_sample | implemented | 机械过孔孔径。 |
| Smallest Blind_Laser | `0.090000,0.130000,999.000000` | mm | official_service_sample | implemented | KiCad micro/blind via 孔径。 |
| Smallest Blind_mec | `0.190000,0.250000,999.000000` | mm | official_service_sample | implemented | KiCad blind/buried via 且层跨接外层时按机械盲孔孔径。 |
| Smallest Buried_Laser | `0.090000,0.130000,999.000000` | mm | official_service_sample | implemented | KiCad micro via 且层跨不接外层时按激光埋孔孔径。 |
| Smallest Buried_mec | `0.190000,0.250000,999.000000` | mm | official_service_sample | implemented | KiCad blind/buried via 且层跨不接外层时按机械埋孔孔径。 |
| Smallest Slot Width | `0.450088,0.599948,5.999988` | mm | plugin_default | implemented | 默认规则精确换算为17.72/23.62/236.22 mil；KiCad 使用非圆钻孔短轴，Excellon 使用铣刀直径。 |
| Largest Blind/Buried Via | `0.500000,0.400000,0.300000` | mm | official_service_sample | implemented | KiCad blind/buried/micro via 最大孔径。 |
| Largest Slot Length | `15.000000,12.000000,10.000000` | mm | official_service_sample | implemented | KiCad 非圆钻孔长边作为槽长；Excellon 使用 G85 圆心距加刀径得到外形总长；建议槽长≤10 mm。 |
| Largest Slot Width | `8.000000,7.000000,6.000000` | mm | official_service_sample | implemented | 对所有槽孔取最大槽宽：KiCad 使用非圆钻孔短轴，Excellon 使用当前铣刀直径；槽宽过大需要增加生产工序，建议槽宽（刀具直径）≤5.8 mm。 |
| Slot Aspect Ratio | `1.500000,2.000000,999.000000` | ratio | official_service_sample | implemented | 单向下限检查：KiCad 使用非圆钻孔长边/短边，Excellon 使用外形总长/刀径；小于1.5报错，1.5至小于2预警，大于等于2正常。 |

### RingHole

| 子项 | 规则 | 单位 | 来源 | 离线状态 | 实现要点 |
| --- | --- | --- | --- | --- | --- |
| Via Annular Ring | `0.101600,0.127000,0.152400` | mm | hqpcb_public_capability | implemented | 默认规则为 4/5/6 mil；第一档到第二档为警告，第二档到第三档为正常；`(via_width-via_drill)/2`。 |
| PTH Annular Ring | `0.152400,0.177800,0.203200` | mm | hqpcb_public_capability | implemented | 默认规则为 6/7/8 mil；第一档到第二档为警告，第二档到第三档为正常；`(pad_size-drill)/2`，Gerber 圆 pad + Excellon 圆孔可补充。 |

### Drill Hole Spacing

| 子项 | 规则 | 单位 | 来源 | 离线状态 | 实现要点 |
| --- | --- | --- | --- | --- | --- |
| Same Net Via Spacing | `0.254000,0.300000,999.000000` | mm | plugin_default | implemented | 同网络过孔边到边距离；相同网络不会被跳过。 |
| Different Net Via Spacing | `0.254000,0.300000,999.000000` | mm | plugin_default | implemented | 不同网络过孔边到边距离。 |
| Different Net PTH Spacing | `0.400050,0.450088,0.500126` | mm | plugin_default | implemented | 固定默认规则为 15.75/17.72/19.69 mil；不同网络 PTH 孔边到孔边距离，同网 PTH 不套用此规则。孔间距过小会影响生产效率、品质良率，建议最小间距≥15 mil，推荐≥17 mil。 |
| Blind/Buried Via Spacing | `0.254000,0.300000,999.000000` | mm | plugin_default | implemented | 两个 blind/buried/micro via 的孔边到边距离。 |

### Drill to Copper

| 子项 | 规则 | 单位 | 来源 | 离线状态 | 实现要点 |
| --- | --- | --- | --- | --- | --- |
| PTH-to-Trace [Outer] | `0.200000,0.250000,999.000000` | mm | plugin_default | implemented | PTH 孔边到外层走线；明确排除 pad flash 和铺铜/region。Gerber/Excellon 使用镀孔与 Conductor/draw 配对补充。 |
| PTH-to-Trace [Inner] | `0.250000,0.300000,999.000000` | mm | plugin_default | implemented | PTH 孔边到内层走线；明确排除 pad 和铺铜。 |
| Via-to-Trace [Outer] | `0.200000,0.250000,999.000000` | mm | plugin_default | implemented | 过孔边到外层走线；明确排除 pad 和铺铜。 |
| Via-to-Trace [Inner] | `0.250000,0.300000,999.000000` | mm | plugin_default | implemented | 过孔边到内层走线；明确排除 pad 和铺铜。 |
| NPTH-to-Copper | `0.200000,0.250000,999.000000` | mm | plugin_default | implemented | NPTH 孔边到全部铜层对象，包括走线、焊盘和铺铜；内部跨层寻找全局最小值，每个物理 NPTH 只输出一条 `Drl` 层结果，命中铜层保留在 related 证据中。 |

### Copper-to-Board Edge

| 子项 | 规则 | 单位 | 来源 | 离线状态 | 实现要点 |
| --- | --- | --- | --- | --- | --- |
| SMD-to-Board Edge | `0.254000,0.381000,0.508000` | mm | official_service_sample | implemented | 真实 SMD pad 外形到 EdgeCuts 中心线的最小距离；排除 ViaPad 和带钻 PTH pad。复合焊盘按 X2 object/flash 与连通关系整体分类，每个逻辑 SMD 仅保留最小板边间距。 |
| Trace-to-Board Edge | `0.203000,0.279000,0.381000` | mm | official_service_sample | implemented | 仅非 flash 的 `Conductor` 真实走线；按线段中心线到 EdgeCuts 的距离减去半线宽，region/zone/pad 不进入该项。 |
| Copper-to-Board Edge | `0.203000,0.279000,0.381000` | mm | official_service_sample | implemented | 铜皮/zone、Via、PTH 等通用铜对象外形到 EdgeCuts 中心线的最小距离；复合 PTH 按一个逻辑焊盘输出。板框圆弧弦高误差不超过 0.001 mm，支持凹边和内轮廓。 |

### Hole-to-Board Edge

| 子项 | 默认规则 | 单位 | 来源 | 离线状态 | 规则描述与实现要点 |
| --- | --- | --- | --- | --- | --- |
| PTH-to-Board Edge（插件孔到板边） | `0.400050,0.500126,0.599948`（15.75/19.69/23.62 mil） | mm | official_service_sample | implemented | PTH孔距离板边过近存在破孔的风险，严重时影响电气性能，建议≥12mil，推荐≥15mil。按镀孔真实孔壁到最近 Edge.Cuts 计算。 |
| Via-to-Board Edge | `0.299974,0.400050,0.500126`（11.81/15.75/19.69 mil） | mm | official_service_sample | implemented | Via孔距离板边过近存在破孔的风险，严重时影响电气性能，建议≥12mil，推荐≥15mil。KiCad 由 Via 对象识别；Excellon 由 `ViaDrill` 识别。 |
| Screw Hole-to-Board Edge（螺丝孔到板边） | `0.400050,0.500126,0.599948`（15.75/19.69/23.62 mil） | mm | official_service_sample | implemented | 螺丝孔距离板边过近存在破孔的风险，建议≥8mil，推荐≥12mil。只依据 PCB mounting/screw footprint 语义识别，不按孔径猜测。 |
| NPTH-to-Board Edge | `0.199898,0.299974,0.400050`（7.87/11.81/15.75 mil） | mm | official_service_sample | implemented | NPTH孔距离板边过近存在破孔的风险，建议≥8mil，推荐≥12mil。无螺丝孔语义的非镀孔归入本项。 |

圆孔使用孔心到板边距离减半径；槽孔使用旋转后长圆孔中心线到板边距离减刀径半径。KiCad 后端使用有效孔形碰撞距离，Gerber 后端使用 Excellon 圆/槽 primitive 与 EdgeCuts 线段的精确几何距离；均不以外接矩形代替孔形。

### Special Drill Holes

| 子项 | 规则 | 单位 | 来源 | 离线状态 | 实现要点 |
| --- | --- | --- | --- | --- | --- |
| Square/Rectangular Drills | `-,-,-` |  | official_service_sample | implemented | 仅在孔形状明确包含直角时报告；KiCad 标准长圆槽和 Excellon G85/铣槽均为圆角槽，不按正/长方形孔报告。生产过程正/长方孔的直角无法加工出来，建议改为圆形或椭圆形。 |
| Castellated Holes | `-,-,-` |  | official_service_sample | implemented | 孔中心到板框距离小于等于孔半径时识别为半孔。 |

### Holes on SMD Pads

| 子项 | 规则 | 单位 | 来源 | 离线状态 | 实现要点 |
| --- | --- | --- | --- | --- | --- |
| Via on BGA Pad | `0.010000,0.010000,0.000000` | mm | official_service_sample | implemented | BGA pad 内过孔重叠。 |
| Via on SMD Pad | `0.150000,0.050000,0.000000` | mm | official_service_sample | implemented | SMD pad 内过孔重叠；Gerber pad + Excellon 孔重叠可补充。 |
| NPTH on SMD Pad | `0.100000,0.010000,0.000000` | mm | official_service_sample | implemented | SMD pad 内 NPTH 重叠；检查孔贯穿的两侧铜层且不因网络不同而跳过。 |
| PTH on SMD Pad | `0.100000,0.050000,0.000000` | mm | official_service_sample | implemented | SMD pad 内 PTH 重叠；检查孔贯穿的两侧铜层且不因网络不同而跳过。 |

### Missing SMask Openings

| 子项 | 规则 | 单位 | 来源 | 离线状态 | 实现要点 |
| --- | --- | --- | --- | --- | --- |
| Missing SMask Opening | `-,-,-` |  | official_service_sample | implemented | 检查外层 SMD pad 的阻焊开窗属性，以及外层铜区是否匹配同侧 F/B.Mask 开窗；正常 pad 开窗不报错。 |

### Solder Mask Analysis

| 子项 | 规则 | 单位 | 来源 | 离线状态 | 实现要点 |
| --- | --- | --- | --- | --- | --- |
| Solder Mask Bridge | `0.127000,0.152400,0.254000` | mm | official_service_sample | implemented | 检查相邻阻焊开窗之间保留的最窄阻焊桥；KiCad 使用同侧 pad 开窗几何，Gerber 使用 F/B.Mask 可见开窗。 |
| Solder Mask Covers Trace | `0.038100,0.050800,0.063500` | mm | official_service_sample | implemented | 对具有预期 pad 网络的开窗，检查开窗边缘到其它网络外层走线的间距，识别可能额外暴露异网走线的盖线异常。 |
| Solder Mask Covers Multiple Nets | `-,-,-` |  | official_service_sample | implemented | 检查同一阻焊开窗是否同时覆盖两个或更多不同网络的铜对象；缺少可靠网络信息时不猜测。 |

## 离线实现路线

Gerber/Excellon 制造文件不保证携带板厚、完整盲埋孔层跨和 BGA footprint 类型。缺少这些语义时，Gerber 分析不会把普通孔猜成盲埋孔，也不会推导板厚长宽比；相关专项以 KiCad PCB 对象分析为准。

1. 持续扩展 Gerber 铜多边形级连通图和阻焊层多边形精确匹配能力。
2. 继续补齐需要完整 Gerber/Excellon 几何融合或层跨拓扑的专项分类。
3. 保持 Gerber/Drill 本地扫描和 KiCad 对象检查的结果都映射到同一规则目录。
4. 保留服务端回归样例：每次离线算法改动后，用服务端 JSON 样例比对类别、子项、颜色、定位能力。

## 注意

华秋服务端规则可能随工艺和下单参数变化。维护 `RULE_CATALOG` 时，应保留“当前规则组 > 结果内规则 > 本地默认规则”的优先级，并确保三档规则组切换后重新判色。
