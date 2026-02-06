"""
Team notification functions for SendFiles.Online.
"""

from app.utils import Utils
from config import ROOT_DOMAIN


def send_team_invitation_email(invitation):
    """Send email invitation to join a team."""
    accept_url = f"{ROOT_DOMAIN}/invite/{invitation.token}/"
    decline_url = f"{ROOT_DOMAIN}/invite/{invitation.token}/decline/"

    Utils.send_email(
        recipients=[invitation.email],
        subject=f"You've been invited to join {invitation.team.name} on SendFiles.Online",
        template='team-invitation',
        data={
            'team_name': invitation.team.name,
            'invited_by': invitation.invited_by.email,
            'role': invitation.get_role_display(),
            'accept_url': accept_url,
            'decline_url': decline_url,
            'expires_at': invitation.expires_at,
        }
    )


def send_member_added_notification(team, member):
    """Send welcome notification to new team member."""
    team_url = f"{ROOT_DOMAIN}/teams/{team.slug}/"

    Utils.send_email(
        recipients=[member.user.email],
        subject=f"Welcome to {team.name} on SendFiles.Online",
        template='team-member-added',
        data={
            'team_name': team.name,
            'role': member.get_role_display(),
            'team_url': team_url,
        }
    )


def send_member_removed_notification(team, member, removed_by):
    """Send notification when a member is removed from a team."""
    Utils.send_email(
        recipients=[member.user.email],
        subject=f"You have been removed from {team.name}",
        template='team-member-removed',
        data={
            'team_name': team.name,
            'removed_by': removed_by.email,
        }
    )


def send_role_changed_notification(team, member, old_role, new_role):
    """Send notification when a member's role is changed."""
    team_url = f"{ROOT_DOMAIN}/teams/{team.slug}/"

    Utils.send_email(
        recipients=[member.user.email],
        subject=f"Your role in {team.name} has been updated",
        template='team-role-changed',
        data={
            'team_name': team.name,
            'old_role': old_role,
            'new_role': new_role,
            'team_url': team_url,
        }
    )
