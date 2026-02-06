"""
Team views for SendFiles.Online.
Business/Enterprise feature for team collaboration.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, Http404
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.utils.text import slugify
from django.db.models import Sum, Count, Q
from django.core.paginator import Paginator

from accounts.models import Team, TeamMember, TeamInvitation, AuditLog, CustomUser
from accounts.views import GlobalVars
from accounts.team_notifications import (
    send_team_invitation_email,
    send_member_added_notification,
    send_member_removed_notification,
    send_role_changed_notification,
)
from transfers.models import Transfer
from app.utils import Utils


def get_client_ip(request):
    """Get client IP address."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


# Permission Mixins

class TeamRequiredMixin(LoginRequiredMixin):
    """Check user has Business/Enterprise plan."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        # Check if user has Business or Enterprise plan
        plan = getattr(request.user, 'plan_subscribed', '')
        if plan not in ('business', 'enterprise'):
            return redirect('pricing')

        return super().dispatch(request, *args, **kwargs)


class TeamAccessMixin(TeamRequiredMixin):
    """Check user is an active team member."""

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        if response.status_code != 200 or isinstance(response, redirect.__class__):
            return response

        team = get_object_or_404(Team, slug=kwargs.get('slug'))
        membership = TeamMember.objects.filter(
            team=team,
            user=request.user,
            is_active=True
        ).first()

        if not membership:
            raise Http404("You don't have access to this team")

        request.team = team
        request.membership = membership
        return super(TeamRequiredMixin, self).dispatch(request, *args, **kwargs)


class TeamAdminMixin(TeamAccessMixin):
    """Check user is owner or admin."""

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        if hasattr(response, 'status_code') and response.status_code != 200:
            return response
        if isinstance(response, type(redirect('/'))):
            return response

        if not request.membership.can_manage_members:
            raise Http404("You don't have permission to manage this team")

        return response


class TeamOwnerMixin(TeamAccessMixin):
    """Check user is team owner."""

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        if hasattr(response, 'status_code') and response.status_code != 200:
            return response
        if isinstance(response, type(redirect('/'))):
            return response

        if request.membership.role != TeamMember.ROLE_OWNER:
            raise Http404("Only the team owner can perform this action")

        return response


# Team Views

class TeamListView(TeamRequiredMixin, View):
    """List user's teams and pending invitations."""

    def get(self, request):
        g = GlobalVars.get_globals(request)

        # Get teams user is a member of
        memberships = TeamMember.objects.filter(
            user=request.user,
            is_active=True
        ).select_related('team')

        teams = [m.team for m in memberships]

        # Get pending invitations
        pending_invitations = TeamInvitation.objects.filter(
            email=request.user.email
        ).exclude(
            expires_at__lt=timezone.now()
        ).select_related('team', 'invited_by')

        return render(request, 'teams/list.html', {
            'g': g,
            'teams': teams,
            'memberships': memberships,
            'pending_invitations': pending_invitations,
        })


class TeamCreateView(TeamRequiredMixin, View):
    """Create a new team."""

    def get(self, request):
        g = GlobalVars.get_globals(request)
        return render(request, 'teams/create.html', {'g': g})

    def post(self, request):
        g = GlobalVars.get_globals(request)
        name = request.POST.get('name', '').strip()

        errors = []
        if not name:
            errors.append('Team name is required')
        elif len(name) > 255:
            errors.append('Team name must be 255 characters or less')

        # Check slug uniqueness
        slug = slugify(name)
        if Team.objects.filter(slug=slug).exists():
            errors.append('A team with this name already exists')

        if errors:
            return render(request, 'teams/create.html', {
                'g': g,
                'errors': errors,
                'name': name,
            })

        # Create team
        team = Team.objects.create(
            name=name,
            slug=slug,
            owner=request.user,
        )

        # Add owner as team member
        TeamMember.objects.create(
            team=team,
            user=request.user,
            role=TeamMember.ROLE_OWNER,
            is_active=True,
            joined_at=timezone.now(),
        )

        # Log audit
        AuditLog.log(
            action=AuditLog.ACTION_SETTINGS_CHANGE,
            user=request.user,
            team=team,
            description=f'Team "{team.name}" created',
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
        )

        return redirect('team_detail', slug=team.slug)


