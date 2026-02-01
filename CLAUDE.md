# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**SendFiles.Online** - A fast, simple file sharing platform competing with WeTransfer, Smash, and similar services.

**Key Features:**
- Up to 10GB free transfers
- No signup required
- 14-day file retention
- Optional password protection
- Optional encryption (server-side or client-side E2E)
- Industrial grayscale design

**Live site**: https://sendfiles.online (when deployed)

## Common Commands

```bash
# Development
source ../venv/bin/activate  # Shared venv with other sfo projects
python manage.py runserver

# Database
python manage.py migrate
python manage.py makemigrations

# Languages
python manage.py set_languages

# Create admin user
python manage.py createsuperuser
```

## Architecture

### Core Apps

- **transfers/** - File transfer functionality (upload, download, share links)
- **accounts/** - User authentication (from djangobase)
- **finances/** - Payment processing (from djangobase)
- **core/** - Static pages (pricing, about, contact)

### Key Models

**Transfer** (`transfers/models.py`)
- UUID primary key + 8-char short_id for URLs
- Tracks files, expiration, password, encryption type
- Status: uploading → ready → expired/deleted

**TransferFile** (`transfers/models.py`)
- Individual files within a transfer
- Stores original name, stored name (UUID), size, mime type

**DownloadEvent** (`transfers/models.py`)
- Analytics for downloads

### API Endpoints

```
POST /api/transfers/                    # Create new transfer
POST /api/transfers/<uuid>/upload/      # Upload file to transfer
POST /api/transfers/<uuid>/finalize/    # Finalize transfer, get share URL
```

### Download URLs

```
/d/<short_id>/                          # Download page
/d/<short_id>/file/<file_id>/           # Download single file
/d/<short_id>/download/                 # Download all as ZIP
/sent/<short_id>/                       # Success page after upload
```

### Configuration

Settings split between:
- `app/settings.py` - Django settings
- `config.py` - Secrets, domain, payment keys (git-ignored)

Key config values in `config.py`:
```python
FILES_LIMIT = 10737418240  # 10GB default
FREE_TIER_RETENTION = 14   # Days
ROOT_DOMAIN = 'https://sendfiles.online'
FILES_API_DOMAIN = 'https://files.sendfiles.online'  # For chunked uploads (future)
```

### File Storage

Files are stored in `/uploads/transfers/` with UUID-based names.
Original filenames are preserved in the database.

## Design System

Industrial grayscale palette:
- Primary: #111111 (gray-900)
- Background: #f5f5f5 (gray-50)
- Borders: #d4d4d4 (gray-200)
- No rounded corners (border-radius: 0)
- Inter + JetBrains Mono fonts

## Deployment

```bash
cd ansible
ansible-playbook -i servers gitpull.yml
ansible -i servers all -m shell -a "supervisorctl restart sendfiles" --become
```

## Related Projects

- **sendfilesencrypted/** - The E2E encrypted version (sendfilesencrypted.com)
- **files.sendfilesencrypted/** - Files API for sendfilesencrypted

## Monetization Tiers (Planned)

| Tier | Price | Size Limit | Retention |
|------|-------|------------|-----------|
| Free | $0 | 10GB | 14 days |
| Pro | $8/mo | 50GB | 30 days |
| Team | $20/mo | 100GB | 90 days |
| Enterprise | Custom | Unlimited | 365 days |
