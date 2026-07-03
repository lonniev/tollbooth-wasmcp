.PHONY: all deps build compose run clean

VENV       := .venv
PY         := $(VENV)/bin/python
CPY        := $(VENV)/bin/componentize-py
COMPONENT  := operator
# The tollbooth-wasmcp adapter, in-repo (sibling). An out-of-repo operator instead
# `pip install tollbooth-wasmcp` into deps/ and points these at deps/tollbooth_wasmcp/…
ADAPTER    := ../..
ADAPTER_PKG := $(ADAPTER)
TOPLEVEL   := $(ADAPTER)/tollbooth_wasmcp/_toplevel
WIT        := $(ADAPTER)/tollbooth_wasmcp/wit
CRYPTO     := $(ADAPTER)/tollbooth_wasmcp/crypto.wasm

all: compose

# Build tool + bundled deps. tollbooth-dpyc goes in --no-deps (its native crypto
# libs are lazy and must not be bundled); only httpx (+ pure deps) is added.
deps:
	uv venv --python 3.12 $(VENV)
	uv pip install --python $(PY) "componentize-py==0.24.*"
	rm -rf deps
	uv pip install --target deps --no-deps "tollbooth-dpyc==0.59.1"
	uv pip install --target deps "httpx==0.28.1"

# Compile the Python component. The adapter package + its top-level shims (pynostr,
# cryptography) join the module path; the standardized WIT world comes from the adapter.
# NOTE: never run `componentize-py bindings` separately — it clobbers poll_loop.py.
build:
	$(CPY) --wit-path $(WIT) --world $(COMPONENT) componentize app \
	  -p . -p deps -p $(ADAPTER_PKG) -p $(TOPLEVEL) -o $(COMPONENT).wasm

# Plug the composed dpyc:crypto component in, then wrap with wasmcp transport.
compose: build
	wac plug $(COMPONENT).wasm --plug $(CRYPTO) -o plugged.wasm
	wasmcp compose server plugged.wasm -o server.wasm --force

run: compose
	spin up

clean:
	rm -rf $(VENV) deps wit_world __pycache__ componentize_py_runtime.pyi $(COMPONENT).wasm plugged.wasm server.wasm
