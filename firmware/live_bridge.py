#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, sys
bridge_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../host_bridge/live_bridge.py"))
os.execv(sys.executable, [sys.executable, bridge_path] + sys.argv[1:])
