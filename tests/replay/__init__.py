"""Replay level of the end-to-end user stories (test-only, never shipped).

A specialist step under replay writes the files the real step wrote in one of
the recorded demonstration runs, instead of calling a model. Everything else
(the runner, the checks, the researcher steps, export, verify, publish) is the
real code. See ``tests/replay/README.md``.
"""
