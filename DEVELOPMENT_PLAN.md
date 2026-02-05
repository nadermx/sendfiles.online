# SendFiles.Online Development Plan

**Created:** February 2026
**Goal:** Achieve feature parity with WeTransfer/Smash and add competitive advantages

---

## Current State

### Pricing Tiers
| Plan | Price | Transfer Limit | Storage | Features |
|------|-------|----------------|---------|----------|
| Free | $0 | 3GB | 7 days | Basic uploads, no password |
| Pro | $10/mo | 200GB | 30 days | Password, tracking, branding |
| Business | $25/mo | 1TB | 90 days | API, webhooks, 10 users |
| Enterprise | Custom | Unlimited | Custom | SSO, dedicated support |

### What We Have
- [x] File uploads up to configured limit
- [x] Download link generation
- [x] Password protection (Pro+)
- [x] Basic download tracking
- [x] REST API (Business+)
- [x] Webhook notifications (Business+)
- [x] Email notifications (optional)
- [x] ZIP download for multiple files

### What We're Missing
- [ ] File previews (images, videos, PDFs, docs)
- [ ] Custom download page branding
- [ ] Monthly transfer limits (free tier)
- [ ] Real-time download notifications
- [ ] Custom subdomain
- [ ] Custom domain (Enterprise)
- [ ] Promo/marketing pop-ins
- [ ] Review/approval workflows
- [ ] SSO/SAML integration
- [ ] User/group provisioning
- [ ] Team management dashboard
- [ ] Transfer analytics dashboard
- [ ] Mobile apps (iOS/Android)
- [ ] Browser extensions
- [ ] Outlook/Gmail plugins
- [ ] Slack/Teams integrations

---

## Phase 1: Core Feature Parity (Week 1-2)

### 1.1 File Previews
**Priority:** HIGH | **Effort:** Medium

Enable inline previews on download page for common file types.

**Files to modify:**
- `transfers/views.py` - Add preview generation logic
- `templates/transfers/download.html` - Add preview UI
- `static/js/preview.js` - Client-side preview handling

**Supported formats:**
| Type | Formats | Method |
|------|---------|--------|
| Images | JPG, PNG, GIF, WebP, SVG | Native `<img>` tag |
| Videos | MP4, WebM, MOV | HTML5 `<video>` with range requests |
| Audio | MP3, WAV, OGG | HTML5 `<audio>` |
| PDFs | PDF | PDF.js or `<embed>` |
| Text | TXT, MD, JSON, CSV | Syntax-highlighted `<pre>` |
| Code | PY, JS, HTML, CSS | Highlight.js |

**Implementation:**
```python
# transfers/models.py
class TransferFile(models.Model):
    # Add preview fields
    preview_type = models.CharField(max_length=20, blank=True)  # image, video, audio, pdf, text, none
    preview_generated = models.BooleanField(default=False)
    thumbnail = models.ImageField(upload_to='thumbnails/', null=True, blank=True)

    def get_preview_type(self):
        ext = self.original_name.split('.')[-1].lower()
        if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg']:
            return 'image'
        elif ext in ['mp4', 'webm', 'mov']:
            return 'video'
        elif ext in ['mp3', 'wav', 'ogg']:
            return 'audio'
        elif ext == 'pdf':
            return 'pdf'
        elif ext in ['txt', 'md', 'json', 'csv', 'py', 'js', 'html', 'css']:
            return 'text'
        return 'none'
```

**UI Changes:**
- Add preview modal/lightbox on download page
- Show thumbnails in file list
- "Preview" button next to each previewable file
- Lazy loading for large file lists

---

### 1.2 Monthly Transfer Limits (Free Tier)
**Priority:** HIGH | **Effort:** Low

Limit free users to prevent abuse and encourage upgrades.

**Limits:**
| Plan | Transfers/Month | Total GB/Month |
|------|-----------------|----------------|
| Free | 10 | 10GB |
| Pro | Unlimited | Unlimited |
| Business | Unlimited | Unlimited |

