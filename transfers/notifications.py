"""
Email and webhook notifications for file transfers.
"""
import logging
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from django.conf import settings

logger = logging.getLogger(__name__)


def send_download_notification(transfer, download_event):
    """
    Send email notification when a file is downloaded.
    """
    if not transfer.notify_on_download:
        return

    if not transfer.sender_email:
        return

    # Rate limit: don't send more than one notification per hour
    if transfer.last_notified_at:
        time_since_last = timezone.now() - transfer.last_notified_at
        if time_since_last.total_seconds() < 3600:  # 1 hour
            return

    try:
        subject = f"Your files were downloaded - {transfer.title or transfer.short_id}"

        # Plain text version
        message = f"""Hi,

Someone just downloaded your files from SendFiles.Online.

Transfer: {transfer.title or f"Transfer {transfer.short_id}"}
Files: {transfer.file_count} ({transfer.format_size()})
Downloaded: {download_event.downloaded_at.strftime('%B %d, %Y at %H:%M UTC')}

Download count: {transfer.download_count}
{f"Downloads remaining: {transfer.max_downloads - transfer.download_count}" if transfer.max_downloads else ""}

View your transfer: {transfer.share_url}

---
SendFiles.Online - Fast, simple file sharing
"""

        # HTML version
        html_message = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: #111; color: #fff; padding: 20px; text-align: center; }}
        .content {{ padding: 30px 20px; background: #fff; }}
        .stats {{ background: #f5f5f5; padding: 15px; margin: 20px 0; }}
        .stats-row {{ display: flex; justify-content: space-between; margin: 5px 0; }}
        .btn {{ display: inline-block; background: #111; color: #fff !important; padding: 12px 24px; text-decoration: none; font-weight: 500; }}
        .footer {{ padding: 20px; text-align: center; color: #666; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 style="margin: 0; font-size: 24px;">SENDFILES</h1>
        </div>
        <div class="content">
            <h2 style="margin-top: 0;">Your files were downloaded</h2>
            <p>Someone just downloaded your files.</p>

            <div class="stats">
                <div class="stats-row">
                    <span>Transfer:</span>
                    <strong>{transfer.title or f"Transfer {transfer.short_id}"}</strong>
                </div>
                <div class="stats-row">
                    <span>Files:</span>
                    <strong>{transfer.file_count} ({transfer.format_size()})</strong>
                </div>
                <div class="stats-row">
                    <span>Downloaded at:</span>
                    <strong>{download_event.downloaded_at.strftime('%B %d, %Y at %H:%M UTC')}</strong>
                </div>
                <div class="stats-row">
                    <span>Total downloads:</span>
                    <strong>{transfer.download_count}</strong>
                </div>
                {f'<div class="stats-row"><span>Downloads remaining:</span><strong>{transfer.max_downloads - transfer.download_count}</strong></div>' if transfer.max_downloads else ''}
            </div>

            <p style="text-align: center; margin-top: 30px;">
                <a href="{transfer.share_url}" class="btn">View Transfer</a>
            </p>
        </div>
        <div class="footer">
            <p>SendFiles.Online - Fast, simple file sharing</p>
            <p>You received this email because you enabled download notifications for this transfer.</p>
        </div>
    </div>
</body>
</html>
"""

        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[transfer.sender_email],
            html_message=html_message,
            fail_silently=True,
        )

        # Update last notified time
        transfer.last_notified_at = timezone.now()
        transfer.save(update_fields=['last_notified_at'])

        logger.info(f"Sent download notification for transfer {transfer.short_id} to {transfer.sender_email}")

    except Exception as e:
        logger.error(f"Failed to send download notification for transfer {transfer.short_id}: {e}")


def send_transfer_ready_notification(transfer):
    """
    Send email notification to recipients when a transfer is ready.
    """
    recipients = transfer.get_recipients_list()
    if not recipients:
        return

    try:
        subject = f"Files shared with you{f' from {transfer.sender_email}' if transfer.sender_email else ''}"

        for recipient in recipients:
            message = f"""Hi,

Someone has shared files with you via SendFiles.Online.

{f"From: {transfer.sender_email}" if transfer.sender_email else ""}
{f"Message: {transfer.message}" if transfer.message else ""}

Files: {transfer.file_count} ({transfer.format_size()})
Expires: {transfer.expires_at.strftime('%B %d, %Y')}

Download your files: {transfer.share_url}

---
SendFiles.Online - Fast, simple file sharing
"""

            html_message = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: #111; color: #fff; padding: 20px; text-align: center; }}
        .content {{ padding: 30px 20px; background: #fff; }}
        .message {{ background: #f5f5f5; padding: 15px; margin: 20px 0; font-style: italic; }}
        .stats {{ background: #f5f5f5; padding: 15px; margin: 20px 0; }}
        .stats-row {{ display: flex; justify-content: space-between; margin: 5px 0; }}
        .btn {{ display: inline-block; background: #111; color: #fff !important; padding: 12px 24px; text-decoration: none; font-weight: 500; }}
        .footer {{ padding: 20px; text-align: center; color: #666; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 style="margin: 0; font-size: 24px;">SENDFILES</h1>
        </div>
        <div class="content">
            <h2 style="margin-top: 0;">Files shared with you</h2>
            {f"<p>From: <strong>{transfer.sender_email}</strong></p>" if transfer.sender_email else ""}

            {f'<div class="message">"{transfer.message}"</div>' if transfer.message else ""}

            <div class="stats">
                <div class="stats-row">
                    <span>Files:</span>
                    <strong>{transfer.file_count} ({transfer.format_size()})</strong>
                </div>
                <div class="stats-row">
                    <span>Expires:</span>
                    <strong>{transfer.expires_at.strftime('%B %d, %Y')}</strong>
                </div>
                {f'<div class="stats-row"><span>Password protected:</span><strong>Yes</strong></div>' if transfer.is_password_protected else ''}
            </div>

            <p style="text-align: center; margin-top: 30px;">
                <a href="{transfer.share_url}" class="btn">Download Files</a>
            </p>
        </div>
        <div class="footer">
            <p>SendFiles.Online - Fast, simple file sharing</p>
        </div>
    </div>
</body>
</html>
"""

            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient],
                html_message=html_message,
                fail_silently=True,
            )

            logger.info(f"Sent transfer notification for {transfer.short_id} to {recipient}")

    except Exception as e:
        logger.error(f"Failed to send transfer notification for transfer {transfer.short_id}: {e}")


def send_portal_upload_notification(portal, portal_upload):
    """
    Send email notification to portal owner when someone uploads files.
    """
    if not portal.notify_on_upload:
        return

    notification_email = portal.notification_email or portal.user.email
    if not notification_email:
        return

    try:
        transfer = portal_upload.transfer
        uploader = portal_upload.uploader_email or portal_upload.uploader_name or 'Anonymous'

        subject = f"New upload to {portal.name}"

        message = f"""Hi,

Someone just uploaded files to your portal "{portal.name}".

Uploaded by: {uploader}
{f"Message: {portal_upload.message}" if portal_upload.message else ""}

Files: {transfer.file_count} ({transfer.format_size()})

View the upload: {transfer.share_url}
Manage your portal: {portal.public_url.replace('/p/', '/portals/').rstrip('/')}/

---
SendFiles.Online - Fast, simple file sharing
"""

        html_message = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: #111; color: #fff; padding: 20px; text-align: center; }}
        .content {{ padding: 30px 20px; background: #fff; }}
        .stats {{ background: #f5f5f5; padding: 15px; margin: 20px 0; }}
        .stats-row {{ display: flex; justify-content: space-between; margin: 5px 0; }}
        .message {{ background: #f5f5f5; padding: 15px; margin: 20px 0; font-style: italic; }}
        .btn {{ display: inline-block; background: #111; color: #fff !important; padding: 12px 24px; text-decoration: none; font-weight: 500; margin: 5px; }}
        .footer {{ padding: 20px; text-align: center; color: #666; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 style="margin: 0; font-size: 24px;">SENDFILES</h1>
        </div>
        <div class="content">
            <h2 style="margin-top: 0;">New upload to {portal.name}</h2>

            <div class="stats">
                <div class="stats-row">
                    <span>Uploaded by:</span>
                    <strong>{uploader}</strong>
                </div>
                <div class="stats-row">
                    <span>Files:</span>
                    <strong>{transfer.file_count} ({transfer.format_size()})</strong>
                </div>
                <div class="stats-row">
                    <span>Time:</span>
                    <strong>{portal_upload.created_at.strftime('%B %d, %Y at %H:%M UTC')}</strong>
                </div>
            </div>

            {f'<div class="message">"{portal_upload.message}"</div>' if portal_upload.message else ""}

            <p style="text-align: center; margin-top: 30px;">
                <a href="{transfer.share_url}" class="btn">View Files</a>
            </p>
        </div>
        <div class="footer">
            <p>SendFiles.Online - Fast, simple file sharing</p>
            <p>You received this email because you enabled notifications for the portal "{portal.name}".</p>
        </div>
    </div>
</body>
</html>
"""

        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[notification_email],
            html_message=html_message,
            fail_silently=True,
        )

        logger.info(f"Sent portal upload notification for {portal.slug} to {notification_email}")

    except Exception as e:
        logger.error(f"Failed to send portal upload notification for {portal.slug}: {e}")
