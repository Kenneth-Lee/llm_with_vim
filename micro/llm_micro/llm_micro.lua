VERSION = "0.1.0"

local micro = import("micro")
local config = import("micro/config")
local buffer = import("micro/buffer")
local shell = import("micro/shell")
local os = import("os")
local runtime = import("runtime")

local state = {
    currentJob = nil,
    interrupted = false,
    stderrOutput = "",
    cachedEngineCmd = nil,
    stdoutOutput = "",
    streamEndLoc = nil,
    streamStartLoc = nil
}

math.randomseed(os.Getpid())

local function trim(s)
    if s == nil then
        return ""
    end
    return tostring(s):gsub("^%s+", ""):gsub("%s+$", "")
end

local function isWindows()
    -- 插件以 module(..., package.seeall) 加载时，Lua 全局 package 常为 nil，不能用 package.config。
    -- 使用 Go runtime.GOOS（micro 暴露）与可执行文件目标系统一致。
    if runtime ~= nil and runtime.GOOS ~= nil and runtime.GOOS ~= "" then
        return runtime.GOOS == "windows"
    end
    if trim(os.Getenv("WINDIR")) ~= "" or trim(os.Getenv("SYSTEMROOT")) ~= "" then
        return true
    end
    return trim(os.Getenv("OS")):lower() == "windows_nt"
end

local function isLLMBuffer(bp)
    local p = bp.Buf.Path or ""
    return p:sub(-4) == ".llm"
end

local function shellEscape(s)
    return "'" .. tostring(s):gsub("'", "'\\''") .. "'"
end

local function cmdQuote(s)
    return '"' .. tostring(s):gsub('"', '""') .. '"'
end

local function fileDir(bp)
    local path = bp.Buf.Path or ""
    if path == "" then
        local wd, _ = os.Getwd()
        return wd or "."
    end

    local slashPos = path:match("^.*()[/\\]")
    if slashPos == nil then
        return "."
    end
    return path:sub(1, slashPos - 1)
end

local function writeTempInput(content)
    local base = ""
    if isWindows() then
        base = trim(os.Getenv("TEMP"))
        if base == "" then
            base = trim(os.Getenv("TMP"))
        end
    else
        base = trim(os.Getenv("TMPDIR"))
    end
    if base == "" then
        base = isWindows() and "." or "/tmp"
    end
    local sep = isWindows() and "\\" or "/"
    local name = string.format("%s%smicro_llm_input_%d_%d.llm", base, sep, os.Getpid(), math.floor(math.random() * 1000000000))
    local f, err = io.open(name, "w")
    if f == nil then
        return nil, err
    end
    f:write(content)
    f:close()
    return name, nil
end

local function removeFile(path)
    if path ~= nil and path ~= "" then
        os.Remove(path)
    end
end

local function userShellPath()
    if isWindows() then
        local pwsh = trim(os.Getenv("COMSPEC"))
        if pwsh == "" then
            pwsh = "cmd.exe"
        end
        return pwsh
    end
    local sh = trim(os.Getenv("SHELL"))
    if sh == "" then
        sh = "/bin/sh"
    end
    return sh
end

local function wrapWithUserShell(cmd)
    if isWindows() then
        local sh = userShellPath()
        return cmdQuote(sh) .. " /d /s /c " .. cmdQuote(cmd)
    end
    -- micro 在 Linux/macOS 上的 JobStart 本身已通过 sh -c 执行命令；
    -- 这里不再额外套用户 shell，避免每次请求触发 shell 启动/初始化开销。
    return cmd
end

local function runUserShellCommand(cmd)
    if isWindows() then
        return shell.RunCommand(wrapWithUserShell(cmd))
    end
    -- 非 Windows 下显式使用 /bin/sh，避免使用用户 shell（如 zsh -lc）造成明显延迟。
    return shell.RunCommand("sh -c " .. shellEscape(cmd))
end

