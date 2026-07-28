const vscode = require('vscode');
const { spawn, execFileSync } = require('child_process');
const path = require('path');
const fs = require('fs');

// 使用Map来跟踪每个文档的进程，key是文档URI
let documentProcesses = new Map();
let firstOpenHintShown = false;

function findLLMEngine() {
    try {
        execFileSync('llm_engine', ['--help'], { stdio: 'ignore', timeout: 3000 });
        return { cmd: 'llm_engine', args: [] };
    } catch (e) {}
    try {
        execFileSync('llm-engine', ['--help'], { stdio: 'ignore', timeout: 3000 });
        return { cmd: 'llm-engine', args: [] };
    } catch (e) {}

    const pythonPath = process.platform === 'win32' ? 'python' : 'python3';
    try {
        execFileSync(pythonPath, ['-m', 'llm_engine', '--help'], { stdio: 'ignore', timeout: 3000 });
        return { cmd: pythonPath, args: ['-m', 'llm_engine'] };
    } catch (e) {}

    return null;
}

async function submitQueryImpl(appendMode) {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
        vscode.window.showErrorMessage('No active editor');
        return;
    }

    const document = editor.document;
    const cursorLine = editor.selection.active.line;
    const range = new vscode.Range(0, 0, cursorLine, document.lineAt(cursorLine).text.length);
    const inputText = document.getText(range);

    const engineInfo = findLLMEngine();
    if (!engineInfo) {
        vscode.window.showErrorMessage('llm_engine 未找到。请运行: pip install llm-engine');
        return;
    }

    const documentUri = document.uri.toString();
    if (documentProcesses.has(documentUri)) {
        const existingProcess = documentProcesses.get(documentUri);
        if (existingProcess && !existingProcess.killed) {
            existingProcess.kill();
        }
        documentProcesses.delete(documentUri);
    }

    const modeLabel = appendMode ? '追加模式' : '替换模式';

    vscode.window.withProgress({
        location: vscode.ProgressLocation.Notification,
        title: "正在请求LLM (" + modeLabel + ")...",
        cancellable: true
    }, (progress, token) => {
        return new Promise((resolve, reject) => {
            const fileDir = path.dirname(document.uri.fsPath);
            const spawnEnv = Object.assign({}, process.env, { LLM_FILE_DIR: fileDir });
            const procArgs = appendMode ? engineInfo.args.concat(['--append']) : engineInfo.args;
            const proc = spawn(engineInfo.cmd, procArgs, { env: spawnEnv });
            documentProcesses.set(documentUri, proc);

            let outputBuffer = '';
            let errorBuffer = '';
            let lineBuffer = '';
            let insertLine = cursorLine + 1;
            let editInProgress = false;
            let pendingWrite = false;
            let generationDone = false;

            function flushLines(callback) {
                if (editInProgress) {
                    pendingWrite = true;
                    return;
                }
                let lines = lineBuffer.split('\n');
                let complete = lines.slice(0, -1);
                let lastIncomplete = lines[lines.length - 1];
                if (complete.length === 0) {
                    if (callback) callback();
                    return;
                }

                editInProgress = true;
                pendingWrite = false;
                let textToInsert = complete.join('\n') + '\n';
                lineBuffer = lastIncomplete;

                editor.edit(editBuilder => {
                    editBuilder.insert(new vscode.Position(insertLine, 0), textToInsert);
                }).then(() => {
                    insertLine += complete.length;
                    editInProgress = false;
                    const lastInsertedLine = insertLine - 1;
                    if (lastInsertedLine < editor.document.lineCount) {
                        const lastLen = editor.document.lineAt(lastInsertedLine).text.length;
                        editor.selection = new vscode.Selection(lastInsertedLine, lastLen, lastInsertedLine, lastLen);
                        editor.revealRange(new vscode.Range(lastInsertedLine, 0, lastInsertedLine, 0));
                    }
                    if (callback) callback();
                    if (pendingWrite) flushLines();
                });
            }

            proc.stdin.write(inputText);
            proc.stdin.end();

            if (appendMode) {
                proc.stdout.on('data', (data) => {
                    if (generationDone) return;
                    lineBuffer += data.toString();
                    flushLines();
                });
            } else {
                proc.stdout.on('data', (data) => {
                    if (generationDone) return;
                    outputBuffer += data.toString();
                    editor.edit(editBuilder => {
                        const fullRange = new vscode.Range(
                            0, 0,
                            editor.document.lineCount - 1,
                            editor.document.lineAt(editor.document.lineCount - 1).text.length
                        );
                        editBuilder.delete(fullRange);
                        editBuilder.insert(new vscode.Position(0, 0), outputBuffer);
                    }).then(() => {
                        const lastLine = editor.document.lineCount - 1;
                        const lastLineLength = editor.document.lineAt(lastLine).text.length;
                        editor.selection = new vscode.Selection(lastLine, lastLineLength, lastLine, lastLineLength);
                        editor.revealRange(new vscode.Range(lastLine, 0, lastLine, 0));
                    });
                });
            }

            proc.stderr.on('data', (data) => {
                errorBuffer += data.toString();
            });

            token.onCancellationRequested(() => {
                if (documentProcesses.has(documentUri)) {
                    const proc = documentProcesses.get(documentUri);
                    if (proc && !proc.killed) {
                        proc.kill('SIGTERM');
                        setTimeout(() => {
                            if (proc && !proc.killed) {
                                try { proc.kill('SIGKILL'); } catch (e) { }
                            }
                        }, 1000);
                    }
                    documentProcesses.delete(documentUri);
                    generationDone = true;
                    reject(new Error('Generation cancelled by user'));
                }
            });

            proc.on('close', (code) => {
                generationDone = true;
                documentProcesses.delete(documentUri);

                if (code !== 0) {
                    if (appendMode) {
                        const applyErrorBlock = () => {
                            const rawLines = (errorBuffer || `LLM process exited with code ${code}`)
                                .split(/\r?\n/)
                                .filter(line => line.trim().length > 0);
                            const commentLines = rawLines.map(line =>
                                line.startsWith('@//') ? line : `@// ERROR: ${line}`
                            );
                            const errorBlock = (commentLines.length > 0 ? commentLines.join('\n') + '\n' : '') + 'User: ';

                            editor.edit(editBuilder => {
                                editBuilder.insert(new vscode.Position(insertLine, 0), errorBlock);
                            }).then(() => {
                                const userLine = insertLine + Math.max(commentLines.length, 0);
                                if (userLine < editor.document.lineCount) {
                                    const userLen = editor.document.lineAt(userLine).text.length;
                                    editor.selection = new vscode.Selection(userLine, userLen, userLine, userLen);
                                    editor.revealRange(new vscode.Range(userLine, 0, userLine, 0));
                                }
                                vscode.window.showErrorMessage(`LLM process exited with code ${code}: ${errorBuffer}`);
                                reject(new Error(errorBuffer));
                            });
                        };

                        if (editInProgress) {
                            let checkInterval = setInterval(() => {
                                if (!editInProgress) {
                                    clearInterval(checkInterval);
                                    applyErrorBlock();
                                }
                            }, 50);
                        } else {
                            applyErrorBlock();
                        }
                    } else {
                        vscode.window.showErrorMessage(`LLM process exited with code ${code}: ${errorBuffer}`);
                        reject(new Error(errorBuffer));
                    }
                    return;
                }

                // 追加模式下等待所有行刷新完成，再插入 User: 提示
                if (appendMode) {
                    function doInsertUser() {
                        let text = lineBuffer;
                        let extraLines = 0;
                        if (text) {
                            // 行缓冲中可能还有最后的未完结行，一并插入
                            text = text + '\n';
                            // 计算实际行数，flushLines 被 generationDone 阻断时 lineBuffer 可能有多行
                            extraLines = text.split('\n').length - 1;
                        } else {
                            text = '';
                        }
                        if (text) {
                            editor.edit(editBuilder => {
                                editBuilder.insert(new vscode.Position(insertLine, 0), text);
                            }).then(() => {
                                insertLine += extraLines;
                                // 插入 User: 提示
                                editor.edit(editBuilder => {
                                    editBuilder.insert(new vscode.Position(insertLine, 0), 'User: ');
                                }).then(() => {
                                    const userLine = insertLine;
                                    if (userLine < editor.document.lineCount) {
                                        const userLen = editor.document.lineAt(userLine).text.length;
                                        editor.selection = new vscode.Selection(userLine, userLen, userLine, userLen);
                                        editor.revealRange(new vscode.Range(userLine, 0, userLine, 0));
                                    }
                                    resolve();
                                });
                            });
                        } else {
                            editor.edit(editBuilder => {
                                editBuilder.insert(new vscode.Position(insertLine, 0), 'User: ');
                            }).then(() => {
                                const userLine = insertLine;
                                if (userLine < editor.document.lineCount) {
                                    const userLen = editor.document.lineAt(userLine).text.length;
                                    editor.selection = new vscode.Selection(userLine, userLen, userLine, userLen);
                                    editor.revealRange(new vscode.Range(userLine, 0, userLine, 0));
                                }
                                resolve();
                            });
                        }
                    }

                    if (editInProgress) {
                        // 如果 flushLines 还在进行中，等它完成再插入 User:
                        let checkInterval = setInterval(() => {
                            if (!editInProgress) {
                                clearInterval(checkInterval);
                                doInsertUser();
                            }
                        }, 50);
                    } else {
                        doInsertUser();
                    }
                } else {
                    // 替换模式
                    editor.edit(editBuilder => {
                        const fullRange = new vscode.Range(
                            0, 0,
                            editor.document.lineCount - 1,
                            editor.document.lineAt(editor.document.lineCount - 1).text.length
                        );
                        editBuilder.delete(fullRange);
                        editBuilder.insert(new vscode.Position(0, 0), outputBuffer);
                    }).then(() => {
                        const lastLine = editor.document.lineCount;
                        editor.edit(editBuilder => {
                            editBuilder.insert(new vscode.Position(lastLine, 0), '\nUser: ');
                        }).then(() => {
                            const newLast = editor.document.lineCount - 1;
                            const newLastLen = editor.document.lineAt(newLast).text.length;
                            editor.selection = new vscode.Selection(newLast, newLastLen, newLast, newLastLen);
                            editor.revealRange(new vscode.Range(newLast, 0, newLast, 0));
                            resolve();
                        });
                    });
                }
            });

            proc.on('error', (err) => {
                generationDone = true;
                documentProcesses.delete(documentUri);
                vscode.window.showErrorMessage(`Failed to start LLM process: ${err.message}`);
                reject(err);
            });
        });
    });
}

