import os
import uuid
import json
import mimetypes
import zipfile
from datetime import timedelta
from io import BytesIO

from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse, FileResponse, Http404
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.conf import settings
from django.core.files.storage import default_storage

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from accounts.views import GlobalVars
from transfers.models import Transfer, TransferFile, DownloadEvent, MonthlyUsage, UploadPortal, PortalUpload
from transfers.notifications import send_download_notification, send_transfer_ready_notification
from transfers.security import scan_transfer, check_file_extension_safety
from transfers.analytics import get_user_analytics, get_transfer_analytics, format_bytes
from config import ROOT_DOMAIN, FILES_LIMIT


def get_client_ip(request):
    """Get the client's IP address."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


class HomeView(View):
    """Main upload page."""

    def get(self, request):
        g = GlobalVars.get_globals(request)

        # Get monthly usage for quota display
        monthly_usage = MonthlyUsage.get_or_create_for_request(request, request.user if request.user.is_authenticated else None)
        is_pro = request.user.is_authenticated and getattr(request.user, 'is_plan_active', False)

        return render(request, 'index.html', {
            'g': g,
            'max_size': FILES_LIMIT,
            'max_size_gb': FILES_LIMIT / (1024 ** 3),
            'monthly_used': monthly_usage.bytes_transferred,
            'monthly_remaining': monthly_usage.remaining_bytes,
            'monthly_limit': 3 * 1024 * 1024 * 1024,  # 3GB
            'is_pro': is_pro,
        })


class CreateTransferAPI(APIView):
    """API endpoint to create a new transfer."""

    def post(self, request):
        data = request.data
        ip = get_client_ip(request)

        # Create transfer
        transfer = Transfer(
            sender_email=data.get('sender_email', ''),
            sender_ip=ip,
            title=data.get('title', ''),
            message=data.get('message', ''),
            recipient_emails=data.get('recipients', ''),
            encryption_type=data.get('encryption', Transfer.NONE),
        )

        # Set password if provided
        password = data.get('password', '')
        if password:
            transfer.set_password(password)

        # Set expiration (free tier max 7 days)
        days = int(data.get('expiration_days', 7))
        days = min(days, 7)  # Max 7 for free tier
        transfer.expires_at = timezone.now() + timedelta(days=days)

        # Set download limit
        max_downloads = data.get('max_downloads')
        if max_downloads is not None:
            transfer.max_downloads = int(max_downloads)

        # Set notification preference
        transfer.notify_on_download = data.get('notify_on_download', False)

        # Security settings
        transfer.require_email_verification = data.get('require_email_verification', False)
        transfer.allowed_domains = data.get('allowed_domains', '').strip()
        transfer.allowed_ips = data.get('allowed_ips', '').strip()

        # Associate with user if logged in
        if request.user.is_authenticated:
            transfer.user = request.user

        transfer.save()

        return Response({
            'transfer_id': str(transfer.id),
            'short_id': transfer.short_id,
            'upload_url': f'/api/transfers/{transfer.id}/upload/',
        }, status=status.HTTP_201_CREATED)


@method_decorator(csrf_exempt, name='dispatch')
class UploadFileAPI(APIView):
    """API endpoint to upload a file to a transfer."""

    def post(self, request, transfer_id):
        try:
            transfer = Transfer.objects.get(id=transfer_id)
        except Transfer.DoesNotExist:
            return Response({'error': 'Transfer not found'}, status=404)

        if transfer.status != Transfer.UPLOADING:
            return Response({'error': 'Transfer is not accepting uploads'}, status=400)

        # Get the uploaded file
        uploaded_file = request.FILES.get('file')
        if not uploaded_file:
            return Response({'error': 'No file provided'}, status=400)

        # Check monthly usage limit for free users
        if not request.user.is_authenticated or not getattr(request.user, 'is_plan_active', False):
            monthly_usage = MonthlyUsage.get_or_create_for_request(request, request.user if request.user.is_authenticated else None)
            if monthly_usage.remaining_bytes < uploaded_file.size:
                return Response({
                    'error': 'Monthly transfer limit exceeded',
                    'remaining_bytes': monthly_usage.remaining_bytes,
                    'limit': 10 * 1024 * 1024 * 1024,
                }, status=429)

        # Check file size limit
        if transfer.total_size + uploaded_file.size > FILES_LIMIT:
            return Response({'error': 'Transfer size limit exceeded'}, status=400)

        # Generate storage name
        stored_name = f"{uuid.uuid4().hex}{os.path.splitext(uploaded_file.name)[1]}"

        # Ensure uploads directory exists
        uploads_dir = os.path.join(settings.MEDIA_ROOT, 'transfers')
        os.makedirs(uploads_dir, exist_ok=True)

        # Save the file
        file_path = os.path.join(uploads_dir, stored_name)
        with open(file_path, 'wb+') as destination:
            for chunk in uploaded_file.chunks():
                destination.write(chunk)

        # Determine mime type
        mime_type, _ = mimetypes.guess_type(uploaded_file.name)
        if not mime_type:
            mime_type = 'application/octet-stream'

        # Create file record
        transfer_file = TransferFile.objects.create(
            transfer=transfer,
            original_name=uploaded_file.name,
            stored_name=stored_name,
            size=uploaded_file.size,
            mime_type=mime_type,
            upload_complete=True,
        )

        # Set preview type
        transfer_file.set_preview_type()
        transfer_file.save(update_fields=['preview_type'])

        # Update transfer totals
        transfer.total_size += uploaded_file.size
        transfer.file_count += 1
        transfer.save(update_fields=['total_size', 'file_count'])

        return Response({
            'file_id': str(transfer_file.id),
            'name': transfer_file.original_name,
            'size': transfer_file.size,
        }, status=status.HTTP_201_CREATED)


class FinalizeTransferAPI(APIView):
    """API endpoint to finalize a transfer after all files are uploaded."""

    def post(self, request, transfer_id):
        try:
            transfer = Transfer.objects.get(id=transfer_id)
        except Transfer.DoesNotExist:
            return Response({'error': 'Transfer not found'}, status=404)

        if transfer.status != Transfer.UPLOADING:
            return Response({'error': 'Transfer already finalized'}, status=400)

        if transfer.file_count == 0:
            return Response({'error': 'No files uploaded'}, status=400)

        # Mark as ready
        transfer.status = Transfer.READY
        transfer.save(update_fields=['status'])

        # Record monthly usage for free users
        if not request.user.is_authenticated or not getattr(request.user, 'is_plan_active', False):
            monthly_usage = MonthlyUsage.get_or_create_for_request(request, request.user if request.user.is_authenticated else None)
            monthly_usage.add_transfer(transfer.total_size)

        # Send email notifications to recipients
        if transfer.get_recipients_list():
            send_transfer_ready_notification(transfer)

        return Response({
            'success': True,
            'share_url': transfer.share_url,
            'short_id': transfer.short_id,
        })


class DownloadPageView(View):
    """Download page for a transfer."""

    def get(self, request, short_id):
        transfer = get_object_or_404(Transfer, short_id=short_id)
        g = GlobalVars.get_globals(request)

        # Check if expired
        if transfer.is_expired:
            return render(request, 'transfers/expired.html', {'g': g})

        # Check download limit
        if transfer.is_download_limited:
            return render(request, 'transfers/limit_reached.html', {'g': g})

        # Check if password required
        if transfer.is_password_protected:
            # Check if already verified in session
            session_key = f'transfer_verified_{transfer.short_id}'
            if not request.session.get(session_key):
                return render(request, 'transfers/password.html', {
                    'g': g,
                    'transfer': transfer,
                })

        # Get files
        files = transfer.files.filter(upload_complete=True)

        return render(request, 'transfers/download.html', {
            'g': g,
            'transfer': transfer,
            'files': files,
        })

    def post(self, request, short_id):
        """Handle password submission."""
        transfer = get_object_or_404(Transfer, short_id=short_id)

        password = request.POST.get('password', '')
        if transfer.check_password(password):
            # Store verification in session
            session_key = f'transfer_verified_{transfer.short_id}'
            request.session[session_key] = True
            return redirect('download_page', short_id=short_id)
        else:
            g = GlobalVars.get_globals(request)
            return render(request, 'transfers/password.html', {
                'g': g,
                'transfer': transfer,
                'error': 'Incorrect password',
            })


class DownloadFileView(View):
    """Download a single file."""

    def get(self, request, short_id, file_id):
        transfer = get_object_or_404(Transfer, short_id=short_id)

        # Check if expired
        if transfer.is_expired:
            raise Http404("Transfer expired")

        # Check download limit
        if transfer.is_download_limited:
            raise Http404("Download limit reached")

        # Check password
        if transfer.is_password_protected:
            session_key = f'transfer_verified_{transfer.short_id}'
            if not request.session.get(session_key):
                return redirect('download_page', short_id=short_id)

        # Get file
        transfer_file = get_object_or_404(TransferFile, id=file_id, transfer=transfer)

        # Log download event
        DownloadEvent.objects.create(
            transfer=transfer,
            file=transfer_file,
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            is_full_download=False,
        )

        # Serve file
        file_path = transfer_file.storage_path
        if not os.path.exists(file_path):
            raise Http404("File not found")

        response = FileResponse(
            open(file_path, 'rb'),
            content_type=transfer_file.mime_type,
        )
        response['Content-Disposition'] = f'attachment; filename="{transfer_file.original_name}"'
        response['Content-Length'] = transfer_file.size
        return response


class DownloadAllView(View):
    """Download all files as a ZIP."""

    def get(self, request, short_id):
        transfer = get_object_or_404(Transfer, short_id=short_id)

        # Check if expired
        if transfer.is_expired:
            raise Http404("Transfer expired")

        # Check download limit
        if transfer.is_download_limited:
            raise Http404("Download limit reached")

        # Check password
        if transfer.is_password_protected:
            session_key = f'transfer_verified_{transfer.short_id}'
            if not request.session.get(session_key):
                return redirect('download_page', short_id=short_id)

        # Get files
        files = transfer.files.filter(upload_complete=True)

        # Create ZIP in memory
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for f in files:
                if os.path.exists(f.storage_path):
                    zip_file.write(f.storage_path, f.original_name)

        # Log download event
        download_event = DownloadEvent.objects.create(
            transfer=transfer,
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            is_full_download=True,
        )

        # Increment download count
        transfer.increment_downloads()

        # Send download notification
        send_download_notification(transfer, download_event)

        # Serve ZIP
        zip_buffer.seek(0)
        zip_name = transfer.title or f"sendfiles-{transfer.short_id}"
        zip_name = "".join(c for c in zip_name if c.isalnum() or c in (' ', '-', '_')).rstrip()

        response = HttpResponse(zip_buffer.read(), content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="{zip_name}.zip"'
        return response


class SuccessView(View):
    """Success page after upload."""

    def get(self, request, short_id):
        transfer = get_object_or_404(Transfer, short_id=short_id)
        g = GlobalVars.get_globals(request)

        return render(request, 'transfers/success.html', {
            'g': g,
            'transfer': transfer,
        })


class PreviewFileView(View):
    """Preview a file inline."""

    def get(self, request, short_id, file_id):
        transfer = get_object_or_404(Transfer, short_id=short_id)
        g = GlobalVars.get_globals(request)

        # Check if expired
        if transfer.is_expired:
            return render(request, 'transfers/expired.html', {'g': g})

        # Check password
        if transfer.is_password_protected:
            session_key = f'transfer_verified_{transfer.short_id}'
            if not request.session.get(session_key):
                return redirect('download_page', short_id=short_id)

        # Get file
        transfer_file = get_object_or_404(TransferFile, id=file_id, transfer=transfer)

        # Get all files for navigation
        files = list(transfer.files.filter(upload_complete=True))
        current_index = next((i for i, f in enumerate(files) if f.id == transfer_file.id), 0)
        prev_file = files[current_index - 1] if current_index > 0 else None
        next_file = files[current_index + 1] if current_index < len(files) - 1 else None

        return render(request, 'transfers/preview.html', {
            'g': g,
            'transfer': transfer,
            'file': transfer_file,
            'files': files,
            'prev_file': prev_file,
            'next_file': next_file,
            'current_index': current_index + 1,
            'total_files': len(files),
        })


class RawFileView(View):
    """Serve raw file for embedding (images, videos, audio, etc.)."""

    def get(self, request, short_id, file_id):
        transfer = get_object_or_404(Transfer, short_id=short_id)

        # Check if expired
        if transfer.is_expired:
            raise Http404("Transfer expired")

        # Check password
        if transfer.is_password_protected:
            session_key = f'transfer_verified_{transfer.short_id}'
            if not request.session.get(session_key):
                raise Http404("Access denied")

        # Get file
        transfer_file = get_object_or_404(TransferFile, id=file_id, transfer=transfer)

        # Only allow previewable files
        if not transfer_file.can_preview:
            raise Http404("Preview not available")

        # Serve file
        file_path = transfer_file.storage_path
        if not os.path.exists(file_path):
            raise Http404("File not found")

        # For text files, read content
        if transfer_file.preview_type == TransferFile.PREVIEW_TEXT:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read(1024 * 1024)  # Max 1MB
                response = HttpResponse(content, content_type='text/plain; charset=utf-8')
            except Exception:
                raise Http404("Cannot read file")
        else:
            # Stream binary files
            response = FileResponse(
                open(file_path, 'rb'),
                content_type=transfer_file.mime_type,
            )
            response['Content-Length'] = transfer_file.size

        # Set inline disposition for preview
        response['Content-Disposition'] = f'inline; filename="{transfer_file.original_name}"'

        # Allow embedding
        response['X-Content-Type-Options'] = 'nosniff'

        return response


# ============================================================================
# UPLOAD PORTALS
# ============================================================================

from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils.text import slugify
import re


class PortalListView(LoginRequiredMixin, View):
    """List user's upload portals."""

    def get(self, request):
        g = GlobalVars.get_globals(request)
        portals = request.user.portals.all()

        return render(request, 'portals/list.html', {
            'g': g,
            'portals': portals,
        })


