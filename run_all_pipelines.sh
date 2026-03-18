#!/bin/bash
# Run NLLB translation pipeline for all locales needing drafts.
# Skips strings that already have an approved_text or machine_draft.
# Uses --no-score to go faster; scoring can be run separately later.

cd /root/spyral_translation

LOCALES=(
  yo am ha ig sw sn so rw xh zu ti   # African
  as bn bo gu hi kn ml mr or pa ta te ur  # South Asian
  ar he fa                             # Middle Eastern (gaps only)
  zh-hans zh-hant                      # Chinese
  sv el ro                             # European (low coverage)
  fr de ru sl pt es it cs bs hr sr ja tr  # European/other (small gaps)
)

LOGFILE="/root/spyral_translation/pipeline_run.log"
echo "=== Pipeline run started at $(date) ===" > "$LOGFILE"

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