**Files to modify:**
- `transfers/models.py` - Add usage tracking
- `transfers/views.py` - Check limits before upload
- `accounts/models.py` - Add monthly usage fields
- `templates/index.html` - Show remaining transfers

**Implementation:**
```python
# accounts/models.py
class CustomUser(AbstractUser):
    # Add usage tracking
    monthly_transfers = models.IntegerField(default=0)
    monthly_bytes = models.BigIntegerField(default=0)
    usage_reset_date = models.DateField(auto_now_add=True)

    def check_transfer_limit(self):
        """Check if user can create a new transfer"""
        if self.is_plan_active:
            return True, None

        # Reset monthly if needed
        if self.usage_reset_date.month != timezone.now().month:
            self.monthly_transfers = 0
            self.monthly_bytes = 0
            self.usage_reset_date = timezone.now().date()
            self.save()

        if self.monthly_transfers >= 10:
            return False, "Monthly transfer limit reached (10/month). Upgrade to Pro for unlimited."

        return True, None
```

---

### 1.3 Real-Time Download Notifications
**Priority:** HIGH | **Effort:** Medium

Notify senders when recipients download their files.

**Notification types:**
- Email notification (immediate or digest)
- In-app notification (if logged in)
- Webhook (Business+)
- Push notification (future mobile app)

**Files to modify:**
- `transfers/views.py` - Trigger notification on download
- `transfers/models.py` - Add notification preferences
- `accounts/models.py` - User notification settings
- `templates/emails/download_notification.html` - New email template

**Implementation:**
```python
# transfers/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import DownloadEvent

@receiver(post_save, sender=DownloadEvent)
def notify_download(sender, instance, created, **kwargs):
    if created:
        transfer = instance.transfer

        # Email notification
        if transfer.sender_email and transfer.notify_on_download:
            send_download_notification_email(
                to=transfer.sender_email,
                transfer=transfer,
                download_event=instance
            )

        # Webhook notification (Business+)
        if transfer.user and transfer.user.webhook_url:
            send_webhook(
                url=transfer.user.webhook_url,
                event='transfer.downloaded',
                data={
                    'transfer_id': str(transfer.id),
                    'short_id': transfer.short_id,
                    'downloaded_at': instance.created_at.isoformat(),
                    'ip_country': instance.country,
                    'file_count': transfer.file_count,
                }
            )
```

---

## Phase 2: Branding & Customization (Week 3-4)

### 2.1 Custom Download Page Branding (Pro+)
**Priority:** HIGH | **Effort:** Medium

Allow Pro users to customize the download page appearance.

**Customization options:**
- Logo upload
- Brand colors (primary, background)
- Custom message/banner
- Hide "Powered by SendFiles.Online" (Business+)

**Files to create/modify:**
- `accounts/models.py` - Add branding fields
- `templates/transfers/download.html` - Apply branding
- `templates/account.html` - Branding settings UI
- `static/css/branding.css` - Dynamic brand styles

**Model:**
```python
# accounts/models.py
class BrandSettings(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)
    logo = models.ImageField(upload_to='brand_logos/', null=True, blank=True)
    primary_color = models.CharField(max_length=7, default='#111111')  # Hex color
    background_color = models.CharField(max_length=7, default='#f5f5f5')
    custom_message = models.TextField(max_length=500, blank=True)
    hide_powered_by = models.BooleanField(default=False)  # Business+ only

    def get_css_vars(self):
        return f"""
        :root {{
            --brand-primary: {self.primary_color};
            --brand-bg: {self.background_color};
        }}
        """
```

---

### 2.2 Custom Subdomain (Business+)
**Priority:** MEDIUM | **Effort:** High

Allow Business users to use `company.sendfiles.online`.

**Implementation approach:**
1. DNS: Wildcard subdomain `*.sendfiles.online` → same server
2. Nginx: Capture subdomain, pass to Django
3. Django: Middleware to identify account by subdomain
4. SSL: Wildcard certificate for `*.sendfiles.online`