class PortalCreateView(LoginRequiredMixin, View):
    """Create a new upload portal."""

    def get(self, request):
        g = GlobalVars.get_globals(request)
        return render(request, 'portals/create.html', {
            'g': g,
        })

    def post(self, request):
        g = GlobalVars.get_globals(request)

        name = request.POST.get('name', '').strip()
        slug = request.POST.get('slug', '').strip().lower()
        description = request.POST.get('description', '').strip()
        welcome_message = request.POST.get('welcome_message', '').strip()

        # Validate
        errors = []
        if not name:
            errors.append('Name is required')
        if not slug:
            slug = slugify(name)
        if not re.match(r'^[a-z0-9-]+$', slug):
            errors.append('Slug can only contain lowercase letters, numbers, and hyphens')
        if UploadPortal.objects.filter(slug=slug).exists():
            errors.append('This URL is already taken')

        if errors:
            return render(request, 'portals/create.html', {
                'g': g,
                'errors': errors,
                'name': name,
                'slug': slug,
                'description': description,
                'welcome_message': welcome_message,
            })

        # Create portal
        portal = UploadPortal.objects.create(
            user=request.user,
            name=name,
            slug=slug,
            description=description,
            welcome_message=welcome_message,
            notification_email=request.user.email,
        )

        return redirect('portal_detail', slug=portal.slug)


