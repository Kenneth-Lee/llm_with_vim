# llm\_with\_vim

这是一个简单而有用的LLM API访问引擎。最初的时候，我主要用它实现从vim对ollama进
行访问的。后来慢慢增加其他的LLM API的支持，同时也扩展了对vscode的支持，让它可以
作为vscode的插件安装（请独立参考[vscode/README.md](vscode/README.md)。）

所以，它现在的名字已经有点名不符实的。但不要紧，我们知道是怎么回事就行。

也许很多人都知道，但也许也有很多人不知道：现在的大语言模型都是没有记忆的。它完
成训练以后，内容就固定了，你给它说什么，它都基于你说的话决定返回什么。

所以我们一般理解的和LLM的“对话”，其实是每次都把所有的对话都过程都告诉LLM，LLM都
当作是“一次对话”。这样给了我们一个玩技巧的空间：你不需要为你原来说过的话负责，
你随时可以修改，你也不需要接受LLM说过的话，你也随时可以修改。

比如说你让AI给你写一份简历，AI写完以后你基本上都满意，但你希望你换一个名字，并
且调整一下你的工作经历。你反复给它说明白这个问题其实不容易，还不如你直接编辑它
的回答，让它把这个当作它自己说的，之后你直接提其他更复杂的修改要求。你如果对它
整个回答都不满意，你也可以删掉他这个回答，然后在问题上增加你的额外要求。这样整
个沟通效率就会高得多。

这种方法最大程度扩展了你对AI的控制能力。

![使用截图](screenshot.png)

## 用法

安装方法请具体参考[INSTALL.md](INSTALL.md)，这里主要介绍原理。

程序的主体是一个python程序，llm_engine.py，它要正常工作，需要在同一个目录上有一
个llm_engine.json作为配置。值得修改的主要是下面这个部分：
```
"config": {
        "engine_type": "ollama",
        "server_addr": "default",
        "model": "qwen2.5:1.5b",
        "keep_alive": 3600
}
```
含义也能猜到，基于默认配置修改就可以了。剩下的部分是脚本内部使用的，可以不用动。
其实你甚至没有必要修改这个文件，直接在每个.llm文件中说明这些参数就可以了，除非
你需要设置默认值。

简单的用法是这样：
```
echo "hello" | python llm_engine.py
```
或者
```
python llm_engine.py < chat.llm
```
这会打印输入的内容，然后补上LLM模型的回答。

但这不是这个工程期望的使用的方式，期望的使用的方式是通过vim来编辑这个问答文件，
然后通过热键把文件的一部分发送给服务器完成整个回答。

按INSTALL.md的方法安装插件后，你打开任何.llm文件都会激活插件。

.llm就是个普通文本文件，里面的内容要求是这样的：

```
Configure:  {'engine_type': 'ollama', 'server_addr': 'default',
             'model': 'qwen2.5:0.5b', 'keep_alive': 36,
             'max_tokens': 512, 'temperature': 1}
System: 你是一个中学数学老师，协助我解决一些中学数学问题。
// 这是注释，但每次进行AI交互会删除，主要用于工具提供一些调试信息给使用者
# 这也是注释，不提交给AI，但交互后也不会删除，主要用于使用者自己看
User: 解如下方程：2x^2 + 3x -10=0。
不需要过程解释。
Assistant: ...
User: 有没有其他解法？
....
```
除了User，其他部分都是可选的，System是给整个对话定调，通常用来定义AI的身份认知。
User后面是你的问题，Assistant是LLM的回答。

如果你在某个User后面输入jj，或者在Normal模式按\<F1\>，llm.vim定义的脚本会把从
文件开始到当前User提问的整个上下文提交给LLM，并把LLM的回答显示在当前User问题后
面。（剩下的部分不会改变）

通过这种方法，你可以反复在这个文本文件中修改你和AI的对话过程，持续改进和它的对
话。而这个过程不改变整个对话就是一个简单的文本文件。可以继续用vim的所有编辑功能，
文本处理能力，语法高亮，拼写检查等所有功能。

Configure的部分可以修改默认的llm_engine.json配置，如果你没有这个部分，发出请求的时
候会根据当前配置给你生成一个，你可以基于这个生成的部分修改相关参数。

ollama之外的平台普遍需要apikey，这个可以配置在llm_engine.json的auth\_keys中，但这个
属于主线维护的一部分，升级版本会冲掉，所以更建议配置在每个文本文件的Configure中，
名字叫auth就可以了。比如这样：
```
Configure:  {'engine_type': 'ali', 'auth': 'sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'}
```

如果在输出的过程中需要中止请求，可以按K键（原K键功能被禁止了）。注意这里不要用
Ctrl-C，Ctrl-C仍是打断当前vim操作的功能，这不会中止请求任务。

\<F2\>映射到outline功能，可以显示一个新窗口给出所有User的位置，你可以通过这个来定
位到特定的问题，只要移动到特定的行然后回车就可以跳转到那个问答上。

这样，你用vim编辑任何一个工程，需要LLM配合，就创建一个llm文件，然后在里面控制会
话，结果拷贝回其他文件就行。

## 一些技巧

* 部分引擎（比如ollama）支持引擎查询，如果你不知道模型的名字，可以把模型名字设
  置为TELLME，这样插件会给你返回具体有哪些模型可以用。

* ollama第一次使用某个模型会比较慢，可能因此会超时，可以通过如下Configure参数调
  整超时时间（以秒为单位）：

  * keep_alive=60。定义模型使用后，在内存中保留多久
  * connect_timeout=30。定义连接超时时间
  * read_timeout=1800。定义请求超时时间

* 如果你不知道引擎是什么协议，可以尝试用通用的OpenAI协议去尝试一下，只要引擎的
  名字和标准模型不一样，就会尝试用OpenAI的协议去访问。如果你不确定你的请求是否
  和请求的一致，可以在Configure中加一个"'verbose': True"的参数，这样输出中会包
  含每次llm请求的信息，让你看看是否符合期望。

## 当前支持的引擎

* [Ollama](https://ollama.com/)，参考配置：Configure: {'engine_type': 'ollama',
  'model': 'qwen2.5:0.5b', 'keep_alive': 3600}

* [DeepSeek](https://www.deepseek.com/) ，参考配置：Configure: {'engine_type':
  'deepseek', 'model': 'deepseek-chat', 'auth': 'Bearer sk-xxx'}

* [智谱 AI](https://open.bigmodel.cn/)，参考配置：Configure: {'engine_type':
  'zhipu', 'model': 'glm-4.7', 'auth': 'Bearer your-api-key'}

* [阿里云百炼](https://dashscope.aliyuncs.com/) ，参考配置：Configure:
  {'engine_type': 'ali', 'model': 'deepseek-r1', 'auth': 'Bearer sk-xxx'}

* [海鲸 AI](https://www.atalk-ai.com/) ，参考配置：Configure: {'engine_type':
  'haijing', 'model': 'DeepSeek-R1', 'auth': 'Basic xxx'}

* [llama.cpp](https://github.com/ggerganov/llama.cpp) ，参考配置：Configure:
  {'engine_type': 'llama', 'server_addr': 'localhost:8080'}

* 对于任何兼容 OpenAI API 格式的服务（如 [vLLM](https://github.com/vllm-project/vllm)），
  可以使用任意引擎名称，参考配置：Configure: {'engine_type': 'vllm',
  'server_addr': 'localhost:8000', 'model': 'Qwen/Qwen2.5-7B-Instruct'}