local function findEngine()
    if type(state.cachedEngineCmd) == "string" and state.cachedEngineCmd ~= "" then
        return state.cachedEngineCmd
    end

    local configured1 = config.GetGlobalOption("llm_micro.enginecmd")
    if type(configured1) == "string" and trim(configured1) ~= "" then
        state.cachedEngineCmd = trim(configured1)
        return state.cachedEngineCmd
    end

    local configured2 = config.GetGlobalOption("plugin.llm_micro.enginecmd")
    if type(configured2) == "string" and trim(configured2) ~= "" then
        state.cachedEngineCmd = trim(configured2)
        return state.cachedEngineCmd
    end

    local envConfigured = trim(os.Getenv("LLM_ENGINE_CMD"))
    if envConfigured ~= "" then
        state.cachedEngineCmd = envConfigured
        return state.cachedEngineCmd
    end

    if isWindows() then
        local out0, err0 = runUserShellCommand("where contextforge >nul 2>&1 && echo contextforge")
        if err0 == nil and out0 ~= nil and out0:find("contextforge") ~= nil then
            state.cachedEngineCmd = "contextforge"
            return state.cachedEngineCmd
        end

        local out1, err1 = runUserShellCommand("where llm_engine >nul 2>&1 && echo llm_engine")
        if err1 == nil and out1 ~= nil and out1:find("llm_engine") ~= nil then
            state.cachedEngineCmd = "llm_engine"
            return state.cachedEngineCmd
        end

        local out2, err2 = runUserShellCommand("where llm-engine >nul 2>&1 && echo llm-engine")
        if err2 == nil and out2 ~= nil and out2:find("llm-engine") ~= nil then
            state.cachedEngineCmd = "llm-engine"
            return state.cachedEngineCmd
        end

        local out3, err3 = runUserShellCommand("where py >nul 2>&1 && py -3 -m llm_engine --help >nul 2>&1 && echo ok")
        if err3 == nil and out3 ~= nil and out3:find("ok") ~= nil then
            state.cachedEngineCmd = "py -3 -m llm_engine"
            return state.cachedEngineCmd
        end

        local out4, err4 = runUserShellCommand("where python >nul 2>&1 && python -m llm_engine --help >nul 2>&1 && echo ok")
        if err4 == nil and out4 ~= nil and out4:find("ok") ~= nil then
            state.cachedEngineCmd = "python -m llm_engine"
            return state.cachedEngineCmd
        end
    else
        local out0, err0 = runUserShellCommand("command -v contextforge >/dev/null 2>&1 && echo contextforge")
        if err0 == nil and out0 ~= nil and out0:find("contextforge") ~= nil then
            state.cachedEngineCmd = "contextforge"
            return state.cachedEngineCmd
        end

        local out1, err1 = runUserShellCommand("command -v llm_engine >/dev/null 2>&1 && echo llm_engine")
        if err1 == nil and out1 ~= nil and out1:find("llm_engine") ~= nil then
            state.cachedEngineCmd = "llm_engine"
            return state.cachedEngineCmd
        end

        local out2, err2 = runUserShellCommand("command -v llm-engine >/dev/null 2>&1 && echo llm-engine")
        if err2 == nil and out2 ~= nil and out2:find("llm-engine") ~= nil then
            state.cachedEngineCmd = "llm-engine"
            return state.cachedEngineCmd
        end

        local out3, err3 = runUserShellCommand("command -v python3 >/dev/null 2>&1 && python3 -m llm_engine --help >/dev/null 2>&1 && echo ok")
        if err3 == nil and out3 ~= nil and out3:find("ok") ~= nil then
            state.cachedEngineCmd = "python3 -m llm_engine"
            return state.cachedEngineCmd
        end

        local out4, err4 = runUserShellCommand("command -v python >/dev/null 2>&1 && python -m llm_engine --help >/dev/null 2>&1 && echo ok")
        if err4 == nil and out4 ~= nil and out4:find("ok") ~= nil then
            state.cachedEngineCmd = "python -m llm_engine"
            return state.cachedEngineCmd
        end
    end

    local home = trim(os.Getenv("HOME"))
    local absCandidates = {}
    if home ~= "" then
        table.insert(absCandidates, home .. "/.local/bin/llm_engine")
    end
    if isWindows() then
        local userProfile = trim(os.Getenv("USERPROFILE"))
        local appData = trim(os.Getenv("APPDATA"))
        if userProfile ~= "" then
            table.insert(absCandidates, userProfile .. "\\AppData\\Roaming\\Python\\Python311\\Scripts\\llm_engine.exe")
            table.insert(absCandidates, userProfile .. "\\AppData\\Roaming\\Python\\Python310\\Scripts\\llm_engine.exe")
            table.insert(absCandidates, userProfile .. "\\AppData\\Roaming\\Python\\Python39\\Scripts\\llm_engine.exe")
            table.insert(absCandidates, userProfile .. "\\.local\\bin\\llm_engine.exe")
        end
        if appData ~= "" then
            table.insert(absCandidates, appData .. "\\Python\\Scripts\\llm_engine.exe")
        end
    else
        table.insert(absCandidates, "/usr/local/bin/llm_engine")
        table.insert(absCandidates, "/usr/bin/llm_engine")
    end

    local i
    for i = 1, #absCandidates do
        local c = absCandidates[i]
        local out = nil
        local err = nil
        if isWindows() then
            out, err = runUserShellCommand('if exist ' .. cmdQuote(c) .. ' (echo ok)')
        else
            out, err = runUserShellCommand("test -x " .. shellEscape(c) .. " && echo ok")
        end
        if err == nil and out ~= nil and out:find("ok") ~= nil then
            state.cachedEngineCmd = c
            return state.cachedEngineCmd
        end
    end

    return nil