class PortalDetailView(LoginRequiredMixin, View):
    """View and manage a portal."""

    def get(self, request, slug):
        g = GlobalVars.get_globals(request)
        portal = get_object_or_404(UploadPortal, slug=slug, user=request.user)
        uploads = portal.uploads.select_related('transfer').order_by('-created_at')[:50]

        return render(request, 'portals/detail.html', {
            'g': g,
            'portal': portal,
            'uploads': uploads,
        })


class PortalEditView(LoginRequiredMixin, View):
    """Edit portal settings."""

    def get(self, request, slug):
        g = GlobalVars.get_globals(request)
        portal = get_object_or_404(UploadPortal, slug=slug, user=request.user)

        return render(request, 'portals/edit.html', {
            'g': g,
            'portal': portal,
        })

    def post(self, request, slug):
        g = GlobalVars.get_globals(request)
        portal = get_object_or_404(UploadPortal, slug=slug, user=request.user)

        # Update fields
        portal.name = request.POST.get('name', portal.name).strip()
        portal.description = request.POST.get('description', '').strip()
        portal.welcome_message = request.POST.get('welcome_message', '').strip()
        portal.require_email = request.POST.get('require_email') == 'on'
        portal.require_name = request.POST.get('require_name') == 'on'
        portal.notify_on_upload = request.POST.get('notify_on_upload') == 'on'
        portal.notification_email = request.POST.get('notification_email', request.user.email).strip()
        portal.allowed_extensions = request.POST.get('allowed_extensions', '').strip()
        portal.is_active = request.POST.get('is_active') == 'on'

        portal.save()

        return redirect('portal_detail', slug=portal.slug)


