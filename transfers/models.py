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


class TransferFile(models.Model):
    """A single file within a transfer."""

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
