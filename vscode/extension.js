const vscode = require('vscode');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

let currentProcess = null;

/**
 * 查找llm_engine.py的路径
 * 搜索顺序: 1. 扩展目录 2. 扩展父目录 3. PATH环境变量
 */
function findLLMEngine(extensionPath) {
    // 1. 检查扩展目录
    let enginePath = path.join(extensionPath, 'llm_engine.py');
    if (fs.existsSync(enginePath)) {
        return enginePath;
    }

    // 2. 检查扩展父目录
    enginePath = path.join(extensionPath, '..', 'llm_engine.py');
    if (fs.existsSync(enginePath)) {
        return enginePath;
    }

    // 3. 检查PATH中是否有llm_engine.py
    // 尝试在当前工作目录
    if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
        enginePath = path.join(vscode.workspace.workspaceFolders[0].uri.fsPath, 'llm_engine.py');
        if (fs.existsSync(enginePath)) {
            return enginePath;
        }
    }

    return null;
}

/**
 * 检查Python环境
 */
function checkPythonEnvironment(pythonPath, scriptPath) {
    return new Promise((resolve, reject) => {
        const testProcess = spawn(pythonPath, ['-c', 'import requests; import json']);

        let errorOutput = '';
        testProcess.stderr.on('data', (data) => {
            errorOutput += data.toString();
        });

        testProcess.on('close', (code) => {
            if (code === 0) {
                resolve(true);
            } else {
                reject(new Error('Python环境缺少必需的包。请运行: pip install requests'));
            }
        });

        testProcess.on('error', (err) => {
            reject(new Error(`无法启动Python: ${err.message}`));
        });
    });
}

/**
 * @param {vscode.ExtensionContext} context
 */
