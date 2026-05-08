# tarka-py

PyO3 bindings for Tarka: native helpers (`tarka._tarka`) plus pure Python modules (`tarka.verifier`, wire protobuf stubs, etc.). Built with [maturin](https://www.maturin.rs/).

## Local Setup (Apple Silicon / M-series MacBooks)

These steps assume an **arm64** Python (recommended on M1/M2/M3/M4). Avoid mixing Rosetta-x86_64 Python with an arm64 Rust toolchain.

1. **Xcode Command Line Tools** (Clang + linker):

   ```bash
   xcode-select --install
   ```

2. **Rust** (stable), via [rustup](https://rustup.rs/):

   ```bash
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
   ```

   On Apple Silicon, `rustc --print host-spec` should show `aarch64-apple-darwin`.

3. **Python 3.10+** in a virtual environment (example):

   ```bash
   cd crates/tarka-py
   python3 -m venv .venv
   source .venv/bin/activate
   pip install --upgrade pip
   pip install maturin
   ```

4. **Build and install the native extension in editable mode** with maturin (pulls runtime deps from `pyproject.toml`; add optional dev extras such as pytest):

   ```bash
   maturin develop --extras dev
   ```

   For an optimized native build (slower compile, faster runtime):

   ```bash
   maturin develop --release --extras dev
   ```

   This compiles the `tarka-py` crate (and its Rust dependency graph, including `tarka-core`) and installs the `tarka` package into the active environment.

5. **Sanity check**:

   ```bash
   python -c "import tarka; import tarka._tarka; print('ok')"
   ```

6. **Tests** (from `crates/tarka-py` with the venv activated):

   ```bash
   pytest tests/
   ```

If `cargo` cannot link, confirm Command Line Tools are installed and that `python3` points at the same architecture as `rustc` (`file "$(which python3)"` should mention `arm64` on M-series).