class PortalDeleteView(LoginRequiredMixin, View):
    """Delete a portal."""

    def post(self, request, slug):
        portal = get_object_or_404(UploadPortal, slug=slug, user=request.user)
        portal.delete()
        return redirect('portal_list')


class PublicPortalView(View):
    """Public upload page for a portal."""

    def get(self, request, slug):
        g = GlobalVars.get_globals(request)
        portal = get_object_or_404(UploadPortal, slug=slug, is_active=True)

        return render(request, 'portals/public.html', {
            'g': g,
            'portal': portal,
        })


class PortalUploadAPI(APIView):
    """API endpoint to upload files to a portal."""

    def post(self, request, slug):
        portal = get_object_or_404(UploadPortal, slug=slug, is_active=True)
        ip = get_client_ip(request)

        # Validate uploader info
        uploader_email = request.data.get('email', '').strip()
        uploader_name = request.data.get('name', '').strip()
        message = request.data.get('message', '').strip()

        if portal.require_email and not uploader_email:
            return Response({'error': 'Email is required'}, status=400)
        if portal.require_name and not uploader_name:
            return Response({'error': 'Name is required'}, status=400)

        # Create transfer for this upload
        transfer = Transfer.objects.create(
            sender_email=uploader_email,
            sender_ip=ip,
            message=message,
            user=portal.user,  # Assign to portal owner
            status=Transfer.UPLOADING,
            expires_at=timezone.now() + timedelta(days=30),  # Portal uploads get 30 days
        )

        # Create portal upload record
        portal_upload = PortalUpload.objects.create(
            portal=portal,
            transfer=transfer,
            uploader_name=uploader_name,
            uploader_email=uploader_email,
            uploader_ip=ip,
            message=message,
        )

        return Response({
            'transfer_id': str(transfer.id),
            'upload_url': f'/api/transfers/{transfer.id}/upload/',
        }, status=status.HTTP_201_CREATED)