async function showHelpImpl(context) {
    const items = [
        {
            label: '提交对话（追加模式）',
            description: 'Ctrl+Enter',
            detail: '保持原上下文不变，追加 Assistant 响应。',
            action: 'append'
        },
        {
            label: '提交对话（替换模式）',
            description: 'F5',
            detail: '重写过滤后的上下文，会清理 @// 临时注释。',
            action: 'replace'
        },
        {
            label: '停止生成',
            description: 'Shift+K',
            detail: '中断当前文档的进行中请求。',
            action: 'stop'
        },
        {
            label: '打开大纲',
            description: 'F2',
            detail: '定位到历史 User/Configure 节点。',
            action: 'outline'
        },
        {
            label: '查看扩展 README',
            description: '详细说明',
            detail: '打开扩展目录内 README 文档。',
            action: 'readme'
        }
    ];

    const picked = await vscode.window.showQuickPick(items, {
        title: 'LLM Chat 快速帮助',
        placeHolder: '选择一项可直接执行'
    });

    if (!picked) {
        return;
    }

    if (picked.action === 'append') {
        await vscode.commands.executeCommand('llm-chat.submitQuery');
        return;
    }
    if (picked.action === 'replace') {
        await vscode.commands.executeCommand('llm-chat.submitQueryReplace');
        return;
    }
    if (picked.action === 'stop') {
        await vscode.commands.executeCommand('llm-chat.stopGeneration');
        return;
    }
    if (picked.action === 'outline') {
        await vscode.commands.executeCommand('llm-chat.showOutline');
        return;
    }
    if (picked.action === 'readme') {
        const readmePath = path.join(context.extensionPath, 'README.md');
        const doc = await vscode.workspace.openTextDocument(readmePath);
        await vscode.window.showTextDocument(doc, { preview: false });
    }
}

