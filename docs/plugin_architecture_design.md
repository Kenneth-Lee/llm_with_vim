# 插件化架构设计文档（plugin-arch）

## 1. 设计目的

我们在[引擎的高层设计逻辑](llm_engine_arch.md#关于功能插件化的思考)进行了一个推
理，尝试看我们能否引入类似dsh的那种通用化的插件机制。结论是我们可以引入插件，但
我们不提供dsh那样的高度灵活，可以让插件自行定义对外接口的插件模式。但我们仍可以
提供插件模式，这样未来引入逻辑完全不同的处理部分，我们可以通过加入插件解决，而
不用在代码中引入额外的分支。

本文的设计包括两个部分：

* 分析当前的架构还有哪些地方需要通过插件化解决
* 设计具体如何提供这些插件

剩下的就是对第二个设计点的展开了。本文的设计起点是2026年11月10日的git库状态。

## 2. 设计逻辑

### 2.1 哪些位置可以插件化

在[引擎的高层设计逻辑](llm_engine_arch.md#关于功能插件化的思考)中我们已经推理过，
处理逻辑相似的我们可以Spec化，处理逻辑差异大的我们就插件化。这是一个有灰度的判断。
我们也用一种“自驱动”的架构演进思路：先进行Spec化，定期审视实现中是否包含太多根
据配置参数走不同分支的模式，在必要的时候再把那个点抽象为插件，直接调用插件。

整个引擎分成如下部分：

* 输入：按不同角色把输入组合带内部表示中，包括对各种引用（@@inc，$image_path$等）
    的解释
* 编码：根据输入和Provider类型，编码成消息。包括把记住的引用和Tool记录进去
* 提交：把编码结果提交LLM
* 输出：解释LLM的返回，输出

审视这四个部分，按用户配置走不同分支的只有一条链路：输入阶段 Configure 行的
tools 列表决定本会话启用哪些工具，编码阶段把这些工具的声明写进请求，而 LLM 返回
的工具调用要由引擎逐一执行——每个工具的执行逻辑各不相同，启用集合又由用户多选。
这正好同时满足“逻辑不同”与“多选”两个插件化条件，所以工具子系统是当前唯一需要
插件化的位置。其余部分的差异都是参数级的，继续按ContextForge的架构定义做Spec化
就可以了。

### 2.2 如何提供插件

插件的本质是某种固定形态的调用接口。所以插件类型可以用一个接口类来表示，比如工
具，我们可以实现一个CFP_Tool接口类（CFP前缀表示ContextForge Plugin），然后我们用
一个json文件描述所有需要的插件，启动的时候先运行每个插件的py文件，把这个接口类
名注册给一个CFPlugin类。之后需要调用这个插件的代码通过
CFPlugin.lookup("plugin_name")找到这种插件的列表，根据具体使用上下文，可以使用
列表中的一个或者使用整个列表。这个逻辑很简单，得到插件类以后，用接口函数调用相
关的功能就行了。

## 3. 核心数据结构

插件机制由三个数据结构承载：插件选择清单（plugins.json）、插件文件（py 模块）、
插件注册表（CFPlugin 内部）。三者的关系是：选择清单决定哪些插件文件被导入，插件
文件在被导入时把自己的名字和服务登记进注册表，使用插件的一方只面对注册表。

**插件选择清单 plugins.json** 回答“哪些插件参与运行”。两个来源：包内
`llm_engine/plugins/plugins.json` 清单内置插件，用户目录
`~/.config/llm-with-vim/plugins.json` 清单用户自己的插件文件，并可用 disable
字段排除内置插件。“写了 10 个只想用 8 个”通过改清单完成，不必动插件文件；包内
清单随 pip 安装只读，用户的选择全部落在自己目录的清单里，与 ContextForge 的配置
分层（L0 内置 / L2 用户全局）一致。

```json
{
  "load": ["my_tool.py", "my_provider.py"],
  "disable": ["bash"]
}
```

**插件文件（py 模块）**一个插件一个文件，身份由文件内的接口类子类携带：
service（注册到哪个服务）、name（服务内唯一名，即 Configure tools 列表中的
名字）、description 与 parameters（给 LLM 看的声明，工具类插件即工具定义）。
工具类插件另有 func_name（LLM 调用时的函数名，缺省与 name 相同），保留两级
命名是为了兼容既有会话记录中的工具名（如 read 与 read_file）。文件被导入时执行
模块级代码完成注册，因此“插件存在”这件事不需要在任何集中清单里重复声明。

**插件注册表（CFPlugin）**是运行期唯一的插件索引，两级结构：
`{服务名: {插件名: 接口类实例}}`。它只回答“有什么服务、每个服务有哪些实现”，
不关心插件来自哪个文件。

工具子系统的现状数据随之收敛：`tool_definitions.json` 与 `TOOL_REGISTRY` 消失，
工具定义变成工具插件的类属性，来源单一化。

## 4. 接口定义

插件作者要写的只有一个接口类子类加一行注册调用。以工具插件为例：

```python
from llm_engine.plugin_loader import CFPlugin, CFP_Tool

class ReadTool(CFP_Tool):
    service = 'tool'
    name = 'read'
    func_name = 'read_file'   # LLM 调用时的函数名，缺省与 name 相同
    description = '读取文件内容'
    parameters = {...}          # JSON schema，形态同原 tool_definitions.json 条目

    def execute(self, arguments, context):
        """执行工具动作。arguments 为 LLM 给出的参数 dict，context 提供运行环境
        （base_dir 等朴素数据）。返回结果字符串，或带标记的 dict（view_image 的
        图片结果，engine.py 会识别）；失败时返回错误串或直接抛 PluginError，
        两种方式都会作为工具结果回给 LLM。"""

CFPlugin.register(ReadTool)
```

不设 setup/teardown：导入即初始化，模块级代码就是 setup；进程退出即销毁。将来
真有跨进程资源需要释放，再在接口类上增加可选方法，不预先建调度机制。

主程序侧的调度接口（新文件 `llm_engine/plugin_loader.py`）：

```python
def load_plugins():
    """读包内与用户目录的 plugins.json，按内置在先、用户在后的顺序导入清单中的
    模块。导入即注册；同一服务下同名插件后注册者覆盖先注册者，因此用户插件可以
    整体替换同名的内置插件。"""

CFPlugin.register(plugin_cls)
    """插件文件模块级调用。service 取类的 service 属性，实例化后登记进注册表。"""

CFPlugin.lookup(service) -> [插件实例]
    """取一个服务的全部插件，用于多选场景（如向 LLM 声明全部可用工具）。"""

CFPlugin.lookup(service, name) -> 插件实例
    """按服务加名字取单个插件，用于单选与分发场景（如执行某个工具）。"""
```

现有对外接口保持不变：tools.py 保留 `get_tool_definitions(tool_names)`、
`get_valid_tool_names(tool_names)`、`get_unknown_tool_names(tool_names)`、
`list_registered_tool_names()`、`execute_tool(func_name, arguments, base_dir)`
五个函数，签名与语义不变，内部改为从注册表取数据与分发；execute_tool 同时接受
LLM 调用名（read_file）与 Configure 工具名（read）；engine.py 的调用点零改动。

整个调用链总结：进程启动时 load_plugins 按选择清单导入插件文件，文件执行时自注册
进 CFPlugin；Configure 行的 tools 列表决定本会话向 LLM 声明哪些工具；LLM 发起
调用时 execute_tool 以 lookup('tool', name) 找到插件实例并调其 execute，结果写回
上下文；进程退出，生命周期结束。两层选择各司其职：plugins.json 决定“装了什么”
（加载期），Configure 决定“这次用哪些”（会话期）。

## 5. 变更历史

| 日期 | 变更内容 | 原因 |
|---|---|---|
| 2026-11-09 | 创建插件化架构设计 | 落实“插件只在多选位置”的架构结论，收口引擎 spec 化遗留分支 |
| 2026-11-10 | 按选择清单加自注册模型重写核心数据结构与接口，去除 setup/teardown | 评审确认 plugins.json 为加载选择清单，注册由插件文件自声明；引擎收口内容移回 ContextForge 文档 |
| 2026-11-10 | 完成工具子系统插件化实现 | 新增 plugin_loader 与九个工具插件，tools.py 变为门面，删除 tool_definitions.json；补记 func_name 两级命名与 execute 返回契约 |