function activate(context) {
    console.log('LLM Chat Assistant extension is now active');

    // 创建状态栏项，显示扩展已激活
    const statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBarItem.text = "$(comment-discussion) LLM Chat";
    statusBarItem.tooltip = "LLM Chat Assistant 已激活";
    context.subscriptions.push(statusBarItem);

    // 监听活动编辑器变化，仅在.llm文件中显示状态栏
    function updateStatusBar() {
        const editor = vscode.window.activeTextEditor;
        if (editor && editor.document.languageId === 'llm-chat') {
            statusBarItem.show();
        } else {
            statusBarItem.hide();
        }
    }

    // 初始更新和监听器
    updateStatusBar();
    vscode.window.onDidChangeActiveTextEditor(updateStatusBar, null, context.subscriptions);

    // 显示激活消息（仅在打开.llm文件时）
    vscode.window.onDidChangeActiveTextEditor((editor) => {
        if (editor && editor.document.languageId === 'llm-chat') {
            vscode.window.showInformationMessage('LLM Chat Assistant 已激活');
        }
    }, null, context.subscriptions);

    // 注册提交查询命令
    let submitCommand = vscode.commands.registerCommand('llm-chat.submitQuery', async function () {
        const editor = vscode.window.activeTextEditor;
        if (!editor) {
            vscode.window.showErrorMessage('No active editor');
            return;
        }

        const document = editor.document;
        const currentLine = editor.selection.active.line;

        // 获取从文档开头到当前行的所有文本
        const range = new vscode.Range(0, 0, currentLine, document.lineAt(currentLine).text.length);
        const inputText = document.getText(range);

        // 找到Python可执行文件路径
        const pythonPath = process.platform === 'win32' ? 'python' : 'python3';

        // 解析符号链接，获取真实路径
        let realExtensionPath = context.extensionPath;
        try {
            realExtensionPath = fs.realpathSync(context.extensionPath);
        } catch (err) {
            // 如果解析失败，使用原路径
        }

        // 查找llm_engine.py
        const scriptPath = findLLMEngine(realExtensionPath);
        if (!scriptPath) {
            vscode.window.showErrorMessage(
                'llm_engine.py 未找到。请将其放在扩展目录、工作区根目录或PATH中。'
            );
            return;
        }

        // 检查Python环境
        try {
            await checkPythonEnvironment(pythonPath, scriptPath);
        } catch (err) {
            vscode.window.showErrorMessage(`环境检查失败: ${err.message}`);
            return;
        }

        // 显示状态消息
        vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: "正在请求LLM...",
            cancellable: true
        }, (progress, token) => {
            return new Promise((resolve, reject) => {
                // 启动Python进程
                const cwd = path.dirname(scriptPath);
                currentProcess = spawn(pythonPath, [scriptPath], { cwd });

                let outputBuffer = '';
                let errorBuffer = '';

                // 发送输入
                currentProcess.stdin.write(inputText);
                currentProcess.stdin.end();

                // 处理输出
                currentProcess.stdout.on('data', (data) => {
                    outputBuffer += data.toString();
                });

                // 处理错误
                currentProcess.stderr.on('data', (data) => {
                    errorBuffer += data.toString();
                });

                // 处理取消
                token.onCancellationRequested(() => {
                    if (currentProcess) {
                        currentProcess.kill();
                        currentProcess = null;
                        reject(new Error('Generation cancelled by user'));
                    }
                });

                // 进程完成
                currentProcess.on('close', (code) => {
                    currentProcess = null;

                    if (code === 0) {
                        // 删除当前内容，替换为输出
                        editor.edit(editBuilder => {
                            editBuilder.delete(range);
                            editBuilder.insert(new vscode.Position(0, 0), outputBuffer);
                        }).then(() => {
                            // 在末尾添加新的User提示
                            const lastLine = editor.document.lineCount;
                            editor.edit(editBuilder => {
                                editBuilder.insert(new vscode.Position(lastLine, 0), '\nUser: ');
                            });
                        });
                        resolve();
                    } else {
                        vscode.window.showErrorMessage(`LLM process exited with code ${code}: ${errorBuffer}`);
                        reject(new Error(errorBuffer));
                    }
                });

                // 处理进程错误
                currentProcess.on('error', (err) => {
                    currentProcess = null;
                    vscode.window.showErrorMessage(`Failed to start LLM process: ${err.message}`);
                    reject(err);
                });
            });
        });
    });

    // 注册停止生成命令
    let stopCommand = vscode.commands.registerCommand('llm-chat.stopGeneration', function () {
        if (currentProcess) {
            currentProcess.kill();
            currentProcess = null;
            vscode.window.showInformationMessage('LLM generation stopped');
        } else {
            vscode.window.showInformationMessage('No active LLM generation');
        }
    });

    // 注册显示大纲命令
    let outlineCommand = vscode.commands.registerCommand('llm-chat.showOutline', async function () {
        const editor = vscode.window.activeTextEditor;
        if (!editor) {
            vscode.window.showErrorMessage('No active editor');
            return;
        }

        const document = editor.document;
        const text = document.getText();
        const lines = text.split('\n');

        // 找到所有User和Configure行
        const items = [];
        for (let i = 0; i < lines.length; i++) {
            const line = lines[i];
            if (line.startsWith('User: ') || line.startsWith('Configure: ')) {
                items.push({
                    label: line.substring(0, 60) + (line.length > 60 ? '...' : ''),
                    description: `Line ${i + 1}`,
                    lineNumber: i
                });
            }
        }

        if (items.length === 0) {
            vscode.window.showInformationMessage('No User queries found');
            return;
        }

        // 显示快速选择
        const selected = await vscode.window.showQuickPick(items, {
            placeHolder: 'Select a query to jump to'
        });

        if (selected) {
            const position = new vscode.Position(selected.lineNumber, 0);
            editor.selection = new vscode.Selection(position, position);
            editor.revealRange(new vscode.Range(position, position), vscode.TextEditorRevealType.InCenter);
        }
    });

    context.subscriptions.push(submitCommand);
    context.subscriptions.push(stopCommand);
    context.subscriptions.push(outlineCommand);
}

function deactivate() {
    if (currentProcess) {
        currentProcess.kill();
        currentProcess = null;
    }
}

module.exports = {
    activate,
    deactivate
}
