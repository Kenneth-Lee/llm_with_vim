" LLM Chat Plugin for Vim
" 重复加载检查
if exists("g:llm_engine_loaded")
	finish
endif
let g:llm_engine_loaded = 1

" 查找llm_engine的执行方式
" 搜索顺序: 1. pip安装的命令 2. python -m llm_engine
function! s:FindLLMEngine()
	" 1. 检查pip安装的命令（推荐方式）
	if executable('llm_engine')
		return 'llm_engine'
	endif
	if executable('llm-engine')
		return 'llm-engine'
	endif

	" 2. 尝试 python -m llm_engine
	let l:python_cmd = executable('python3') ? 'python3' : 'python'
	let l:check = system(l:python_cmd . ' -m llm_engine --help 2>/dev/null')
	if v:shell_error == 0
		return l:python_cmd . ' -m llm_engine'
	endif

	return ''
endfunction

" 检查环境是否有效
function! s:CheckEnvironment()
	let l:engine = s:FindLLMEngine()
	if empty(l:engine)
		return {'ok': 0, 'msg': 'llm_engine 未找到。请运行: pip install -e /path/to/llm_with_vim'}
	endif

	return {'ok': 1, 'engine': l:engine}
endfunction

" 全局变量存储环境检查结果
let s:env_status = {'checked': 0, 'ok': 0}

" outline的文件名（该文件不需要保存）
let s:outline_bname = 'diaglog-outline.buffer'

" === 非阻塞LLM请求状态 ===
let s:gen_job = v:null
let s:gen_timer = -1
let s:gen_state = {}

" 中断LLM请求
function! s:StopGen()
	if s:gen_job == v:null || job_status(s:gen_job) != 'run'
		return
	endif
	let s:gen_state.int_by_key = 1
	call job_stop(s:gen_job)
	" 1秒后仍未退出则SIGKILL
	call timer_start(1000, function('s:KillGenFallback'))
endfunction

function! s:KillGenFallback(timer_id)
	if s:gen_job != v:null && job_status(s:gen_job) == 'run'
		call job_stop(s:gen_job, 'kill')
	endif
endfunction

" 临时解除nomodifiable写入目标buffer，写完恢复
function! s:BufWrite(buf, lnum, text)
	call setbufvar(a:buf, '&modifiable', 1)
	call appendbufline(a:buf, a:lnum, a:text)
	call setbufvar(a:buf, '&modifiable', 0)
endfunction

function! s:BufSetLine(buf, lnum, text)
	call setbufvar(a:buf, '&modifiable', 1)
	call setbufline(a:buf, a:lnum, a:text)
	call setbufvar(a:buf, '&modifiable', 0)
endfunction

" 输出回调（每次一行，写入目标buffer而非当前buffer）
function! s:HandleGenOutput(channel, msg)
	let s = s:gen_state
	if !bufexists(s.target_buf) | return | endif
	if s.line_no
		call s:BufWrite(s.target_buf, s.line_no, a:msg)
	else
		call s:BufSetLine(s.target_buf, 1, a:msg)
	endif
	let s.line_no += 1
	" 仅当用户在目标buffer中时才移动光标
	if bufnr('%') == s.target_buf
		call cursor(s.line_no, 1)
	endif
	redraw
endfunction

" 错误回调
function! s:HandleGenErr(channel, msg)
	let s = s:gen_state
	if !bufexists(s.target_buf) | return | endif
	call s:BufWrite(s.target_buf, 0, a:msg)
	let s.interrupted = 2
endfunction

" 进程退出回调（清理工作）
function! s:HandleGenExit(job, status)
	if s:gen_timer >= 0
		call timer_stop(s:gen_timer)
		let s:gen_timer = -1
	endif
	let s = s:gen_state
	let &laststatus = s.old_lst
	let &statusline = ''
	if bufexists(s.temp_buf)
		execute 'bdelete! ' . s.temp_buf
	endif
	if bufexists(s.target_buf)
		" 恢复modifiable状态（生成期间被设为nomodifiable）
		call setbufvar(s.target_buf, '&modifiable', 1)
		if s.int_by_key
			call appendbufline(s.target_buf, s.line_no, '<<===中断操作===>>')
		elseif s.interrupted
			call appendbufline(s.target_buf, s.line_no, '<<===执行错误，尽快undo，不要存盘！！===>>')
		else
			call appendbufline(s.target_buf, s.line_no, 'User: ')
		endif
		if bufnr('%') == s.target_buf
			call cursor(s.line_no + 1, 1)
		endif
	endif
	let s:gen_job = v:null
	redraw
