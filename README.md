# iFEM 重构软件

面向逆有限元结构重构的桌面软件原型。当前版本支持二维梁表面应变积分重构、
二维/三维直线与解析圆弧混合路径建模、测点布置、截面应变/应力后处理以及
二维和三维结果显示。

## 启动

macOS 开发环境请使用项目脚本，避免误用缺少三维依赖的 Conda `base` 环境：

```bash
./run_in_venv.sh
```

启动后首先进入项目启动中心，可选择“新建项目”“打开项目”“示例工程”
或进入无测点的空白工作台。开始页右上角可选择“云瓷蓝”“月白青”或“暖砂岩”风格，
工作台内也可通过“更多 > 界面风格…”或 `Ctrl+,` 修改；选择会自动保存，但不会写入
项目文件。关闭启动中心会直接退出程序，不会在后台创建主工作台。

也可以生成无需打开终端的本机 `.app` 启动器，并在桌面建立快捷入口：

```bash
./packaging/macos/build_launcher.sh --desktop
```

双击桌面的“iFEM 重构软件”即可启动，也可将其拖入 Dock。启动器仍调用当前源码，
后续修改程序后只需重新打开，无需重新构建；运行日志位于
`~/Library/Logs/iFEM Reconstruction/launcher.log`。

## 项目库

软件统一使用项目库管理 `.ifemproj` 文件，默认位置为：

```text
~/Documents/iFEM/Projects
```

- 新建项目时先输入项目名称，软件会预留对应的库内路径。
- `Ctrl+S` 保存到当前项目路径；“另存项目”只需输入新的项目名称。
- “打开项目”显示项目库列表、模型摘要和最近修改时间，不再打开系统文件选择器。
- 项目库窗口可直接在文件管理器中显示该目录，也可刷新和搜索项目。
- 开发或部署环境可通过 `IFEM_PROJECTS_DIR` 覆盖默认项目库目录。

旧 JSON 数据仍通过工作台中的数据交换入口导入，不作为项目库项目直接打开。

安装或更新依赖：

```bash
./install_in_venv.sh
```

运行测试：

```bash
QT_QPA_PLATFORM=offscreen \
MPLCONFIGDIR="$PWD/.mplconfig" \
PYTHONDONTWRITEBYTECODE=1 \
  /Users/qiutian/miniconda3/envs/venv/bin/python -m unittest -v
```

## 开发文档

- [总体路线图与实施记录](docs/IFEM_SOFTWARE_ROADMAP.md)
- [实施任务清单与下一切片](docs/IMPLEMENTATION_BACKLOG.md)
- [Qt 界面设计系统](docs/UI_DESIGN_SYSTEM.md)

## 交互建模流程

1. 在启动中心选择“新建项目”，或进入工作台后点击顶部“交互建模”。
2. 先选择“二维建模”或“三维建模”，再选择直线段或解析圆弧段创建起始路径。
3. 使用“追加到末端”逐段组合直线和圆弧；直段支持全局 `±X/±Y/±Z` 或沿末端切线续接，圆弧保持为单个解析实体。
4. 在 XY、XZ、YZ 投影视图中拖动节点，或在属性面板输入精确 `x/y/z` 坐标；二维模型固定在 XY 平面。
5. 使用“拆分梁段”插入节点，或使用“延伸梁段”绘制额外的直线路径段。
6. 可在平面视图添加上下表面测点，也可选择“三维表面测点”后直接在真实梁表面连续点击布点；悬停时预览弧长和环向角，按 `Esc` 退出。
7. 为整根梁选择统一的矩形、圆形、圆管、矩形管或工字形截面，填写尺寸和材料弹性模量，并保存为 `.ifemproj`。
8. 切换“三维预览”可查看截面沿混合路径的扫掠实体；测点红色贴片的长边与双向箭头共同表示测量轴，可分别设置环向位置和轴角。
9. 软件按建模空间、几何类型、单元族和测量类型匹配算法；当前全局 X 轴二维直梁可直接计算，其余模型安全保存并等待相应插件。

测点位置、贴片和测量轴只在输入与建模视图中显示；二维和三维结果视图专注展示结构形态及应变/应力场，不叠加测点布置符号。

## 当前架构入口

- `main.py`：桌面程序入口和启动错误处理。
- `gui_qt.py`：当前 Qt 工作台，后续逐步拆分为独立工作区和控制器。
- `reconstruction.py`：现有二维梁算法实现，架构重构期间保持数值公式不变。
- `ifem/domain`：与界面无关的算法协议和领域类型。
- `ifem/application`：算法调度和应用服务。
- `ifem/algorithms`：逆有限元算法插件及兼容适配器。
- `ifem/modeling`：可测试的梁节点、单元和测点编辑服务。
- `ifem/infrastructure`：项目文件和旧 JSON 兼容转换。
- `ifem/infrastructure/project_library.py`：固定项目库、命名校验和项目索引。
- `ifem/ui/project_library.py`：项目命名与项目库浏览界面。
- `ifem/modeling/path_editor.py`：算法无关的空间梁路径、节点、单元和测点编辑服务。
- `ifem/ui/modeler.py`：直梁、曲梁和空间折线梁交互建模工作区。
- `ifem/ui/modeler_3d.py`：PyVistaQt/VTK 三维几何预览与拾取。
- `visualization_data.py`：结构模型与结果帧的可视化中间层。
- `visualization_3d.py`：PyVistaQt/VTK 三维结果视图，仅显示结构与结果场。
