VERSION = "0.1.0"

local micro = import("micro")
local config = import("micro/config")
local buffer = import("micro/buffer")
local shell = import("micro/shell")
local os = import("os")

local state = {
    currentJob = nil,
    interrupted = false,
    stderrOutput = "",
    outlineMarks = {}
}

math.randomseed(os.Getpid())

local function trim(s)
    if s == nil then
        return ""
    end
    return tostring(s):gsub("^%s+", ""):gsub("%s+$", "")
end

local function isLLMBuffer(bp)
    local p = bp.Buf.Path or ""
    return p:sub(-4) == ".llm"
end

local function shellEscape(s)
    return "'" .. tostring(s):gsub("'", "'\\''") .. "'"
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

local function lineCount(buf)
    local n = 0
    while true do
        local line = buf:Line(n)
        if line == nil then
            break
        end
        n = n + 1
    end
    return n
end

local function writeTempInput(content)
    local base = os.Getenv("TMPDIR")
    if base == "" then
        base = "/tmp"
    end
    local name = string.format("%s/micro_llm_input_%d_%d.llm", base, os.Getpid(), math.floor(math.random() * 1000000000))
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
    local sh = trim(os.Getenv("SHELL"))
    if sh == "" then
        sh = "/bin/sh"
    end
    return sh
end

local function wrapWithUserShell(cmd)
    local sh = userShellPath()
    return shellEscape(sh) .. " -lc " .. shellEscape(cmd)
end

local function runUserShellCommand(cmd)
    return shell.RunCommand(wrapWithUserShell(cmd))
end

local function findEngine()
    local configured1 = config.GetGlobalOption("llm_micro.enginecmd")
    if type(configured1) == "string" and trim(configured1) ~= "" then
        return trim(configured1)
    end

    local configured2 = config.GetGlobalOption("plugin.llm_micro.enginecmd")
    if type(configured2) == "string" and trim(configured2) ~= "" then
        return trim(configured2)
    end

    local envConfigured = trim(os.Getenv("LLM_ENGINE_CMD"))
    if envConfigured ~= "" then
        return envConfigured
    end

    local out1, err1 = runUserShellCommand("command -v llm_engine >/dev/null 2>&1 && echo llm_engine")
    if err1 == nil and out1 ~= nil and out1:find("llm_engine") ~= nil then
        return "llm_engine"
    end

    local out2, err2 = runUserShellCommand("command -v llm-engine >/dev/null 2>&1 && echo llm-engine")
    if err2 == nil and out2 ~= nil and out2:find("llm-engine") ~= nil then
        return "llm-engine"
    end

    local out3, err3 = runUserShellCommand("command -v python3 >/dev/null 2>&1 && python3 -m llm_engine --help >/dev/null 2>&1 && echo ok")
    if err3 == nil and out3 ~= nil and out3:find("ok") ~= nil then
        return "python3 -m llm_engine"
    end

    local out4, err4 = runUserShellCommand("command -v python >/dev/null 2>&1 && python -m llm_engine --help >/dev/null 2>&1 && echo ok")
    if err4 == nil and out4 ~= nil and out4:find("ok") ~= nil then
        return "python -m llm_engine"
    end

    local home = trim(os.Getenv("HOME"))
    local absCandidates = {}
    if home ~= "" then
        table.insert(absCandidates, home .. "/.local/bin/llm_engine")
    end
    table.insert(absCandidates, "/usr/local/bin/llm_engine")
    table.insert(absCandidates, "/usr/bin/llm_engine")

    local i
    for i = 1, #absCandidates do
        local c = absCandidates[i]
        local out, err = runUserShellCommand("test -x " .. shellEscape(c) .. " && echo ok")
        if err == nil and out ~= nil and out:find("ok") ~= nil then
            return c
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
    local cmdOut, _ = runUserShellCommand("command -v llm_engine 2>/dev/null || true")
    local cmdOut2, _ = runUserShellCommand("command -v llm-engine 2>/dev/null || true")

    table.insert(lines, "[llm_micro doctor]")
    table.insert(lines, "HOME=" .. (home ~= "" and home or "(empty)"))
    table.insert(lines, "PATH=" .. (path ~= "" and path or "(empty)"))
    table.insert(lines, "SHELL=" .. userShellPath())
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
    table.insert(lines, "command -v llm_engine => " .. trim(cmdOut))
    table.insert(lines, "command -v llm-engine => " .. trim(cmdOut2))

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

