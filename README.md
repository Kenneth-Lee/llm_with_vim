# llm\_with\_ai

这是一个用ollama等大模型的api编写故事的脚本，主要用来配合vim使用。对比直接使用
命令行，它的好处在于可以回退问题，也可以更改模型的回答，从而把问答推向需要控制
的方向。

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

如果在输出的过程中需要中止请求，可以按K键（原K键功能被禁止了）。注意这里不要用
Ctrl-C，Ctrl-C仍是打断当前vim操作的功能，这不会中止请求任务。

<F2>映射到outline功能，可以显示一个新窗口给出所有User的位置，你可以通过这个来定
位到特定的问题，只要移动到特定的行然后回车就可以跳转到那个问答上。
