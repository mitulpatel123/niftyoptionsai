# DEPLOYMENT GUIDE - Quick Start

## Pre-Deployment Checklist ✅

- [ ] All 7 fixes have been implemented locally
- [ ] IMPLEMENTATION_SUMMARY.md reviewed
- [ ] CHANGES_DETAILED.md reviewed
- [ ] You have VPS SSH access
- [ ] PostgreSQL running on VPS
- [ ] Python 3.8+ and pip on VPS

---

## Step 1: Local Testing (Optional but Recommended)

### Test 1: Feature Building
```bash
cd /Users/mitulpatel/Test/Trading/niftyoptionsai

# Test if feature build works with new code
python jobs/build_labels_daily.py --date 2026-05-25 --symbols NIFTY

# Expected output:
# ✅ Features built successfully
# ✅ Check latest_features.csv has current timestamp
```

### Test 2: Database Maintenance
```bash
# Only if you have local PostgreSQL running
# python scripts/db_maintenance.py

# This will try to:
# - Delete data older than 90 days
# - Compress hypertables
# - Analyze database
```

### Test 3: Metadata Caching
```bash
# Test metadata loader with caching
python -c "
import sys
sys.path.insert(0, '.')
from ingest.metadata_loader import MetadataLoader
loader = MetadataLoader()
instruments = loader.fetchinstrumentmetadata()
print(f'Loaded {len(instruments)} instruments')
# Should cache to /tmp/dhan_instrument_master.csv
"

# On second run, should use cache
# Look for: "Using cached instrument master"
```

---

## Step 2: Deploy to VPS

### 2.1 Connect to VPS
```bash
ssh user@your-vps-ip
# Or if using PEM file:
ssh -i your-key.pem user@your-vps-ip

# Verify you're on VPS
pwd  # Should show /home/user or similar
```

### 2.2 Backup Current Code (IMPORTANT!)
```bash
# On VPS
cd /opt/niftyoptionsai
git init  # If not already git repo
git add .
git commit -m "Backup before fixes deployment - $(date)"

# Or manual backup
cd /opt
cp -r niftyoptionsai niftyoptionsai.backup.$(date +%Y%m%d)
```

### 2.3 Upload New Code from Mac
```bash
# On Mac (local terminal)
cd ~/Test/Trading/niftyoptionsai

# Copy modified files
scp ingest/optionchainingest.py user@vps:/opt/niftyoptionsai/ingest/
scp ingest/websocket_listener.py user@vps:/opt/niftyoptionsai/ingest/
scp ingest/metadata_loader.py user@vps:/opt/niftyoptionsai/ingest/
scp utils/rate_limiter.py user@vps:/opt/niftyoptionsai/utils/

# Copy new scripts
scp scripts/db_maintenance.py user@vps:/opt/niftyoptionsai/scripts/

# Copy systemd files
scp deployment/*.service user@vps:/tmp/
scp deployment/*.timer user@vps:/tmp/
```

### 2.4 Install Systemd Services
```bash
# On VPS
sudo mv /tmp/niftyoptionsai*.service /etc/systemd/system/
sudo mv /tmp/niftyoptionsai*.timer /etc/systemd/system/

# Verify files copied
sudo ls -la /etc/systemd/system/niftyoptionsai*

# Should show:
# niftyoptionsai-daily-features.service
# niftyoptionsai-daily-features.timer
# niftyoptionsai-db-maintenance.service
# niftyoptionsai-db-maintenance.timer
```

### 2.5 Enable Systemd Timers
```bash
# On VPS
sudo systemctl daemon-reload

# Enable (auto-start on reboot)
sudo systemctl enable niftyoptionsai-daily-features.timer
sudo systemctl enable niftyoptionsai-db-maintenance.timer

# Start now (don't wait for next scheduled time)
sudo systemctl start niftyoptionsai-daily-features.timer
sudo systemctl start niftyoptionsai-db-maintenance.timer

# Verify status
sudo systemctl status niftyoptionsai-daily-features.timer
sudo systemctl status niftyoptionsai-db-maintenance.timer

# List all timers (should show your two timers)
sudo systemctl list-timers
```

---

## Step 3: Verify Deployment

### 3.1 Check Service Status
```bash
# On VPS
sudo systemctl list-timers niftyoptionsai*

# Should show output like:
# NEXT                         LEFT      LAST       PASSED UNIT
# Fri 2026-05-25 10:05:00 UTC  5h 32min  n/a        n/a    niftyoptionsai-daily-features.timer
# Fri 2026-05-25 10:30:00 UTC  5h 57min  n/a        n/a    niftyoptionsai-db-maintenance.timer
```

### 3.2 Check Logs Directory
```bash
# On VPS
ls -la /opt/niftyoptionsai/logs/

# Should have (or will create):
# daily-features.log
# daily-features.err.log
# db-maintenance.log
# db-maintenance.err.log
```

### 3.3 Test Run Manually (Optional)
```bash
# On VPS - Run feature build immediately (don't wait for schedule)
python /opt/niftyoptionsai/jobs/run_daily_pipeline.py --skip-ingestion

# Or run database maintenance
python /opt/niftyoptionsai/scripts/db_maintenance.py

# Check output for success messages
```

