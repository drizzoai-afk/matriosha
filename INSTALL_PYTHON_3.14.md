# Installing Matriosha on Python 3.14.4

Matriosha now supports Python 3.14.4.

The default installation path avoids hard dependency on `pyarrow`/`lancedb`, so base installs work without waiting for every vector-stack wheel to be available on PyPI.

## Quick Install (Recommended)

```bash
pip install "git+https://github.com/drizzoai-afk/matriosha_legacy.git@launch-readiness-e2e"
```

## If you explicitly need LanceDB/PyArrow features

Install the optional vector extra:

```bash
pip install "matriosha[vector] @ git+https://github.com/drizzoai-afk/matriosha_legacy.git@launch-readiness-e2e"
```

If your platform/Python combo cannot resolve a wheel for `pyarrow`, use one of these alternatives.

### Option A: Conda/Mamba (best for binary availability)

```bash
conda install -c conda-forge pyarrow
pip install "git+https://github.com/drizzoai-afk/matriosha_legacy.git@launch-readiness-e2e"
```

### Option B: Pre-release PyArrow wheels

```bash
pip install --pre pyarrow
pip install "git+https://github.com/drizzoai-afk/matriosha_legacy.git@launch-readiness-e2e"
```

### Option C: Build PyArrow from source

macOS:

```bash
brew install apache-arrow
pip install pyarrow --no-binary pyarrow
pip install "git+https://github.com/drizzoai-afk/matriosha_legacy.git@launch-readiness-e2e"
```

Ubuntu/Debian:

```bash
sudo apt install libarrow-dev
pip install pyarrow --no-binary pyarrow
pip install "git+https://github.com/drizzoai-afk/matriosha_legacy.git@launch-readiness-e2e"
```
