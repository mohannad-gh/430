# VolleyLB — Club Management System

A Django app for managing a Lebanese volleyball club. Covers all Sprint 1 & 2 user stories.

## Quick Start

### 1. Install dependencies
```bash
pip install django anthropic requests
```

### 2. Set your Anthropic API key (for AI scheduling)
```bash
export ANTHROPIC_API_KEY=your_key_here
```

### 3. Run migrations
```bash
python manage.py migrate
```

### 4. Seed demo data
```bash
python manage.py seed
```

### 5. Run the server
```bash
python manage.py runserver
```

Open http://127.0.0.1:8000

---

## Demo Credentials

| Role        | Username | Password  |
|-------------|----------|-----------|
| Coordinator | coord1   | demo1234  |
| Coach       | coach1   | demo1234  |
| Coach       | coach2   | demo1234  |
| Player      | riley    | demo1234  |
| Player      | taylor   | demo1234  |
| Player      | jessy    | demo1234  |
| Player      | mira     | demo1234  |
| Player      | jana     | demo1234  |
| Player      | zeinab   | demo1234  |

---

## Features Covered

### Management
- ✅ Role-based dashboards (Coordinator, Coach, Player)
- ✅ Coordinator creates and manages teams
- ✅ Coordinator assigns coaches to teams
- ✅ Coach manages team roster
- ✅ Player joins / leaves a team
- ✅ Player sees team members
- ✅ Coordinator manages courts/venues
- ✅ Coordinator manages user roles

### Scheduling
- ✅ Player sets weekly availability
- ✅ Coach creates training sessions and matches
- ✅ Coordinator assigns courts to sessions
- ✅ Conflict detection (time, court, team)
- ✅ Coach tracks attendance history
- ✅ Player views personal schedule
- ✅ AI Smart Scheduling (Claude API + Open-Meteo weather)

### Communication & Messaging
- ✅ Coach sends team announcements
- ✅ Coordinator broadcasts club-wide messages
- ✅ In-app notification system
- ✅ **Private & Team Chat**: Real-time messaging with read receipts, typing indicators, and muting.

### Performance Insights
- ✅ **Game Statistics**: Coach records serving, blocking, defense, and attack after matches.
- ✅ **Time Frame Analysis**: Filter performance data by specific dates.
- ✅ **Player History**: Players can view their individual performance trends.
- ✅ **Comparative Analysis**: Quantitative percentage change between two time periods.
- ✅ **Individual Deep-dive**: Filter stats by specific player or specific metric.
- ✅ **Personalized Recommendations**: Coaches send targeted training advice to players.

### Finance (Coordinator)
- ✅ Define registration fees
- ✅ Assign fees to players/teams
- ✅ Set payment deadlines
- ✅ View payment statuses (paid/pending/overdue)
- ✅ Auto late fee application
- ✅ Financial summary dashboard
- ✅ **Coach Payouts**: Automated calculation of earnings ($75/training, $100/match).

### Finance (Player)
- ✅ View fees and payment status
- ✅ Mark fee as paid
- ✅ Payment history
- ✅ Notifications for upcoming/overdue payments

### Finance (Coach)
- ✅ View earnings per session
- ✅ Total earnings over time
- ✅ Payout history
- ✅ Payment notifications

---

## Tech Stack
- **Backend**: Django 4+
- **Database**: SQLite (dev)
- **AI**: Anthropic Claude API (sonnet-4)
- **Weather**: Open-Meteo (no API key needed)
- **Frontend**: Django templates, custom CSS (no JS frameworks)
- **Fonts**: Bebas Neue + Rajdhani (Google Fonts)