class PortalFinalizeAPI(APIView):
    """Finalize a portal upload."""

    def post(self, request, slug, transfer_id):
        portal = get_object_or_404(UploadPortal, slug=slug, is_active=True)

        try:
            transfer = Transfer.objects.get(id=transfer_id)
        except Transfer.DoesNotExist:
            return Response({'error': 'Transfer not found'}, status=404)

        # Verify this transfer belongs to this portal
        try:
            portal_upload = PortalUpload.objects.get(portal=portal, transfer=transfer)
        except PortalUpload.DoesNotExist:
            return Response({'error': 'Invalid transfer'}, status=400)

        if transfer.status != Transfer.UPLOADING:
            return Response({'error': 'Transfer already finalized'}, status=400)

        if transfer.file_count == 0:
            return Response({'error': 'No files uploaded'}, status=400)

        # Mark as ready
        transfer.status = Transfer.READY
        transfer.save(update_fields=['status'])

        # Update portal stats
        portal.total_uploads += 1
        portal.total_files += transfer.file_count
        portal.total_bytes += transfer.total_size
        portal.save(update_fields=['total_uploads', 'total_files', 'total_bytes'])

        # Send notification to portal owner
        if portal.notify_on_upload:
            from transfers.notifications import send_portal_upload_notification
            send_portal_upload_notification(portal, portal_upload)

        return Response({
            'success': True,
            'message': 'Upload complete',
        })


# ============================================================================
# ANALYTICS DASHBOARD
# ============================================================================

class AnalyticsDashboardView(LoginRequiredMixin, View):
    """User analytics dashboard."""

    def get(self, request):
        g = GlobalVars.get_globals(request)

        # Get period from query params (default 30 days)
        days = int(request.GET.get('days', 30))
        days = min(days, 365)  # Max 1 year

        # Get analytics
        analytics = get_user_analytics(request.user, days=days)

        # Format bytes for display
        analytics['total_bytes_formatted'] = format_bytes(analytics['total_bytes'])

        # Prepare chart data as JSON
        import json
        transfers_chart_data = json.dumps(analytics['transfers_by_day'], default=str)
        downloads_chart_data = json.dumps(analytics['downloads_by_day'], default=str)
        hourly_chart_data = json.dumps(analytics['downloads_by_hour'], default=str)

        return render(request, 'transfers/analytics.html', {
            'g': g,
            'analytics': analytics,
            'transfers_chart_data': transfers_chart_data,
            'downloads_chart_data': downloads_chart_data,
            'hourly_chart_data': hourly_chart_data,
            'selected_days': days,
        })


class TransferAnalyticsView(LoginRequiredMixin, View):
    """Analytics for a single transfer."""

    def get(self, request, short_id):
        g = GlobalVars.get_globals(request)

        transfer = get_object_or_404(Transfer, short_id=short_id, user=request.user)
        analytics = get_transfer_analytics(transfer)

        import json
        downloads_chart_data = json.dumps(analytics['downloads_by_day'], default=str)

        return render(request, 'transfers/transfer_analytics.html', {
            'g': g,
            'transfer': transfer,
            'analytics': analytics,
            'downloads_chart_data': downloads_chart_data,
        })