endfunction

" 状态栏定时器
function! s:GenTimerCb(timer_id)
	let elapsed = localtime() - s:gen_state.start_sec
	let &statusline = '请求LLM（' . elapsed . '秒），按K（大写）中断...'
	redraw
endfunction

" 把[1,当前行]发入llm_engine获取输出（非阻塞，用户可浏览文件）
function! DoGen()
	" 防止并发请求
	if s:gen_job != v:null && job_status(s:gen_job) == 'run'
		echohl WarningMsg
		echo 'LLM请求进行中，按K中断当前请求'
		echohl None
		return
	endif

	" 检查环境
	if !s:env_status.checked || !s:env_status.ok
		let s:env_status = s:CheckEnvironment()
		let s:env_status.checked = 1
		if !s:env_status.ok
			echohl ErrorMsg
			echo '错误: ' . s:env_status.msg
			echohl None
			return
		endif
	endif

	" 为每个buffer创建唯一的临时buffer名称
	let l:current_buf = bufnr('%')
	let l:temp_buf_name = 'temp_llm_input_' . l:current_buf

	" 保存开头到当前位置到临时Buffer中作为输入
	let content = join(getline(1, '.'), "\n")
	let l:temp_buf = bufnr(l:temp_buf_name, 1)
	call bufload(l:temp_buf)
	call setbufline(l:temp_buf, 1, split(content, "\n"))

	" 清除用于输入的内容
	execute '1,.d'
	normal O

	" 生成期间设为只读，防止用户编辑导致行号错位
	setlocal nomodifiable

	" 初始化状态
	let s:gen_state = {
		\ 'target_buf': l:current_buf,
		\ 'temp_buf': l:temp_buf,
		\ 'line_no': 0,
		\ 'interrupted': 0,
		\ 'int_by_key': 0,
		\ 'old_lst': &laststatus,
		\ 'start_sec': localtime(),
	\ }

	" 构建命令
	let l:file_dir = expand('%:p:h')
	let l:cmd = s:env_status.engine

	" 异步请求LLM（exit_cb在进程退出后清理）
	let s:gen_job = job_start(l:cmd, {
		\ 'in_io': 'buffer',
		\ 'in_buf': l:temp_buf,
		\ 'out_cb': function('s:HandleGenOutput'),
		\ 'err_cb': function('s:HandleGenErr'),
		\ 'exit_cb': function('s:HandleGenExit'),
		\ 'env': {'LLM_FILE_DIR': l:file_dir},
	\ })

	" 设置状态栏并启动定时器
	let &laststatus = 2
	let &statusline = '请求LLM...'
	let s:gen_timer = timer_start(500, function('s:GenTimerCb'), {'repeat': -1})
endfunction

" 根据outline的行号退出outline窗口，转到正文对应位置
function! DiaglogOutlineGotoLine(lnum)
	let l:lnum = b:outline_marks[a:lnum-1]
	execute "q!"
	execute "bd" s:outline_bname
	execute l:lnum
endfunction

" 预览图片（光标需在 $$path$$ 位置）
function! PreviewImage()
	" 获取当前行
	let line = getline('.')
	" 匹配 $$...$$ 模式
	let match = matchstr(line, '\$\$[^$]*\$\$')
	if empty(match)
		echohl WarningMsg
		echo '当前行没有图片引用，格式: $$path/to/image.png$$'
		echohl None
		return
	endif
	
	" 提取图片路径
	let img_path = substitute(match, '\$\$\(.*\)\$\$', '\1', '')
	
	" 处理路径：如果是相对路径，基于当前文件目录
	if img_path[0] !=# '/' && img_path[1:2] !=# ':\\'
		let base_dir = expand('%:p:h')
		let img_path = base_dir . '/' . img_path
	endif
	
	" 检查文件是否存在
	if !filereadable(img_path)
		echohl ErrorMsg
		echo '图片不存在: ' . img_path
		echohl None
		return
	endif
	
	" 尝试用系统命令打开图片
	if has('mac')
		call system('open ' . shellescape(img_path))
	elseif has('unix')
		call system('xdg-open ' . shellescape(img_path) . ' &')
	elseif has('win32')
		call system('start "" ' . shellescape(img_path))
	else
		let &statusline = '图片路径: ' . img_path
		return
	endif
	
	let &statusline = '正在打开图片: ' . img_path