end

function Doctor(bp)
    local lines = {}

    local path = trim(os.Getenv("PATH"))
    local home = trim(os.Getenv("HOME"))
    local envCmd = trim(os.Getenv("LLM_ENGINE_CMD"))
    local optCmd1 = config.GetGlobalOption("llm_micro.enginecmd")
    local optCmd2 = config.GetGlobalOption("plugin.llm_micro.enginecmd")
    local cmdOut = ""
    local cmdOut2 = ""
    if isWindows() then
        cmdOut, _ = runUserShellCommand("where llm_engine 2>nul")
        cmdOut2, _ = runUserShellCommand("where llm-engine 2>nul")
    else
        cmdOut, _ = runUserShellCommand("command -v llm_engine 2>/dev/null || true")
        cmdOut2, _ = runUserShellCommand("command -v llm-engine 2>/dev/null || true")
    end

    table.insert(lines, "[llm_micro doctor]")
    table.insert(lines, "HOME=" .. (home ~= "" and home or "(empty)"))
    table.insert(lines, "PATH=" .. (path ~= "" and path or "(empty)"))
    table.insert(lines, "SHELL=" .. userShellPath())
    table.insert(lines, "PLATFORM=" .. (isWindows() and "windows" or "posix"))
    table.insert(lines, "LLM_ENGINE_CMD(env)=" .. (envCmd ~= "" and envCmd or "(empty)"))
    if type(optCmd1) == "string" and trim(optCmd1) ~= "" then
        table.insert(lines, "llm_micro.enginecmd(option)=" .. trim(optCmd1))
    else
        table.insert(lines, "llm_micro.enginecmd(option)=(empty)")
    end
    if type(optCmd2) == "string" and trim(optCmd2) ~= "" then
        table.insert(lines, "plugin.llm_micro.enginecmd(option)=" .. trim(optCmd2))
    else
        table.insert(lines, "plugin.llm_micro.enginecmd(option)=(empty)")
    end
    if isWindows() then
        table.insert(lines, "where llm_engine => " .. trim(cmdOut))
        table.insert(lines, "where llm-engine => " .. trim(cmdOut2))
    else
        table.insert(lines, "command -v llm_engine => " .. trim(cmdOut))
        table.insert(lines, "command -v llm-engine => " .. trim(cmdOut2))
    end

    local resolved = findEngine()
    table.insert(lines, "resolved engine => " .. (resolved or "(not found)"))
    table.insert(lines, "")
    table.insert(lines, "如需强制指定：")
    table.insert(lines, "> set llm_micro.enginecmd '/absolute/path/to/llm_engine'")

    micro.TermMessage(table.concat(lines, "\n"))
end

local function collectContextToCursor(bp)
    local y = bp.Cursor.Y
    local lines = {}
    local i
    for i = 0, y do
        table.insert(lines, bp.Buf:Line(i) or "")
    end
    -- 与 vim/vscode 行为保持一致：输入末尾保留换行，避免 Assistant 输出粘在最后一行 User 后面
    return table.concat(lines, "\n") .. "\n"
end

local function findImagePath(line)
    return line:match("%$%$([^$]+)%$%$")
end

local function absImagePath(bp, p)
    if p:sub(1, 1) == "/" then
        return p
    end
    if p:match("^[A-Za-z]:[/\\]") then
        return p
    end
    return fileDir(bp) .. "/" .. p
end

