#!/bin/env bash

set -xe
source /home/seb/git/s2-polars-data-analysis/venv/bin/activate
jupyter lab --ip=0.0.0.0 --no-browser --port=8888 --NotebookApp.token='' --NotebookApp.password="JPT_PASSWD" --NotebookApp.disable_check_xsrf=True --notebook-dir=/home/seb/git/s2-polars-data-analysis/jupyter_notebooks/
