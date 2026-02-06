from django.urls import path
from transfers.views import (
    CreateTransferAPI,
    UploadFileAPI,
    FinalizeTransferAPI,
    DownloadPageView,
    DownloadFileView,
    DownloadAllView,
    SuccessView,
    PreviewFileView,
    RawFileView,
    # Portals
    PortalListView,
    PortalCreateView,
    PortalDetailView,
    PortalEditView,
    PortalDeleteView,
    PublicPortalView,
    PortalUploadAPI,
    PortalFinalizeAPI,
    AnalyticsDashboardView,
    TransferAnalyticsView,
)
from transfers.tus_views import TusUploadView

urlpatterns = [
    # API endpoints
    path('api/transfers/', CreateTransferAPI.as_view(), name='create_transfer'),
    path('api/transfers/<uuid:transfer_id>/upload/', UploadFileAPI.as_view(), name='upload_file'),
    path('api/transfers/<uuid:transfer_id>/finalize/', FinalizeTransferAPI.as_view(), name='finalize_transfer'),

    # TUS resumable upload endpoints
    path('api/tus/<uuid:transfer_id>/', TusUploadView.as_view(), name='tus_upload'),
    path('api/tus/<uuid:transfer_id>/<str:upload_id>/', TusUploadView.as_view(), name='tus_upload_file'),

    # Download pages
    path('d/<str:short_id>/', DownloadPageView.as_view(), name='download_page'),
    path('d/<str:short_id>/file/<uuid:file_id>/', DownloadFileView.as_view(), name='download_file'),
    path('d/<str:short_id>/download/', DownloadAllView.as_view(), name='download_all'),

    # Preview pages
    path('d/<str:short_id>/preview/<uuid:file_id>/', PreviewFileView.as_view(), name='preview_file'),
    path('d/<str:short_id>/raw/<uuid:file_id>/', RawFileView.as_view(), name='raw_file'),

    # Success page
    path('sent/<str:short_id>/', SuccessView.as_view(), name='transfer_success'),

    # Upload Portals (user management)
    path('portals/', PortalListView.as_view(), name='portal_list'),
    path('portals/create/', PortalCreateView.as_view(), name='portal_create'),
    path('portals/<str:slug>/', PortalDetailView.as_view(), name='portal_detail'),
    path('portals/<str:slug>/edit/', PortalEditView.as_view(), name='portal_edit'),
    path('portals/<str:slug>/delete/', PortalDeleteView.as_view(), name='portal_delete'),

    # Public portal page
    path('p/<str:slug>/', PublicPortalView.as_view(), name='public_portal'),

    # Portal API
    path('api/portals/<str:slug>/upload/', PortalUploadAPI.as_view(), name='portal_upload_api'),
    path('api/portals/<str:slug>/finalize/<uuid:transfer_id>/', PortalFinalizeAPI.as_view(), name='portal_finalize_api'),

    # Analytics
    path('analytics/', AnalyticsDashboardView.as_view(), name='analytics_dashboard'),
    path('analytics/<str:short_id>/', TransferAnalyticsView.as_view(), name='transfer_analytics'),
]