class TeamDetailView(TeamAccessMixin, View):
    """Team dashboard with stats and recent transfers."""

    def get(self, request, slug):
        g = GlobalVars.get_globals(request)
        team = request.team
        membership = request.membership

        # Get team stats
        total_transfers = Transfer.objects.filter(team=team).count()
        total_size = Transfer.objects.filter(team=team).aggregate(
            total=Sum('total_size')
        )['total'] or 0

        # Get recent transfers based on role
        if membership.role in [TeamMember.ROLE_OWNER, TeamMember.ROLE_ADMIN]:
            recent_transfers = Transfer.objects.filter(team=team).order_by('-created_at')[:10]
        else:
            # Members see team-visible and their own transfers
            recent_transfers = Transfer.objects.filter(
                Q(team=team, visibility=Transfer.VISIBILITY_TEAM) |
                Q(team=team, user=request.user)
            ).order_by('-created_at')[:10]

        # Get member count
        member_count = team.member_count

        return render(request, 'teams/detail.html', {
            'g': g,
            'team': team,
            'membership': membership,
            'total_transfers': total_transfers,
            'total_size': total_size,
            'recent_transfers': recent_transfers,
            'member_count': member_count,
        })


class TeamSettingsView(TeamAdminMixin, View):
    """Edit team settings."""

    def get(self, request, slug):
        g = GlobalVars.get_globals(request)
        return render(request, 'teams/settings.html', {
            'g': g,
            'team': request.team,
            'membership': request.membership,
        })

    def post(self, request, slug):
        g = GlobalVars.get_globals(request)
        team = request.team

        # Update settings
        team.name = request.POST.get('name', team.name).strip()
        team.max_members = int(request.POST.get('max_members', team.max_members))
        team.default_expiration_days = int(request.POST.get('default_expiration_days', team.default_expiration_days))
        team.require_2fa = request.POST.get('require_2fa') == 'on'
        team.allowed_domains = request.POST.get('allowed_domains', '').strip()
        team.use_owner_branding = request.POST.get('use_owner_branding') == 'on'

        team.save()

        # Log audit
        AuditLog.log(
            action=AuditLog.ACTION_SETTINGS_CHANGE,
            user=request.user,
            team=team,
            description='Team settings updated',
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
        )

        return render(request, 'teams/settings.html', {
            'g': g,
            'team': team,
            'membership': request.membership,
            'success': 'Settings updated successfully',
        })


class TeamDeleteView(TeamOwnerMixin, View):
    """Delete team (owner only)."""

    def get(self, request, slug):
        g = GlobalVars.get_globals(request)
        return render(request, 'teams/delete.html', {
            'g': g,
            'team': request.team,
        })

    def post(self, request, slug):
        g = GlobalVars.get_globals(request)
        team = request.team

        # Verify team name for confirmation
        confirm_name = request.POST.get('confirm_name', '').strip()
        if confirm_name != team.name:
            return render(request, 'teams/delete.html', {
                'g': g,
                'team': team,
                'error': 'Team name does not match',
            })

        # Delete team (cascades to members, invitations)
        team_name = team.name
        team.delete()

        return redirect('team_list')


class TeamMembersView(TeamAccessMixin, View):
    """List team members and pending invitations."""

    def get(self, request, slug):
        g = GlobalVars.get_globals(request)
        team = request.team

        members = TeamMember.objects.filter(
            team=team,
            is_active=True
        ).select_related('user').order_by('role', 'joined_at')

        pending_invitations = TeamInvitation.objects.filter(
            team=team
        ).exclude(
            expires_at__lt=timezone.now()
        ).select_related('invited_by')

        return render(request, 'teams/members.html', {
            'g': g,
            'team': team,
            'membership': request.membership,
            'members': members,
            'pending_invitations': pending_invitations,
        })


