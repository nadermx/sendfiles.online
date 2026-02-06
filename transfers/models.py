import uuid
import os
from datetime import timedelta

from django.db import models
from django.utils import timezone
from django.conf import settings

from accounts.models import CustomUser


def generate_short_id():
    """Generate a short 8-character ID for share links."""
    return uuid.uuid4().hex[:8]


class Transfer(models.Model):
    """A file transfer (can contain multiple files)."""

    # Status choices
    UPLOADING = 'uploading'
    READY = 'ready'
    EXPIRED = 'expired'
    DELETED = 'deleted'
    STATUS_CHOICES = [
        (UPLOADING, 'Uploading'),
        (READY, 'Ready'),
        (EXPIRED, 'Expired'),
        (DELETED, 'Deleted'),
    ]

    # Encryption choices
    NONE = 'none'
    SERVER = 'server'
    CLIENT = 'client'
    ENCRYPTION_CHOICES = [
        (NONE, 'No Encryption'),
        (SERVER, 'Server-Side Encryption'),
        (CLIENT, 'Client-Side E2E'),
    ]

    # Core fields
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    short_id = models.CharField(max_length=16, unique=True, default=generate_short_id)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    # Sender info
    sender_email = models.EmailField(blank=True, null=True)
    sender_ip = models.GenericIPAddressField()
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transfers'
    )

    # Transfer settings
    title = models.CharField(max_length=255, blank=True)
    message = models.TextField(blank=True)
    password_hash = models.CharField(max_length=128, blank=True)  # bcrypt hash
    encryption_type = models.CharField(
        max_length=20,
        choices=ENCRYPTION_CHOICES,
        default=NONE
    )

    # Limits
    max_downloads = models.PositiveIntegerField(null=True, blank=True)
    download_count = models.PositiveIntegerField(default=0)

    # Recipients (comma-separated emails)
    recipient_emails = models.TextField(blank=True)

    # Notification settings
    notify_on_download = models.BooleanField(default=False)
    last_notified_at = models.DateTimeField(null=True, blank=True)

    # Security settings (Pro/Business features)
    require_email_verification = models.BooleanField(default=False)
    allowed_domains = models.TextField(blank=True, help_text="Comma-separated list of allowed email domains")
    allowed_ips = models.TextField(blank=True, help_text="Comma-separated list of allowed IP addresses/ranges")
    two_factor_code = models.CharField(max_length=6, blank=True)  # For 2FA download verification

    # Virus scan status
    SCAN_PENDING = 'pending'
    SCAN_CLEAN = 'clean'
    SCAN_INFECTED = 'infected'
    SCAN_ERROR = 'error'
    SCAN_STATUS_CHOICES = [
        (SCAN_PENDING, 'Pending'),
        (SCAN_CLEAN, 'Clean'),
        (SCAN_INFECTED, 'Infected'),
        (SCAN_ERROR, 'Scan Error'),
    ]
    virus_scan_status = models.CharField(max_length=20, choices=SCAN_STATUS_CHOICES, default=SCAN_PENDING)
    virus_scan_result = models.TextField(blank=True)

    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=UPLOADING)
    total_size = models.BigIntegerField(default=0)
    file_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['short_id']),
            models.Index(fields=['status', 'expires_at']),
            models.Index(fields=['sender_ip', 'created_at']),
        ]

    def __str__(self):
        return f"Transfer {self.short_id} ({self.file_count} files)"

    def save(self, *args, **kwargs):
        if not self.expires_at:
            # Default 14-day expiration
            self.expires_at = timezone.now() + timedelta(days=14)
        super().save(*args, **kwargs)

    def set_password(self, password):
        """Hash and store the password."""
        import bcrypt
        self.password_hash = bcrypt.hashpw(
            password.encode('utf-8'),
            bcrypt.gensalt()
        ).decode('utf-8')

    def check_password(self, password):
        """Verify the password."""
        if not self.password_hash:
            return True
        import bcrypt
        return bcrypt.checkpw(
            password.encode('utf-8'),
            self.password_hash.encode('utf-8')
        )

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at or self.status == self.EXPIRED

    @property
    def is_download_limited(self):
        if self.max_downloads is None:
            return False
        return self.download_count >= self.max_downloads

    @property
    def is_password_protected(self):
        return bool(self.password_hash)

    @property
    def share_url(self):
        from config import ROOT_DOMAIN
        return f"{ROOT_DOMAIN}/d/{self.short_id}"

    def format_size(self):
        """Return human-readable file size."""
        size = self.total_size
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"

    def increment_downloads(self):
        self.download_count += 1
        self.save(update_fields=['download_count'])

    def get_recipients_list(self):
        """Return list of recipient emails."""
        if not self.recipient_emails:
            return []
        return [e.strip() for e in self.recipient_emails.split(',') if e.strip()]

    def get_allowed_domains_list(self):
        """Return list of allowed email domains."""
        if not self.allowed_domains:
            return []
        return [d.strip().lower() for d in self.allowed_domains.split(',') if d.strip()]

    def get_allowed_ips_list(self):
        """Return list of allowed IP addresses."""
        if not self.allowed_ips:
            return []
        return [ip.strip() for ip in self.allowed_ips.split(',') if ip.strip()]

    def is_domain_allowed(self, email):
        """Check if an email's domain is allowed."""
        allowed = self.get_allowed_domains_list()
        if not allowed:
            return True  # No restrictions
        domain = email.split('@')[-1].lower()
        return domain in allowed

    def is_ip_allowed(self, ip_address):
        """Check if an IP address is allowed."""
        allowed = self.get_allowed_ips_list()
        if not allowed:
            return True  # No restrictions
        # Simple check - could be extended for CIDR ranges
        return ip_address in allowed

    def generate_2fa_code(self):
        """Generate a new 2FA code for download verification."""
        import random
        self.two_factor_code = ''.join([str(random.randint(0, 9)) for _ in range(6)])
        self.save(update_fields=['two_factor_code'])
        return self.two_factor_code

    def verify_2fa_code(self, code):
        """Verify a 2FA code."""
        if not self.two_factor_code:
            return False
        return self.two_factor_code == code

    @property
    def is_scan_clean(self):
        """Check if virus scan passed."""
        return self.virus_scan_status == self.SCAN_CLEAN


