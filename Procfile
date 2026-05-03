# Railway Procfile — defines each runnable process type.
#
# We don't actually run any of these as long-running web services. Each
# is registered in Railway as a CRON service whose start command is
# `python <file>`. See docs/CLOUD_DEPLOY.md for the cron schedule matrix.
#
# Listed here for reference / for any local dev who wants to use foreman:

scraper:    python cheaphomesfla_scraper.py
jb_email:   python jb/email_campaign.py
jb_sms:     python jb/sms_campaign.py
watchdog:   python tools/system_watchdog.py
