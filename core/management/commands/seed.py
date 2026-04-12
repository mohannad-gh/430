from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import date, time, timedelta
from decimal import Decimal
from core.models import UserProfile, Team, Court, Session, Fee, PlayerFee, Availability, Announcement, Notification, CoachEarning


class Command(BaseCommand):
    help = 'Seed demo data'

    def handle(self, *args, **kwargs):
        self.stdout.write('Seeding demo data...')

        def make_user(username, first, last, role, password='demo1234'):
            u, created = User.objects.get_or_create(username=username, defaults={
                'first_name': first, 'last_name': last, 'email': f'{username}@volleylb.com'
            })
            if created:
                u.set_password(password)
                u.save()
            UserProfile.objects.get_or_create(user=u, defaults={'role': role})
            return u

        coord = make_user('coord1', 'Karim', 'Haddad', 'coordinator')
        coach1 = make_user('coach1', 'Marc', 'Khoury', 'coach')
        coach2 = make_user('coach2', 'Sarah', 'Makki', 'coach')
        p1 = make_user('riley', 'Riley', 'Zoghby', 'player')
        p2 = make_user('taylor', 'Taylor', 'Mourad', 'player')
        p3 = make_user('jessy', 'Jessy', 'Samaha', 'player')
        p4 = make_user('mira', 'Mira', 'Farran', 'player')
        p5 = make_user('jana', 'Jana', 'Tabet', 'player')
        p6 = make_user('zeinab', 'Zeinab', 'Hajj', 'player')

        for p, num, pos in [(p1, 1, 'Libero'), (p2, 4, 'Outside'), (p3, 7, 'Opposite'), (p4, 8, 'Middle'), (p5, 12, 'Setter'), (p6, 23, 'Middle')]:
            prof = p.profile
            prof.jersey_number = num
            prof.position = pos
            prof.save()

        c1, _ = Court.objects.get_or_create(name='Main Sports Hall', defaults={'location': 'Beirut Sports City', 'court_type': 'indoor', 'capacity': 24})
        c2, _ = Court.objects.get_or_create(name='Tyre Court', defaults={'location': 'Tyre, South Lebanon', 'court_type': 'indoor', 'capacity': 20})
        c3, _ = Court.objects.get_or_create(name='Manara Court', defaults={'location': 'Manara, Beirut', 'court_type': 'outdoor', 'capacity': 16})
        c4, _ = Court.objects.get_or_create(name='Dahyeh Court', defaults={'location': 'Dahyeh, South Beirut', 'court_type': 'outdoor', 'capacity': 18})

        team1, _ = Team.objects.get_or_create(name='Beirut Eagles', defaults={'coordinator': coord, 'description': 'Main competitive team'})
        team1.coaches.add(coach1)
        team1.players.add(p1, p2, p3, p4, p5, p6)

        team2, _ = Team.objects.get_or_create(name='Hamra Lions', defaults={'coordinator': coord, 'description': 'Development team'})
        team2.coaches.add(coach2)

        today = date.today()
        for player, days in [
            (p1, [('monday', 'evening'), ('wednesday', 'evening'), ('friday', 'afternoon')]),
            (p2, [('tuesday', 'evening'), ('thursday', 'evening'), ('saturday', 'morning')]),
            (p3, [('monday', 'evening'), ('wednesday', 'evening'), ('friday', 'evening')]),
            (p4, [('monday', 'afternoon'), ('wednesday', 'afternoon'), ('saturday', 'morning')]),
            (p5, [('tuesday', 'morning'), ('thursday', 'evening'), ('saturday', 'evening')]),
            (p6, [('monday', 'evening'), ('thursday', 'evening'), ('sunday', 'morning')]),
        ]:
            for day, slot in days:
                Availability.objects.get_or_create(player=player, day=day, slot=slot)

        sessions_data = [
            ('Morning Training', 'training', today + timedelta(days=2), time(7, 0), time(9, 0), c1, team1),
            ('Evening Drill', 'training', today + timedelta(days=4), time(18, 0), time(20, 0), c2, team1),
            ('Beirut Eagles vs Hamra Lions', 'match', today + timedelta(days=7), time(16, 0), time(18, 0), c3, team1),
            ('Tyre Invitational', 'match', today + timedelta(days=10), time(14, 0), time(16, 0), c2, team1),
            ('Past Training', 'training', today - timedelta(days=5), time(18, 0), time(20, 0), c1, team1),
        ]
        for title, stype, d, st, et, court, team in sessions_data:
            Session.objects.get_or_create(title=title, date=d, defaults={
                'session_type': stype, 'start_time': st, 'end_time': et,
                'court': court, 'team': team, 'created_by': coach1,
                'status': 'completed' if d < today else 'scheduled'
            })

        Announcement.objects.get_or_create(
            title='Welcome to VolleyLB!',
            defaults={'content': 'Season 2026 has officially kicked off. Training starts this week. Make sure to update your availability!', 'author': coord, 'scope': 'club'}
        )
        Announcement.objects.get_or_create(
            title='Beirut Eagles — New Match Added',
            defaults={'content': 'We have a match against Hamra Lions next week. Attendance is mandatory. Coach Marc.', 'author': coach1, 'scope': 'team', 'team': team1}
        )

        fee1, _ = Fee.objects.get_or_create(name='Spring 2026 Registration', defaults={
            'amount': Decimal('150.00'), 'late_fee_amount': Decimal('25.00'),
            'deadline': today + timedelta(days=14), 'created_by': coord, 'team': team1
        })
        for player, status in [(p1, 'paid'), (p2, 'paid'), (p3, 'pending'), (p4, 'overdue'), (p5, 'pending'), (p6, 'pending')]:
            pf, _ = PlayerFee.objects.get_or_create(fee=fee1, player=player, defaults={
                'amount_due': Decimal('175.00') if status == 'overdue' else Decimal('150.00'),
                'status': status, 'late_fee_applied': status == 'overdue'
            })
            if status == 'paid' and not pf.paid_at:
                pf.paid_at = timezone.now() - timedelta(days=3)
                pf.save()

        sessions_completed = Session.objects.filter(team=team1, status='completed')
        for s in sessions_completed:
            CoachEarning.objects.get_or_create(coach=coach1, session=s, defaults={
                'amount': Decimal('75.00'), 'paid': True, 'paid_at': timezone.now() - timedelta(days=2)
            })

        Notification.objects.get_or_create(
            recipient=p3, title='Payment Reminder',
            defaults={'message': 'Your Spring 2026 Registration fee of $150 is due in 14 days.', 'notif_type': 'payment'}
        )
        Notification.objects.get_or_create(
            recipient=p4, title='Payment Overdue',
            defaults={'message': 'Your Spring 2026 Registration is overdue. A late fee of $25 has been applied.', 'notif_type': 'payment'}
        )

        self.stdout.write(self.style.SUCCESS('''
Coordinator : coord1 / demo1234
Coach       : coach1 / demo1234
Coach       : coach2 / demo1234
Player      : riley  / demo1234
Player      : jessy  / demo1234
Done!
'''))