**Files to create/modify:**
- `accounts/models.py` - Add subdomain field
- `app/middleware.py` - Subdomain detection middleware
- `ansible/files/nginx.conf.j2` - Wildcard server block

**Middleware:**
```python
# app/middleware.py
class SubdomainMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().split(':')[0]

        # Check for subdomain
        if host.endswith('.sendfiles.online') and host != 'sendfiles.online':
            subdomain = host.replace('.sendfiles.online', '')

            # Skip www
            if subdomain != 'www':
                try:
                    account = CustomUser.objects.get(subdomain=subdomain)
                    request.brand_account = account
                except CustomUser.DoesNotExist:
                    pass

        return self.get_response(request)
```

---

### 2.3 Custom Domain (Enterprise)
**Priority:** LOW | **Effort:** High

Allow Enterprise customers to use their own domain (e.g., `files.company.com`).

**Requirements:**
- Customer creates CNAME record pointing to `custom.sendfiles.online`
- We provision SSL via Let's Encrypt
- Domain verification via DNS TXT record

**Implementation:**
- Use Caddy or nginx-proxy with auto-SSL
- Store custom domains in database
- Background job to verify and provision SSL

---

## Phase 3: Team Features (Week 5-6)

### 3.1 Team Management Dashboard
**Priority:** HIGH | **Effort:** High

Admin panel for Business accounts to manage team members.

**Features:**
- Invite team members by email
- Role-based permissions (Admin, Member, Viewer)
- View team transfer history
- Set team-wide settings
- Usage analytics per member

**New models:**
```python
# teams/models.py
class Team(models.Model):
    name = models.CharField(max_length=100)
    owner = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='owned_teams')
    created_at = models.DateTimeField(auto_now_add=True)
    max_members = models.IntegerField(default=10)

class TeamMember(models.Model):
    ROLES = [
        ('admin', 'Admin'),
        ('member', 'Member'),
        ('viewer', 'Viewer'),
    ]
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    role = models.CharField(max_length=10, choices=ROLES, default='member')
    invited_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

class TeamInvite(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    email = models.EmailField()
    token = models.CharField(max_length=64, unique=True)
    role = models.CharField(max_length=10, default='member')
    expires_at = models.DateTimeField()
```

**URLs:**
```
/team/                    - Team dashboard
/team/members/            - Member list
/team/invite/             - Invite form
/team/settings/           - Team settings
/team/analytics/          - Usage analytics
/join/<token>/            - Accept invite
```

---

### 3.2 Transfer Analytics Dashboard
**Priority:** MEDIUM | **Effort:** Medium

Visual dashboard showing transfer and download statistics.

**Metrics:**
- Transfers created (daily/weekly/monthly)
- Total data transferred
- Downloads by file
- Geographic distribution
- Top recipients
- Peak usage times

**Implementation:**
- Use Chart.js for visualizations
- Aggregate data in daily summary table
- Cache dashboard queries

---

### 3.3 Review/Approval Workflows (Enterprise)
**Priority:** LOW | **Effort:** High

Require manager approval before files are shared externally.

**Workflow:**
1. User creates transfer
2. Transfer status = "pending_approval"
3. Manager receives notification
4. Manager approves/rejects
5. If approved, download link becomes active

---

## Phase 4: Enterprise Features (Week 7-8)

### 4.1 SSO/SAML Integration
**Priority:** HIGH (for Enterprise) | **Effort:** High

Support single sign-on via SAML 2.0 and OIDC.

**Supported providers:**
- Okta
- Azure AD
- Google Workspace
- OneLogin
- Generic SAML 2.0

**Libraries:**
- `python-saml` for SAML
- `mozilla-django-oidc` for OIDC

