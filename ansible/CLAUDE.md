# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Ansible deployment automation for sendfiles.online. Deploys Django + Gunicorn + Nginx + Supervisor stack on Ubuntu servers.

## Production Server

- **IP:** 147.182.208.66
- **Service:** sendfiles (supervisor)
- **Path:** /home/www/sendfiles/
- **Logs:** /var/log/sendfiles/
- **Venv:** /home/www/sendfiles/venv/

## Common Commands

```bash
# Deploy code updates (git pull + restart)
ansible -i servers all -m shell -a "cd /home/www/sendfiles && git pull" --become
ansible -i servers all -m shell -a "supervisorctl restart sendfiles" --become

# Check logs
ansible -i servers all -m shell -a "tail -100 /var/log/sendfiles/sendfiles.err.log" --become

# Run Django management commands
ansible -i servers all -m shell -a "cd /home/www/sendfiles && /home/www/sendfiles/venv/bin/python manage.py migrate" --become

# Install/update pip requirements
ansible -i servers all -m shell -a "/home/www/sendfiles/venv/bin/pip install -r /home/www/sendfiles/requirements.txt" --become

# Run shell commands on server
ansible -i servers all -m shell -a "command here" --become

# Full initial deployment (new server)
ansible-playbook -i servers djangodeployubuntu20.yml
```

## Configuration Files

**Required (git-ignored, copy from .example):**
- `servers` - Server inventory (IP addresses)
- `group_vars/all` - Ansible variables (credentials, project settings)

**Templates:**
- `files/nginx.conf.j2` - Nginx site config (port 8000 proxy, gzip, static files)
- `files/supervisor.conf.j2` - Gunicorn with 3 workers on port 8000 + unix socket

## Variables (group_vars/all)

| Variable | Purpose |
|----------|---------|
| `ansible_user` | SSH user (also runs gunicorn) |
| `location` | Directory name in /home/www/ |
| `githuburl` | Repository clone URL |
| `projectname` | Used for nginx/supervisor config names |
| `domain` | Server name for nginx |

## Playbooks

- **djangodeployubuntu20.yml** - Full server setup (packages, nginx, supervisor, virtualenv, clone repo)
- **disableroot.yml** - Security hardening (disable root SSH)

## Stack Details

- Gunicorn binds to `127.0.0.1:8000`
- Nginx proxies to `127.0.0.1:8000` with gzip compression
- Static files served directly from `/home/www/{location}/static/`
- Max upload size: ~10GB (`client_max_body_size 10000m`)
- Uploads use TUS protocol for resumable chunked uploads (5MB chunks)
