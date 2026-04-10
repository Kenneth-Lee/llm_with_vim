#!/bin/bash
# 视觉模型测试脚本

echo "=== llm_with_vim 图像功能测试 ==="
echo ""

# 检查 llava 是否已安装
if ! ollama list | grep -q "llava"; then
    echo "❌ 未找到 llava 模型。正在拉取..."
    ollama pull llava
fi

# 创建测试图片
python3 << 'PYEOF'
from PIL import Image, ImageDraw, ImageFont
try:
    img = Image.new('RGB', (400, 200), color='#4a90d9')
    draw = ImageDraw.Draw(img)
    draw.text((50, 80), "Test Image for LLM", fill="white")
    img.save('/tmp/test_image.png')
    print("✓ 测试图片已创建: /tmp/test_image.png")
except Exception as e:
    print(f"创建图片失败: {e}")
PYEOF

echo ""
echo "=== 测试1: 命令行直接测试 ==="
echo "请运行以下命令测试："
echo ""
echo 'cd work/llm_with_vim && cat << EOF | python3 -m llm_engine'
echo 'Configure: {"engine_type": "ollama", "model": "llava"}'
echo 'System: You are a vision assistant.'
echo 'User: What do you see in this image?'
echo '\$\$/tmp/test_image.png\$\$'
echo 'EOF'
echo ""

echo "=== 测试2: Vim 内测试 ==="
echo "1. 打开 test/llava_test.llm"
echo "2. 按 F1 运行"
echo ""

cat > test_vl.llm <>OF
Configure:  {'engine_type': 'ollama', 'model': 'llava', 'keep_alive': 3600}
System: You are a helpful vision assistant. Look at images and describe them.
User: What can you see in this image?
\$\$/tmp/test_image.png\$\$
EOF

echo "✓ 已创建 test_vl.llm 供 Vim 测试使用"
echo ""
echo "注意:"
echo "- 确保 ollama 服务正在运行: ollama serve"
echo "- llava 模型需要几 GB 空间"
echo "- 第一次加载模型可能较慢，请调大 read_timeout"