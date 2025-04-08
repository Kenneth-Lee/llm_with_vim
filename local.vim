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

noremap K <Nop>

function! DoGen()
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
	let l:job = job_start('python llama.py', {
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
			let &stl = '请求LLM（' . waitm/10 . '秒），按K（大写）中断...'
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

function Setting()
	syn match comment "^#.*$"
	syn match comment "^//.*$"
	syn match Question "^User: .*$"
	syn keyword Type User Assistant System Configure

	nmap j gj
	nmap k gk
	ab WAns Write a new scene:
	ab ITns In the next scene,
	imap jj <C-G>u<ESC>:call DoGen()<CR>
	nmap <F1> :call DoGen()<CR>
	set spell
	set complete+=kspell
endfunction

augroup story_txt
  autocmd!
  autocmd BufRead,BufNewFile *.txt,*.tmp call Setting()
augroup END
