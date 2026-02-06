"""
Team URL patterns for SendFiles.Online.
"""

from django.urls import path
from accounts.team_views import (
    TeamListView,
    TeamCreateView,
    TeamDetailView,
    TeamSettingsView,
    TeamDeleteView,
    TeamMembersView,
    TeamInviteMemberView,
    TeamRemoveMemberView,
    TeamUpdateMemberRoleView,
    TeamTransfersView,
    TeamAnalyticsView,
    TeamAuditLogView,
    AcceptInvitationView,
    DeclineInvitationView,
    ResendInvitationView,
    CancelInvitationView,
)

urlpatterns = [
    # Team management
    path('teams/', TeamListView.as_view(), name='team_list'),
    path('teams/create/', TeamCreateView.as_view(), name='team_create'),
    path('teams/<str:slug>/', TeamDetailView.as_view(), name='team_detail'),
    path('teams/<str:slug>/settings/', TeamSettingsView.as_view(), name='team_settings'),
    path('teams/<str:slug>/delete/', TeamDeleteView.as_view(), name='team_delete'),

    # Member management
    path('teams/<str:slug>/members/', TeamMembersView.as_view(), name='team_members'),
    path('teams/<str:slug>/members/invite/', TeamInviteMemberView.as_view(), name='team_invite_member'),
    path('teams/<str:slug>/members/<uuid:member_id>/remove/', TeamRemoveMemberView.as_view(), name='team_remove_member'),
    path('teams/<str:slug>/members/<uuid:member_id>/role/', TeamUpdateMemberRoleView.as_view(), name='team_update_member_role'),

    # Team content
    path('teams/<str:slug>/transfers/', TeamTransfersView.as_view(), name='team_transfers'),
    path('teams/<str:slug>/analytics/', TeamAnalyticsView.as_view(), name='team_analytics'),
    path('teams/<str:slug>/audit/', TeamAuditLogView.as_view(), name='team_audit_log'),

    # Invitation management (admin)
    path('teams/<str:slug>/invitations/<uuid:invitation_id>/resend/', ResendInvitationView.as_view(), name='team_resend_invitation'),
    path('teams/<str:slug>/invitations/<uuid:invitation_id>/cancel/', CancelInvitationView.as_view(), name='team_cancel_invitation'),

    # Invitation acceptance (public)
    path('invite/<str:token>/', AcceptInvitationView.as_view(), name='accept_invitation'),
    path('invite/<str:token>/decline/', DeclineInvitationView.as_view(), name='decline_invitation'),
]
