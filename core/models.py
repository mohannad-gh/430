from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class UserProfile(models.Model):
    ROLE_CHOICES = [
        ('coordinator', 'Coordinator'),
        ('coach', 'Coach'),
        ('player', 'Player'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='player')
    phone = models.CharField(max_length=20, blank=True)
    jersey_number = models.IntegerField(null=True, blank=True)
    position = models.CharField(max_length=50, blank=True)

    def __str__(self):
        return f"{self.user.username} ({self.role})"


class Court(models.Model):
    COURT_TYPE = [('indoor', 'Indoor'), ('outdoor', 'Outdoor')]
    name = models.CharField(max_length=100)
    location = models.CharField(max_length=200)
    court_type = models.CharField(max_length=10, choices=COURT_TYPE, default='indoor')
    capacity = models.IntegerField(default=20)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Team(models.Model):
    name = models.CharField(max_length=100)
    coordinator = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='coordinated_teams')
    coaches = models.ManyToManyField(User, related_name='coached_teams', blank=True)
    players = models.ManyToManyField(User, related_name='teams', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class TeamJoinRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
    ]

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='join_requests')
    player = models.ForeignKey(User, on_delete=models.CASCADE, related_name='team_join_requests')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='reviewed_join_requests')

    class Meta:
        unique_together = ('team', 'player')

    def __str__(self):
        return f"{self.player.username} -> {self.team.name} ({self.status})"


class TeamLeaveRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
    ]

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='leave_requests')
    player = models.ForeignKey(User, on_delete=models.CASCADE, related_name='team_leave_requests')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='reviewed_leave_requests')

    class Meta:
        unique_together = ('team', 'player')

    def __str__(self):
        return f"{self.player.username} <- {self.team.name} ({self.status})"


class Availability(models.Model):
    DAY_CHOICES = [
        ('monday', 'Monday'), ('tuesday', 'Tuesday'), ('wednesday', 'Wednesday'),
        ('thursday', 'Thursday'), ('friday', 'Friday'), ('saturday', 'Saturday'), ('sunday', 'Sunday'),
    ]
    SLOT_CHOICES = [('morning', 'Morning'), ('afternoon', 'Afternoon'), ('evening', 'Evening')]

    player = models.ForeignKey(User, on_delete=models.CASCADE, related_name='availabilities')
    day = models.CharField(max_length=10, choices=DAY_CHOICES)
    slot = models.CharField(max_length=10, choices=SLOT_CHOICES)

    class Meta:
        unique_together = ('player', 'day', 'slot')

    def __str__(self):
        return f"{self.player.username} - {self.day} {self.slot}"


class Session(models.Model):
    SESSION_TYPE = [('training', 'Training'), ('match', 'Match')]
    STATUS_CHOICES = [('scheduled', 'Scheduled'), ('completed', 'Completed'), ('cancelled', 'Cancelled')]

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='sessions')
    court = models.ForeignKey(Court, on_delete=models.SET_NULL, null=True, blank=True, related_name='sessions')
    session_type = models.CharField(max_length=10, choices=SESSION_TYPE, default='training')
    title = models.CharField(max_length=200)
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='scheduled')
    opponent = models.CharField(max_length=100, blank=True)  # for matches
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_sessions')
    ai_generated = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.title} - {self.date}"


class Attendance(models.Model):
    STATUS_CHOICES = [('present', 'Present'), ('absent', 'Absent'), ('late', 'Late')]
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name='attendances')
    player = models.ForeignKey(User, on_delete=models.CASCADE, related_name='attendances')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='absent')
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        unique_together = ('session', 'player')

    def __str__(self):
        return f"{self.player.username} - {self.session.title} - {self.status}"


class Announcement(models.Model):
    SCOPE_CHOICES = [('team', 'Team'), ('club', 'Club-wide')]
    title = models.CharField(max_length=200)
    content = models.TextField()
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='announcements')
    team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name='announcements')
    scope = models.CharField(max_length=10, choices=SCOPE_CHOICES, default='team')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class Notification(models.Model):
    TYPE_CHOICES = [
        ('payment', 'Payment'), ('session', 'Session'), ('announcement', 'Announcement'), ('general', 'General')
    ]
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=200)
    message = models.TextField()
    notif_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='general')
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.recipient.username} - {self.title}"


class Fee(models.Model):
    STATUS_CHOICES = [('pending', 'Pending'), ('paid', 'Paid'), ('overdue', 'Overdue')]
    name = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    late_fee_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    deadline = models.DateField()
    team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_fees')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class PlayerFee(models.Model):
    STATUS_CHOICES = [('pending', 'Pending'), ('paid', 'Paid'), ('overdue', 'Overdue')]
    fee = models.ForeignKey(Fee, on_delete=models.CASCADE, related_name='player_fees')
    player = models.ForeignKey(User, on_delete=models.CASCADE, related_name='player_fees')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    amount_due = models.DecimalField(max_digits=10, decimal_places=2)
    late_fee_applied = models.BooleanField(default=False)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('fee', 'player')

    def __str__(self):
        return f"{self.player.username} - {self.fee.name} - {self.status}"


class CoachEarning(models.Model):
    coach = models.ForeignKey(User, on_delete=models.CASCADE, related_name='earnings')
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name='earnings')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    paid = models.BooleanField(default=False)
    paid_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.coach.username} - {self.session.title} - ${self.amount}"
