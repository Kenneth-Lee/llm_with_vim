# llm_with_vim 更新日志

## v2.1.0 (2025-03-31)
### 新增：多模态图像支持
- 新增 `$$图片路径$$` 语法，在 User 消息中嵌入图片
- 支持 Ollama 视觉模型（llava, bakllava 等）
- Vim 插件新增 `<F3>` 快捷键用于预览图片
- 新增图片语法高亮（`$$...$$` 显示为 Special 组）
- 新增 `imgpath` 缩写快速插入图片引用

### 与上游代码合并
- 合并远程的 verbose 调试模式
- 保留 `sys.stdout.flush()` 优化

## v2.0.0 (2025-03-31)
### 新功能：图像支持（初始版本）
- 基础图像解析和 base64 编码
- 多格式支持：PNG/JPEG/GIF/WebP
- 相对路径和绝对路径支持

---

# llm_with_vim Update Log

## v2.1.0 (2025-03-31)
### Added: Multimodal Image Support
- Added `$$image_path$$` syntax for embedding images in User messages
- Support for Ollama vision models (llava, bakllava, etc.)
- Vim plugin: new `<F3>` shortcut for image preview
- Image syntax highlighting (`$$...$$` as Special group)
- New `imgpath` abbreviation for quick image reference

### Merged from upstream
- Merged remote verbose debug mode
- Kept `sys.stdout.flush()` optimization