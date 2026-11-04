#!/bin/env bash
# Starts Jupyter Lab on the notebooks, for a systemd unit or by hand.
# The notebooks read the snapshot from $S2_IPC_DIR (default ~/SC2Replays/ipcs), i.e.
#   S2_IPC_DIR=~/SCReplaysOnNVMe/ipcs ./start-jupyter-lab.sh

set -xe
cd /home/seb/git/s2-polars-data-analysis
export S2_IPC_DIR="${S2_IPC_DIR:-$HOME/SC2Replays/ipcs}"
exec uv run jupyter lab --ip=0.0.0.0 --no-browser --port=8888 --NotebookApp.token='' --NotebookApp.password="JPT_PASSWD" --NotebookApp.disable_check_xsrf=True --notebook-dir=/home/seb/git/s2-polars-data-analysis/jupyter_notebooks/