---

## Step 4: Monitor First Week

### Daily Checks
```bash
# Watch feature build logs (runs at 15:35 IST = 10:05 UTC)
ssh user@vps "tail -20 /opt/niftyoptionsai/logs/daily-features.log"

# Watch database maintenance logs (runs at 16:00 IST = 10:30 UTC)
ssh user@vps "tail -20 /opt/niftyoptionsai/logs/db-maintenance.log"

# Check for errors
ssh user@vps "tail -20 /opt/niftyoptionsai/logs/daily-features.err.log"
```

### Weekly Health Check
```bash
# Check database size (should be under control)
ssh user@vps "psql -d niftyoptionsai -c 'SELECT 
  pg_size_pretty(pg_database_size(current_database())) as db_size;'"

# Check optionchainsnapshot row count (should be ~125K per day)
ssh user@vps "psql -d niftyoptionsai -c 'SELECT COUNT(*) FROM optionchainsnapshot;'"

# Check feature freshness
ssh user@vps "psql -d niftyoptionsai -c 'SELECT MAX(timestamp) FROM feature_store;'"
```

---

## Troubleshooting

### Issue: Systemd timers not running

**Check 1: Is timer enabled?**
```bash
sudo systemctl is-enabled niftyoptionsai-daily-features.timer
# Should return: enabled
```

**Check 2: Did timer start?**
```bash
sudo systemctl is-active niftyoptionsai-daily-features.timer
# Should return: active
```

**Check 3: When will it run?**
```bash
sudo systemctl status niftyoptionsai-daily-features.timer
# Shows NEXT scheduled time
```

**Fix: Restart timer**
```bash
sudo systemctl restart niftyoptionsai-daily-features.timer
sudo systemctl restart niftyoptionsai-db-maintenance.timer
```

---

### Issue: Data quality looks worse (more rows deleted)

**This is expected!** The first run will:
- Filter out 49% of junk data (zero LTP strikes)
- Result: Feature quality improves even if row count drops

**Verify the filter is working:**
```bash
# Check logs for
grep "Option chain parsed" /opt/niftyoptionsai/logs/daily-features.log

# Should show messages like:
# "Option chain parsed: 52,341 kept, 48,929 skipped (48.3%)"
```

---

### Issue: Timer runs but features don't update

**Check 1: Is feature build script running?**
```bash
ps aux | grep build_labels_daily

# If found, it's running. Wait for it to finish.
```

**Check 2: Check error logs**
```bash
tail -100 /opt/niftyoptionsai/logs/daily-features.err.log
```

**Check 3: Run manually for debugging**
```bash
cd /opt/niftyoptionsai
python jobs/run_daily_pipeline.py --skip-ingestion 2>&1 | tee manual-test.log

# Review output for errors
cat manual-test.log
```

---

### Issue: Database maintenance uses too much CPU

**Solution: Reduce frequency or run at off-peak time**
```bash
# Edit timer to run at 20:00 IST (17:30 UTC) instead
sudo systemctl edit niftyoptionsai-db-maintenance.timer

# Change:
# OnCalendar=*-*-* 10:30:00  → OnCalendar=*-*-* 17:30:00

# Restart
sudo systemctl restart niftyoptionsai-db-maintenance.timer
```

---

## Rollback (If Needed)

### Quick Rollback
```bash
# On VPS
cd /opt/niftyoptionsai

# Stop timers
sudo systemctl stop niftyoptionsai-daily-features.timer
sudo systemctl stop niftyoptionsai-db-maintenance.timer

# Restore from backup
cp -r niftyoptionsai.backup.20260525/* .

# Restart your main ingestion service
sudo systemctl restart niftyoptionsai-predictor  # or whatever your service is called
```

---

## Success Indicators ✅

After 1-2 days, you should see:

1. **Features Updated**
   - `latest_features.csv` has today's date/time
   - Feature building completes without errors

2. **Data Quality Improved**
   - Logs show ~50% rows skipped (garbage filtered)
   - Feature store has cleaner data

3. **Database Healthy**
   - Size stabilizes (90-day retention policy)
   - Maintenance completes without errors

4. **No Errors in Logs**
   - daily-features.err.log is empty or minimal
   - db-maintenance.err.log is empty or minimal

---

## Timeline

| When | What | Expected |
|------|------|----------|
| Deploy | Code uploaded | No errors |
| T+0h | Timers enabled | Timers show "active" |
| T+24h | Daily feature build | Features updated at 15:35 IST |
| T+24h | Database maintenance | Cleanup runs at 16:00 IST |
| T+7d | Week 1 complete | Everything running smoothly |

---

## Questions?

**Check these files for more details:**
1. IMPLEMENTATION_SUMMARY.md - Full explanation of all fixes
2. CHANGES_DETAILED.md - Line-by-line changes
3. IMPLEMENTATION_GUIDE.md - Deployment guide (this file)

---

**Good luck with the deployment! Your system is now production-ready. 🚀**
