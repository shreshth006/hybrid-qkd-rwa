#!/usr/bin/env bash
# Runs the report's full protocol (50 realisations x 100,000 measured requests),
# then rebuilds the report from those results. Progress: tail -f full_run.log
set -u
J="$HOME/Desktop/Projects/hybrid-qkd-rwa"
SIM="$J/simulation"
TOOLS="$J/report/tools"
export PANDOC="$SIM/.venv/lib/python3.13/site-packages/pypandoc/files/pandoc"
STATUS="$J/FULL_RUN_STATUS.txt"

echo "running since $(date)" > "$STATUS"
cd "$SIM" || exit 1
if ! .venv/bin/python tdpc_rwa_simulator.py --mode full --seeds 50 --requests 100000 --no-color \
        --outdir results_full50 > results_full50.log 2>&1; then
    echo "FAILED: simulation error at $(date). See simulation/results_full50.log" > "$STATUS"
    exit 1
fi

cd "$TOOLS" || exit 1
cp -n "$J/report/Review_3_completed.docx" "$J/report/Review_3_completed_10x20k.docx"
cp -n "$J/report/Review_3_completed.pdf" "$J/report/Review_3_completed_10x20k.pdf"
if ! python3 build_report.py "$SIM/results_full50" "$SIM/results_full50.log" x > "$J/report/rebuild.log" 2>&1; then
    { echo "SIMULATION DONE at $(date), but the report was NOT rebuilt:"; cat "$J/report/rebuild.log"; } > "$STATUS"
    exit 1
fi
python3 make_docx.py "$J/report/Review_3_completed.docx" >> "$J/report/rebuild.log" 2>&1 &&
    soffice --headless --convert-to pdf --outdir "$J/report" "$J/report/Review_3_completed.docx" >> "$J/report/rebuild.log" 2>&1
echo "DONE at $(date): report rebuilt from 50 x 100,000-request results (previous version kept as *_10x20k)" > "$STATUS"
