#!/bin/bash

python >/dev/null 2>&1 <<EOF
import requests
import sys
import time
import signal
import json
EOF

ret=$?
if [ $ret -ne 0 ]; then
	echo "Python运行环境未设置（可能你没有激活venv？）"
	exit $ret
fi

exit 0
