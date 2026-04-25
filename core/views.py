import json
import requests
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Sum, Q

from .models import (
    UserProfile, Team, Court, Availability, Session,
    Attendance, Announcement, Notification, Fee, PlayerFee, CoachEarning,
    Conversation, ConversationParticipant, Message,
)
from django.utils import timezone
from .models import TeamJoinRequest
from .models import TeamLeaveRequest

import os
import anthropic


# ─── helpers ──────────────────────────────────────────────────────────────────

def get_role(user):
    try:
        return user.profile.role
    except Exception:
        return 'player'


def require_role(*roles):
    def decorator(view_func):
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')
            if get_role(request.user) not in roles:
                messages.error(request, "You don't have permission to do that.")
                return redirect('dashboard')
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def send_notification(recipient, title, message, notif_type='general'):
    Notification.objects.create(
        recipient=recipient, title=title, message=message, notif_type=notif_type
    )


def apply_late_fees():
    today = date.today()
    overdue = PlayerFee.objects.filter(
        status='pending',
        fee__deadline__lt=today,
        late_fee_applied=False
    )
    for pf in overdue:
        pf.status = 'overdue'
        if pf.fee.late_fee_amount > 0:
            pf.amount_due += pf.fee.late_fee_amount
            pf.late_fee_applied = True
        pf.save()
        send_notification(
            pf.player,
            'Payment Overdue',
            f'Your payment for "{pf.fee.name}" is overdue. Late fee has been applied.',
            'payment'
        )


# ─── auth ─────────────────────────────────────────────────────────────────────