endfunction

" 实现Outline
function! OpenDiaglogOutline()
	if buflisted(s:outline_bname)
		if bufname() == s:outline_bname
			execute "q!"
			execute "bd!" s:outline_bname
		endif
		return
	endif

	let l:all_lines = getline(0, '$')
	let l:cline = line(".")
	let l:ocline = 1

	execute '35vnew' s:outline_bname
	execute 'set nowrap'
	execute 'syn match Search "[>+-]"'

	let l:n = 1
	let l:m = 1
	let l:last_line = ""
	let b:outline_marks = []
	let l:levelstr=""
	for line in l:all_lines
		if line =~ "^User: " || line =~ "^Configure: "
			call setbufline(s:outline_bname, l:m, line)
			call add(b:outline_marks, l:n)
			let l:m += 1
			if l:cline > l:n
				let l:ocline = l:m   " 更新outline下标
			endif
		endif
		let l:last_line = line
		let l:n += 1
	endfor

	execute l:ocline

	execute "nmap <buffer> <CR> :call DiaglogOutlineGotoLine(line('.'))<CR>"
	execute "nmap <buffer> q :q!<CR>:bd " . s:outline_bname . "<CR>"
	execute "nmap <buffer> <F2> :q!<CR>:bd " . s:outline_bname . "<CR>"
endfunction

function! s:SetupLLMBuffer()
	" 检查环境并显示错误（如果有）
	if !s:env_status.checked
		let s:env_status = s:CheckEnvironment()
		let s:env_status.checked = 1
		if !s:env_status.ok
			echohl WarningMsg
			echo 'LLM插件环境检查失败: ' . s:env_status.msg
			echohl None
		endif
	endif

	" syntax本来就是针对当前Buffer的
	syn match comment "^@##.*$"
	syn match comment "^@//.*$"
	syn match Title "^Configure: .*$"
	" 图片引用语法 $$path$$
	syn match Special "\$\$[^$]*\$\$"
	syn keyword Type Assistant System
	syn match Type "^@@inc "
	syn keyword Keyword User

	" 给当前buffer设置热键
	nmap <buffer> j gj
	nmap <buffer> k gk
	nnoremap <buffer> K :call <SID>StopGen()<CR>
	nmap <buffer> <F1> :call DoGen()<CR>
	nmap <buffer> <F2> :call OpenDiaglogOutline()<CR>
	" F3: 预览图片（光标在$$...$$位置）
	nmap <buffer> <F3> :call PreviewImage()<CR>
	imap <buffer> jj <C-G>u<ESC>:call DoGen()<CR>

	ab <buffer> WAns Write a new scene:
	ab <buffer> ITns In the next scene,
	ab <buffer> configO Configure:  {'engine_type': 'ollama', 'server_addr': 'localhost', 'model': 'gpt-oss:20b', 'max_tokens': 1024, 'temperature': 1, 'keep_alive': 3600, 'tools' : ['read', 'web_search']}
	ab <buffer> configAli Configure: {'engine_type': 'ali', 'auth': 'sk-xxxxxxxxxxxxxxxxxxxxx'}
	ab <buffer> configHj Configure:  {'engine_type': 'haijing', 'auth': 'Basic xxxxxxxxxxxxxxxxxxxxxxxxxxx'}
	ab <buffer> configZp Configure:  {'engine_type': 'zhipu', 'auth': 'Bearer xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx.xxxxxxxxxxxxxxxx', 'max_tokens': 10240, 'temperature': 1}
	" 图片引用示例缩写
	ab <buffer> imgpath $$path/to/image.png$$
	setlocal spell
	setlocal complete+=kspell
endfunction

" 对.llm文件实现LLM的交互逻辑
augroup llm_filetype
  autocmd!
  autocmd FileType llm call s:SetupLLMBuffer()
augroup END
