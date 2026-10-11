cd /home/ubuntu/ict-trading-bot 2>/dev/null || { echo NO_REPO; exit 3; }
echo "== git: $(git rev-parse --short HEAD) branch=$(git rev-parse --abbrev-ref HEAD)"
echo "== has ml_bakeoff in checkout: $(test -f scripts/research/ml_bakeoff.py && echo yes || echo no)"
echo "== has script_run: $(test -f scripts/research/script_run.py && echo yes || echo no)"
PY=/home/ubuntu/ict-trading-bot/.venv/bin/python
echo "== venv python: $($PY -V 2>&1)"
for m in numpy pandas yaml pyarrow sklearn lightgbm catboost torch transformers chronos timesfm tirex tabpfn tabicl huggingface_hub; do
  v=$($PY -c "import $m;print(getattr($m,'__version__','ok'))" 2>&1 | tail -1)
  echo "   $m: $v"
done
echo "== mem/disk"; free -m | sed -n 1,2p; df -h / | tail -1
echo "== heavy lock file: $(ls -la runtime_logs/trainer/.heavy.lock 2>&1 | tail -1)"
echo "== role marker: $(cat /etc/ict-trainer-vm.role 2>/dev/null | head -1; cat /etc/ict-vm-role 2>/dev/null | head -1)"
echo "== datasets dir candidates"
ls -d runtime_logs/trainer/datasets* ml/datasets/store* data/datasets* 2>/dev/null | head
find / -maxdepth 6 -name "*.parquet" -path "*dataset*" 2>/dev/null | head -8
echo "== HF cache: $(du -sh ~/.cache/huggingface 2>/dev/null | cut -f1)"
echo "== git sync timer"; systemctl list-timers --no-pager 2>/dev/null | grep -iE "git|sync" | head -3
