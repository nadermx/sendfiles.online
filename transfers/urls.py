from django.urls import path
from transfers.views import (
    CreateTransferAPI,
    UploadFileAPI,
    FinalizeTransferAPI,
    DownloadPageView,
    DownloadFileView,
    DownloadAllView,
    SuccessView,
)

urlpatterns = [
    # API endpoints
    path('api/transfers/', CreateTransferAPI.as_view(), name='create_transfer'),
    path('api/transfers/<uuid:transfer_id>/upload/', UploadFileAPI.as_view(), name='upload_file'),
    path('api/transfers/<uuid:transfer_id>/finalize/', FinalizeTransferAPI.as_view(), name='finalize_transfer'),

    # Download pages
    path('d/<str:short_id>/', DownloadPageView.as_view(), name='download_page'),
    path('d/<str:short_id>/file/<uuid:file_id>/', DownloadFileView.as_view(), name='download_file'),
    path('d/<str:short_id>/download/', DownloadAllView.as_view(), name='download_all'),

    # Success page
    path('sent/<str:short_id>/', SuccessView.as_view(), name='transfer_success'),
]