**Configuration per customer:**
```python
# enterprise/models.py
class SSOConfig(models.Model):
    team = models.OneToOneField(Team, on_delete=models.CASCADE)
    provider = models.CharField(max_length=20)  # saml, oidc

    # SAML settings
    idp_entity_id = models.CharField(max_length=255, blank=True)
    idp_sso_url = models.URLField(blank=True)
    idp_certificate = models.TextField(blank=True)

    # OIDC settings
    oidc_client_id = models.CharField(max_length=255, blank=True)
    oidc_client_secret = models.CharField(max_length=255, blank=True)
    oidc_discovery_url = models.URLField(blank=True)

    # Settings
    auto_provision_users = models.BooleanField(default=True)
    default_role = models.CharField(max_length=10, default='member')
```

---

### 4.2 User Provisioning (SCIM)
**Priority:** MEDIUM | **Effort:** High

Automatic user provisioning via SCIM 2.0 protocol.

**Features:**
- Auto-create users when added in IdP
- Auto-deactivate when removed
- Sync user attributes (name, email, department)
- Group synchronization

---

### 4.3 Audit Logging
**Priority:** HIGH (for Enterprise) | **Effort:** Medium

Comprehensive audit trail for compliance.

**Logged events:**
- User login/logout
- Transfer created/deleted
- File downloaded
- Settings changed
- Team member added/removed
- Permission changes

**Model:**
```python
# audit/models.py
class AuditLog(models.Model):
    timestamp = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(CustomUser, null=True, on_delete=models.SET_NULL)
    team = models.ForeignKey(Team, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=50)  # transfer.created, user.login, etc.
    resource_type = models.CharField(max_length=50)  # transfer, user, team
    resource_id = models.CharField(max_length=100)
    ip_address = models.GenericIPAddressField(null=True)
    user_agent = models.TextField(blank=True)
    details = models.JSONField(default=dict)

    class Meta:
        indexes = [
            models.Index(fields=['team', 'timestamp']),
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['action']),
        ]
```

---

## Phase 5: Integrations (Week 9-10)

### 5.1 Slack Integration
**Priority:** HIGH | **Effort:** Medium

Share files directly from Slack.

**Features:**
- `/sendfiles` slash command to create transfer
- Upload files in Slack, share via SendFiles link
- Notifications when files are downloaded
- Install via Slack App Directory

---

### 5.2 Microsoft Teams Integration
**Priority:** HIGH | **Effort:** Medium

Similar to Slack integration for MS Teams users.

---

### 5.3 Gmail/Outlook Plugins
**Priority:** MEDIUM | **Effort:** Medium

Browser extensions for email clients.

**Features:**
- "Attach large file" button in compose
- Auto-upload attachments over limit
- Replace attachment with download link

---

### 5.4 Zapier/Make Integration
**Priority:** MEDIUM | **Effort:** Low

Enable no-code automation.

**Triggers:**
- Transfer created
- File downloaded
- Transfer expired

**Actions:**
- Create transfer
- Upload file
- Get transfer details

---

## Phase 6: Mobile & Extensions (Week 11-12)

### 6.1 Progressive Web App (PWA)
**Priority:** HIGH | **Effort:** Low

Make the web app installable on mobile.

**Features:**
- Add to home screen
- Offline support (view past transfers)
- Push notifications
- Share target (receive files from other apps)

**Files:**
- `static/site.webmanifest` - Already exists, enhance
- `static/js/sw.js` - Service worker
- `templates/base.html` - PWA meta tags

---

### 6.2 Native Mobile Apps (Future)
**Priority:** LOW | **Effort:** Very High

iOS and Android apps using React Native or Flutter.

**Features:**
- Upload photos/videos from camera roll
- Share sheet integration
- Background uploads
- Push notifications

---

### 6.3 Browser Extensions
**Priority:** MEDIUM | **Effort:** Medium

Chrome/Firefox extensions.

**Features:**
- Right-click "Send via SendFiles"
- Drag files to extension icon
- Quick access to recent transfers

---

## Phase 7: Performance & Scale (Ongoing)

