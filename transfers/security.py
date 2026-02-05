"""
Security utilities for file transfers.
"""
import logging
import subprocess
import os

from django.conf import settings

logger = logging.getLogger(__name__)


def scan_file_for_viruses(file_path):
    """
    Scan a file for viruses using ClamAV (clamscan).

    Returns:
        tuple: (is_clean: bool, result_message: str)
    """
    if not os.path.exists(file_path):
        return False, "File not found"

    try:
        # Try clamscan first (standalone scanner)
        result = subprocess.run(
            ['clamscan', '--no-summary', file_path],
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode == 0:
            return True, "No virus found"
        elif result.returncode == 1:
            # Virus found
            return False, result.stdout.strip() or "Virus detected"
        else:
            # Error
            return False, f"Scan error: {result.stderr.strip()}"

    except FileNotFoundError:
        # ClamAV not installed, try clamdscan (daemon scanner)
        try:
            result = subprocess.run(
                ['clamdscan', '--no-summary', file_path],
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode == 0:
                return True, "No virus found"
            elif result.returncode == 1:
                return False, result.stdout.strip() or "Virus detected"
            else:
                return False, f"Scan error: {result.stderr.strip()}"

        except FileNotFoundError:
            # ClamAV not installed at all
            logger.warning("ClamAV not installed, skipping virus scan")
            return True, "Scan skipped (ClamAV not installed)"

    except subprocess.TimeoutExpired:
        return False, "Scan timed out"
    except Exception as e:
        logger.error(f"Virus scan error: {e}")
        return False, f"Scan error: {str(e)}"


def scan_transfer(transfer):
    """
    Scan all files in a transfer for viruses.

    Returns:
        bool: True if all files are clean
    """
    from transfers.models import Transfer

    all_clean = True
    results = []

    for transfer_file in transfer.files.all():
        file_path = transfer_file.storage_path
        is_clean, message = scan_file_for_viruses(file_path)

        if not is_clean:
            all_clean = False
            results.append(f"{transfer_file.original_name}: {message}")
        else:
            results.append(f"{transfer_file.original_name}: Clean")

    if all_clean:
        transfer.virus_scan_status = Transfer.SCAN_CLEAN
    else:
        transfer.virus_scan_status = Transfer.SCAN_INFECTED

    transfer.virus_scan_result = "\n".join(results)
    transfer.save(update_fields=['virus_scan_status', 'virus_scan_result'])

    return all_clean


def check_file_extension_safety(filename):
    """
    Check if a file extension is potentially dangerous.

    Returns:
        tuple: (is_safe: bool, reason: str)
    """
    dangerous_extensions = [
        'exe', 'bat', 'cmd', 'com', 'msi', 'scr', 'pif',  # Windows executables
        'vbs', 'vbe', 'js', 'jse', 'ws', 'wsf', 'wsc', 'wsh',  # Scripts
        'ps1', 'psm1', 'psd1',  # PowerShell
        'app', 'dmg', 'pkg',  # Mac
        'sh', 'bash', 'run', 'bin',  # Linux
        'jar', 'class',  # Java
        'dll', 'sys', 'drv',  # System files
    ]

    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''

    if ext in dangerous_extensions:
        return False, f"Potentially dangerous file type: .{ext}"

    # Check for double extensions (e.g., document.pdf.exe)
    parts = filename.lower().rsplit('.', 2)
    if len(parts) > 2 and parts[-1] in dangerous_extensions:
        return False, f"Suspicious double extension detected"

    return True, "File extension OK"


def send_email_verification_code(transfer, recipient_email):
    """
    Send a verification code to download files.
    """
    from django.core.mail import send_mail
    from django.conf import settings

    code = transfer.generate_2fa_code()

    subject = f"Verify your download - {transfer.title or transfer.short_id}"

    message = f"""Hi,

Someone is trying to download files from SendFiles.Online and has requested email verification.

Your verification code is: {code}

This code will expire in 10 minutes.

If you did not request this, please ignore this email.

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
        .code {{ font-size: 32px; font-family: monospace; letter-spacing: 8px; text-align: center; padding: 20px; background: #f5f5f5; margin: 20px 0; }}
        .footer {{ padding: 20px; text-align: center; color: #666; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 style="margin: 0; font-size: 24px;">SENDFILES</h1>
        </div>
        <div class="content">
            <h2 style="margin-top: 0;">Verify Your Download</h2>
            <p>Someone is trying to download files and has requested email verification.</p>
            <p>Your verification code is:</p>
            <div class="code">{code}</div>
            <p style="color: #666; font-size: 14px;">This code will expire in 10 minutes.</p>
        </div>
        <div class="footer">
            <p>SendFiles.Online - Fast, simple file sharing</p>
            <p>If you did not request this, please ignore this email.</p>
        </div>
    </div>
</body>
</html>
"""

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception as e:
        logger.error(f"Failed to send verification code: {e}")
        return False