class TeamInviteMemberView(TeamAdminMixin, View):
    """Send invitation to join team."""

    def get(self, request, slug):
        g = GlobalVars.get_globals(request)
        return render(request, 'teams/invite.html', {
            'g': g,
            'team': request.team,
            'roles': TeamMember.ROLE_CHOICES[1:],  # Exclude owner
        })

    def post(self, request, slug):
        g = GlobalVars.get_globals(request)
        team = request.team

        email = request.POST.get('email', '').strip().lower()
        role = request.POST.get('role', TeamMember.ROLE_MEMBER)

        errors = []

        if not email:
            errors.append('Email is required')

        # Check if already a member
        if CustomUser.objects.filter(email=email).exists():
            user = CustomUser.objects.get(email=email)
            if TeamMember.objects.filter(team=team, user=user, is_active=True).exists():
                errors.append('This user is already a team member')

        # Check if already invited
        if TeamInvitation.objects.filter(
            team=team,
            email=email,
            expires_at__gt=timezone.now()
        ).exists():
            errors.append('An invitation has already been sent to this email')

        # Check domain restrictions
        if team.allowed_domains:
            allowed = [d.strip().lower() for d in team.allowed_domains.split(',')]
            email_domain = email.split('@')[-1]
            if email_domain not in allowed:
                errors.append(f'Only emails from {team.allowed_domains} can be invited')

        # Check member limit
        if team.member_count >= team.max_members:
            errors.append('Team has reached maximum member limit')

        if errors:
            return render(request, 'teams/invite.html', {
                'g': g,
                'team': team,
                'roles': TeamMember.ROLE_CHOICES[1:],
                'errors': errors,
                'email': email,
                'role': role,
            })

        # Create invitation
        invitation = TeamInvitation.objects.create(
            team=team,
            email=email,
            role=role,
            invited_by=request.user,
        )

        # Send email
        send_team_invitation_email(invitation)

        # Log audit
        AuditLog.log(
            action=AuditLog.ACTION_MEMBER_INVITE,
            user=request.user,
            team=team,
            description=f'Invited {email} as {role}',
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            metadata={'invited_email': email, 'role': role},
        )

        return redirect('team_members', slug=team.slug)


class TeamRemoveMemberView(TeamAdminMixin, View):
    """Remove member from team."""

    def post(self, request, slug, member_id):
        team = request.team

        member = get_object_or_404(TeamMember, id=member_id, team=team)

        # Cannot remove owner
        if member.role == TeamMember.ROLE_OWNER:
            return JsonResponse({'error': 'Cannot remove team owner'}, status=400)

        # Cannot remove yourself
        if member.user == request.user:
            return JsonResponse({'error': 'Cannot remove yourself'}, status=400)

        # Store info for notification
        removed_user = member.user

        # Delete membership
        member.delete()

        # Send notification
        send_member_removed_notification(team, member, request.user)

        # Log audit
        AuditLog.log(
            action=AuditLog.ACTION_MEMBER_REMOVE,
            user=request.user,
            team=team,
            description=f'Removed {removed_user.email} from team',
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            metadata={'removed_email': removed_user.email},
        )

        return redirect('team_members', slug=team.slug)


class TeamUpdateMemberRoleView(TeamAdminMixin, View):
    """Update member's role."""

    def post(self, request, slug, member_id):
        team = request.team

        member = get_object_or_404(TeamMember, id=member_id, team=team)
        new_role = request.POST.get('role')

        # Cannot change owner role
        if member.role == TeamMember.ROLE_OWNER:
            return JsonResponse({'error': 'Cannot change owner role'}, status=400)

        # Cannot set someone as owner
        if new_role == TeamMember.ROLE_OWNER:
            return JsonResponse({'error': 'Cannot set member as owner'}, status=400)

        old_role = member.get_role_display()
        member.role = new_role
        member.save()

        # Send notification
        send_role_changed_notification(team, member, old_role, member.get_role_display())

        # Log audit
        AuditLog.log(
            action=AuditLog.ACTION_SETTINGS_CHANGE,
            user=request.user,
            team=team,
            description=f'Changed {member.user.email} role from {old_role} to {member.get_role_display()}',
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
        )

        return redirect('team_members', slug=team.slug)


class TeamTransfersView(TeamAccessMixin, View):
    """List team transfers."""

    def get(self, request, slug):
        g = GlobalVars.get_globals(request)
        team = request.team
        membership = request.membership

        # Filter transfers based on role
        if membership.role in [TeamMember.ROLE_OWNER, TeamMember.ROLE_ADMIN]:
            transfers = Transfer.objects.filter(team=team)
        elif membership.role == TeamMember.ROLE_MEMBER:
            transfers = Transfer.objects.filter(
                Q(team=team, visibility=Transfer.VISIBILITY_TEAM) |
                Q(team=team, user=request.user)
            )
        else:  # Viewer
            transfers = Transfer.objects.filter(
                team=team,
                visibility__in=[Transfer.VISIBILITY_TEAM, Transfer.VISIBILITY_PUBLIC]
            )

        transfers = transfers.order_by('-created_at')

        # Pagination
        paginator = Paginator(transfers, 25)
        page = request.GET.get('page', 1)
        transfers_page = paginator.get_page(page)

        return render(request, 'teams/transfers.html', {
            'g': g,
            'team': team,
            'membership': membership,
            'transfers': transfers_page,
        })