local function buildOutline(bp)
    state.outlineMarks = {}
    local total = lineCount(bp.Buf)
    local lines = {}

    local i
    for i = 0, total - 1 do
        local line = bp.Buf:Line(i) or ""
        if line:match("^User: ") or line:match("^Configure: ") then
            table.insert(state.outlineMarks, i)
            local item = string.format("%d. L%d %s", #state.outlineMarks, i + 1, line)
            table.insert(lines, item)
        end
    end

    if #lines == 0 then
        micro.InfoBar():Message("llm: 当前文件没有 User/Configure 节点")
        return
    end

    table.insert(lines, "")
    table.insert(lines, "运行命令: > llmjump <编号> 进行跳转")
    micro.TermMessage(table.concat(lines, "\n"))
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

    local out = output or ""
    out = out:gsub("\r\n", "\n")

    if state.interrupted then
        out = out .. "\n<<===中断操作===>>"
    elseif state.stderrOutput ~= "" then
        out = out .. "\n" .. state.stderrOutput
    end

    if out == "" then
        out = "@// llm_engine 未返回内容"
    end

    local replaced = out .. "\nUser: "
    bp.Buf:Replace(startLoc, endLoc, replaced)

    state.currentJob = nil
    state.interrupted = false
    state.stderrOutput = ""
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

function Submit(bp)
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
    local rawCmd = "LLM_FILE_DIR=" .. shellEscape(dir) .. " " .. engineCmd .. " < " .. shellEscape(tempPath)
    local cmd = wrapWithUserShell(rawCmd)

    state.interrupted = false
    state.stderrOutput = ""
    state.currentJob = shell.JobStart(cmd, nil, onLLMStderr, onLLMExit, bp, startLoc, endLoc, tempPath)
    micro.InfoBar():Message("llm: 已提交，请求进行中... (Ctrl+K / Alt+K 中断)")
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

function Outline(bp)
    if not isLLMBuffer(bp) then
        micro.InfoBar():Error("llm: 仅在 .llm 文件中可用")
        return
    end
    buildOutline(bp)
end

function Jump(bp, args)
    if #args < 1 then
        micro.InfoBar():Message("用法: llmjump <编号>")
        return
    end

    local idx = tonumber(args[1])
    if idx == nil or idx < 1 or idx > #state.outlineMarks then
        micro.InfoBar():Error("llm: 无效编号，请先运行 llmoutline")
        return
    end

    local target = state.outlineMarks[idx]
    bp.Cursor:Goto(buffer.Loc(0, target))
    micro.InfoBar():Message(string.format("llm: 已跳转到第 %d 项 (L%d)", idx, target + 1))
end

function PreviewImage(bp)
    local line = bp.Buf:Line(bp.Cursor.Y) or ""
    local p = findImagePath(line)
    if p == nil or p == "" then
        micro.InfoBar():Message("llm: 当前行没有 $$path$$ 图片引用")
        return
    end

    local full = absImagePath(bp, p)
    local checkCmd = "test -f " .. shellEscape(full) .. " && echo ok"
    local out, _ = shell.RunCommand(checkCmd)
    if out == nil or out:find("ok") == nil then
        micro.InfoBar():Error("llm: 图片不存在: " .. full)
        return
    end

    local opener = "xdg-open " .. shellEscape(full) .. " >/dev/null 2>&1 &"
    if shell.RunBackgroundShell ~= nil then
        local _, err = shell.RunBackgroundShell(opener)
        if err ~= nil then
            micro.InfoBar():Error("llm: 打开图片失败: " .. tostring(err))
            return
        end
    else
        local _, err = shell.RunCommand(opener)
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
    config.MakeCommand("llmstop", Stop, config.NoComplete)
    config.MakeCommand("llmoutline", Outline, config.NoComplete)
    config.MakeCommand("llmjump", Jump, config.NoComplete)
    config.MakeCommand("llmimg", PreviewImage, config.NoComplete)
    config.MakeCommand("llmdoctor", Doctor, config.NoComplete)

    config.TryBindKey("F1", "lua:llm_micro.Submit", true)
    config.TryBindKey("Ctrl-k", "lua:llm_micro.Stop", true)
    config.TryBindKey("Alt-k", "lua:llm_micro.Stop", true)
    config.TryBindKey("F2", "lua:llm_micro.Outline", true)
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