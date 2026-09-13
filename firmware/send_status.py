#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, sys
send_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../host_bridge/send_status.py"))
os.execv(sys.executable, [sys.executable, send_path] + sys.argv[1:])
