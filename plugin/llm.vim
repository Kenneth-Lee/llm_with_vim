" LLM Chat Plugin for Vim
" 重复加载检查
if exists("g:llm_engine_loaded")
	finish
endif
let g:llm_engine_loaded = 1

" 查找llm_engine.py的路径
" 搜索顺序: 1. 插件目录 2. PATH环境变量
function! s:FindLLMEngine()
	" 1. 检查插件目录
	let l:script_dir = expand('<sfile>:p:h')
	let l:engine_path = l:script_dir . '/llm_engine.py'
	if filereadable(l:engine_path)
		return l:engine_path
	endif
	
	" 检查插件父目录（兼容plugin/子目录结构）
	let l:parent_dir = fnamemodify(l:script_dir, ':h')
	let l:engine_path = l:parent_dir . '/llm_engine.py'
	if filereadable(l:engine_path)
		return l:engine_path
	endif
	
	" 2. 检查PATH中是否有llm_engine.py
	if executable('llm_engine.py')
		return 'llm_engine.py'
	endif
	
	" 3. 检查当前工作目录
	if filereadable('llm_engine.py')
		return 'llm_engine.py'
	endif
	
	return ''
endfunction

" 检查环境是否有效
function! s:CheckEnvironment()
	" 检查Python
	if !executable('python3') && !executable('python')
		return {'ok': 0, 'msg': 'Python 3 未安装或不在PATH中'}
	endif
	
	" 检查llm_engine.py
	let l:engine = s:FindLLMEngine()
	if empty(l:engine)
		return {'ok': 0, 'msg': 'llm_engine.py 未找到。请将其放在插件目录或PATH中'}
	endif
	
	" 测试Python环境（检查requests包）
	let l:python_cmd = executable('python3') ? 'python3' : 'python'
	let l:test_cmd = l:python_cmd . ' -c "import requests; import json"'
	let l:result = system(l:test_cmd)
	if v:shell_error != 0
		return {'ok': 0, 'msg': 'Python环境缺少必需的包。请运行: pip install requests'}
	endif
	
	return {'ok': 1, 'engine': l:engine, 'python': l:python_cmd}
endfunction

" 全局变量存储环境检查结果
let s:env_status = {'checked': 0, 'ok': 0}

" outline的文件名（该文件不需要保存）
let s:outline_bname = 'diaglog-outline.buffer'

" 把[1,当前行]发入llm_engine.py获取输出
function! DoGen()
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
	
	" 保存开头到当前位置到临时Buffer中作为输入
	let content = join(getline(1, '.'), "\n")
	let l:temp_buf = bufnr('temp_llm_input', 1)
	call bufload(l:temp_buf)
	call setbufline(l:temp_buf, 1, split(content, "\n"))

	" 清除用于输入的内容
	execute '1,.d'
	normal O

	" 输出位置，0表示初始状态
	let l:line_no = 0
	let l:interrupted = 0
	let l:int_by_key = 0

	" 输出回调（每次输出一行）
	function! HandleOutput(channel, msg) closure
		if l:line_no
			call append(l:line_no, a:msg)
		else
			call setline(1, a:msg)
		endif

		let l:line_no += 1
		call cursor(l:line_no, 1)
		redraw
	endfunction

	" 输出错误
	function! HandleErr(channel, msg) closure
		call append(0, a:msg)
		let l:interrupted = 2
	endfunction

	" 构建命令
	let l:cmd = s:env_status.python . ' ' . s:env_status.engine

	" 异步请求LLM
	let l:job = job_start(l:cmd, {
		\ 'in_io': 'buffer',
		\ 'in_buf': l:temp_buf,
		\ 'out_cb': function('HandleOutput'),
		\ 'err_cb': function('HandleErr'),
	\ })

	let old_lst = &laststatus
	let &laststatus = 2
	let &stl = '请求LLM...'
	let waitm = 0

	while job_status(l:job) == 'run'
		" 清空并检查所有待处理的按键
		let l:key = 0
		while 1
			let l:key = getchar(1)
			if l:key == 0
				break  " 没有更多按键了
			endif
			if l:key == char2nr('K')
				let l:interrupted = 2
				let l:int_by_key = 1
				call job_stop(l:job)
				break  " 检测到K键，跳出
			endif
			" 其他按键被消费掉，避免污染缓冲区
		endwhile

		if l:int_by_key
			break  " 已中断，退出主循环
		endif

		sleep 50m
		let waitm += 1

		" 更频繁地更新状态栏（每0.5秒）
		if (waitm % 5) == 0
			let &statusline = '请求LLM（' . (waitm/10.0) . '秒），按K（大写）中断...'
			redraw
		endif
	endwhile

	let &laststatus = old_lst
	execute 'bdelete! ' . l:temp_buf
	if l:int_by_key == 1
		normal o<<===中断操作===>>
	elseif l:interrupted
		normal o<<===执行错误，尽快undo，不要存盘！！===>>
	else
		normal oUser:
	endif
endfunction

" 根据outline的行号退出outline窗口，转到正文对应位置
function! DiaglogOutlineGotoLine(lnum)
	let l:lnum = b:outline_marks[a:lnum-1]
	execute "q!"
	execute "bd" s:outline_bname
	execute l:lnum
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
	syn match comment "^#.*$"
	syn match comment "^//.*$"
	syn match Search "^User: .*$"
	syn match Title "^Configure: .*$"
	syn keyword Type Assistant System

	" 给当前buffer设置热键
	nmap <buffer> j gj
	nmap <buffer> k gk
	noremap <buffer> K <Nop>
	nmap <buffer> <F1> :call DoGen()<CR>
	nmap <buffer> <F2> :call OpenDiaglogOutline()<CR>
	imap <buffer> jj <C-G>u<ESC>:call DoGen()<CR>

	ab <buffer> WAns Write a new scene:
	ab <buffer> ITns In the next scene,
	setlocal spell
	setlocal complete+=kspell
endfunction

" 对.llm文件实现LLM的交互逻辑
augroup llm_filetype
  autocmd!
  autocmd FileType llm call s:SetupLLMBuffer()
augroup END
