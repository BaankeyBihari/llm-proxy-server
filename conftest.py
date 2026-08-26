# Empty on purpose: its presence makes pytest add the repo root to sys.path
# (default "prepend" import mode), so `from ignition.handler import ...` in
# tests resolves without a src-layout or editable install.
