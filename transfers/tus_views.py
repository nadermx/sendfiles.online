"""
TUS Protocol implementation for resumable file uploads.

TUS is an open protocol for resumable file uploads. This module implements
the server-side handling for tus uploads, integrated with our Transfer system.

Protocol: https://tus.io/protocols/resumable-upload.html
"""

import os
import uuid
import mimetypes
from django.conf import settings
from django.http import HttpResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.core.cache import cache

from transfers.models import Transfer, TransferFile, MonthlyUsage
from config import FILES_LIMIT


# Cache timeout for upload metadata (24 hours)
TUS_CACHE_TIMEOUT = 86400

# Supported tus extensions
TUS_EXTENSIONS = 'creation,creation-with-upload,termination,expiration'
TUS_VERSION = '1.0.0'
TUS_MAX_SIZE = FILES_LIMIT  # Match our file limit


def get_tus_upload_path():
    """Get the directory for tus uploads."""
    path = os.path.join(settings.MEDIA_ROOT, 'tus_uploads')
    os.makedirs(path, exist_ok=True)
    return path


def get_upload_metadata(upload_id):
    """Get metadata for an upload from cache."""
    return cache.get(f'tus_upload:{upload_id}')


def set_upload_metadata(upload_id, metadata):
    """Store metadata for an upload in cache."""
    cache.set(f'tus_upload:{upload_id}', metadata, TUS_CACHE_TIMEOUT)


def delete_upload_metadata(upload_id):
    """Delete metadata for an upload from cache."""
    cache.delete(f'tus_upload:{upload_id}')


def parse_metadata(metadata_header):
    """Parse tus Upload-Metadata header into a dict."""
    metadata = {}
    if not metadata_header:
        return metadata

    import base64
    for item in metadata_header.split(','):
        item = item.strip()
        if ' ' in item:
            key, value = item.split(' ', 1)
            try:
                metadata[key] = base64.b64decode(value).decode('utf-8')
            except Exception:
                metadata[key] = value
        else:
            metadata[item] = None

    return metadata


def add_tus_headers(response):
    """Add common tus headers to response."""
    response['Tus-Resumable'] = TUS_VERSION
    response['Access-Control-Allow-Origin'] = '*'
    response['Access-Control-Allow-Methods'] = 'OPTIONS, POST, HEAD, PATCH, DELETE'
    response['Access-Control-Allow-Headers'] = 'Tus-Resumable, Upload-Length, Upload-Metadata, Upload-Offset, Content-Type, X-CSRFToken, Authorization'
    response['Access-Control-Expose-Headers'] = 'Upload-Offset, Upload-Length, Location, Tus-Resumable, Tus-Version, Tus-Extension, Tus-Max-Size'
    return response