function activate(context) {
    console.log('LLM Chat Assistant extension is now active');

    const statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBarItem.text = "$(comment-discussion) LLM Chat";
    statusBarItem.tooltip = "LLM Chat Assistant 已激活，按 F4 或命令面板运行 LLM: Show Help";
    context.subscriptions.push(statusBarItem);

    function updateStatusBar() {
        const editor = vscode.window.activeTextEditor;
        if (editor && editor.document.languageId === 'llm-chat') {
            statusBarItem.show();
        } else {
            statusBarItem.hide();
        }
    }

    updateStatusBar();
    vscode.window.onDidChangeActiveTextEditor(updateStatusBar, null, context.subscriptions);

    function showFirstOpenHint(editor) {
        if (firstOpenHintShown) {
            return;
        }
        if (!editor || editor.document.languageId !== 'llm-chat') {
            return;
        }
        firstOpenHintShown = true;
        vscode.window
            .showInformationMessage('LLM Chat 快捷提示：按 F4 可随时查看帮助与常用操作。', '打开帮助')
            .then(selection => {
                if (selection === '打开帮助') {
                    vscode.commands.executeCommand('llm-chat.showHelp');
                }
            });
    }

    vscode.window.onDidChangeActiveTextEditor((editor) => {
        showFirstOpenHint(editor);
    }, null, context.subscriptions);

    showFirstOpenHint(vscode.window.activeTextEditor);

    let submitCommand = vscode.commands.registerCommand('llm-chat.submitQuery', async function () {
        await submitQueryImpl(true);
    });

    let submitReplaceCommand = vscode.commands.registerCommand('llm-chat.submitQueryReplace', async function () {
        await submitQueryImpl(false);
    });

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
                setTimeout(() => {
                    if (proc && !proc.killed) {
                        try { proc.kill('SIGKILL'); } catch (e) { }
                    }
                }, 1000);
                documentProcesses.delete(documentUri);
                vscode.window.showInformationMessage('LLM generation stopped');
            } else {
                vscode.window.showInformationMessage('No active LLM generation for this document');
            }
        } else {
            vscode.window.showInformationMessage('No active LLM generation for this document');
        }
    });

    let outlineCommand = vscode.commands.registerCommand('llm-chat.showOutline', async function () {
        const editor = vscode.window.activeTextEditor;
        if (!editor) {
            vscode.window.showErrorMessage('No active editor');
            return;
        }

        const document = editor.document;
        const text = document.getText();
        const lines = text.split('\n');

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

        const selected = await vscode.window.showQuickPick(items, {
            placeHolder: 'Select a query to jump to'
        });

        if (selected) {
            const position = new vscode.Position(selected.lineNumber, 0);
            editor.selection = new vscode.Selection(position, position);
            editor.revealRange(new vscode.Range(position, position), vscode.TextEditorRevealType.InCenter);
        }
    });

    let helpCommand = vscode.commands.registerCommand('llm-chat.showHelp', async function () {
        await showHelpImpl(context);
    });

    context.subscriptions.push(submitCommand);
    context.subscriptions.push(submitReplaceCommand);
    context.subscriptions.push(stopCommand);
    context.subscriptions.push(outlineCommand);
    context.subscriptions.push(helpCommand);
}

function deactivate() {
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