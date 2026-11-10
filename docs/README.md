# 文档目录说明

本目录主要存放本项目本身的设计文档。注意和编辑器插件本身的文档区分，比如../vim
用于保存vim插件，里面的doc目录存放的是插件的文档，和这里的设计文档无关。

现在的主要设计文档包括：

* [引擎的高层设计逻辑](llm_engine_arch.md)
* [ContextForge 架构重构设计文档](contextforge_architecture_design.md)
* [ContextForge 自解释与新手引导设计文档](contextforge_guided_assistance_design.md)
* [ContextForge Provider 新增与接入指南](contextforge_provider_onboarding_guide.md)
* [上下文稳定提交与缓存命中优化设计文档](context_submission_consistency_design.md)，这是针对如何提高服务器KV-Cache命中率的设计文档。
* [@@inc原语的设计思路](inc_directive.md)
* [插件化设计](plugin_architecture_design.md)

其中ContextForge是本项目进入架构标准化的项目名称，目的是建立一个可以编辑上下文
的Agent。和其他自动生成提交上下文的Agent思路不同，本项目的目的就是让用户直接看
到提交的全部上下文，知道自己提交了什么，从而对LLM进行精细的控制。