local function normalizeExitArgs(args)
    if args == nil then
        return nil, nil, nil, nil
    end

    -- 有些实现会把用户参数整体作为单个 table 传入
    if args[1] ~= nil and type(args[1]) == "table" then
        local a = args[1]
        return a[1], a[2], a[3], a[4]
    end

    -- 常见实现：用户参数逐个出现在 args 中
    return args[1], args[2], args[3], args[4]
end

local function endLocForText(text)
    -- 返回 Loc(X=col, Y=line)，Micro 的 buffer.Loc 字段名为 X（列）和 Y（行）
    local s = text or ""
    local line = 0
    local col = 0
    local i
    for i = 1, #s do
        local ch = s:sub(i, i)
        if ch == "\n" then
            line = line + 1
            col = 0
        else
            col = col + 1
        end
    end
    return buffer.Loc(col, line)
end

local function offsetEndLoc(baseLoc, text)
    -- 计算将 text 插入到 baseLoc 后，text 的结束位置（绝对位置）
    -- 注意：Micro 的 buffer.Loc 字段名为 X（列）和 Y（行）
    local te = endLocForText(text or "")
    return buffer.Loc(te.X, baseLoc.Y + te.Y)
end

local function onLLMStdout(out, args)
    local bp, startLoc = normalizeExitArgs(args)
    if bp == nil or startLoc == nil then
        return
    end
    if out == nil or out == "" then
        return
    end

    local chunk = tostring(out):gsub("\r\n", "\n")

    if state.streamStartLoc ~= nil then
        -- 追加模式：累积输出，替换从 streamStartLoc 到 streamEndLoc 的范围
        state.stdoutOutput = state.stdoutOutput .. chunk
        local replaceEnd = state.streamEndLoc
        if replaceEnd == nil then
            replaceEnd = state.streamStartLoc
        end
        bp.Buf:Replace(state.streamStartLoc, replaceEnd, state.stdoutOutput)
        state.streamEndLoc = offsetEndLoc(state.streamStartLoc, state.stdoutOutput)
    else
        -- 替换模式：从文档开头替换到 streamEndLoc
        state.stdoutOutput = state.stdoutOutput .. chunk
        local replaceEnd = state.streamEndLoc
        if replaceEnd == nil then
            replaceEnd = buffer.Loc(0, 0)
        end
        bp.Buf:Replace(startLoc, replaceEnd, state.stdoutOutput)
        state.streamEndLoc = endLocForText(state.stdoutOutput)
    end
end

local function onLLMExit(output, args)
    local bp, startLoc, endLoc, tempPath = normalizeExitArgs(args)

    if bp == nil or startLoc == nil or endLoc == nil then
        state.currentJob = nil
        state.interrupted = false
        state.stderrOutput = ""
        micro.InfoBar():Error("llm: 回调参数异常，请运行 llmdoctor")
        return
    end

    removeFile(tempPath)

    local out = state.stdoutOutput
    if out == nil or out == "" then
        out = output or ""
        out = out:gsub("\r\n", "\n")
    end

    if state.interrupted then
        out = out .. "\n<<===中断操作===>>"
    elseif state.stderrOutput ~= "" then
        out = out .. "\n" .. state.stderrOutput
    end

    if out == "" then
        out = "@// llm_engine 未返回内容"
    end

    local replaced = out .. "\nUser: "

    if state.streamStartLoc ~= nil then
        -- 追加模式：替换从 streamStartLoc 到 streamEndLoc 的范围
        -- replaced 末尾不带 \n，以确保文件最后一行是 User: 且尾部无多余空行
        -- 但这种情况下 buffer 在最后一个 \n 后有一个空行，所以下次提交的 Loc(0, lastLine+1) 有效
        local replaceEnd = state.streamEndLoc
        if replaceEnd == nil then
            replaceEnd = state.streamStartLoc
        end
        bp.Buf:Replace(state.streamStartLoc, replaceEnd, replaced .. "\n")
    else
        -- 替换模式：从 startLoc 到 endLoc
        local replaceEnd = state.streamEndLoc
        if replaceEnd == nil then
            replaceEnd = endLoc
        end
        bp.Buf:Replace(startLoc, replaceEnd, replaced)
    end

    state.currentJob = nil
    state.interrupted = false
    state.stderrOutput = ""
    state.stdoutOutput = ""
    state.streamEndLoc = nil
    state.streamStartLoc = nil
    micro.InfoBar():Message("llm: 请求完成")
