# llm\_with\_ai

这是一个用ollama等大模型的api编写故事的脚本，主要用来配合vim使用。对比直接使用
命令行，它的好处在于可以回退问题，也可以更改模型的回答，从而把问答推向需要控制
的方向。

![使用截图](screenshot.png)

## 用法

首先是配置，默认的配置在当前目录的config.json中，主要要配置的是下面这个部分：
```
"config": {
        "engine_type": "ollama",
        "server_addr": "default",
        "model": "qwen2.5:1.5b",
        "keep_alive": 3600
}
```
含义也能猜到，直接看看默认的config.json就可以了。剩下的部分是脚本内部使用的，可
以不用动。

简单的用法是这样：
```
echo "hello" | python llama.py
python llama.py < chat.txt
```
这会打印输入的内容，然后补上LLM模型的回答。

但这不是这个工程期望的使用的方式，期望的使用的方式是通过vim来编辑这个问答文件，
然后通过随时编辑这个文件来给LLM发请求。

比如，现在需要和某个LLM模型对话了，你只要用vim打开一个.txt文件，然后在里面
```
:source local.vim
```

这个动作其实应该可以自动化的，比如可以在~/.vimrc最后加上这一段：
```
if filereadable("local.vim")
    source local.vim
endif
```
这样你包含这个local.vim中进入vim，它就自动生效了。

之后.txt文件里面的内容要求是这样的：
```
Configure:  {'engine_type': 'ollama', 'server_addr': 'default',
             'model': 'qwen2.5:0.5b', 'keep_alive': 36,
             'max_tokens': 512, 'temperature': 1}
System: 你是一个中学数学老师，协助我解决一些中学数学问题。
// 这是注释
User: 解如下方程：2x^2 + 3x -10=0。
不需要过程解释。
Assistant: ...
User: ....
....
```
除了User，其他部分都是可选的，System是给整个对话定调。User后面是你的问题，
Assistant是LLM的回答。

如果你在某个User后面输入jj，或者在Normal模式按\<F1\>，local.vim定义的脚本会把从
文件开始到当前User提问的整个上下文提交给LLM，并把LLM的回答显示在当前User问题后
面。（剩下的部分不会改变）

通过这种方法，你可以反复在这个文本文件中修改你和AI的对话过程，持续改进和它的对
话。而这个过程不改变整个对话就是一个简单的文本文件。可以继续用vim的所有编辑功能，
文本处理能力，语法高亮，拼写检查等所有功能。

Configure的部分可以修改默认的config.json配置，如果你没有这个部分，发出请求的时
候会根据当前配置给你生成一个，你可以基于这个生成的部分修改相关参数。

ollama之外的平台普遍需要apikey，这个可以配置在config.json的auth\_keys中，但这个
属于主线维护的一部分，升级版本会冲掉，所以更建议配置每个文本文件的Configure中，
名字叫auth就可以了。比如这样：
```
Configure:  {'engine_type': 'ali', 'auth': 'sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'}
```

如果在输出的过程中需要中止请求，可以按K键（原K键功能被禁止了）。注意这里不要用
Ctrl-C，Ctrl-C仍是打断当前vim操作的功能，这不会中止请求任务。

\<F2\>映射到outline功能，可以显示一个新窗口给出所有User的位置，你可以通过这个来定
位到特定的问题，只要移动到特定的行然后回车就可以跳转到那个问答上。

## FAQ

Q：为什么不做成vim插件？

A：插件是全局的，这个工具更像是个独立的应用，只是借用了一下vim的编程能力而已，
没有必要做成插件。当然我也不反对你移植成插件。

Q：为什么不遵循某种标准的api标准？

A：我的目的是解决问题，现在都是我要用哪个平台我就适配那个平台（也欢迎其他开发者
增加自己的平台），如果事实上这些平台有标准，它自然会统一，否则就由着它这样吧。

Q：为什么不适配到vscode上？

A：问得好，因为我没空，而且vscode我用得很少。所以……还是欢迎其他开发者适配到
vscode上的。

Q：为什么不解释一下config.json的其他域？

A：那些你可以认为是代码的一部分，主要是用来处理别名的（比如你选了引擎，默认的
api地址可以不用配置之类的）。这个主要是图我自己的方便，你不修改它们不影响使用。
所以，有修改这些东西的需要，就自己看看代码吧——反正这个代码也不长。

# 详细配置逻辑

在llama.py中，向LLM Server发出请求的参数都设置在history中，这个对于不同的引擎是
不一样的，通用的配置放在config.json的default\_config中，初值也在这里，然后全局
的配置，在config.json的config中可以覆盖它，而且config还可以放非通用的配置，最后，
每个单独的会话的“Config:”行，覆盖这个config的配置。

## 已知问题

* 我在llama.py中调用了str.removeprefix，这是Python 3.9才有的函数，如果你用的版
  本比这个旧，麻烦自己修改一下，实现一下这个函数。

## Security Considerations

* **API Keys**: Store API keys securely and never commit them to version control. Consider using environment variables or secure credential managers instead of storing keys directly in config.json.
* **Configuration Validation**: Configuration values are now validated to prevent code injection and command execution attacks.
* **Input Sanitization**: The tool validates user inputs to prevent malicious payloads from being processed.
* **Timeout Handling**: API requests now have timeout limits to prevent hanging connections.

## Best Practices

* Regularly update dependencies to patch security vulnerabilities
* Review and audit configuration files for sensitive information
* Use strong authentication methods for API access
* Monitor API usage for unusual patterns
