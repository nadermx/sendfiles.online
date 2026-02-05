# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**SendFiles.Online** - A fast, simple file sharing platform built on DjangoBase. Competes with WeTransfer, Smash, and similar services.

**Live site**: https://sendfiles.online

**Key Features:**
- Up to 10GB free transfers (14-day retention)
- No signup required for basic transfers
- Optional password protection and encryption
- Industrial grayscale design (Inter + JetBrains Mono fonts)

## Development Commands

```bash
# Activate shared venv (from project root)
source ../venv/bin/activate

# Run development server
python manage.py runserver

# Database migrations
python manage.py makemigrations
python manage.py migrate

# Load translation strings
python manage.py set_languages
```

## Architecture

### Core Apps

| App | Purpose |
|-----|---------|
| `transfers/` | File upload, download, share links |
| `accounts/` | User auth (email-based, from DjangoBase) |
| `finances/` | Payments (Stripe, PayPal, Square, Coinbase) |
| `core/` | Static pages (pricing, about, contact) |
| `translations/` | Database-driven i18n system |

### Key Models (transfers/)

- **Transfer** - UUID pk + 8-char `short_id` for URLs. Status flow: `uploading → ready → expired/deleted`
- **TransferFile** - Individual files (original name, UUID stored name, size, mime type)
- **DownloadEvent** - Download analytics

### API Endpoints

```
POST /api/transfers/                    # Create transfer
POST /api/transfers/<uuid>/upload/      # Upload file
POST /api/transfers/<uuid>/finalize/    # Finalize, get share URL
```

### URL Routes

```
/d/<short_id>/                  # Download page
/d/<short_id>/file/<file_id>/   # Single file download
/d/<short_id>/download/         # Download all as ZIP
/sent/<short_id>/               # Upload success page
```

### Configuration

- `app/settings.py` - Django settings
- `config.py` - Secrets, domain, payment keys (git-ignored, copy from `config_example.py`)

Key config values:
```python
FILES_LIMIT = 10737418240       # 10GB
FREE_TIER_RETENTION = 14        # Days
ROOT_DOMAIN = 'https://sendfiles.online'
```

### File Storage

Files stored in `/uploads/transfers/` with UUID names. Original filenames preserved in database.

### Translation System

Database-driven (not Django i18n). Use in templates:
```html
{{ g.i18n.code_name|default:"Fallback text" }}
```

## Deployment

**Server:** 147.182.208.66 (Ubuntu, Supervisor: `sendfiles`, Path: `/home/www/sendfiles/`)

```bash
cd ansible

# Deploy code updates
ansible -i servers all -m shell -a "cd /home/www/sendfiles && git pull" --become

# Restart application
ansible -i servers all -m shell -a "supervisorctl restart sendfiles" --become

# Update nginx config
ansible -i servers all -m template -a "src=files/nginx.conf.j2 dest=/etc/nginx/sites-available/sendfiles.conf" --become
ansible -i servers all -m shell -a "nginx -t && systemctl reload nginx" --become

# Check logs
ansible -i servers all -m shell -a "tail -100 /var/log/sendfiles/sendfiles.err.log" --become

# Full initial deployment (new server)
ansible-playbook -i servers djangodeployubuntu20.yml
```

## Design System

- Primary: #111111 (gray-900)
- Background: #f5f5f5 (gray-50)
- Borders: #d4d4d4 (gray-200)
- No rounded corners (border-radius: 0)
- Fonts: Inter (body), JetBrains Mono (code/sizes)

## Related Projects

- **sfe/** (sendfilesencrypted.com) - E2E encrypted version
- **sfe-files/** - Files API for SFE
