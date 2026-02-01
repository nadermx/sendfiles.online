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
from transfers.models import Transfer, TransferFile, DownloadEvent
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
        return render(request, 'index.html', {
            'g': g,
            'max_size': FILES_LIMIT,
            'max_size_gb': FILES_LIMIT / (1024 ** 3),
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

        # Set expiration
        days = int(data.get('expiration_days', 14))
        days = min(days, 14)  # Max 14 for free tier
        transfer.expires_at = timezone.now() + timedelta(days=days)

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

        # TODO: Send email notifications to recipients

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
        DownloadEvent.objects.create(
            transfer=transfer,
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            is_full_download=True,
        )

        # Increment download count
        transfer.increment_downloads()

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
