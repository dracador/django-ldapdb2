# Debugging & Logging

Enable Django logging to see what LDAP operations are being issued.

## Logging Setup

```python
# settings.py
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'level': 'DEBUG'},
    },
    'loggers': {
        # activate ldapdb logger for very detailed logging
        'ldapdb': {'handlers': ['console'], 'level': 'DEBUG'},
        
        # activate django db logger for just SQL-like queries
        'django.db.backends': {'handlers': ['console'], 'level': 'DEBUG'},
    },
}
```