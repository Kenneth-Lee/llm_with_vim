const vscode = require('vscode');
const { spawn, execFileSync } = require('child_process');
const path = require('path');
const fs = require('fs');

// 使用Map来跟踪每个文档的进程，key是文档URI
let documentProcesses = new Map();

/**
 * 查找llm_engine的执行方式
 * 返回 {cmd, args} 对象
 * 搜索顺序: 1. pip安装的命令 2. 扩展目录脚本 3. 工作区目录
 */
function findLLMEngine() {
    // 1. 检查pip安装的命令（推荐方式）
    try {
        execFileSync('llm_engine', ['--help'], { stdio: 'ignore', timeout: 3000 });
        return { cmd: 'llm_engine', args: [] };
    } catch (e) {
        // 命令不存在或执行失败，继续查找
    }
    try {
        execFileSync('llm-engine', ['--help'], { stdio: 'ignore', timeout: 3000 });
        return { cmd: 'llm-engine', args: [] };
    } catch (e) {
        // 继续查找
    }

    // 2. 尝试 python -m llm_engine
    const pythonPath = process.platform === 'win32' ? 'python' : 'python3';
    try {
        execFileSync(pythonPath, ['-m', 'llm_engine', '--help'], { stdio: 'ignore', timeout: 3000 });
        return { cmd: pythonPath, args: ['-m', 'llm_engine'] };
    } catch (e) {
        // 继续查找
    }

    return null;
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

        // 解析符号链接，获取真实路径
        let realExtensionPath = context.extensionPath;
        try {
            realExtensionPath = fs.realpathSync(context.extensionPath);
        } catch (err) {
            // 如果解析失败，使用原路径
        }

        // 查找llm_engine
        const engineInfo = findLLMEngine();
        if (!engineInfo) {
            vscode.window.showErrorMessage(
                'llm_engine 未找到。请运行: pip install llm-engine'
            );
            return;
        }

        // 获取当前文档的URI作为唯一标识
        const documentUri = document.uri.toString();

        // 如果当前文档已经有正在运行的进程，先停止它
        if (documentProcesses.has(documentUri)) {
            const existingProcess = documentProcesses.get(documentUri);
            if (existingProcess && !existingProcess.killed) {
                existingProcess.kill();
            }
            documentProcesses.delete(documentUri);
        }

        // 生成期间设为只读，防止用户编辑导致内容错乱
        let readOnlyDisposable = null;
        try {
            readOnlyDisposable = vscode.workspace.onWillSaveTextDocument(e => {
                if (e.document.uri.toString() === documentUri) {
                    e.waitUntil(Promise.resolve([]));
                }
            });
            // 使用 VSCode API 禁止编辑（通过拦截输入）
            await vscode.commands.executeCommand('workbench.action.files.setActiveEditorReadonlyInSession');
        } catch (err) {
            // 旧版VSCode可能不支持此命令，忽略
        }

        // 恢复编辑器可写状态的辅助函数
        function restoreWritable() {
            if (readOnlyDisposable) {
                readOnlyDisposable.dispose();
                readOnlyDisposable = null;
            }
            try {
                vscode.commands.executeCommand('workbench.action.files.setActiveEditorWriteableInSession');
            } catch (err) {
                // ignore
            }
        }

        // 显示状态消息
        vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: "正在请求LLM...",
            cancellable: true
        }, (progress, token) => {
            return new Promise((resolve, reject) => {
                // 启动引擎进程
                const fileDir = path.dirname(document.uri.fsPath);
                const spawnEnv = Object.assign({}, process.env, { LLM_FILE_DIR: fileDir });
                const proc = spawn(engineInfo.cmd, engineInfo.args, { env: spawnEnv });
                documentProcesses.set(documentUri, proc);

                let outputBuffer = '';
                let errorBuffer = '';

                // 发送输入
                proc.stdin.write(inputText);
                proc.stdin.end();

                // 处理输出 - 实时更新
                proc.stdout.on('data', (data) => {
                    outputBuffer += data.toString();

                    // 临时恢复可写以更新内容
                    restoreWritable();
                    editor.edit(editBuilder => {
                        // 删除之前的内容
                        const fullRange = new vscode.Range(
                            0, 0,
                            editor.document.lineCount - 1,
                            editor.document.lineAt(editor.document.lineCount - 1).text.length
                        );
                        editBuilder.delete(fullRange);
                        // 插入新内容
                        editBuilder.insert(new vscode.Position(0, 0), outputBuffer);
                    }).then(() => {
                        // 滚动到文档末尾
                        const lastLine = editor.document.lineCount - 1;
                        const lastLineLength = editor.document.lineAt(lastLine).text.length;
                        editor.selection = new vscode.Selection(lastLine, lastLineLength, lastLine, lastLineLength);
                        editor.revealRange(new vscode.Range(lastLine, 0, lastLine, 0));
                        // 重新设为只读
                        try {
                            vscode.commands.executeCommand('workbench.action.files.setActiveEditorReadonlyInSession');
                        } catch (err) { }
                    });
                });

                // 处理错误
                proc.stderr.on('data', (data) => {
                    errorBuffer += data.toString();
                });

                // 处理取消
                token.onCancellationRequested(() => {
                    if (documentProcesses.has(documentUri)) {
                        const proc = documentProcesses.get(documentUri);
                        if (proc && !proc.killed) {
                            proc.kill('SIGTERM');
                            // 1秒后SIGKILL兜底
                            setTimeout(() => {
                                if (proc && !proc.killed) {
                                    try { proc.kill('SIGKILL'); } catch (e) { }
                                }
                            }, 1000);
                        }
                        documentProcesses.delete(documentUri);
                        restoreWritable();
                        reject(new Error('Generation cancelled by user'));
                    }
                });

                // 进程完成
                proc.on('close', (code) => {
                    documentProcesses.delete(documentUri);
                    restoreWritable();

                    if (code === 0) {
                        // 最终确保内容完整
                        editor.edit(editBuilder => {
                            const fullRange = new vscode.Range(
                                0, 0,
                                editor.document.lineCount - 1,
                                editor.document.lineAt(editor.document.lineCount - 1).text.length
                            );
                            editBuilder.delete(fullRange);
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
                proc.on('error', (err) => {
                    documentProcesses.delete(documentUri);
                    restoreWritable();
                    vscode.window.showErrorMessage(`Failed to start LLM process: ${err.message}`);
                    reject(err);
                });
            });
        });
    });

    // 注册停止生成命令
    let stopCommand = vscode.commands.registerCommand('llm-chat.stopGeneration', function () {
        const editor = vscode.window.activeTextEditor;
        if (!editor) {
            vscode.window.showInformationMessage('No active editor');
            return;
        }

        const documentUri = editor.document.uri.toString();
        if (documentProcesses.has(documentUri)) {
            const proc = documentProcesses.get(documentUri);
            if (proc && !proc.killed) {
                proc.kill('SIGTERM');
                // 1秒后SIGKILL兜底
                setTimeout(() => {
                    if (proc && !proc.killed) {
                        try { proc.kill('SIGKILL'); } catch (e) { }
                    }
                }, 1000);
                documentProcesses.delete(documentUri);
                // 恢复可编辑
                try {
                    vscode.commands.executeCommand('workbench.action.files.setActiveEditorWriteableInSession');
                } catch (err) { }
                vscode.window.showInformationMessage('LLM generation stopped');
            } else {
                vscode.window.showInformationMessage('No active LLM generation for this document');
            }
        } else {
            vscode.window.showInformationMessage('No active LLM generation for this document');
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
    // 清理所有正在运行的进程
    for (const [uri, process] of documentProcesses.entries()) {
        if (process && !process.killed) {
            process.kill();
        }
    }
    documentProcesses.clear();
}

module.exports = {
    activate,
    deactivate
}