end

local function onLLMStderr(err, args)
    if err ~= nil and err ~= "" then
        if state.stderrOutput == "" then
            state.stderrOutput = "@// " .. tostring(err)
        else
            state.stderrOutput = state.stderrOutput .. "\n@// " .. tostring(err)
        end
    end
end

local function doSubmit(bp, appendMode)
    -- 必须在 Submit / SubmitReplace 之前定义（Lua 局部函数作用域规则）
    if state.currentJob ~= nil then
        micro.InfoBar():Message("llm: 正在请求中，可按 Ctrl+K 或 Alt+K 中断")
        return
    end

    if not isLLMBuffer(bp) then
        micro.InfoBar():Error("llm: 仅在 .llm 文件中可用")
        return
    end

    local engineCmd = findEngine()
    if engineCmd == nil then
        micro.InfoBar():Error("llm: 未找到 llm_engine，请先 pip install -e .")
        return
    end

    local content = collectContextToCursor(bp)
    local tempPath, err = writeTempInput(content)
    if tempPath == nil then
        micro.InfoBar():Error("llm: 临时文件创建失败: " .. tostring(err))
        return
    end

    local endLine = bp.Cursor.Y
    local endCol = string.len(bp.Buf:Line(endLine) or "")
    local startLoc = buffer.Loc(0, 0)
    local endLoc = buffer.Loc(endCol, endLine)

    local dir = fileDir(bp)
    local modeFlag = appendMode and " --append" or ""
    local rawCmd = ""
    if isWindows() then
        -- Windows 下用 type 管道输入更稳定，并把 stderr 合并到 stdout
        rawCmd = 'set "LLM_FILE_DIR=' .. dir .. '" && type ' .. cmdQuote(tempPath) .. ' | ' .. engineCmd .. modeFlag .. ' 2>&1'
    else
        -- 用 exec 替换外层 sh，确保 Ctrl-K 的 JobStop 能直接终止 llm_engine。
        rawCmd = "LLM_FILE_DIR=" .. shellEscape(dir) .. " exec " .. engineCmd .. modeFlag .. " < " .. shellEscape(tempPath)
    end
    local cmd = wrapWithUserShell(rawCmd)

    if isWindows() then
        -- Windows 下同步执行
        local out, runErr = shell.RunCommand(cmd)
        removeFile(tempPath)

        local finalOut = out or ""
        finalOut = finalOut:gsub("\r\n", "\n")
        if runErr ~= nil and tostring(runErr) ~= "" then
            if finalOut ~= "" then
                finalOut = finalOut .. "\n"
            end
            finalOut = finalOut .. "@// " .. tostring(runErr)
        end
        if finalOut == "" then
            finalOut = "@// llm_engine 未返回内容"
        end

        if appendMode then
            -- 确保 buffer 有足够行数使 Loc(0, endLine+1) 有效
            local lineCount = bp.Buf:LinesNum()
            while endLine + 1 >= lineCount do
                local lastEnd = buffer.Loc(string.len(bp.Buf:Line(lineCount - 1) or ""), lineCount - 1)
                bp.Buf:Replace(lastEnd, lastEnd, "\n")
                lineCount = bp.Buf:LinesNum()
            end
            local insertLoc = buffer.Loc(0, endLine + 1)
            bp.Buf:Replace(insertLoc, insertLoc, finalOut .. "\nUser: \n")
        else
            bp.Buf:Replace(startLoc, endLoc, finalOut .. "\nUser: ")
        end
        micro.InfoBar():Message("llm: 请求完成")
        return
    end

    state.interrupted = false
    state.stderrOutput = ""
    state.stdoutOutput = ""

    if appendMode then
        -- 插入点在光标行的下一行开头。先确保 buffer 有足够行数。
        local lineCount = bp.Buf:LinesNum()
        while endLine + 1 >= lineCount do
            local lastEnd = buffer.Loc(string.len(bp.Buf:Line(lineCount - 1) or ""), lineCount - 1)
            bp.Buf:Replace(lastEnd, lastEnd, "\n")
            lineCount = bp.Buf:LinesNum()
        end
        local insertLoc = buffer.Loc(0, endLine + 1)
        state.streamStartLoc = insertLoc
        state.streamEndLoc = insertLoc
        state.currentJob = shell.JobStart(cmd, onLLMStdout, onLLMStderr, onLLMExit, bp, insertLoc, insertLoc, tempPath)
    else
        state.streamStartLoc = nil
        state.streamEndLoc = endLoc
        state.currentJob = shell.JobStart(cmd, onLLMStdout, onLLMStderr, onLLMExit, bp, startLoc, endLoc, tempPath)
    end

    if appendMode then
        micro.InfoBar():Message("llm: 已提交（追加模式），请求进行中... (Ctrl+K / Alt+K 中断)")
    else
        micro.InfoBar():Message("llm: 已提交（替换模式），请求进行中... (Ctrl+K / Alt+K 中断)")
    end