### 7.1 CDN Integration
- Use CloudFlare or AWS CloudFront for file delivery
- Edge caching for popular downloads
- Faster global downloads

### 7.2 Resumable Uploads
- Implement tus.io protocol
- Resume interrupted uploads
- Critical for large files

### 7.3 Chunked Uploads
- Split large files into chunks
- Parallel upload for speed
- Better progress tracking

### 7.4 Storage Optimization
- Automatic deduplication
- Compression for text files
- Tiered storage (hot/cold)

---

## Implementation Priority Matrix

| Feature | Impact | Effort | Priority | Phase |
|---------|--------|--------|----------|-------|
| File previews | High | Medium | P1 | 1 |
| Monthly limits (free) | High | Low | P1 | 1 |
| Download notifications | High | Medium | P1 | 1 |
| Custom branding | High | Medium | P1 | 2 |
| Team dashboard | High | High | P1 | 3 |
| SSO/SAML | High | High | P1 | 4 |
| Custom subdomain | Medium | High | P2 | 2 |
| Analytics dashboard | Medium | Medium | P2 | 3 |
| Slack integration | Medium | Medium | P2 | 5 |
| PWA | Medium | Low | P2 | 6 |
| Audit logging | Medium | Medium | P2 | 4 |
| MS Teams integration | Medium | Medium | P3 | 5 |
| Email plugins | Low | Medium | P3 | 5 |
| Custom domain | Low | High | P3 | 2 |
| Review workflows | Low | High | P4 | 3 |
| SCIM provisioning | Low | High | P4 | 4 |
| Native mobile apps | Low | Very High | P4 | 6 |

---

## Database Migrations Required

```bash
# Phase 1
python manage.py makemigrations transfers  # preview fields
python manage.py makemigrations accounts   # usage tracking

# Phase 2
python manage.py makemigrations accounts   # branding, subdomain

# Phase 3
python manage.py startapp teams
python manage.py makemigrations teams

# Phase 4
python manage.py startapp enterprise
python manage.py startapp audit
python manage.py makemigrations enterprise audit
```

---

## New Django Apps to Create

```
sendfiles.online/
├── teams/              # Team management
│   ├── models.py
│   ├── views.py
│   ├── urls.py
│   └── admin.py
├── enterprise/         # SSO, SCIM, custom domain
│   ├── models.py
│   ├── views.py
│   ├── saml.py
│   └── scim.py
├── audit/              # Audit logging
│   ├── models.py
│   ├── middleware.py
│   └── signals.py
├── integrations/       # Slack, Teams, Zapier
│   ├── slack/
│   ├── teams/
│   └── zapier/
└── analytics/          # Dashboards, reporting
    ├── models.py
    ├── views.py
    └── aggregators.py
```

---

## Timeline Summary

| Phase | Duration | Focus |
|-------|----------|-------|
| Phase 1 | Week 1-2 | File previews, limits, notifications |
| Phase 2 | Week 3-4 | Branding, subdomains |
| Phase 3 | Week 5-6 | Team features, analytics |
| Phase 4 | Week 7-8 | Enterprise (SSO, audit) |
| Phase 5 | Week 9-10 | Integrations (Slack, Teams) |
| Phase 6 | Week 11-12 | Mobile, PWA, extensions |

**Total estimated time:** 12 weeks (3 months)

---

## Success Metrics

| Metric | Current | Target (3 months) |
|--------|---------|-------------------|
| Monthly active users | TBD | 10,000 |
| Paid conversions | TBD | 2% |
| Pro subscribers | TBD | 200 |
| Business subscribers | TBD | 20 |
| Average transfer size | TBD | 500MB |
| Download success rate | TBD | 99% |

---

## Next Steps

1. [ ] Review and prioritize features with stakeholders
2. [ ] Set up development/staging environment
3. [ ] Begin Phase 1 implementation
4. [ ] Create feature flags for gradual rollout
5. [ ] Set up monitoring and analytics
