" 重复加载检查
if exists("g:llama_story_enable")
	finish
endif
let g:llama_story_enable = 1

" 检查工作环境
let envcheck = system("./testenv.sh")
if v:shell_error != 0
	echo "环境检查失败：" . envcheck
	finish
endif

" outline的文件名（该文件不需要保存）
let s:outline_bname = 'diaglog-outline.buffer'

" 把[1,当前行]发入llama.py获取输出
function DoGen()
	" 保存开头到当前位置到临时Buffer中作为输入
	let content = join(getline(1, '.'), "\n")
	let l:temp_buf = bufnr('temp_llama_input', 1)
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

	" 异步请求LLM
	let l:job = job_start('python3 llama.py', {
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
		if getchar(1) == char2nr('K')
			let l:interrupted = 2
			let l:int_by_key = 1
			call job_stop(l:job)
		endif
		sleep 100m
		let waitm += 1
		if (waitm % 10) == 0
			let &statusline = '请求LLM（' . waitm/10 . '秒），按K（大写）中断...'
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

	execute "nmap <buffer> <CR> :call OutlineGotoLine(line('.'))<CR>"
	execute "nmap <buffer> q :q!<CR>:bd " . s:outline_bname . "<CR>"
	execute "nmap <buffer> <F2> :q!<CR>:bd " . s:outline_bname . "<CR>"
endfunction

function Setting()
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

" 对文本文件实现LLM的故事逻辑
augroup story_txt
  autocmd!
  autocmd BufRead,BufNewFile *.txt,*.tmp call Setting()
augroup END