class TeamAnalyticsView(TeamAccessMixin, View):
    """Team analytics dashboard."""

    def get(self, request, slug):
        g = GlobalVars.get_globals(request)
        team = request.team

        # Aggregate stats
        stats = Transfer.objects.filter(team=team).aggregate(
            total_transfers=Count('id'),
            total_size=Sum('total_size'),
            total_downloads=Sum('download_count'),
        )

        # Transfers by status
        by_status = Transfer.objects.filter(team=team).values('status').annotate(
            count=Count('id')
        )

        # Recent activity (last 30 days)
        thirty_days_ago = timezone.now() - timezone.timedelta(days=30)
        recent_transfers = Transfer.objects.filter(
            team=team,
            created_at__gte=thirty_days_ago
        ).count()

        return render(request, 'teams/analytics.html', {
            'g': g,
            'team': team,
            'membership': request.membership,
            'stats': stats,
            'by_status': by_status,
            'recent_transfers': recent_transfers,
        })


class TeamAuditLogView(TeamAdminMixin, View):
    """View team audit log."""

    def get(self, request, slug):
        g = GlobalVars.get_globals(request)
        team = request.team

        logs = AuditLog.objects.filter(team=team).select_related('user').order_by('-created_at')

        # Pagination
        paginator = Paginator(logs, 50)
        page = request.GET.get('page', 1)
        logs_page = paginator.get_page(page)

        return render(request, 'teams/audit.html', {
            'g': g,
            'team': team,
            'membership': request.membership,
            'logs': logs_page,
        })


# Invitation Views (Public)

class AcceptInvitationView(LoginRequiredMixin, View):
    """Accept team invitation."""

    def get(self, request, token):
        g = GlobalVars.get_globals(request)

        invitation = get_object_or_404(TeamInvitation, token=token)

        if invitation.is_expired:
            return render(request, 'teams/invitation_expired.html', {'g': g})

        # Check if user email matches invitation
        if request.user.email.lower() != invitation.email.lower():
            return render(request, 'teams/invitation_email_mismatch.html', {
                'g': g,
                'invitation': invitation,
            })

        return render(request, 'teams/accept_invitation.html', {
            'g': g,
            'invitation': invitation,
        })

    def post(self, request, token):
        invitation = get_object_or_404(TeamInvitation, token=token)

        if invitation.is_expired:
            return redirect('team_list')

        if request.user.email.lower() != invitation.email.lower():
            return redirect('team_list')

        # Check if already a member
        if TeamMember.objects.filter(team=invitation.team, user=request.user).exists():
            invitation.delete()
            return redirect('team_detail', slug=invitation.team.slug)

        # Create membership
        member = TeamMember.objects.create(
            team=invitation.team,
            user=request.user,
            role=invitation.role,
            is_active=True,
            joined_at=timezone.now(),
        )

        # Send welcome notification
        send_member_added_notification(invitation.team, member)

        # Log audit
        AuditLog.log(
            action=AuditLog.ACTION_SETTINGS_CHANGE,
            user=request.user,
            team=invitation.team,
            description=f'{request.user.email} joined the team',
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
        )

        # Delete invitation
        invitation.delete()

        return redirect('team_detail', slug=member.team.slug)


class DeclineInvitationView(LoginRequiredMixin, View):
    """Decline team invitation."""

    def get(self, request, token):
        invitation = get_object_or_404(TeamInvitation, token=token)
        invitation.delete()
        return redirect('team_list')


class ResendInvitationView(TeamAdminMixin, View):
    """Resend invitation email."""

    def post(self, request, slug, invitation_id):
        team = request.team
        invitation = get_object_or_404(TeamInvitation, id=invitation_id, team=team)

        # Update expiration
        invitation.expires_at = timezone.now() + timezone.timedelta(days=7)
        invitation.save()

        # Resend email
        send_team_invitation_email(invitation)

        return redirect('team_members', slug=team.slug)


class CancelInvitationView(TeamAdminMixin, View):
    """Cancel pending invitation."""

    def post(self, request, slug, invitation_id):
        team = request.team
        invitation = get_object_or_404(TeamInvitation, id=invitation_id, team=team)
        invitation.delete()

        return redirect('team_members', slug=team.slug)