def home(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return redirect('login')


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            return redirect('dashboard')
        messages.error(request, 'Invalid username or password.')
    return render(request, 'auth/login.html')


def logout_view(request):
    logout(request)
    return redirect('login')


def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        role = request.POST.get('role', 'player')
        if User.objects.filter(username=username).exists():
            messages.error(request, 'Username already taken.')
        else:
            user = User.objects.create_user(
                username=username, email=email, password=password,
                first_name=first_name, last_name=last_name
            )
            UserProfile.objects.create(user=user, role=role)
            login(request, user)
            return redirect('dashboard')
    return render(request, 'auth/register.html')


# ─── dashboard ────────────────────────────────────────────────────────────────

@login_required
def dashboard(request):
    apply_late_fees()
    role = get_role(request.user)
    ctx = {'role': role}

    unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()
    ctx['unread_count'] = unread_count

    if role == 'coordinator':
        ctx['teams'] = Team.objects.all()
        ctx['total_players'] = User.objects.filter(profile__role='player').count()
        ctx['total_coaches'] = User.objects.filter(profile__role='coach').count()
        ctx['courts'] = Court.objects.filter(is_active=True)
        ctx['upcoming_sessions'] = Session.objects.filter(
            date__gte=date.today(), status='scheduled'
        ).order_by('date', 'start_time')[:5]
        # financial summary
        total_collected = PlayerFee.objects.filter(status='paid').aggregate(s=Sum('amount_due'))['s'] or 0
        total_pending = PlayerFee.objects.filter(status='pending').aggregate(s=Sum('amount_due'))['s'] or 0
        total_overdue = PlayerFee.objects.filter(status='overdue').aggregate(s=Sum('amount_due'))['s'] or 0
        ctx['total_collected'] = total_collected
        ctx['total_pending'] = total_pending
        ctx['total_overdue'] = total_overdue
        ctx['announcements'] = Announcement.objects.all().order_by('-created_at')[:3]

    elif role == 'coach':
        coached_teams = request.user.coached_teams.all()
        ctx['teams'] = coached_teams
        ctx['upcoming_sessions'] = Session.objects.filter(
            team__in=coached_teams, date__gte=date.today(), status='scheduled'
        ).order_by('date', 'start_time')[:5]
        ctx['recent_sessions'] = Session.objects.filter(
            team__in=coached_teams, status='completed'
        ).order_by('-date')[:3]
        earnings = CoachEarning.objects.filter(coach=request.user)
        ctx['total_earnings'] = earnings.aggregate(s=Sum('amount'))['s'] or 0
        ctx['pending_earnings'] = earnings.filter(paid=False).aggregate(s=Sum('amount'))['s'] or 0
        ctx['announcements'] = Announcement.objects.filter(
            Q(team__in=coached_teams) | Q(scope='club')
        ).order_by('-created_at')[:3]

    else:  # player
        player_teams = request.user.teams.all()
        ctx['teams'] = player_teams
        ctx['upcoming_sessions'] = Session.objects.filter(
            team__in=player_teams, date__gte=date.today(), status='scheduled'
        ).order_by('date', 'start_time')[:5]
        ctx['pending_fees'] = PlayerFee.objects.filter(
            player=request.user, status__in=['pending', 'overdue']
        ).select_related('fee')
        ctx['announcements'] = Announcement.objects.filter(
            Q(team__in=player_teams) | Q(scope='club')
        ).order_by('-created_at')[:3]

    return render(request, 'dashboard.html', ctx)


#  Messaging views 


@login_required
def conversations_list(request):
    # show conversations the user participates in plus team chats they belong to
    convs = Conversation.objects.filter(participants__user=request.user).order_by('-created_at')
    # also ensure team chats for user's teams are available
    teams = request.user.teams.all()
    team_convs = Conversation.objects.filter(team__in=teams, is_team=True)
    for tc in team_convs:
        if tc not in convs:
            convs = list(convs) + [tc]
    return render(request, 'messages/list.html', {'conversations': convs})


@login_required
def conversation_detail(request, pk):
    conv = get_object_or_404(Conversation, pk=pk)
    # permission: must be participant or team member if team chat
    if not conv.is_team:
        if not conv.participants.filter(user=request.user).exists():
            messages.error(request, "You don't have access to that conversation.")
            return redirect('conversations_list')
    else:
        if conv.team and request.user not in conv.team.players.all() and request.user not in conv.team.coaches.all() and request.user != conv.team.coordinator:
            messages.error(request, "You don't have access to that team chat.")
            return redirect('conversations_list')

    messages_qs = conv.messages.order_by('created_at').select_related('sender')[:500]
    # mark read for participant
    try:
        part = conv.participants.get(user=request.user)
        part.last_read_at = timezone.now()
        part.save()
    except ConversationParticipant.DoesNotExist:
        # auto-join non-team private convo if invited? keep strict and require existence
        pass

    return render(request, 'messages/detail.html', {'conversation': conv, 'messages': messages_qs})


@login_required
def send_message(request, pk):
    conv = get_object_or_404(Conversation, pk=pk)
    if request.method == 'POST':
        content = request.POST.get('content', '').strip()
        if content:
            # check mute
            try:
                part = ConversationParticipant.objects.get(conversation=conv, user=request.user)
                if part.is_muted():
                    return JsonResponse({'ok': False, 'error': 'You are muted in this conversation.'})
            except ConversationParticipant.DoesNotExist:
                if not conv.is_team:
                    return JsonResponse({'ok': False, 'error': 'Not a participant.'})

            msg = Message.objects.create(conversation=conv, sender=request.user, content=content)
            # simple notification to other participants
            recipients = [p.user for p in conv.participants.exclude(user=request.user)]
            for r in recipients:
                send_notification(r, 'New Message', f'New message from {request.user.get_full_name() or request.user.username}', 'general')
            return JsonResponse({'ok': True, 'message_id': msg.pk, 'content': msg.content, 'created_at': msg.created_at.isoformat()})
    return JsonResponse({'ok': False, 'error': 'Invalid request'})


@login_required
def delete_message(request, conv_pk, msg_pk):
    conv = get_object_or_404(Conversation, pk=conv_pk)
    msg = get_object_or_404(Message, pk=msg_pk, conversation=conv)
    role = get_role(request.user)
    # only sender, coach or coordinator can delete
    can_delete = (msg.sender == request.user) or (role in ['coach', 'coordinator'] and (
        (conv.is_team and request.user in (conv.team.coaches.all() | User.objects.filter(pk=conv.team.coordinator_id))) or role == 'coordinator'
    ))
    if not can_delete:
        return JsonResponse({'ok': False, 'error': 'Permission denied'})
    msg.mark_deleted(by_user=request.user)
    return JsonResponse({'ok': True})


@login_required
def mute_participant(request, conv_pk, user_pk):
    conv = get_object_or_404(Conversation, pk=conv_pk)
    role = get_role(request.user)
    # only coach or coordinator for team chats, or coordinator globally
    if role not in ['coach', 'coordinator']:
        return JsonResponse({'ok': False, 'error': 'Permission denied'})
    # verify coach belongs to team for team chat
    if conv.is_team and role == 'coach' and request.user not in conv.team.coaches.all():
        return JsonResponse({'ok': False, 'error': 'Permission denied'})
    part = get_object_or_404(ConversationParticipant, conversation=conv, user__pk=user_pk)
    # prevent coach from muting the coordinator of the team
    if conv.is_team and conv.team.coordinator and part.user == conv.team.coordinator and role == 'coach':
        return JsonResponse({'ok': False, 'error': 'Cannot mute the coordinator'})
    # mute for 1 hour by default
    part.muted_until = timezone.now() + timedelta(hours=1)
    part.save()
    send_notification(part.user, 'You were muted', f'You were muted in {conv}.', 'general')
    return JsonResponse({'ok': True})


@login_required
def mark_typing(request, conv_pk):
    conv = get_object_or_404(Conversation, pk=conv_pk)
    try:
        part = ConversationParticipant.objects.get(conversation=conv, user=request.user)
        part.last_typing_at = timezone.now()
        part.save()
        return JsonResponse({'ok': True})
    except ConversationParticipant.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Not a participant'})


@login_required
def mark_read(request, conv_pk):
    conv = get_object_or_404(Conversation, pk=conv_pk)
    try:
        part = ConversationParticipant.objects.get(conversation=conv, user=request.user)
        part.last_read_at = timezone.now()
        part.save()
        return JsonResponse({'ok': True})
    except ConversationParticipant.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Not a participant'})


@login_required
def participants_status(request, conv_pk):
    conv = get_object_or_404(Conversation, pk=conv_pk)
    parts = conv.participants.select_related('user')
    data = []
    now = timezone.now()
    for p in parts:
        is_typing = False
        is_online = False
        if p.last_typing_at:
            is_typing = (now - p.last_typing_at).total_seconds() < 10
        if p.last_read_at:
            is_online = (now - p.last_read_at).total_seconds() < 120
        data.append({'user_id': p.user.pk, 'username': p.user.get_full_name() or p.user.username, 'is_typing': is_typing, 'is_online': is_online})
    return JsonResponse({'ok': True, 'participants': data})


@login_required
def message_readers(request, conv_pk, msg_pk):
    conv = get_object_or_404(Conversation, pk=conv_pk)
    msg = get_object_or_404(Message, pk=msg_pk, conversation=conv)
    # gather participants (excluding sender) whose last_read_at >= message.created_at
    readers = ConversationParticipant.objects.filter(conversation=conv, last_read_at__gte=msg.created_at).exclude(user=msg.sender)
    data = [{'id': r.user.pk, 'name': r.user.get_full_name() or r.user.username, 'read_at': r.last_read_at.isoformat() if r.last_read_at else None} for r in readers]
    return JsonResponse({'ok': True, 'readers': data})


@login_required
def add_participant(request, conv_pk):
    conv = get_object_or_404(Conversation, pk=conv_pk)
    role = get_role(request.user)
    if not conv.is_team:
        return JsonResponse({'ok': False, 'error': 'Can only manage participants for team chats'})
    if role == 'coach' and request.user not in conv.team.coaches.all():
        return JsonResponse({'ok': False, 'error': 'Permission denied'})
    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        u = get_object_or_404(User, pk=user_id)
        ConversationParticipant.objects.get_or_create(conversation=conv, user=u)
        return JsonResponse({'ok': True})
    return JsonResponse({'ok': False, 'error': 'Invalid'})


@login_required
def remove_participant(request, conv_pk, user_pk):
    conv = get_object_or_404(Conversation, pk=conv_pk)
    role = get_role(request.user)
    if not conv.is_team:
        return JsonResponse({'ok': False, 'error': 'Can only manage participants for team chats'})
    if role == 'coach' and request.user not in conv.team.coaches.all():
        return JsonResponse({'ok': False, 'error': 'Permission denied'})
    part = get_object_or_404(ConversationParticipant, conversation=conv, user__pk=user_pk)
    part.delete()
    return JsonResponse({'ok': True})


@login_required
def start_private_conversation(request, user_pk):
    other = get_object_or_404(User, pk=user_pk)
    # find existing private conversation between the two users
    convs = Conversation.objects.filter(is_team=False, participants__user=request.user).distinct()
    for c in convs:
        if c.participants.filter(user=other).exists():
            return redirect('conversation_detail', pk=c.pk)
    # create new
    conv = Conversation.objects.create(title=f"{request.user.username} & {other.username}")
    ConversationParticipant.objects.create(conversation=conv, user=request.user)
    ConversationParticipant.objects.create(conversation=conv, user=other)
    return redirect('conversation_detail', pk=conv.pk)


@login_required
def start_team_conversation(request, team_pk):
    team = get_object_or_404(Team, pk=team_pk)
    # only allow team members (players, coaches, coordinator) to open the team chat
    if request.user not in team.players.all() and request.user not in team.coaches.all() and request.user != team.coordinator and get_role(request.user) != 'coordinator':
        messages.error(request, "You don't have access to the team chat.")
        return redirect('team_detail', pk=team.pk)

    conv, created = Conversation.objects.get_or_create(team=team, is_team=True, defaults={'title': f'{team.name} Team Chat'})

    # ensure participants: coordinator, coaches, players
    # add coordinator
    if team.coordinator:
        ConversationParticipant.objects.get_or_create(conversation=conv, user=team.coordinator)
    # add coaches
    for c in team.coaches.all():
        ConversationParticipant.objects.get_or_create(conversation=conv, user=c)
    # add existing players
    for p in team.players.all():
        ConversationParticipant.objects.get_or_create(conversation=conv, user=p)

    return redirect('conversation_detail', pk=conv.pk)


# ─── teams ────────────────────────────────────────────────────────────────────

@login_required
def teams_list(request):
    role = get_role(request.user)
    if role == 'coordinator':
        teams = Team.objects.all()
    elif role == 'coach':
        teams = request.user.coached_teams.all()
    else:
        teams = Team.objects.all()
    return render(request, 'teams/list.html', {'teams': teams, 'role': role})


@login_required
@require_role('coordinator')
def team_create(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        description = request.POST.get('description', '')
        team = Team.objects.create(
            name=name, description=description, coordinator=request.user
        )
        messages.success(request, f'Team "{team.name}" created.')
        return redirect('team_detail', pk=team.pk)
    return render(request, 'teams/form.html', {'action': 'Create'})


@login_required
def team_detail(request, pk):
    team = get_object_or_404(Team, pk=pk)
    role = get_role(request.user)
    all_coaches = User.objects.filter(profile__role='coach').exclude(id__in=team.coaches.all())
    all_players = User.objects.filter(profile__role='player').exclude(id__in=team.players.all())
    sessions = team.sessions.order_by('-date')[:10]
    return render(request, 'teams/detail.html', {
        'team': team, 'role': role,
        'all_coaches': all_coaches, 'all_players': all_players,
        'sessions': sessions,
    })


@login_required
@require_role('coordinator')
def team_edit(request, pk):
    team = get_object_or_404(Team, pk=pk)
    if request.method == 'POST':
        team.name = request.POST.get('name')
        team.description = request.POST.get('description', '')
        team.save()
        messages.success(request, 'Team updated.')
        return redirect('team_detail', pk=pk)
    return render(request, 'teams/form.html', {'team': team, 'action': 'Edit'})


@login_required
@require_role('coordinator')
def team_delete(request, pk):
    team = get_object_or_404(Team, pk=pk)
    if request.method == 'POST':
        team.delete()
        messages.success(request, 'Team deleted.')
        return redirect('teams_list')
    return render(request, 'teams/confirm_delete.html', {'team': team})


@login_required
@require_role('coordinator')
def assign_coach(request, pk):
    team = get_object_or_404(Team, pk=pk)
    if request.method == 'POST':
        coach_id = request.POST.get('coach_id')
        coach = get_object_or_404(User, pk=coach_id)
        team.coaches.add(coach)
        send_notification(coach, 'Assigned to Team', f'You have been assigned as coach of {team.name}.', 'general')
        messages.success(request, f'{coach.username} assigned as coach.')
    return redirect('team_detail', pk=pk)


@login_required
@require_role('coordinator')
def remove_coach(request, pk, coach_id):
    team = get_object_or_404(Team, pk=pk)
    coach = get_object_or_404(User, pk=coach_id)
    team.coaches.remove(coach)
    messages.success(request, f'{coach.username} removed from coaching staff.')
    return redirect('team_detail', pk=pk)


@login_required
@require_role('player')
def join_team(request, pk):
    team = get_object_or_404(Team, pk=pk)
    if request.method == 'POST':
        # legacy direct join - keep for coordinator override but generally use requests
        team.players.add(request.user)
        messages.success(request, f'You joined {team.name}.')
        # ensure team conversation contains this participant
        try:
            conv, created = Conversation.objects.get_or_create(team=team, is_team=True, defaults={'title': f'{team.name} Team Chat'})
            ConversationParticipant.objects.get_or_create(conversation=conv, user=request.user)
        except Exception:
            pass
    return redirect('team_detail', pk=pk)


@login_required
@require_role('player')
def request_join_team(request, pk):
    team = get_object_or_404(Team, pk=pk)
    if request.method == 'POST':
        # don't duplicate requests or if already a member
        if request.user in team.players.all():
            messages.info(request, 'You are already a member of this team.')
            return redirect('team_detail', pk=pk)
        req, created = TeamJoinRequest.objects.get_or_create(team=team, player=request.user)
        if not created and req.status == 'pending':
            messages.info(request, 'You already have a pending request.')
        else:
            # if previously rejected or accepted, reset to pending
            req.status = 'pending'
            req.created_at = timezone.now()
            req.reviewed_at = None
            req.reviewed_by = None
            req.save()
            messages.success(request, 'Request sent to coach(es) for approval.')
            # notify coaches and coordinator
            recipients = list(team.coaches.all())
            if team.coordinator:
                recipients.append(team.coordinator)
            for r in set(recipients):
                send_notification(r, 'Join Request', f'{request.user.get_full_name() or request.user.username} requested to join {team.name}.', 'general')
    return redirect('team_detail', pk=pk)


@login_required
@require_role('player')
def request_leave_team(request, pk):
    team = get_object_or_404(Team, pk=pk)
    if request.method == 'POST':
        if request.user not in team.players.all():
            messages.info(request, 'You are not a member of this team.')
            return redirect('team_detail', pk=pk)
        req, created = TeamLeaveRequest.objects.get_or_create(team=team, player=request.user)
        if not created and req.status == 'pending':
            messages.info(request, 'You already have a pending leave request.')
        else:
            req.status = 'pending'
            req.created_at = timezone.now()
            req.reviewed_at = None
            req.reviewed_by = None
            req.save()
            messages.success(request, 'Leave request sent to coach(es) for approval.')
            recipients = list(team.coaches.all())
            if team.coordinator:
                recipients.append(team.coordinator)
            for r in set(recipients):
                send_notification(r, 'Leave Request', f'{request.user.get_full_name() or request.user.username} requested to leave {team.name}.', 'general')
    return redirect('team_detail', pk=pk)


@login_required
@require_role('coordinator', 'coach')
def team_leave_requests(request, pk):
    team = get_object_or_404(Team, pk=pk)
    role = get_role(request.user)
    if role == 'coach' and request.user not in team.coaches.all():
        messages.error(request, "You don't have permission to view leave requests for this team.")
        return redirect('team_detail', pk=pk)
    pending = team.leave_requests.filter(status='pending').order_by('created_at')
    return render(request, 'teams/leave_requests.html', {'team': team, 'pending': pending})


@login_required
@require_role('coordinator', 'coach')
def review_leave_request(request, pk, request_id):
    team = get_object_or_404(Team, pk=pk)
    lr = get_object_or_404(TeamLeaveRequest, pk=request_id, team=team)
    role = get_role(request.user)
    if role == 'coach' and request.user not in team.coaches.all():
        messages.error(request, "You don't have permission to review leave requests for this team.")
        return redirect('team_detail', pk=pk)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'accept':
            team.players.remove(lr.player)
            lr.status = 'accepted'
            lr.reviewed_at = timezone.now()
            lr.reviewed_by = request.user
            lr.save()
            send_notification(lr.player, 'Leave Request Accepted', f'Your request to leave {team.name} was accepted.', 'general')
            messages.success(request, f'{lr.player.username} removed from the team.')
            # remove from team conversation participants if a team chat exists
            try:
                conv = Conversation.objects.get(team=team, is_team=True)
                ConversationParticipant.objects.filter(conversation=conv, user=lr.player).delete()
            except Conversation.DoesNotExist:
                pass
        elif action == 'reject':
            lr.status = 'rejected'
            lr.reviewed_at = timezone.now()
            lr.reviewed_by = request.user
            lr.save()
            send_notification(lr.player, 'Leave Request Rejected', f'Your request to leave {team.name} was rejected.', 'general')
            messages.success(request, f'{lr.player.username} leave request rejected.')
    return redirect('team_leave_requests', pk=pk)


@login_required
@require_role('coordinator', 'coach')
def team_join_requests(request, pk):
    team = get_object_or_404(Team, pk=pk)
    # only coaches or coordinator for that team can view
    role = get_role(request.user)
    if role == 'coach' and request.user not in team.coaches.all():
        messages.error(request, "You don't have permission to view requests for this team.")
        return redirect('team_detail', pk=pk)
    pending = team.join_requests.filter(status='pending').order_by('created_at')
    return render(request, 'teams/requests.html', {'team': team, 'pending': pending})


@login_required
@require_role('coordinator', 'coach')
def review_join_request(request, pk, request_id):
    team = get_object_or_404(Team, pk=pk)
    jr = get_object_or_404(TeamJoinRequest, pk=request_id, team=team)
    role = get_role(request.user)
    if role == 'coach' and request.user not in team.coaches.all():
        messages.error(request, "You don't have permission to review requests for this team.")
        return redirect('team_detail', pk=pk)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'accept':
            team.players.add(jr.player)
            jr.status = 'accepted'
            jr.reviewed_at = timezone.now()
            jr.reviewed_by = request.user
            jr.save()
            send_notification(jr.player, 'Join Request Accepted', f'Your request to join {team.name} was accepted.', 'general')
            messages.success(request, f'{jr.player.username} added to the team.')
            # add to team conversation participants (create conversation if missing)
            try:
                conv, created = Conversation.objects.get_or_create(team=team, is_team=True, defaults={'title': f'{team.name} Team Chat'})
                ConversationParticipant.objects.get_or_create(conversation=conv, user=jr.player)
            except Exception:
                pass
        elif action == 'reject':
            jr.status = 'rejected'
            jr.reviewed_at = timezone.now()
            jr.reviewed_by = request.user
            jr.save()
            send_notification(jr.player, 'Join Request Rejected', f'Your request to join {team.name} was rejected.', 'general')
            messages.success(request, f'{jr.player.username} request rejected.')
    return redirect('team_join_requests', pk=pk)


@login_required
@require_role('player')
def leave_team(request, pk):
    team = get_object_or_404(Team, pk=pk)
    if request.method == 'POST':
        team.players.remove(request.user)
        messages.success(request, f'You left {team.name}.')
        # remove from team conversation participants
        try:
            conv = Conversation.objects.get(team=team, is_team=True)
            ConversationParticipant.objects.filter(conversation=conv, user=request.user).delete()
        except Conversation.DoesNotExist:
            pass
    return redirect('teams_list')


@login_required
@require_role('coordinator', 'coach')
def remove_player(request, pk, player_id):
    team = get_object_or_404(Team, pk=pk)
    player = get_object_or_404(User, pk=player_id)
    if request.method == 'POST':
        team.players.remove(player)
        messages.success(request, f'{player.username} removed from team.')
        # remove from team conversation participants
        try:
            conv = Conversation.objects.get(team=team, is_team=True)
            ConversationParticipant.objects.filter(conversation=conv, user=player).delete()
        except Conversation.DoesNotExist:
            pass
    return redirect('team_detail', pk=pk)


# ─── availability ─────────────────────────────────────────────────────────────

@login_required
@require_role('player')
def availability(request):
    days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    slots = ['morning', 'afternoon', 'evening']
    if request.method == 'POST':
        Availability.objects.filter(player=request.user).delete()
        for day in days:
            for slot in slots:
                if request.POST.get(f'{day}_{slot}'):
                    Availability.objects.create(player=request.user, day=day, slot=slot)
        messages.success(request, 'Availability updated.')
        return redirect('availability')
    user_avail = set(
        Availability.objects.filter(player=request.user).values_list('day', 'slot')
    )
    return render(request, 'availability.html', {
        'days': days, 'slots': slots, 'user_avail': user_avail
    })


@login_required
@require_role('coach', 'coordinator')
def team_availability(request, pk):
    team = get_object_or_404(Team, pk=pk)
    # only coaches of the team or coordinators can view
    if get_role(request.user) == 'coach' and team not in request.user.coached_teams.all():
        messages.error(request, "You don't have permission to view this team's availability.")
        return redirect('teams_list')

    days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    slots = ['morning', 'afternoon', 'evening']

    # Build a list of days each containing a list for each slot (morning/afternoon/evening)
    players = team.players.all()
    avail_grid = []
    for day in days:
        slot_lists = []
        for slot in slots:
            avails = Availability.objects.filter(day=day, slot=slot, player__in=players).select_related('player')
            slot_lists.append([a.player.username for a in avails])
        avail_grid.append({'day': day, 'slot_lists': slot_lists})

    return render(request, 'teams/availability.html', {
        'team': team, 'slots': slots, 'avail_grid': avail_grid
    })


# ─── sessions ─────────────────────────────────────────────────────────────────

@login_required
def sessions_list(request):
    role = get_role(request.user)
    if role == 'coordinator':
        sessions = Session.objects.all().order_by('date', 'start_time')
    elif role == 'coach':
        sessions = Session.objects.filter(
            team__in=request.user.coached_teams.all()
        ).order_by('date', 'start_time')
    else:
        sessions = Session.objects.filter(
            team__in=request.user.teams.all()
        ).order_by('date', 'start_time')
    return render(request, 'sessions/list.html', {'sessions': sessions, 'role': role})


@login_required
@require_role('coordinator', 'coach')
def session_create(request):
    role = get_role(request.user)
    if role == 'coach':
        teams = request.user.coached_teams.all()
    else:
        teams = Team.objects.all()
    courts = Court.objects.filter(is_active=True)

    if request.method == 'POST':
        team_id = request.POST.get('team')
        court_id = request.POST.get('court')
        title = request.POST.get('title')
        session_type = request.POST.get('session_type', 'training')
        date_str = request.POST.get('date')
        start_time = request.POST.get('start_time')
        end_time = request.POST.get('end_time')
        opponent = request.POST.get('opponent', '')
        notes = request.POST.get('notes', '')

        team = get_object_or_404(Team, pk=team_id)
        court = Court.objects.filter(pk=court_id).first()

        # conflict detection
        conflicts = Session.objects.filter(
            date=date_str, status='scheduled'
        ).filter(
            Q(court=court, court__isnull=False) |
            Q(team=team)
        ).filter(
            start_time__lt=end_time, end_time__gt=start_time
        )
        if conflicts.exists():
            conflict = conflicts.first()
            messages.error(request, f'Scheduling conflict detected with: {conflict.title} at {conflict.start_time}')
            return render(request, 'sessions/form.html', {
                'teams': teams, 'courts': courts, 'action': 'Create'
            })

        session = Session.objects.create(
            team=team, court=court, title=title, session_type=session_type,
            date=date_str, start_time=start_time, end_time=end_time,
            opponent=opponent, notes=notes, created_by=request.user
        )
        # notify players
        for player in team.players.all():
            send_notification(
                player, 'New Session Scheduled',
                f'{session.title} on {session.date} at {session.start_time}', 'session'
            )
        messages.success(request, 'Session created.')
        return redirect('session_detail', pk=session.pk)

    return render(request, 'sessions/form.html', {
        'teams': teams, 'courts': courts, 'action': 'Create'
    })


@login_required
def session_detail(request, pk):
    session = get_object_or_404(Session, pk=pk)
    role = get_role(request.user)
    attendances = session.attendances.select_related('player')
    return render(request, 'sessions/detail.html', {
        'session': session, 'role': role, 'attendances': attendances
    })


@login_required
@require_role('coordinator', 'coach')
def session_edit(request, pk):
    session = get_object_or_404(Session, pk=pk)
    role = get_role(request.user)
    if role == 'coach':
        teams = request.user.coached_teams.all()
    else:
        teams = Team.objects.all()
    courts = Court.objects.filter(is_active=True)

    if request.method == 'POST':
        session.title = request.POST.get('title')
        session.session_type = request.POST.get('session_type', 'training')
        session.date = request.POST.get('date')
        session.start_time = request.POST.get('start_time')
        session.end_time = request.POST.get('end_time')
        session.opponent = request.POST.get('opponent', '')
        session.notes = request.POST.get('notes', '')
        court_id = request.POST.get('court')
        session.court = Court.objects.filter(pk=court_id).first()
        session.save()
        messages.success(request, 'Session updated.')
        return redirect('session_detail', pk=pk)

    return render(request, 'sessions/form.html', {
        'session': session, 'teams': teams, 'courts': courts, 'action': 'Edit'
    })


@login_required
@require_role('coordinator', 'coach')
def session_delete(request, pk):
    session = get_object_or_404(Session, pk=pk)
    if request.method == 'POST':
        session.delete()
        messages.success(request, 'Session deleted.')
        return redirect('sessions_list')
    return render(request, 'sessions/confirm_delete.html', {'session': session})


@login_required
@require_role('coordinator', 'coach')
def manage_attendance(request, pk):
    session = get_object_or_404(Session, pk=pk)
    players = session.team.players.all()
    if request.method == 'POST':
        for player in players:
            status = request.POST.get(f'status_{player.pk}', 'absent')
            Attendance.objects.update_or_create(
                session=session, player=player,
                defaults={'status': status}
            )
        session.status = 'completed'
        session.save()
        messages.success(request, 'Attendance recorded.')
        return redirect('session_detail', pk=pk)
    existing = {a.player_id: a.status for a in session.attendances.all()}
    return render(request, 'sessions/attendance.html', {
        'session': session, 'players': players, 'existing': existing
    })


@login_required
@require_role('coach')
def ai_schedule(request):
    coached_teams = request.user.coached_teams.all()
    courts = Court.objects.filter(is_active=True)
    recommendation = None

    if request.method == 'POST':
        team_id = request.POST.get('team')
        date_from = request.POST.get('date_from')
        date_to = request.POST.get('date_to')
        prefer_morning = request.POST.get('prefer_morning') == 'on'
        prefer_afternoon = request.POST.get('prefer_afternoon') == 'on'
        prefer_evening = request.POST.get('prefer_evening') == 'on'
        avoid_bad_weather = request.POST.get('avoid_bad_weather') == 'on'
        selected_court_ids = request.POST.getlist('courts')

        team = get_object_or_404(Team, pk=team_id)
        selected_courts = Court.objects.filter(pk__in=selected_court_ids)

        # Get player availabilities
        players = team.players.all()
        avail_summary = {}
        for player in players:
            avails = Availability.objects.filter(player=player)
            for a in avails:
                key = f"{a.day}_{a.slot}"
                avail_summary[key] = avail_summary.get(key, 0) + 1

        # Get weather from Open-Meteo for the date range
        weather_info = "Weather data unavailable."
        try:
            weather_resp = requests.get(
                'https://api.open-meteo.com/v1/forecast',
                params={
                    'latitude': 33.8938, 'longitude': 35.5018,
                    'daily': 'precipitation_sum,weathercode',
                    'timezone': 'Asia/Beirut',
                    'start_date': date_from,
                    'end_date': date_to,
                },
                timeout=5
            )
            weather_data = weather_resp.json()
            daily = weather_data.get('daily', {})
            weather_lines = []
            for i, d in enumerate(daily.get('time', [])):
                code = daily['weathercode'][i]
                rain = daily['precipitation_sum'][i]
                cond = 'Rainy' if rain > 2 else ('Cloudy' if code > 2 else 'Clear')
                weather_lines.append(f"{d}: {cond}, precipitation {rain}mm")
            weather_info = '\n'.join(weather_lines)
        except Exception:
            pass

        # Build prompt for Claude
        court_list = '\n'.join([f"- {c.name} ({'Indoor' if c.court_type == 'indoor' else 'Outdoor'})" for c in selected_courts])
        avail_text = '\n'.join([f"- {k}: {v} players available" for k, v in sorted(avail_summary.items(), key=lambda x: -x[1])[:10]])

        # Include booked sessions summary for the date range so the LLM can avoid conflicts
        booked_lines = []
        try:
            for s in Session.objects.filter(date__gte=date_from, date__lte=date_to, status='scheduled').select_related('court'):
                booked_lines.append(f"- {s.date}: {s.start_time.strftime('%H:%M')}-{s.end_time.strftime('%H:%M')} on {s.court.name if s.court else 'TBD'}")
        except Exception:
            booked_lines = []

        prompt = f"""You are a volleyball scheduling assistant for VolleyLB, a Lebanese volleyball club.

Team: {team.name} ({players.count()} players)
Date Range: {date_from} to {date_to}
Preferences: {'Morning' if prefer_morning else ''} {'Afternoon' if prefer_afternoon else ''} {'Evening' if prefer_evening else ''}
Avoid bad weather: {avoid_bad_weather}

Available Courts:
{court_list}

Player Availability Summary (day_slot: number of players available):
{avail_text}

Weather Forecast for date range:
{weather_info}

Booked Sessions in date range:
{('\n'.join(booked_lines) if booked_lines else 'None')}

Analyze the above and recommend ONE optimal training session. Consider:
1. Maximum player attendance based on availability
2. Weather (avoid outdoor courts on rainy days if requested)
3. Court availability
4. Preferred time slots

Respond in this EXACT JSON format:
{{
  "date": "YYYY-MM-DD",
  "start_time": "HH:MM",
  "end_time": "HH:MM",
  "court": "Court Name",
  "reason": "Brief explanation of why this slot was chosen",
  "analysis_points": ["point 1", "point 2", "point 3"]
}}"""

        # Prefer using Anthropic if an API key is present, otherwise or on failure
        # fall back to a deterministic local scheduler to avoid dependence on paid LLMs.
        api_key = os.environ.get('ANTHROPIC_API_KEY', '')
        use_local = os.environ.get('USE_LOCAL_SCHEDULER', '') == '1' or not api_key

        if not use_local:
            try:
                client = anthropic.Anthropic(api_key=api_key)
                response = client.messages.create(
                    model='claude-sonnet-4-20250514',
                    max_tokens=1000,
                    messages=[{'role': 'user', 'content': prompt}]
                )
                text = response.content[0].text.strip()
                # extract JSON
                if '```' in text:
                    text = text.split('```')[1]
                    if text.startswith('json'):
                        text = text[4:]
                recommendation = json.loads(text)
            except Exception as e:
                # on any failure, log message and fall back to local planner
                messages.warning(request, f'AI scheduling (Anthropic) failed; using local scheduler.')
                use_local = True

        if use_local:
            # Build a simple deterministic scheduler:
            # - For each date in range and each slot (morning/afternoon/evening), count available players
            # - Exclude outdoor courts on rainy days if avoid_bad_weather is set
            # - Pick the date/slot/court with highest availability, prefer indoor courts when tied
            slot_times = {'morning': ('09:00', '11:00'), 'afternoon': ('15:00', '17:00'), 'evening': ('19:00', '21:00')}
            rainy_dates = set()
            try:
                daily = weather_data.get('daily', {}) if 'weather_data' in locals() else {}
                times = daily.get('time', [])
                prec = daily.get('precipitation_sum', [])
                for i, d in enumerate(times):
                    r = 0
                    try:
                        r = float(prec[i])
                    except Exception:
                        r = 0
                    if r > 2:
                        rainy_dates.add(d)
            except Exception:
                rainy_dates = set()

            def date_range(start_s, end_s):
                try:
                    s = datetime.strptime(start_s, '%Y-%m-%d').date()
                    e = datetime.strptime(end_s, '%Y-%m-%d').date()
                except Exception:
                    return []
                days = []
                cur = s
                while cur <= e:
                    days.append(cur)
                    cur += timedelta(days=1)
                return days

            considered_courts = list(selected_courts) if selected_courts.exists() else list(Court.objects.filter(is_active=True))
            team_size = team.players.count()

            best = None
            for d in date_range(date_from, date_to):
                d_str = d.isoformat()
                weekday = d.strftime('%A').lower()
                for slot in ['morning', 'afternoon', 'evening']:
                    avail_count = avail_summary.get(f"{weekday}_{slot}", 0)
                    # soft preference bonus if coach selected this slot
                    pref_bonus = 0
                    if (slot == 'morning' and prefer_morning) or (slot == 'afternoon' and prefer_afternoon) or (slot == 'evening' and prefer_evening):
                        pref_bonus = 0.2
                    for court in considered_courts:
                        if avoid_bad_weather and court.court_type == 'outdoor' and d_str in rainy_dates:
                            continue
                        # check for session conflicts on this court for the candidate slot
                        s_start, s_end = slot_times.get(slot, ('19:00', '21:00'))
                        conflict_exists = Session.objects.filter(
                            date=d,
                            status='scheduled',
                            court=court
                        ).filter(start_time__lt=s_end, end_time__gt=s_start).exists()
                        if conflict_exists:
                            continue
                        score = avail_count
                        score += pref_bonus
                        # small preference for indoor courts and sufficient capacity
                        if court.court_type == 'indoor':
                            score += 0.1
                        if court.capacity >= team_size:
                            score += 0.05
                        if best is None or score > best['score']:
                            best = {
                                'score': score,
                                'date': d_str,
                                'slot': slot,
                                'court': court,
                            }

            if best:
                start_time, end_time = slot_times.get(best['slot'], ('19:00', '21:00'))
                recommendation = {
                    'date': best['date'],
                    'start_time': start_time,
                    'end_time': end_time,
                    'court': best['court'].name,
                    'reason': f"Selected for highest player availability ({int(best['score'])} players) and court suitability.",
                    'analysis_points': [
                        f"{int(best['score'])} players available for {best['slot']}",
                        f"Court '{best['court'].name}' selected ({best['court'].court_type})"
                    ]
                }
            else:
                recommendation = None

    return render(request, 'sessions/ai_schedule.html', {
        'teams': coached_teams, 'courts': courts, 'recommendation': recommendation
    })


# ─── courts ───────────────────────────────────────────────────────────────────

@login_required
def courts_list(request):
    courts = Court.objects.all()
    role = get_role(request.user)
    return render(request, 'courts/list.html', {'courts': courts, 'role': role})


@login_required
@require_role('coordinator')
def court_create(request):
    if request.method == 'POST':
        Court.objects.create(
            name=request.POST.get('name'),
            location=request.POST.get('location'),
            court_type=request.POST.get('court_type', 'indoor'),
            capacity=request.POST.get('capacity', 20),
        )
        messages.success(request, 'Court created.')
        return redirect('courts_list')
    return render(request, 'courts/form.html', {'action': 'Create'})


@login_required
@require_role('coordinator')
def court_edit(request, pk):
    court = get_object_or_404(Court, pk=pk)
    if request.method == 'POST':
        court.name = request.POST.get('name')
        court.location = request.POST.get('location')
        court.court_type = request.POST.get('court_type', 'indoor')
        court.capacity = request.POST.get('capacity', 20)
        court.is_active = request.POST.get('is_active') == 'on'
        court.save()
        messages.success(request, 'Court updated.')
        return redirect('courts_list')
    return render(request, 'courts/form.html', {'court': court, 'action': 'Edit'})


@login_required
@require_role('coordinator')
def court_delete(request, pk):
    court = get_object_or_404(Court, pk=pk)
    if request.method == 'POST':
        court.delete()
        messages.success(request, 'Court deleted.')
        return redirect('courts_list')
    return render(request, 'courts/confirm_delete.html', {'court': court})


# ─── announcements ────────────────────────────────────────────────────────────

@login_required
def announcements_list(request):
    role = get_role(request.user)
    if role == 'coordinator':
        announcements = Announcement.objects.all().order_by('-created_at')
    elif role == 'coach':
        announcements = Announcement.objects.filter(
            Q(team__in=request.user.coached_teams.all()) | Q(scope='club')
        ).order_by('-created_at')
    else:
        announcements = Announcement.objects.filter(
            Q(team__in=request.user.teams.all()) | Q(scope='club')
        ).order_by('-created_at')
    return render(request, 'announcements/list.html', {'announcements': announcements, 'role': role})


@login_required
@require_role('coordinator', 'coach')
def announcement_create(request):
    role = get_role(request.user)
    if role == 'coach':
        teams = request.user.coached_teams.all()
    else:
        teams = Team.objects.all()

    if request.method == 'POST':
        title = request.POST.get('title')
        content = request.POST.get('content')
        scope = request.POST.get('scope', 'team')
        team_id = request.POST.get('team')
        team = Team.objects.filter(pk=team_id).first() if team_id else None

        ann = Announcement.objects.create(
            title=title, content=content, scope=scope,
            team=team, author=request.user
        )

        # notify
        if scope == 'club':
            recipients = User.objects.all()
        else:
            recipients = team.players.all() if team else User.objects.none()

        for u in recipients:
            send_notification(u, f'Announcement: {title}', content, 'announcement')

        messages.success(request, 'Announcement posted.')
        return redirect('announcements_list')

    return render(request, 'announcements/form.html', {'teams': teams, 'role': role})


# ─── notifications ────────────────────────────────────────────────────────────

@login_required
def notifications_list(request):
    notifs = Notification.objects.filter(recipient=request.user).order_by('-created_at')
    return render(request, 'notifications/list.html', {'notifications': notifs})


@login_required
def mark_notification_read(request, pk):
    notif = get_object_or_404(Notification, pk=pk, recipient=request.user)
    notif.is_read = True
    notif.save()
    return redirect('notifications_list')


@login_required
def mark_all_read(request):
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    return redirect('notifications_list')


# ─── fees ─────────────────────────────────────────────────────────────────────

@login_required
def fees_list(request):
    role = get_role(request.user)
    if role == 'coordinator':
        fees = Fee.objects.all().order_by('-created_at')
        return render(request, 'fees/list.html', {'fees': fees, 'role': role})
    else:
        player_fees = PlayerFee.objects.filter(player=request.user).select_related('fee').order_by('-fee__deadline')
        return render(request, 'fees/player_fees.html', {'player_fees': player_fees, 'role': role})


@login_required
@require_role('coordinator')
def fee_create(request):
    teams = Team.objects.all()
    if request.method == 'POST':
        fee = Fee.objects.create(
            name=request.POST.get('name'),
            amount=request.POST.get('amount'),
            late_fee_amount=request.POST.get('late_fee_amount', 0),
            deadline=request.POST.get('deadline'),
            # request.POST.get('team') may be an empty string if no team selected; handle safely
            team=(Team.objects.filter(pk=request.POST.get('team')).first() if request.POST.get('team') else None),
            created_by=request.user,
        )
        messages.success(request, f'Fee "{fee.name}" created.')
        return redirect('fee_detail', pk=fee.pk)
    return render(request, 'fees/form.html', {'teams': teams})


@login_required
@require_role('coordinator')
def fee_edit(request, pk):
    fee = get_object_or_404(Fee, pk=pk)
    teams = Team.objects.all()
    if request.method == 'POST':
        fee.name = request.POST.get('name')
        fee.amount = request.POST.get('amount')
        fee.late_fee_amount = request.POST.get('late_fee_amount', 0)
        fee.deadline = request.POST.get('deadline')
        fee.team = Team.objects.filter(pk=request.POST.get('team')).first() if request.POST.get('team') else None
        fee.save()
        messages.success(request, f'Fee "{fee.name}" updated.')
        return redirect('fee_detail', pk=fee.pk)
    return render(request, 'fees/form.html', {'teams': teams, 'fee': fee})


@login_required
@require_role('coordinator')
def fee_delete(request, pk):
    fee = get_object_or_404(Fee, pk=pk)
    if request.method == 'POST':
        fee.delete()
        messages.success(request, 'Fee deleted.')
        return redirect('fees_list')
    return render(request, 'fees/confirm_delete.html', {'fee': fee})


@login_required
@require_role('coordinator')
def fee_detail(request, pk):
    fee = get_object_or_404(Fee, pk=pk)
    player_fees = PlayerFee.objects.filter(fee=fee).select_related('player')
    all_players = User.objects.filter(profile__role='player').exclude(
        id__in=player_fees.values_list('player_id', flat=True)
    )
    return render(request, 'fees/detail.html', {
        'fee': fee, 'player_fees': player_fees, 'all_players': all_players
    })


@login_required
@require_role('coordinator')
def fee_assign(request, pk):
    fee = get_object_or_404(Fee, pk=pk)
    if request.method == 'POST':
        assign_type = request.POST.get('assign_type')
        if assign_type == 'team':
            team_id = request.POST.get('team_id')
            team = get_object_or_404(Team, pk=team_id)
            for player in team.players.all():
                pf, created = PlayerFee.objects.get_or_create(
                    fee=fee, player=player,
                    defaults={'amount_due': fee.amount, 'status': 'pending'}
                )
                if created:
                    send_notification(
                        player, 'New Fee Assigned',
                        f'You have been assigned fee: {fee.name} (${fee.amount}) due {fee.deadline}', 'payment'
                    )
        else:
            player_ids = request.POST.getlist('player_ids')
            for pid in player_ids:
                player = User.objects.filter(pk=pid).first()
                if player:
                    pf, created = PlayerFee.objects.get_or_create(
                        fee=fee, player=player,
                        defaults={'amount_due': fee.amount, 'status': 'pending'}
                    )
                    if created:
                        send_notification(
                            player, 'New Fee Assigned',
                            f'You have been assigned fee: {fee.name} (${fee.amount}) due {fee.deadline}', 'payment'
                        )
        messages.success(request, 'Fee assigned.')
    return redirect('fee_detail', pk=pk)


@login_required
def pay_fee(request, pk):
    pf = get_object_or_404(PlayerFee, pk=pk, player=request.user)
    if request.method == 'POST':
        pf.status = 'paid'
        pf.paid_at = timezone.now()
        pf.save()
        send_notification(
            request.user, 'Payment Confirmed',
            f'Your payment for "{pf.fee.name}" has been marked as paid.', 'payment'
        )
        messages.success(request, 'Payment marked as paid.')
    return redirect('fees_list')


@login_required
@require_role('coordinator')
def financial_summary(request):
    apply_late_fees()
    total_collected = PlayerFee.objects.filter(status='paid').aggregate(s=Sum('amount_due'))['s'] or 0
    total_pending = PlayerFee.objects.filter(status='pending').aggregate(s=Sum('amount_due'))['s'] or 0
    total_overdue = PlayerFee.objects.filter(status='overdue').aggregate(s=Sum('amount_due'))['s'] or 0
    fees = Fee.objects.all().order_by('-created_at')
    # include payouts summary
    paid_payouts = CoachEarning.objects.filter(paid=True).aggregate(s=Sum('amount'))['s'] or 0
    pending_payouts = CoachEarning.objects.filter(paid=False).aggregate(s=Sum('amount'))['s'] or 0
    payouts = CoachEarning.objects.select_related('coach', 'session', 'session__team').order_by('-session__date')

    return render(request, 'fees/summary.html', {
        'total_collected': total_collected,
        'total_pending': total_pending,
        'total_overdue': total_overdue,
        'fees': fees,
        'paid_payouts': paid_payouts,
        'pending_payouts': pending_payouts,
        'payouts': payouts,
    })


# ─── earnings ────────────────────────────────────────────────────────────────

@login_required
@require_role('coach')
def earnings_list(request):
    earnings = CoachEarning.objects.filter(coach=request.user).select_related('session').order_by('-session__date')
    total = earnings.aggregate(s=Sum('amount'))['s'] or 0
    paid_total = earnings.filter(paid=True).aggregate(s=Sum('amount'))['s'] or 0
    pending_total = earnings.filter(paid=False).aggregate(s=Sum('amount'))['s'] or 0
    return render(request, 'earnings/list.html', {
        'earnings': earnings, 'total': total,
        'paid_total': paid_total, 'pending_total': pending_total
    })


@login_required
@require_role('coordinator')
def payouts(request):
    """Coordinator payout management.

    Shows history of expected/paid/pending payouts. Training = $75 per coach per session.
    Match = $100 per coach for both teams (if opponent matches a Team name).
    """
    # helper to compute amount
    def payout_amount(session):
        return Decimal('100.00') if session.session_type == 'match' else Decimal('75.00')

    # collect existing earnings
    existing = list(CoachEarning.objects.select_related('session', 'coach').all())

    # map existing by (coach_id, session_id)
    existing_map = {(e.coach_id, e.session_id): e for e in existing}

    # consider sessions up to today (history) and recent future (include future if desired)
    sessions = Session.objects.order_by('-date')

    entries = []
    for s in sessions:
        # primary team coaches
        coaches = list(s.team.coaches.all())
        # if match and opponent corresponds to a Team name, include that team's coaches
        if s.session_type == 'match' and s.opponent:
            opp = Team.objects.filter(name__iexact=s.opponent).first()
            if opp:
                coaches += list(opp.coaches.all())

        # dedupe coaches
        seen = set()
        for coach in coaches:
            if coach.id in seen:
                continue
            seen.add(coach.id)
            key = (coach.id, s.id)
            if key in existing_map:
                e = existing_map[key]
                entries.append({
                    'type': 'existing', 'earning': e, 'session': s, 'coach': coach,
                    'amount': e.amount, 'paid': e.paid
                })
            else:
                amt = payout_amount(s)
                entries.append({
                    'type': 'expected', 'session': s, 'coach': coach,
                    'amount': amt, 'paid': False
                })

    # sort entries by session date desc
    entries.sort(key=lambda x: x['session'].date if x.get('session') else date.min, reverse=True)

    if request.method == 'POST':
        selected = request.POST.getlist('entry')
        now = timezone.now()
        processed = 0
        for val in selected:
            # val formats: existing:<earning_pk> OR expected:<session_id>:<coach_id>
            parts = val.split(':')
            if parts[0] == 'existing' and len(parts) == 2:
                try:
                    ce = CoachEarning.objects.get(pk=int(parts[1]))
                except Exception:
                    continue
                if not ce.paid:
                    ce.paid = True
                    ce.paid_at = now
                    ce.save()
                    send_notification(ce.coach, 'Payout Processed', f'Your earning for "{ce.session.title}" was paid by the coordinator.', 'payment')
                    processed += 1
            elif parts[0] == 'expected' and len(parts) == 3:
                try:
                    sid = int(parts[1]); cid = int(parts[2])
                except Exception:
                    continue
                # check again that no earning exists
                if CoachEarning.objects.filter(coach_id=cid, session_id=sid).exists():
                    continue
                sess = Session.objects.filter(pk=sid).first()
                coach = User.objects.filter(pk=cid).first()
                if not sess or not coach:
                    continue
                amt = payout_amount(sess)
                ce = CoachEarning.objects.create(coach=coach, session=sess, amount=amt, paid=True, paid_at=now)
                send_notification(coach, 'Payout Processed', f'Your earning for "{sess.title}" was paid by the coordinator.', 'payment')
                processed += 1

        messages.success(request, f'{processed} payouts processed.')
        return redirect('payouts')

    return render(request, 'earnings/payouts.html', {'entries': entries})


@login_required
@require_role('coordinator')
def payout_edit(request, pk):
    ce = get_object_or_404(CoachEarning, pk=pk)
    if request.method == 'POST':
        amount = request.POST.get('amount')
        paid = request.POST.get('paid') == 'on'
        try:
            ce.amount = Decimal(amount)
        except Exception:
            messages.error(request, 'Invalid amount.')
            return render(request, 'earnings/edit_payout.html', {'earning': ce})

        if paid and not ce.paid:
            ce.paid = True
            ce.paid_at = timezone.now()
        elif not paid and ce.paid:
            ce.paid = False
            ce.paid_at = None

        ce.save()
        send_notification(ce.coach, 'Payout Updated', f'Your payout for "{ce.session.title}" was updated by the coordinator.', 'payment')
        messages.success(request, 'Payout updated.')
        return redirect('payouts')

    return render(request, 'earnings/edit_payout.html', {'earning': ce})


@login_required
@require_role('coordinator')
def payout_delete(request, pk):
    ce = get_object_or_404(CoachEarning, pk=pk)
    if request.method == 'POST':
        ce.delete()
        messages.success(request, 'Payout removed.')
        return redirect('payouts')
    return render(request, 'earnings/confirm_delete_payout.html', {'earning': ce})


@login_required
@require_role('coordinator')
def payout_record(request, session_id, coach_id):
    """Create a recorded (unpaid) CoachEarning for an expected entry."""
    sess = get_object_or_404(Session, pk=session_id)
    coach = get_object_or_404(User, pk=coach_id)

    # compute default amount
    amt = Decimal('100.00') if sess.session_type == 'match' else Decimal('75.00')

    # avoid duplicate
    ce, created = CoachEarning.objects.get_or_create(
        coach=coach, session=sess,
        defaults={'amount': amt, 'paid': False}
    )
    if created:
        messages.success(request, 'Payout recorded.')
    else:
        messages.info(request, 'Payout already exists.')
    return redirect('payouts')


# ─── users ────────────────────────────────────────────────────────────────────

@login_required
@require_role('coordinator')
def users_list(request):
    users = User.objects.select_related('profile').all().order_by('profile__role', 'username')
    return render(request, 'users/list.html', {'users': users})


@login_required
@require_role('coordinator')
def user_edit(request, pk):
    target = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        target.first_name = request.POST.get('first_name', '')
        target.last_name = request.POST.get('last_name', '')
        target.email = request.POST.get('email', '')
        target.save()
        profile = target.profile
        profile.role = request.POST.get('role', profile.role)
        profile.jersey_number = request.POST.get('jersey_number') or None
        profile.position = request.POST.get('position', '')
        profile.save()
        messages.success(request, 'User updated.')
        return redirect('users_list')
    return render(request, 'users/edit.html', {'target': target})