@method_decorator(csrf_exempt, name='dispatch')
class TusUploadView(View):
    """
    TUS upload endpoint.

    Handles:
    - OPTIONS: Return tus capabilities
    - POST: Create new upload
    - HEAD: Get upload status
    - PATCH: Append data to upload
    - DELETE: Cancel upload
    """

    def options(self, request, *args, **kwargs):
        """Return tus capabilities."""
        response = HttpResponse(status=204)
        response['Tus-Version'] = TUS_VERSION
        response['Tus-Extension'] = TUS_EXTENSIONS
        response['Tus-Max-Size'] = str(TUS_MAX_SIZE)
        return add_tus_headers(response)

    def post(self, request, transfer_id):
        """Create a new tus upload."""
        # Validate transfer
        try:
            transfer = Transfer.objects.get(id=transfer_id)
        except Transfer.DoesNotExist:
            return HttpResponse('Transfer not found', status=404)

        if transfer.status != Transfer.UPLOADING:
            return HttpResponse('Transfer is not accepting uploads', status=400)

        # Get upload size
        upload_length = request.headers.get('Upload-Length')
        if not upload_length:
            return HttpResponse('Upload-Length header required', status=400)

        upload_length = int(upload_length)

        # Check size limit
        if upload_length > TUS_MAX_SIZE:
            return HttpResponse('File too large', status=413)

        # Check monthly usage for free users
        if not request.user.is_authenticated or not getattr(request.user, 'is_plan_active', False):
            monthly_usage = MonthlyUsage.get_or_create_for_request(request, request.user if request.user.is_authenticated else None)
            if monthly_usage.remaining_bytes < upload_length:
                return HttpResponse('Monthly transfer limit exceeded', status=429)

        # Parse metadata
        metadata = parse_metadata(request.headers.get('Upload-Metadata', ''))
        filename = metadata.get('filename', 'unnamed')
        filetype = metadata.get('filetype', 'application/octet-stream')

        # Generate upload ID
        upload_id = uuid.uuid4().hex

        # Create empty file for upload
        file_path = os.path.join(get_tus_upload_path(), upload_id)
        open(file_path, 'wb').close()

        # Store metadata in cache
        set_upload_metadata(upload_id, {
            'transfer_id': str(transfer_id),
            'filename': filename,
            'filetype': filetype,
            'length': upload_length,
            'offset': 0,
            'file_path': file_path,
        })

        # Build location URL
        location = request.build_absolute_uri(f'/api/tus/{transfer_id}/{upload_id}/')

        # Handle creation-with-upload extension
        response_status = 201
        new_offset = 0
        if request.body:
            # Append the initial data
            with open(file_path, 'ab') as f:
                f.write(request.body)

            # Update offset
            new_offset = len(request.body)
            upload_meta = get_upload_metadata(upload_id)
            upload_meta['offset'] = new_offset
            set_upload_metadata(upload_id, upload_meta)

            # Check if complete
            if new_offset >= upload_length:
                self._finalize_upload(upload_id, upload_meta, request)

        response = HttpResponse(status=response_status)
        response['Location'] = location
        response['Upload-Offset'] = str(new_offset)
        return add_tus_headers(response)

    def head(self, request, transfer_id, upload_id):
        """Get upload status."""
        upload_meta = get_upload_metadata(upload_id)
        if not upload_meta:
            response = HttpResponse('Upload not found', status=404)
            return add_tus_headers(response)

        response = HttpResponse(status=200)
        response['Upload-Offset'] = str(upload_meta['offset'])
        response['Upload-Length'] = str(upload_meta['length'])
        response['Cache-Control'] = 'no-store'
        return add_tus_headers(response)

    def patch(self, request, transfer_id, upload_id):
        """Append data to upload."""
        upload_meta = get_upload_metadata(upload_id)
        if not upload_meta:
            response = HttpResponse('Upload not found', status=404)
            return add_tus_headers(response)

        # Validate transfer
        if upload_meta['transfer_id'] != str(transfer_id):
            response = HttpResponse('Invalid transfer', status=400)
            return add_tus_headers(response)

        # Check content type
        content_type = request.headers.get('Content-Type', '')
        if content_type != 'application/offset+octet-stream':
            response = HttpResponse('Invalid Content-Type', status=415)
            return add_tus_headers(response)

        # Check offset
        client_offset = int(request.headers.get('Upload-Offset', 0))
        if client_offset != upload_meta['offset']:
            response = HttpResponse('Offset mismatch', status=409)
            response['Upload-Offset'] = str(upload_meta['offset'])
            return add_tus_headers(response)

        # Append data
        file_path = upload_meta['file_path']
        data = request.body

        with open(file_path, 'ab') as f:
            f.write(data)

        # Update offset
        new_offset = upload_meta['offset'] + len(data)
        upload_meta['offset'] = new_offset
        set_upload_metadata(upload_id, upload_meta)

        # Check if complete
        if new_offset >= upload_meta['length']:
            self._finalize_upload(upload_id, upload_meta, request)

        response = HttpResponse(status=204)
        response['Upload-Offset'] = str(new_offset)
        return add_tus_headers(response)

    def delete(self, request, transfer_id, upload_id):
        """Cancel upload."""
        upload_meta = get_upload_metadata(upload_id)
        if not upload_meta:
            response = HttpResponse('Upload not found', status=404)
            return add_tus_headers(response)

        # Delete file
        file_path = upload_meta['file_path']
        if os.path.exists(file_path):
            os.remove(file_path)

        # Delete metadata
        delete_upload_metadata(upload_id)

        response = HttpResponse(status=204)
        return add_tus_headers(response)

    def _finalize_upload(self, upload_id, upload_meta, request):
        """Finalize a completed upload - create TransferFile record."""
        try:
            transfer = Transfer.objects.get(id=upload_meta['transfer_id'])
        except Transfer.DoesNotExist:
            return

        # Move file to permanent storage
        tus_path = upload_meta['file_path']
        original_name = upload_meta['filename']
        file_ext = os.path.splitext(original_name)[1]
        stored_name = f"{uuid.uuid4().hex}{file_ext}"

        transfers_dir = os.path.join(settings.MEDIA_ROOT, 'transfers')
        os.makedirs(transfers_dir, exist_ok=True)

        final_path = os.path.join(transfers_dir, stored_name)
        os.rename(tus_path, final_path)

        # Get file size
        file_size = os.path.getsize(final_path)

        # Determine mime type
        mime_type = upload_meta.get('filetype')
        if not mime_type or mime_type == 'application/octet-stream':
            mime_type, _ = mimetypes.guess_type(original_name)
            if not mime_type:
                mime_type = 'application/octet-stream'

        # Create file record
        transfer_file = TransferFile.objects.create(
            transfer=transfer,
            original_name=original_name,
            stored_name=stored_name,
            size=file_size,
            mime_type=mime_type,
            upload_complete=True,
        )

        # Set preview type
        transfer_file.set_preview_type()
        transfer_file.save(update_fields=['preview_type'])

        # Update transfer totals
        transfer.total_size += file_size
        transfer.file_count += 1
        transfer.save(update_fields=['total_size', 'file_count'])

        # Delete upload metadata
        delete_upload_metadata(upload_id)
