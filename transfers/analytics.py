"""
Analytics utilities for tracking transfer statistics.
"""
from django.db.models import Count, Sum, Avg
from django.db.models.functions import TruncDate, TruncMonth, ExtractHour
from django.utils import timezone
from datetime import timedelta

from transfers.models import Transfer, DownloadEvent


def get_user_analytics(user, days=30):
    """
    Get analytics data for a user's transfers.

    Returns dict with:
    - total_transfers
    - total_files
    - total_bytes
    - total_downloads
    - transfers_by_day
    - downloads_by_day
    - top_transfers
    """
    start_date = timezone.now() - timedelta(days=days)

    # Get user's transfers
    transfers = Transfer.objects.filter(
        user=user,
        created_at__gte=start_date
    )

    # Basic stats
    stats = transfers.aggregate(
        total_transfers=Count('id'),
        total_files=Sum('file_count'),
        total_bytes=Sum('total_size'),
        total_downloads=Sum('download_count'),
    )

    # Transfers by day
    transfers_by_day = transfers.annotate(
        date=TruncDate('created_at')
    ).values('date').annotate(
        count=Count('id'),
        size=Sum('total_size'),
    ).order_by('date')

    # Downloads by day
    downloads = DownloadEvent.objects.filter(
        transfer__user=user,
        downloaded_at__gte=start_date
    )

    downloads_by_day = downloads.annotate(
        date=TruncDate('downloaded_at')
    ).values('date').annotate(
        count=Count('id'),
    ).order_by('date')

    # Top transfers by downloads
    top_transfers = transfers.filter(
        download_count__gt=0
    ).order_by('-download_count')[:10]

    # Downloads by hour (for activity chart)
    downloads_by_hour = downloads.annotate(
        hour=ExtractHour('downloaded_at')
    ).values('hour').annotate(
        count=Count('id'),
    ).order_by('hour')

    return {
        'total_transfers': stats['total_transfers'] or 0,
        'total_files': stats['total_files'] or 0,
        'total_bytes': stats['total_bytes'] or 0,
        'total_downloads': stats['total_downloads'] or 0,
        'transfers_by_day': list(transfers_by_day),
        'downloads_by_day': list(downloads_by_day),
        'top_transfers': top_transfers,
        'downloads_by_hour': list(downloads_by_hour),
        'period_days': days,
    }


def get_transfer_analytics(transfer):
    """
    Get detailed analytics for a single transfer.
    """
    downloads = transfer.download_events.all()

    # Download timeline
    downloads_by_day = downloads.annotate(
        date=TruncDate('downloaded_at')
    ).values('date').annotate(
        count=Count('id'),
    ).order_by('date')

    # Unique downloaders (by IP)
    unique_ips = downloads.values('ip_address').distinct().count()

    # Device breakdown (basic parsing of user agent)
    user_agents = downloads.values('user_agent')
    devices = {'desktop': 0, 'mobile': 0, 'tablet': 0, 'other': 0}

    for ua in user_agents:
        agent = ua['user_agent'].lower()
        if 'mobile' in agent or 'android' in agent or 'iphone' in agent:
            if 'tablet' in agent or 'ipad' in agent:
                devices['tablet'] += 1
            else:
                devices['mobile'] += 1
        elif 'windows' in agent or 'macintosh' in agent or 'linux' in agent:
            devices['desktop'] += 1
        else:
            devices['other'] += 1

    return {
        'total_downloads': transfer.download_count,
        'unique_downloaders': unique_ips,
        'downloads_by_day': list(downloads_by_day),
        'devices': devices,
        'recent_downloads': downloads[:20],
    }


def format_bytes(bytes_value):
    """Format bytes to human readable string."""
    if bytes_value is None:
        bytes_value = 0
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_value < 1024:
            return f"{bytes_value:.1f} {unit}"
        bytes_value /= 1024
    return f"{bytes_value:.1f} PB"
