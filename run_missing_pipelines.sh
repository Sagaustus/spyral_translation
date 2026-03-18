#!/bin/bash
cd /root/spyral_translation

# Locales that failed in the first run due to missing NLLB mappings
LOCALES=(as bn bo bs el gu he hr kn ml mr or pa ro ru sl sr sv ta te tr ur fa)

LOGFILE="/root/spyral_translation/pipeline_run_2.log"
echo "=== Pipeline run 2 started at $(date) ===" > "$LOGFILE"

for LOCALE in "${LOCALES[@]}"; do
  echo ""
  echo ">>> Running pipeline for: $LOCALE"
  echo "--- $LOCALE started at $(date) ---" >> "$LOGFILE"
  python3 manage.py run_pipeline \
    --locale "$LOCALE" \
    --engine nllb \
    --limit 960 \
    --no-score \
    --verbose \
    2>&1 | tee -a "$LOGFILE"
  echo "--- $LOCALE finished at $(date) ---" >> "$LOGFILE"
done

echo ""
echo "=== All pipelines finished at $(date) ===" | tee -a "$LOGFILE"
