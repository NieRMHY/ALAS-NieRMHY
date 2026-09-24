#!/bin/bash
# Add by MHY: 拉取远程 ALAS 日志并聚合岛屿经济数据
LDIR="/home/niermhy/workspace/project/project_myself/AzurLane/ALAS/ALAS-NieRMHY"
MDIR="$LDIR/log/island_monitor"
export HOME=/home/niermhy
export PYTHONPATH="$LDIR"
mkdir -p "$MDIR"
TODAY=$(date +%F)
DST="$MDIR/${TODAY}_ALAS.txt"
if scp -P 32721 -o BatchMode=yes -o ConnectTimeout=15 "NieRMHY@192.168.1.41:D:/AzurLane/AzurLaneAutoScript3.14/log/${TODAY}_ALAS.txt" "$DST"; then
    cd "$LDIR" || exit 1
    printf "import module.island.island_monitor as im\nim.main()\n" > .run_mon_tmp.py
    uv run python .run_mon_tmp.py >> "$MDIR/runner.log" 2>&1 && echo "[$(date +%F_%T)] ok" >> "$MDIR/runner.log"
    rm -f .run_mon_tmp.py
else
    echo "[$(date +%F_%T)] scp fail" >> "$MDIR/runner.log"
fi
