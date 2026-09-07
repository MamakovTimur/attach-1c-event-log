#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compatibility entry point; the canonical CLI lives in tools/attach_event_log.py."""

from tools.attach_event_log import main


if __name__ == "__main__":
    raise SystemExit(main())
