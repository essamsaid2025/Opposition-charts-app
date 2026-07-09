"""Streamlit entrypoint: `streamlit run app.py`.
Kept to three lines on purpose - all wiring lives in fap.bootstrap,
all rendering in fap.ui."""
from fap.bootstrap import init_app
from fap.ui.shell import run

run(init_app())