end

function Submit(bp)
    doSubmit(bp, true)
end

function SubmitReplace(bp)
    doSubmit(bp, false)
end

function Stop(bp)
    if state.currentJob == nil then
        micro.InfoBar():Message("llm: 当前没有进行中的请求")
        return
    end
    state.interrupted = true
    shell.JobStop(state.currentJob)
    micro.InfoBar():Message("llm: 已发送中断")
end

function PreviewImage(bp)
    local line = bp.Buf:Line(bp.Cursor.Y) or ""
    local p = findImagePath(line)
    if p == nil or p == "" then
        micro.InfoBar():Message("llm: 当前行没有 $$path$$ 图片引用")
        return
    end

    local full = absImagePath(bp, p)
    local checkCmd = ""
    if isWindows() then
        checkCmd = 'if exist ' .. cmdQuote(full) .. ' (echo ok)'
    else
        checkCmd = "test -f " .. shellEscape(full) .. " && echo ok"
    end
    local out, _ = runUserShellCommand(checkCmd)
    if out == nil or out:find("ok") == nil then
        micro.InfoBar():Error("llm: 图片不存在: " .. full)
        return
    end

    local opener = ""
    if isWindows() then
        opener = 'start "" ' .. cmdQuote(full)
    else
        opener = "xdg-open " .. shellEscape(full) .. " >/dev/null 2>&1 &"
    end
    if shell.RunBackgroundShell ~= nil then
        local _, err = shell.RunBackgroundShell(wrapWithUserShell(opener))
        if err ~= nil then
            micro.InfoBar():Error("llm: 打开图片失败: " .. tostring(err))
            return
        end
    else
        local _, err = runUserShellCommand(opener)
        if err ~= nil then
            micro.InfoBar():Error("llm: 打开图片失败: " .. tostring(err))
            return
        end
    end

    micro.InfoBar():Message("llm: 正在打开图片 " .. full)
end

function init()
    config.RegisterGlobalOption("llm_micro", "enginecmd", "")
    config.RegisterGlobalOption("plugin.llm_micro", "enginecmd", "")

    config.MakeCommand("llmsubmit", Submit, config.NoComplete)
    config.MakeCommand("llmsubmitreplace", SubmitReplace, config.NoComplete)
    config.MakeCommand("llmstop", Stop, config.NoComplete)
    config.MakeCommand("llmimg", PreviewImage, config.NoComplete)
    config.MakeCommand("llmdoctor", Doctor, config.NoComplete)

    config.TryBindKey("F1", "lua:llm_micro.Submit", true)
    config.TryBindKey("F5", "lua:llm_micro.SubmitReplace", true)
    config.TryBindKey("Ctrl-k", "lua:llm_micro.Stop", true)
    config.TryBindKey("Alt-k", "lua:llm_micro.Stop", true)
    config.TryBindKey("F3", "lua:llm_micro.PreviewImage", true)

    config.AddRuntimeFile("llm_micro", config.RTHelp, "help/llm-micro.md")
    config.AddRuntimeFilesFromDirectory("llm_micro", config.RTSyntax, "syntax", "*.yaml")

    -- init 在 buffer 初始化后执行，当前已打开文件可能错过 onBufferOpen，需补做一次语法绑定
    local cur = micro.CurPane()
    if cur ~= nil and cur.Buf ~= nil then
        onBufferOpen(cur.Buf)
    end
end

function onBufferOpen(buf)
    local p = buf.Path or ""
    if p:sub(-4) == ".llm" then
        buf:SetOptionNative("filetype", "llm-chat")
        buf:SetOptionNative("commenttype", "# %s")
        buf:UpdateRules()
    end
end