class TransferFile(models.Model):
    """A single file within a transfer."""

    # Preview type choices
    PREVIEW_IMAGE = 'image'
    PREVIEW_VIDEO = 'video'
    PREVIEW_AUDIO = 'audio'
    PREVIEW_PDF = 'pdf'
    PREVIEW_TEXT = 'text'
    PREVIEW_OFFICE = 'office'
    PREVIEW_NONE = 'none'
    PREVIEW_TYPES = [
        (PREVIEW_IMAGE, 'Image'),
        (PREVIEW_VIDEO, 'Video'),
        (PREVIEW_AUDIO, 'Audio'),
        (PREVIEW_PDF, 'PDF'),
        (PREVIEW_TEXT, 'Text/Code'),
        (PREVIEW_OFFICE, 'Office Document'),
        (PREVIEW_NONE, 'No Preview'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transfer = models.ForeignKey(
        Transfer,
        on_delete=models.CASCADE,
        related_name='files'
    )

    # File info
    original_name = models.CharField(max_length=512)
    stored_name = models.CharField(max_length=128)  # UUID-based for storage
    size = models.BigIntegerField()
    mime_type = models.CharField(max_length=255, default='application/octet-stream')
    checksum = models.CharField(max_length=64, blank=True)  # SHA-256

    # Preview fields
    preview_type = models.CharField(max_length=10, choices=PREVIEW_TYPES, default=PREVIEW_NONE)
    thumbnail = models.CharField(max_length=256, blank=True)  # Path to thumbnail
    preview_generated = models.BooleanField(default=False)

    # Upload tracking
    uploaded_at = models.DateTimeField(auto_now_add=True)
    upload_complete = models.BooleanField(default=False)

    class Meta:
        ordering = ['original_name']

    def __str__(self):
        return self.original_name

    def format_size(self):
        """Return human-readable file size."""
        size = self.size
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"

    @property
    def storage_path(self):
        """Return the full path to the stored file."""
        return os.path.join(settings.MEDIA_ROOT, 'transfers', self.stored_name)

    @property
    def extension(self):
        """Return file extension."""
        if '.' in self.original_name:
            return self.original_name.rsplit('.', 1)[1].lower()
        return ''

    def get_icon_class(self):
        """Return CSS class for file type icon."""
        ext = self.extension
        if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp']:
            return 'file-image'
        elif ext in ['mp4', 'mov', 'avi', 'mkv', 'webm']:
            return 'file-video'
        elif ext in ['mp3', 'wav', 'flac', 'aac', 'ogg']:
            return 'file-audio'
        elif ext in ['pdf']:
            return 'file-pdf'
        elif ext in ['doc', 'docx']:
            return 'file-word'
        elif ext in ['xls', 'xlsx']:
            return 'file-excel'
        elif ext in ['ppt', 'pptx']:
            return 'file-powerpoint'
        elif ext in ['zip', 'rar', '7z', 'tar', 'gz']:
            return 'file-archive'
        elif ext in ['py', 'js', 'html', 'css', 'json', 'xml']:
            return 'file-code'
        else:
            return 'file'

    def detect_preview_type(self):
        """Detect the preview type based on file extension and mime type."""
        ext = self.extension
        mime = self.mime_type.lower()

        # Image files
        if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp', 'ico'] or mime.startswith('image/'):
            return self.PREVIEW_IMAGE

        # Video files
        if ext in ['mp4', 'webm', 'ogg', 'mov'] or mime.startswith('video/'):
            # Only allow browser-playable formats
            if ext in ['mp4', 'webm', 'ogg'] or mime in ['video/mp4', 'video/webm', 'video/ogg']:
                return self.PREVIEW_VIDEO

        # Audio files
        if ext in ['mp3', 'wav', 'ogg', 'aac', 'flac', 'm4a'] or mime.startswith('audio/'):
            # Only allow browser-playable formats
            if ext in ['mp3', 'wav', 'ogg', 'aac', 'm4a'] or mime in ['audio/mpeg', 'audio/wav', 'audio/ogg', 'audio/aac']:
                return self.PREVIEW_AUDIO

        # PDF files
        if ext == 'pdf' or mime == 'application/pdf':
            return self.PREVIEW_PDF

        # Text/Code files
        text_extensions = [
            'txt', 'md', 'markdown', 'rst', 'log',
            'py', 'js', 'ts', 'jsx', 'tsx', 'vue', 'svelte',
            'html', 'htm', 'css', 'scss', 'sass', 'less',
            'json', 'xml', 'yaml', 'yml', 'toml', 'ini', 'cfg',
            'sh', 'bash', 'zsh', 'fish', 'bat', 'ps1',
            'sql', 'graphql', 'gql',
            'java', 'kt', 'scala', 'groovy',
            'c', 'cpp', 'cc', 'h', 'hpp', 'cs',
            'go', 'rs', 'rb', 'php', 'pl', 'pm',
            'swift', 'r', 'lua', 'ex', 'exs', 'erl',
            'dockerfile', 'makefile', 'cmake',
            'csv', 'tsv',
        ]
        if ext in text_extensions or mime.startswith('text/'):
            # Limit preview to files under 1MB
            if self.size <= 1024 * 1024:
                return self.PREVIEW_TEXT

        return self.PREVIEW_NONE

    def set_preview_type(self):
        """Set the preview type if not already set."""
        if not self.preview_type or self.preview_type == self.PREVIEW_NONE:
            self.preview_type = self.detect_preview_type()

    @property
    def can_preview(self):
        """Check if this file can be previewed."""
        return self.preview_type != self.PREVIEW_NONE

    @property
    def thumbnail_url(self):
        """Return the URL to the thumbnail if available."""
        if self.thumbnail:
            return f"/media/thumbnails/{self.thumbnail}"
        return None

    def get_preview_url(self):
        """Return the URL for previewing this file."""
        return f"/d/{self.transfer.short_id}/preview/{self.id}/"

    def get_raw_url(self):
        """Return the URL for raw file access (for embedding)."""
        return f"/d/{self.transfer.short_id}/raw/{self.id}/"

    def get_code_language(self):
        """Return the language for syntax highlighting."""
        ext_to_lang = {
            'py': 'python',
            'js': 'javascript',
            'ts': 'typescript',
            'jsx': 'jsx',
            'tsx': 'tsx',
            'vue': 'vue',
            'html': 'html',
            'htm': 'html',
            'css': 'css',
            'scss': 'scss',
            'sass': 'sass',
            'less': 'less',
            'json': 'json',
            'xml': 'xml',
            'yaml': 'yaml',
            'yml': 'yaml',
            'toml': 'toml',
            'md': 'markdown',
            'markdown': 'markdown',
            'sh': 'bash',
            'bash': 'bash',
            'zsh': 'bash',
            'sql': 'sql',
            'java': 'java',
            'kt': 'kotlin',
            'scala': 'scala',
            'c': 'c',
            'cpp': 'cpp',
            'cc': 'cpp',
            'h': 'c',
            'hpp': 'cpp',
            'cs': 'csharp',
            'go': 'go',
            'rs': 'rust',
            'rb': 'ruby',
            'php': 'php',
            'swift': 'swift',
            'r': 'r',
            'lua': 'lua',
            'ex': 'elixir',
            'exs': 'elixir',
            'dockerfile': 'dockerfile',
            'makefile': 'makefile',
        }
        return ext_to_lang.get(self.extension, 'plaintext')


class UploadPortal(models.Model):
    """
    An upload portal allows users to receive files from others.
    Similar to WeTransfer's (now discontinued) Portals feature.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=64, unique=True)
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='portals'
    )

    # Portal settings
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    welcome_message = models.TextField(blank=True, help_text="Message shown to uploaders")

    # Branding (Pro feature)
    logo = models.CharField(max_length=512, blank=True)  # URL to logo
    primary_color = models.CharField(max_length=7, default='#111111')  # Hex color
    background_image = models.CharField(max_length=512, blank=True)  # URL to background

    # Upload restrictions
    max_file_size = models.BigIntegerField(default=3221225472)  # 3GB default
    max_files = models.PositiveIntegerField(default=50)
    allowed_extensions = models.TextField(blank=True, help_text="Comma-separated, e.g., 'pdf,doc,docx'")
    require_email = models.BooleanField(default=True)
    require_name = models.BooleanField(default=False)

    # Custom form fields (JSON array)
    custom_fields = models.JSONField(default=list, blank=True)

    # Notifications
    notify_on_upload = models.BooleanField(default=True)
    notification_email = models.EmailField(blank=True)

    # Status
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Stats
    total_uploads = models.PositiveIntegerField(default=0)
    total_files = models.PositiveIntegerField(default=0)
    total_bytes = models.BigIntegerField(default=0)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.slug})"

    @property
    def public_url(self):
        from config import ROOT_DOMAIN
        return f"{ROOT_DOMAIN}/p/{self.slug}/"

    def get_allowed_extensions_list(self):
        if not self.allowed_extensions:
            return []
        return [ext.strip().lower() for ext in self.allowed_extensions.split(',') if ext.strip()]

    def is_extension_allowed(self, filename):
        allowed = self.get_allowed_extensions_list()
        if not allowed:
            return True  # No restrictions
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        return ext in allowed


class PortalUpload(models.Model):
    """An upload submitted to a portal."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portal = models.ForeignKey(
        UploadPortal,
        on_delete=models.CASCADE,
        related_name='uploads'
    )
    transfer = models.ForeignKey(
        'Transfer',
        on_delete=models.CASCADE,
        related_name='portal_upload'
    )

    # Uploader info
    uploader_name = models.CharField(max_length=255, blank=True)
    uploader_email = models.EmailField(blank=True)
    uploader_ip = models.GenericIPAddressField()
    message = models.TextField(blank=True)

    # Custom field responses (JSON object)
    custom_responses = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Upload to {self.portal.name} by {self.uploader_email or self.uploader_ip}"


class MonthlyUsage(models.Model):
    """Track monthly usage for rate limiting free tier."""

    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='monthly_usage'
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    year = models.PositiveIntegerField()
    month = models.PositiveIntegerField()
    bytes_transferred = models.BigIntegerField(default=0)
    transfer_count = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [
            ('user', 'year', 'month'),
            ('ip_address', 'year', 'month'),
        ]
        indexes = [
            models.Index(fields=['user', 'year', 'month']),
            models.Index(fields=['ip_address', 'year', 'month']),
        ]

    def __str__(self):
        identifier = self.user.email if self.user else self.ip_address
        return f"{identifier} - {self.year}/{self.month}: {self.format_usage()}"

    def format_usage(self):
        """Return human-readable usage."""
        size = self.bytes_transferred
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"

    @classmethod
    def get_or_create_for_request(cls, request, user=None):
        """Get or create monthly usage record for user or IP."""
        now = timezone.now()
        year = now.year
        month = now.month

        if user and user.is_authenticated:
            usage, created = cls.objects.get_or_create(
                user=user,
                year=year,
                month=month,
                defaults={'bytes_transferred': 0, 'transfer_count': 0}
            )
        else:
            ip = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
            if not ip:
                ip = request.META.get('REMOTE_ADDR')

            usage, created = cls.objects.get_or_create(
                ip_address=ip,
                year=year,
                month=month,
                defaults={'bytes_transferred': 0, 'transfer_count': 0}
            )

        return usage

    def add_transfer(self, size_bytes):
        """Record a new transfer."""
        self.bytes_transferred += size_bytes
        self.transfer_count += 1
        self.save(update_fields=['bytes_transferred', 'transfer_count', 'updated_at'])

    @property
    def remaining_bytes(self):
        """Return remaining bytes for free tier (3GB/month)."""
        FREE_TIER_MONTHLY_LIMIT = 3 * 1024 * 1024 * 1024  # 3GB
        return max(0, FREE_TIER_MONTHLY_LIMIT - self.bytes_transferred)

    @property
    def is_limit_exceeded(self):
        """Check if monthly limit is exceeded."""
        FREE_TIER_MONTHLY_LIMIT = 3 * 1024 * 1024 * 1024  # 3GB
        return self.bytes_transferred >= FREE_TIER_MONTHLY_LIMIT


class DownloadEvent(models.Model):
    """Track download events for analytics."""

    id = models.BigAutoField(primary_key=True)
    transfer = models.ForeignKey(
        Transfer,
        on_delete=models.CASCADE,
        related_name='download_events'
    )
    file = models.ForeignKey(
        TransferFile,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='download_events'
    )

    downloaded_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField(blank=True)
    is_full_download = models.BooleanField(default=True)  # Full transfer vs single file

    class Meta:
        ordering = ['-downloaded_at']
        indexes = [
            models.Index(fields=['transfer', 'downloaded_at']),
        ]

    def __str__(self):
        return f"Download of {self.transfer.short_id} at {self.downloaded_at}"
