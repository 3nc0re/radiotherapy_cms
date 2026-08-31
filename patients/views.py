from django.shortcuts import render, get_object_or_404, redirect
from .models import Patient, FractionHistory, MedicalIncapacity, User, TreatmentProtocol
from .forms import PatientForm, FractionHistoryForm, MedicalIncapacityForm, UserRegistrationForm, UserLoginForm, FractionEditForm
from django.http import JsonResponse
from datetime import date, timedelta
from django.contrib.auth import login, logout, authenticate
from django.contrib import messages
from django.db.models import Q, Count, Max, F, DateField, Prefetch
from django.db.models.functions import Coalesce
from django.db import models
from django.utils import timezone
from .services import generate_fractions_for_patient, auto_confirm_today_fractions, get_patient_treatment_info
from django.views.decorators.csrf import csrf_exempt
import json
from django.views.decorators.http import require_POST
from .decorators import login_required, staff_required, admin_required
import os
from typing import Optional, List
from django.conf import settings

# Create your views here.

def splash(request):
    """Головна сторінка - перенаправляє на дашборд або логін"""
    if request.user.is_authenticated:
        return redirect('dashboard')
    else:
        return redirect('login')


def get_pending_mvtn_staging_patients(today=None):
    """
    Повертає список пацієнтів для контролю МВТН:
    1. Пацієнти, які досягли КТ чи початку лікування, але ще не мають рішення по МВТН (відстійник первинного МВТН).
    2. Пацієнти, у яких МВТН відкритий, але його дата закінчення не покриває термін виписки (потрібно продовжити в МІС).
    """
    if today is None:
        today = timezone.localdate()
        
    active_q = Q(is_active=True, mis_discharged=False) & (Q(discharge_date__isnull=True) | Q(discharge_date__gte=today))
    stage_q = Q(ct_simulation_date__isnull=False) | Q(treatment_start_date__isnull=False)
    
    candidates = Patient.objects.filter(active_q).filter(stage_q).prefetch_related('medical_incapacities', 'fractions')
    
    pending = []
    for p in candidates:
        incapacities = list(p.medical_incapacities.all())
        
        no_emp = any(inc.no_employment_relation is True for inc in incapacities)
        if no_emp:
            continue
            
        valid_incapacities = [inc for inc in incapacities if inc.end_date is not None]
        actual_discharge = p.get_actual_discharge_date or p.discharge_date
        
        if not valid_incapacities:
            ref_date = p.treatment_start_date or p.ct_simulation_date
            days_passed = (today - ref_date).days if ref_date else 0
            is_critical = days_passed >= 4
            default_start_date = p.treatment_start_date or p.ct_simulation_date
            
            pending.append({
                'patient': p,
                'type': 'new_staging',
                'ref_date': ref_date,
                'days_passed': max(0, days_passed),
                'days_until_exp': None,
                'is_critical': is_critical,
                'default_start_date': default_start_date.strftime('%d.%m.%Y') if default_start_date else '',
                'stage_label': 'Початок лікування' if p.treatment_start_date else 'КТ-симуляція',
                'status_title': 'Потребує первинного рішення щодо МВТН',
                'current_incapacity_end': None,
                'actual_discharge': actual_discharge
            })
        else:
            latest_inc = max(valid_incapacities, key=lambda x: x.end_date)
            if actual_discharge and actual_discharge > latest_inc.end_date:
                days_until_exp = (latest_inc.end_date - today).days
                is_critical = days_until_exp <= 3
                days_passed = (today - latest_inc.end_date).days if today > latest_inc.end_date else 0
                
                pending.append({
                    'patient': p,
                    'type': 'extension_needed',
                    'ref_date': latest_inc.end_date,
                    'days_passed': max(0, days_passed),
                    'days_until_exp': days_until_exp,
                    'is_critical': is_critical,
                    'default_start_date': (latest_inc.end_date + timedelta(days=1)).strftime('%d.%m.%Y'),
                    'stage_label': 'МВТН не покриває курс',
                    'status_title': f'МВТН діє до {latest_inc.end_date.strftime("%d.%m.%Y")}, виписка {actual_discharge.strftime("%d.%m.%Y")}',
                    'current_incapacity_end': latest_inc.end_date,
                    'actual_discharge': actual_discharge
                })

    pending.sort(key=lambda x: (0 if x['is_critical'] else 1, -x['days_passed']))
    return pending


@login_required
def mvtn_control_list(request):
    """Окрема вкладка "Контроль МВТН" із переліком пацієнтів, які потребують відкриття або продовження МВТН"""
    today = timezone.localdate()
    search_query = request.GET.get('q', '').strip()
    
    items = get_pending_mvtn_staging_patients(today)
    
    if search_query:
        items = [
            i for i in items if (
                search_query.lower() in i['patient'].last_name.lower() or
                search_query.lower() in i['patient'].first_name.lower() or
                (i['patient'].middle_name and search_query.lower() in i['patient'].middle_name.lower())
            )
        ]
        
    critical_count = sum(1 for i in items if i['is_critical'])
    new_staging_count = sum(1 for i in items if i['type'] == 'new_staging')
    extension_count = sum(1 for i in items if i['type'] == 'extension_needed')
    
    return render(request, 'patients/mvtn_control_list.html', {
        'items': items,
        'today': today,
        'search_query': search_query,
        'total_count': len(items),
        'critical_count': critical_count,
        'new_staging_count': new_staging_count,
        'extension_count': extension_count,
    })


@login_required
def dashboard(request):
    today = timezone.localdate()
    # Автоматично деактивуємо тільки тих пацієнтів, чиє лікування закінчилося І які вже були виписані в МІС
    Patient.objects.filter(is_active=True, mis_discharged=True, discharge_date__lt=today).update(is_active=False)
    
    # Список щоденних мотивуючих фраз та медичного гумору (37 цитат)
    quotes = [
        "💡 Папір усе стерпить. Клінічний аудит — ні.",
        "💡 Не записав у картку — отже, пацієнт здоровий, а ти нічого не робив.",
        "💡 Найкраща медична документація — ця, яку не доведеться пояснювати прокурору.",
        "💡 Тиха ніч — це не везіння, це просто черговий ще не дізнався, що ти на зміні.",
        "💡 Лікар не скаржиться. Лікар мовчки пише.",
        "💡 Променева терапія — це мистецтво точності та терпіння.",
        "💡 Крок за кроком, фракція за фракцією — до повної ремісії.",
        "💡 Успіх лікування залежить від майстерності лікаря та волі пацієнта.",
        "💡 Точність планування КТ — запорука успішної радіотерапії.",
        "💡 OAR — це не просто кольорові плями на КТ, це чиєсь нормальне життя після лікування.",
        "💡 Якщо органу ризику не видно на КТ, це не означає, що лінійник про нього забуде.",
        "💡 Міліметр ліворуч, міліметр праворуч — і замість радикального курсу маємо екстрену зустріч із суміжниками.",
        "💡 Складний контуринг розвиває дрібну моторику, просторове мислення та хронічний брак часу.",
        "💡 Ізодози як люди: найважливіші завжди знаходяться під найбільшим тиском.",
        "💡 «Google сказав, що мені залишилося тиждень» — найкращий зачин для первинного прийому.",
        "💡 Усі пацієнти унікальні, але відмовитися від розмітки КТ намагаються однаково.",
        "💡 Скептицизм пацієнта зникає приблизно на 5-й фракції.",
        "💡 Добре спланований робочий день триває до першого непрофільного пацієнта «просто запитати».",
        "💡 Найсильніша седація для пацієнта — це спокійний голос лікаря, який сам виспався (міф).",
        "💡 Контуринг без компромісів: мінімум на OAR, максимум на CTV.",
        "💡 Градієнт має значення. Точність у кожному міліметрі.",
        "💡 Якісний план сьогодні — якісне життя пацієнта завтра.",
        "💡 Автоматизуй те, що можна, приділи увагу тому, що важливо — пацієнту.",
        "💡 Доказова медицина, чіткий протокол, нуль випадковостей.",
        "💡 Медична документація — це не бюрократія, це юридичний та клінічний захист.",
        "💡 Добре описаний анамнез заощаджує час на консиліумі.",
        "💡 Лікар не скаржиться. Лікар мовчки пише.",
        "💡 Променева терапія — це мистецтво точності та терпіння.",
        "💡 Крок за кроком, фракція за фракцією — до повної ремісії.",
        "💡 Успіх лікування залежить від майстерності лікаря та волі пацієнта.",
        "💡 Точність планування КТ — запорука успішної радіотерапії.",
        "💡 Найкращий спосіб передбачити майбутнє — створити його разом із пацієнтом.",
        "💡 Справжній лікар лікує не хворобу, а людину.",
        "💡 Терпіння та праця долають найскладніші клінічні виклики.",
        "💡 Турбота та професіоналізм — ліки без побічних ефектів.",
        "💡 Де закінчується точність розмітки, там починається випадковість. Ми обираємо точність.",
        "💡 Папір усе стерпить, але медична карта — це документ про людське життя.",
        "💡 Промінь надії завжди має правильну геометрію та точне дозування.",
        "💡 Радіаційний онколог бачить світ крізь призму ізодоз та віри в результат.",
        "💡 У медицині немає дрібниць — особливо в контурингу та розрахунку СОД.",
        "💡 Наша робота — це тиха боротьба, де кожна успішна фракція наближає одужання."
    ]
    # Вибираємо цитату дня на основі дня року
    day_of_year = today.timetuple().tm_yday
    quote_of_the_day = quotes[day_of_year % len(quotes)]
    
    tomorrow = today + timedelta(days=1)
    
    ct_today_count = Patient.objects.filter(ct_simulation_date=today, is_active=True).count()
    start_today_count = Patient.objects.filter(treatment_start_date=today, is_active=True).count()
    
    active_patients_q = Q(is_active=True) & (Q(discharge_date__isnull=True) | Q(discharge_date__gte=today))
    
    # Виписки (сьогодні/завтра): використовуємо discharge_date як фолбек замість treatment_start_date
    discharge_today_count = Patient.objects.filter(active_patients_q).annotate(
        actual_discharge_date=Coalesce(
            Max('fractions__date'),
            F('discharge_date'),
            output_field=DateField()
        )
    ).filter(
        actual_discharge_date__in=[today, tomorrow]
    ).count()
    
    ct_count = Patient.objects.filter(ct_simulation_date__isnull=False, treatment_start_date__isnull=True, is_active=True).count()
    start_count = Patient.objects.filter(treatment_start_date__isnull=False, treatment_start_date__gt=today, is_active=True).count()
    in_treatment_count = Patient.objects.filter(treatment_start_date__isnull=False, treatment_start_date__lte=today, is_active=True).filter(active_patients_q).count()
    
    notifications = []
    active_patients = Patient.objects.filter(active_patients_q).prefetch_related(
        Prefetch(
            'medical_incapacities',
            queryset=MedicalIncapacity.objects.order_by('-end_date'),
            to_attr='prefetched_incapacities'
        ),
        'fractions'
    )
    
    for patient in active_patients:
        # Blood test check
        if patient.is_in_treatment:
            due_date = patient.next_blood_test_due_date
            if due_date:
                trigger_date = due_date - timedelta(days=1) if patient.has_radiomodification else due_date
                if today >= trigger_date:
                    notifications.append({
                        'type': 'blood_test',
                        'patient': patient,
                        'due_date': due_date
                    })
        
        # MVTN/Incapacity check: сповіщення лише за 3 дні до закінчення МВТН, якщо вона не покриває курс
        incapacity = patient.prefetched_incapacities[0] if hasattr(patient, 'prefetched_incapacities') and patient.prefetched_incapacities else None
        if incapacity and incapacity.end_date and incapacity.end_date >= today:
            actual_end = patient.get_actual_discharge_date
            incapacity_end = incapacity.end_date
            days_to_exp = (incapacity_end - today).days
            
            if days_to_exp <= 3 and actual_end and actual_end > incapacity_end:
                actual_end_str = actual_end.strftime('%d.%m.%Y') if actual_end else '—'
                incapacity_end_str = incapacity_end.strftime('%d.%m.%Y')
                message = f"⚠️ У пацієнта {patient.full_name} МВТН закінчується через {days_to_exp} дн. ({incapacity_end_str}) і не покриває курс лікування (завершення: {actual_end_str})! Потрібно продовжити в МІС."
                notifications.append({
                    'type': 'incapacity_alert',
                    'patient': patient,
                    'message': message,
                    'incapacity_end_date': incapacity_end,
                    'actual_discharge_date': actual_end
                })
                
    notifications.sort(key=lambda n: 0 if n['type'] == 'incapacity_alert' else 1)
    
    # Виписані цього тижня: тільки ті, чия дата виписки вже минула/сьогодні і припадає на останні 7 днів
    from_date = today - timedelta(days=7)
    discharged_this_week = Patient.objects.filter(
        discharge_date__range=[from_date, today]
    ).filter(Q(is_active=False) | Q(discharge_date=today) | Q(mis_discharged=True)).count()
    
    # Розрахунок запланованої виписки (поточний/наступний тиждень)
    if today.weekday() < 4:  # Понеділок - Четвер
        start_of_week = today - timedelta(days=today.weekday())
        planned_discharge_label = "Випишуться цього тижня"
    else:  # П'ятниця - Неділя
        start_of_week = today + timedelta(days=(7 - today.weekday()))
        planned_discharge_label = "Випишуться наступного тижня"
        
    end_of_week = start_of_week + timedelta(days=6)
    planned_discharge_count = Patient.objects.filter(
        discharge_date__range=[start_of_week, end_of_week],
        is_active=True
    ).count()

    pending_mvtn_list = get_pending_mvtn_staging_patients(today)
    
    context = {
        'ct_today_count': ct_today_count,
        'start_today_count': start_today_count,
        'discharge_today_count': discharge_today_count,
        'ct_count': ct_count,
        'start_count': start_count,
        'in_treatment_count': in_treatment_count,
        'discharged_this_week': discharged_this_week,
        'planned_discharge_count': planned_discharge_count,
        'planned_discharge_label': planned_discharge_label,
        'notifications': notifications,
        'quote_of_the_day': quote_of_the_day,
    }
    return render(request, 'patients/dashboard.html', context)

def _sort_patients_queryset(patients, sort_by, sort_order):
    """Допоміжна функція для сортування QuerySet пацієнтів"""
    if sort_by == 'full_name':
        order_field = 'last_name'
    elif sort_by == 'ct_simulation_date':
        order_field = 'ct_simulation_date'
    elif sort_by == 'treatment_start_date':
        order_field = 'treatment_start_date'
    elif sort_by == 'discharge_date':
        order_field = 'discharge_date'
    elif sort_by == 'medical_incapacity_end':
        if sort_order == 'desc':
            return patients.annotate(
                latest_incapacity_end=models.Subquery(
                    MedicalIncapacity.objects.filter(
                        patient=models.OuterRef('pk')
                    ).order_by('-end_date').values('end_date')[:1]
                )
            ).order_by('-latest_incapacity_end')
        else:
            return patients.annotate(
                latest_incapacity_end=models.Subquery(
                    MedicalIncapacity.objects.filter(
                        patient=models.OuterRef('pk')
                    ).order_by('-end_date').values('end_date')[:1]
                )
            ).order_by('latest_incapacity_end')
    else:
        order_field = 'last_name'
        
    if sort_order == 'desc':
        order_field = f'-{order_field}'
        
    return patients.order_by(order_field)


@login_required
def patient_list(request, filter_type=None):
    today = timezone.localdate()
    
    if filter_type == 'archive':
        return patient_archive(request)
        
    # Активні: discharge_date немає або у майбутньому
    base_query = Patient.objects.filter(
        models.Q(discharge_date__isnull=True) | models.Q(discharge_date__gte=today)
    )
    
    if filter_type:
        if filter_type == 'ct-simulation':
            patients = base_query.filter(
                ct_simulation_date__isnull=False,
                treatment_start_date__isnull=True
            )
        elif filter_type == 'treatment-start':
            patients = base_query.filter(
                treatment_start_date__isnull=False,
                treatment_start_date__gt=today
            )
        elif filter_type == 'in-treatment':
            patients = base_query.filter(
                treatment_start_date__isnull=False,
                treatment_start_date__lte=today
            )
        elif filter_type == 'discharge-prep':
            three_days_later = today + timedelta(days=3)
            patients = base_query.filter(
                discharge_date__isnull=False,
                discharge_date__gt=today,
                discharge_date__lte=three_days_later
            )
        else:
            patients = base_query.all()
    else:
        patients = base_query.all()
    
    # Сортування
    sort_by = request.GET.get('sort', 'last_name')
    sort_order = request.GET.get('order', 'asc')
    
    patients = _sort_patients_queryset(patients, sort_by, sort_order)
        
    return render(request, 'patients/patient_list.html', {
        'patients': patients,
        'filter_type': filter_type,
        'current_sort': sort_by,
        'current_order': sort_order,
        'is_archive': False
    })

@login_required
def patient_create(request):
    if request.method == 'POST':
        form = PatientForm(request.POST)
        print("POST data:", request.POST)
        print("Form errors:", form.errors)
        print("Non-field errors:", form.non_field_errors())
        if form.is_valid():
            patient = form.save()
            if not patient.validate_diagnosis_compliance():
                messages.warning(request, "Діагноз неповний згідно з Наказом № 473")
            return redirect('patient_list')
    else:
        form = PatientForm()
    return render(request, 'patients/patient_form.html', {'form': form})

@login_required
def patient_update(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    if request.method == 'POST':
        form = PatientForm(request.POST, instance=patient)
        if form.is_valid():
            patient = form.save()
            if not patient.validate_diagnosis_compliance():
                messages.warning(request, "Діагноз неповний згідно з Наказом № 473")
            return redirect('patient_list')
    else:
        form = PatientForm(instance=patient)
    return render(request, 'patients/patient_form.html', {'form': form, 'patient': patient})

@login_required
def patient_delete(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    if request.method == 'POST':
        patient.delete()
        return redirect('patient_list')
    return render(request, 'patients/patient_confirm_delete.html', {'patient': patient})

@login_required
@require_POST
def archive_patient(request, pk):
    """Примусово переводить пацієнта в архів, встановлюючи дату виписки на вчорашній день"""
    patient = get_object_or_404(Patient, pk=pk)
    # Встановлюємо дату виписки в минулому, щоб пацієнт одразу потрапив у статус "Архів"
    yesterday = timezone.localdate() - timedelta(days=1)
    patient.discharge_date = yesterday
    patient.save()
    messages.success(request, f'Пацієнта {patient.full_name} успішно переведено в архів.')
    return redirect('patient_list')

@login_required
@require_POST
def update_fraction_status_api(request):
    """Оновлення статусу фракції асинхронно через Fetch API"""
    try:
        data = json.loads(request.body)
        fraction_id = data.get('fraction_id')
        status = data.get('status')
        
        if status not in ['scheduled', 'delivered', 'missed']:
            return JsonResponse({'success': False, 'error': 'Некоректний статус'}, status=400)
            
        fraction = get_object_or_404(FractionHistory, pk=fraction_id)
        old_status = fraction.status
        fraction.status = status
        fraction.save()
        
        patient = fraction.patient
        
        # Якщо статус змінився, запускаємо перебудову розкладу
        if status != old_status:
            from .services import shift_patient_schedule
            shift_patient_schedule(patient)
            
        # Завжди перераховуємо отриману дозу
        patient.recalculate_received_dose()
        
        # Оновлюємо інформацію про виписку
        patient.refresh_from_db()
        
        fractions_list = []
        for f in patient.fractions.all().order_by('date'):
            fractions_list.append({
                'id': f.id,
                'date': f.date.strftime('%d.%m.%Y'),
                'original_date': f.original_date.strftime('%d.%m.%Y') if f.original_date else None,
                'status': f.status,
            })
            
        return JsonResponse({
            'success': True,
            'message': f"Статус фракції від {fraction.date.strftime('%d.%m.%Y')} оновлено.",
            'new_sod': patient.received_dose,
            'new_discharge_date': patient.discharge_date.strftime('%d.%m.%Y') if patient.discharge_date else None,
            'current_fraction': patient.current_fraction,
            'total_fractions': patient.total_fractions or 0,
            'fractions': fractions_list
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
@require_POST
def update_patient_notes(request, pk):
    """Оновлення нотаток пацієнта через AJAX"""
    patient = get_object_or_404(Patient, pk=pk)
    try:
        data = json.loads(request.body)
        patient.notes = data.get('notes', '')
        patient.save()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)

@login_required
def fraction_list(request):
    today = timezone.localdate()
    active_patients_q = Q(is_active=True) & (Q(discharge_date__isnull=True) | Q(discharge_date__gte=today))
    
    # АВТОМАТИКА: Пропущені фракції за минулі дні
    overdue_fractions = FractionHistory.objects.filter(
        date__lt=today,
        status='scheduled',
        patient__in=Patient.objects.filter(active_patients_q)
    ).order_by('date')
    
    if overdue_fractions.exists():
        patient_earliest_dates = {}
        for f in overdue_fractions:
            if f.patient_id not in patient_earliest_dates:
                patient_earliest_dates[f.patient_id] = f.date
        
        for patient_id in patient_earliest_dates.keys():
            patient = Patient.objects.get(pk=patient_id)
            delivered_count = patient.fractions.filter(status='delivered').count()
            total = patient.total_fractions or 0
            if total > 0 and delivered_count >= total:
                patient.fractions.filter(date__lt=today, status='scheduled').delete()
            else:
                patient.fractions.filter(date__lt=today, status='scheduled').update(status='missed')
            from .services import shift_patient_schedule
            shift_patient_schedule(patient)
            patient.recalculate_received_dose()
            
    # Фракції на сьогодні (для всіх активних пацієнтів)
    today_fractions = FractionHistory.objects.filter(
        date=today,
        patient__in=Patient.objects.filter(active_patients_q)
    ).select_related('patient').order_by('patient__last_name', 'patient__first_name')
    
    # Отримуємо активних пацієнтів, які мають фракції
    patients_with_fractions = Patient.objects.filter(
        active_patients_q,
        fractions__isnull=False
    ).distinct().prefetch_related(
        'fractions'
    ).order_by('last_name', 'first_name')
    
    # ОПТИМІЗАЦІЯ N+1: підраховуємо фракції у пам'яті Python (замість 200+ повторних SQL-запитів)
    patients_data = []
    for patient in patients_with_fractions:
        all_fractions = sorted(list(patient.fractions.all()), key=lambda f: f.date)
        completed_count = sum(1 for f in all_fractions if f.status == 'delivered')
        pending_count = sum(1 for f in all_fractions if f.status == 'scheduled')
        missed_count = sum(1 for f in all_fractions if f.status == 'missed')
        
        patients_data.append({
            'patient': patient,
            'fractions': all_fractions,
            'total_fractions': len(all_fractions),
            'completed_fractions': completed_count,
            'pending_fractions': pending_count,
            'missed_fractions': missed_count,
        })
        
    return render(request, 'patients/fraction_list.html', {
        'patients_data': patients_data,
        'today_fractions': today_fractions,
        'today': today
    })

@login_required
def fraction_confirm(request, pk):
    fraction = get_object_or_404(FractionHistory, pk=pk)
    if request.method == 'POST':
        fraction.confirmed_by_doctor = True
        fraction.save()
        return redirect('fraction_list')
    return render(request, 'patients/fraction_confirm.html', {'fraction': fraction})

@login_required
def fraction_nurse_confirm(request, pk):
    fraction = get_object_or_404(FractionHistory, pk=pk)
    if request.method == 'POST':
        fraction.delivered = True
        fraction.save()
        return redirect('fraction_list')
    return render(request, 'patients/fraction_nurse_confirm.html', {'fraction': fraction})

@login_required
def fraction_edit(request, pk):
    """Редагування фракції"""
    fraction = get_object_or_404(FractionHistory, pk=pk)
    
    if request.method == 'POST':
        form = FractionEditForm(request.POST, instance=fraction)
        if form.is_valid():
            # Зберігаємо оригінальну дату, якщо це перша зміна
            if not fraction.original_date and form.cleaned_data['date'] != fraction.date:
                fraction.original_date = fraction.date
            
            old_status = fraction.status
            fraction = form.save()
            
            # Якщо статус змінився, запускаємо перебудову розкладу
            if fraction.status != old_status:
                from .services import shift_patient_schedule
                shift_patient_schedule(fraction.patient)
                
            # Завжди перераховуємо отриману дозу
            fraction.patient.recalculate_received_dose()
            
            # Перераховуємо дату виписки, якщо змінилася дата фракції
            if 'date' in form.changed_data:
                from .services import recalculate_discharge_date
                recalculate_discharge_date(fraction.patient)
            
            messages.success(request, f'Фракцію від {fraction.date.strftime("%d.%m.%Y")} успішно оновлено')
            return redirect('patient_detail', pk=fraction.patient.pk)
    else:
        form = FractionEditForm(instance=fraction)
    
    return render(request, 'patients/fraction_edit.html', {
        'form': form, 
        'fraction': fraction,
        'patient': fraction.patient
    })

@login_required
def medical_incapacity_create(request, patient_pk):
    patient = get_object_or_404(Patient, pk=patient_pk)
    if request.method == 'POST':
        form = MedicalIncapacityForm(request.POST)
        if form.is_valid():
            incapacity = form.save(commit=False)
            incapacity.patient = patient
            incapacity.save()
            return redirect('patient_detail', pk=patient_pk)
    else:
        form = MedicalIncapacityForm()
    return render(request, 'patients/medical_incapacity_form.html', {'form': form, 'patient': patient})

@login_required
def medical_incapacity_delete(request, patient_pk, incapacity_pk):
    incapacity = get_object_or_404(MedicalIncapacity, pk=incapacity_pk, patient_id=patient_pk)
    if request.method == 'POST':
        incapacity.delete()
        return redirect('patient_detail', pk=patient_pk)
    return render(request, 'patients/medical_incapacity_confirm_delete.html', {'incapacity': incapacity})

@login_required
def patient_detail(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    
    # АВТОМАТИКА: Пропущені фракції за минулі дні для цього конкретного пацієнта
    today = timezone.localdate()
    is_active = patient.discharge_date is None or patient.discharge_date >= today
    if is_active:
        overdue_fractions = patient.fractions.filter(date__lt=today, status='scheduled').order_by('date')
        if overdue_fractions.exists():
            delivered_count = patient.fractions.filter(status='delivered').count()
            total = patient.total_fractions or 0
            if total > 0 and delivered_count >= total:
                overdue_fractions.delete()
            else:
                overdue_fractions.update(status='missed')
            from .services import shift_patient_schedule
            shift_patient_schedule(patient)
            # Перечитуємо пацієнта після оновлення дат та виписки
            patient.refresh_from_db()
            patient.recalculate_received_dose()
            
    fractions = patient.fractions.all().order_by('-date')
    incapacities = patient.medical_incapacities.all().order_by('-created_at')
    treatment_info = get_patient_treatment_info(patient)
    
    # Підрахунки для статистики фракцій
    missed_fractions_count = patient.fractions.filter(status='missed').count()
    postponed_fractions_count = patient.fractions.filter(original_date__isnull=False).count()
    
    # Завантажуємо ШІ-документи та щоденники
    ai_doc = getattr(patient, 'ai_documentation', None)
    ai_diaries = patient.ai_diaries.all().order_by('-date', '-fraction_number')
    
    return render(request, 'patients/patient_detail.html', {
        'patient': patient,
        'fractions': fractions,
        'incapacities': incapacities,
        'treatment_info': treatment_info,
        'missed_fractions_count': missed_fractions_count,
        'postponed_fractions_count': postponed_fractions_count,
        'ai_doc': ai_doc,
        'ai_diaries': ai_diaries
    })

def login_view(request):
    if request.method == 'POST':
        form = UserLoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            user = authenticate(username=username, password=password)
            if user is not None:
                if user.role == 'nurse' and not user.approved:
                    messages.error(request, 'Очікуйте підтвердження лікаря')
                    return render(request, 'patients/login.html', {'form': form})
                login(request, user)
                return redirect('dashboard')
            else:
                messages.error(request, 'Невірний логін або пароль')
    else:
        form = UserLoginForm()
    return render(request, 'patients/login.html', {'form': form})

def register_view(request):
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.approved = True if user.role == 'doctor' else False
            user.save()
            messages.success(request, 'Реєстрація успішна! Тепер можете увійти.')
            return redirect('login')
    else:
        form = UserRegistrationForm()
    return render(request, 'patients/register.html', {'form': form})

def logout_view(request):
    logout(request)
    return redirect('login')

@login_required
def admin_users(request):
    if request.user.role != 'admin':
        messages.error(request, 'Доступ заборонено')
        return redirect('dashboard')
    
    users = User.objects.all()
    return render(request, 'patients/admin_users.html', {'users': users})

@admin_required
def admin_approve_user(request, user_id):
    if request.method == 'POST':
        user = get_object_or_404(User, pk=user_id)
        approve = request.POST.get('approve') == 'true'
        user.approved = approve
        user.save()
        messages.success(request, f'Користувач {user.username} {"затверджено" if approve else "відхилено"}')
    
    return redirect('admin_users')

@login_required
def confirm_blood_test(request, patient_id):
    patient = get_object_or_404(Patient, id=patient_id)
    today = timezone.localdate()
    
    test_date_str = request.POST.get('test_date') or request.GET.get('test_date')
    if test_date_str:
        from django.utils.dateparse import parse_date
        parsed_date = parse_date(test_date_str)
        if not parsed_date:
            try:
                parts = test_date_str.split('.')
                if len(parts) == 3:
                    parsed_date = date(int(parts[2]), int(parts[1]), int(parts[0]))
            except (ValueError, IndexError):
                parsed_date = None
        patient.last_blood_test_date = parsed_date or today
    else:
        patient.last_blood_test_date = today

    patient.save()
    patient.refresh_from_db()

    msg = f'Аналіз крові підтверджено для {patient.full_name} ({patient.last_blood_test_date.strftime("%d.%m.%Y")})'
    
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '') or request.content_type == 'application/json'
    if is_ajax:
        next_due = patient.next_blood_test_due_date
        return JsonResponse({
            'success': True,
            'message': msg,
            'last_blood_test_date': patient.last_blood_test_date.strftime('%d.%m.%Y'),
            'next_blood_test_due_date': next_due.strftime('%d.%m.%Y') if next_due else None,
            'days_until_next': (next_due - today).days if next_due else None,
        })

    messages.success(request, msg)
    referer = request.META.get('HTTP_REFERER')
    if referer:
        return redirect(referer)
    return redirect('dashboard')

@login_required
def generate_fractions(request, patient_id):
    if request.method == 'POST':
        patient = get_object_or_404(Patient, pk=patient_id)
        success = generate_fractions_for_patient(patient)
        if success:
            messages.success(request, f'Фракції згенеровано для {patient.full_name}')
        else:
            messages.error(request, 'Недостатньо даних для генерації фракцій')
        return redirect('patient_detail', pk=patient_id)
    return redirect('patient_detail', pk=patient_id)

@login_required
def recalculate_discharge(request, patient_id):
    """Перераховує дату виписки на основі фракцій"""
    if request.method == 'POST':
        patient = get_object_or_404(Patient, pk=patient_id)
        from .services import shift_patient_schedule, recalculate_discharge_date
        shift_patient_schedule(patient)
        new_date = recalculate_discharge_date(patient)
        patient.recalculate_received_dose()
        if new_date:
            messages.success(request, f'Дату виписки оновлено на {new_date.strftime("%d.%m.%Y")}')
        else:
            messages.error(request, 'Не вдалося перерахувати дату виписки')
        return redirect('patient_detail', pk=patient_id)
    return redirect('patient_detail', pk=patient_id)

@login_required
def auto_confirm_fractions(request):
    if request.method == 'POST':
        count = auto_confirm_today_fractions()
        messages.success(request, f'Автоматично підтверджено {count} фракцій')
    return redirect('fraction_list')

@login_required
def search_patients(request):
    query = request.GET.get('q', '')
    if query:
        patients = Patient.objects.filter(
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(middle_name__icontains=query) |
            Q(diagnosis__icontains=query)
        )
    else:
        patients = Patient.objects.none()
    
    return render(request, 'patients/patient_list.html', {
        'patients': patients,
        'search_query': query
    })

@login_required
def inpatient_list(request):
    """Список стаціонарних пацієнтів та ліжкового фонду"""
    today = timezone.localdate()
    # Автоматично деактивуємо тільки тих пацієнтів, чиє лікування закінчилося І які вже були виписані в МІС
    Patient.objects.filter(is_active=True, mis_discharged=True, discharge_date__lt=today).update(is_active=False)
    
    # Фільтруємо пацієнтів ВИКЛЮЧНО за статусом inpatient та is_active=True
    current_inpatients = Patient.objects.filter(
        hospitalization_status='inpatient',
        is_active=True
    ).order_by('last_name', 'first_name')
    
    # Збагачуємо пацієнтів динамічною датою виписки та прапорцем позиченого ліжка
    for p in current_inpatients:
        p.actual_discharge_date = p.get_actual_discharge_date
        p.is_borrowed = (p.bed_owner != 'Олег')
        
    # Розподіл за статтю
    own_male_patients = [p for p in current_inpatients if p.gender == 'M' and p.bed_owner == 'Олег']
    borrowed_male_patients = [p for p in current_inpatients if p.gender == 'M' and p.bed_owner != 'Олег']
    
    own_female_patients = [p for p in current_inpatients if p.gender == 'F' and p.bed_owner == 'Олег']
    borrowed_female_patients = [p for p in current_inpatients if p.gender == 'F' and p.bed_owner != 'Олег']
    
    # Про всяк випадок переносимо надлишок власних пацієнтів у секцію додаткових карток
    if len(own_male_patients) > 2:
        borrowed_male_patients.extend(own_male_patients[2:])
        own_male_patients = own_male_patients[:2]
        
    if len(own_female_patients) > 2:
        borrowed_female_patients.extend(own_female_patients[2:])
        own_female_patients = own_female_patients[:2]
        
    # Формуємо матрицю власних ліжок (завжди довжиною 2)
    own_male_beds = []
    for i in range(2):
        if i < len(own_male_patients):
            own_male_beds.append({'occupied': True, 'patient': own_male_patients[i]})
        else:
            own_male_beds.append({'occupied': False, 'patient': None})
            
    own_female_beds = []
    for i in range(2):
        if i < len(own_female_patients):
            own_female_beds.append({'occupied': True, 'patient': own_female_patients[i]})
        else:
            own_female_beds.append({'occupied': False, 'patient': None})
            
    # Пацієнти у черзі (статус queue)
    queue_patients = Patient.objects.filter(
        hospitalization_status='queue',
        is_active=True
    ).order_by('planned_admission_date', 'last_name', 'first_name')
    
    return render(request, 'patients/inpatient_list.html', {
        'patients': current_inpatients,
        'own_male_beds': own_male_beds,
        'own_female_beds': own_female_beds,
        'borrowed_male_patients': borrowed_male_patients,
        'borrowed_female_patients': borrowed_female_patients,
        'queue_patients': queue_patients,
    })

@login_required
@require_POST
def admit_patient(request, pk):
    """Госпіталізація пацієнта з черги у стаціонар"""
    patient = get_object_or_404(Patient, pk=pk)
    bed_owner = request.POST.get('bed_owner', 'Олег').strip()
    if not bed_owner:
        bed_owner = 'Олег'
        
    patient.hospitalization_status = 'inpatient'
    patient.treatment_start_date = timezone.localdate()
    patient.bed_owner = bed_owner
    patient.save()
    
    # Автоматично генеруємо фракції, якщо вказано загальну кількість та РОД
    if patient.total_fractions and patient.dose_per_fraction:
        generate_fractions_for_patient(patient)
        
    messages.success(request, f'Пацієнта {patient.full_name} успішно госпіталізовано.')
    return redirect('inpatient_list')

@login_required
def patient_archive(request):
    """Список пацієнтів в архіві з підтримкою сортування"""
    today = timezone.localdate()
    archived_patients = Patient.objects.filter(
        discharge_date__isnull=False,
        discharge_date__lt=today  # Тільки виписані пацієнти (дата виписки в минулому)
    )
    
    sort_by = request.GET.get('sort', 'discharge_date')
    sort_order = request.GET.get('order', 'desc')
    
    archived_patients = _sort_patients_queryset(archived_patients, sort_by, sort_order)
    
    return render(request, 'patients/patient_list.html', {
        'patients': archived_patients,
        'filter_type': 'archive',
        'is_archive': True,
        'current_sort': sort_by,
        'current_order': sort_order
    })

@login_required
@require_POST
def approve_user(request, pk):
    if not request.user.is_superuser:
        return redirect('dashboard')
    
    user_to_approve = User.objects.get(pk=pk)
    user_to_approve.approved = True
    user_to_approve.save()
    messages.success(request, f"Користувача {user_to_approve.username} було затверджено.")
    return redirect('admin_users')

@login_required
@require_POST
def save_today_fractions(request):
    """Зберігає фракції за сьогодні - відмічені як виконані, невідмічені як пропущені"""
    today = timezone.localdate()
    
    # Отримуємо ID відмічених фракцій
    delivered_ids = request.POST.getlist('delivered_fractions')
    delivered_ids = [int(id) for id in delivered_ids if id]
    
    # Отримуємо всі фракції на сьогодні для АКТИВНИХ пацієнтів
    active_patients_q = Q(discharge_date__isnull=True) | Q(discharge_date__gte=today)
    today_fractions = FractionHistory.objects.filter(
        date=today,
        patient__in=Patient.objects.filter(active_patients_q)
    )
    
    delivered_count = 0
    missed_count = 0
    patients_to_recalculate = set()
    
    for fraction in today_fractions:
        old_status = fraction.status
        if fraction.id in delivered_ids:
            fraction.status = 'delivered'
            delivered_count += 1
        else:
            fraction.status = 'missed'
            missed_count += 1
            
        fraction.save()
        if fraction.status != old_status:
            patients_to_recalculate.add(fraction.patient)
        
    for patient in patients_to_recalculate:
        from .services import shift_patient_schedule
        shift_patient_schedule(patient)
        patient.recalculate_received_dose()
        
    if delivered_count > 0 and missed_count > 0:
        messages.success(request, f"Збережено: {delivered_count} виконано, {missed_count} пропущено")
    elif delivered_count > 0:
        messages.success(request, f"Підтверджено {delivered_count} фракцій")
    elif missed_count > 0:
        messages.warning(request, f"Відмічено {missed_count} пропущених фракцій")
    else:
        messages.info(request, "Немає фракцій для збереження")
    
    return redirect('fraction_list')

@login_required
@require_POST
def confirm_fractions_doctor(request):
    fraction_ids = request.POST.getlist('fraction_ids')
    if fraction_ids:
        FractionHistory.objects.filter(id__in=fraction_ids).update(status='delivered')
        patients = Patient.objects.filter(fractions__id__in=fraction_ids).distinct()
        from .services import shift_patient_schedule
        for patient in patients:
            shift_patient_schedule(patient)
            patient.recalculate_received_dose()
        messages.success(request, f"Підтверджено {len(fraction_ids)} фракцій.")
    return redirect('fraction_list')

@login_required
@require_POST
def confirm_fractions_nurse(request):
    fraction_ids = request.POST.getlist('fraction_ids')
    if fraction_ids:
        FractionHistory.objects.filter(id__in=fraction_ids).update(status='delivered')
        patients = Patient.objects.filter(fractions__id__in=fraction_ids).distinct()
        from .services import shift_patient_schedule
        for patient in patients:
            shift_patient_schedule(patient)
            patient.recalculate_received_dose()
        messages.success(request, f"Підтверджено {len(fraction_ids)} фракцій.")
    return redirect('fraction_list')

@login_required
@require_POST
def update_all_discharge_dates(request):
    """Масове оновлення дат виписки для всіх пацієнтів"""
    from .services import recalculate_discharge_date
    
    patients_with_fractions = Patient.objects.filter(
        fractions__isnull=False
    ).distinct()
    
    updated_count = 0
    for patient in patients_with_fractions:
        old_date = patient.discharge_date
        new_date = recalculate_discharge_date(patient)
        if new_date and new_date != old_date:
            updated_count += 1
    
    if updated_count > 0:
        messages.success(request, f'Успішно оновлено дати виписки для {updated_count} пацієнтів')
    else:
        messages.info(request, 'Всі дати виписки вже актуальні')
    
    return redirect('dashboard')

@login_required
@require_POST
def approve_all_fractions(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    today = timezone.localdate()
    is_active = patient.discharge_date is None or patient.discharge_date >= today
    
    success = False
    message = ''
    if is_active:
        fractions_to_update = patient.fractions.filter(status='scheduled', date=today)
        count = fractions_to_update.count()
        if count > 0:
            fractions_to_update.update(status='delivered')
            patient.recalculate_received_dose()
            success = True
            message = f'Затверджено {count} фракцій за сьогодні для {patient.full_name}.'
            messages.success(request, message)
        else:
            message = f'Немає запланованих фракцій на сьогодні для {patient.full_name}.'
            messages.info(request, message)
    else:
        message = f'Пацієнт {patient.full_name} перебуває в архіві.'
        messages.error(request, message)
        
    if 'application/json' in request.headers.get('Accept', ''):
        fractions_list = []
        for f in patient.fractions.all().order_by('date'):
            fractions_list.append({
                'id': f.id,
                'date': f.date.strftime('%d.%m.%Y'),
                'original_date': f.original_date.strftime('%d.%m.%Y') if f.original_date else None,
                'status': f.status,
            })
        return JsonResponse({
            'success': success,
            'message': message,
            'new_sod': patient.received_dose,
            'new_discharge_date': patient.discharge_date.strftime('%d.%m.%Y') if patient.discharge_date else None,
            'current_fraction': patient.current_fraction,
            'total_fractions': patient.total_fractions or 0,
            'fractions': fractions_list
        })
        
    referer = request.META.get('HTTP_REFERER')
    if referer:
        return redirect(referer)
    return redirect('patient_detail', pk=pk)


from django.views.decorators.http import require_POST
from django.http import JsonResponse
import json
from .services import encrypt_notes, decrypt_notes

@login_required
@require_POST
def set_user_pin(request):
    try:
        data = json.loads(request.body)
        password = data.get('password')
        pin = data.get('pin')
        
        if not password or not pin:
            return JsonResponse({'success': False, 'error': 'Пароль та PIN-код обов\'язкові'}, status=400)
            
        if not request.user.check_password(password):
            return JsonResponse({'success': False, 'error': 'Невірний пароль облікового запису'}, status=403)
            
        if not pin.isdigit() or len(pin) != 4:
            return JsonResponse({'success': False, 'error': 'PIN-код має складатися з 4 цифр'}, status=400)
            
        request.user.set_pin(pin)
        request.user.save()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)

@login_required
@require_POST
def decrypt_patient_notes(request, pk):
    try:
        data = json.loads(request.body)
        pin = data.get('pin')
        if not pin:
            return JsonResponse({'success': False, 'error': 'Введіть PIN-код'}, status=400)
            
        patient = get_object_or_404(Patient, pk=pk)
        
        # Перевірка PIN-коду з брутфорс захистом
        success, status_code = request.user.check_pin(pin)
        if status_code == 'locked':
            from django.utils import timezone
            remaining = int((request.user.pin_lockout_until - timezone.now()).total_seconds())
            mins = max(1, remaining // 60)
            return JsonResponse({'success': False, 'error': f'Блокування. Спробуйте через {mins} хв.'}, status=403)
        elif status_code == 'no_pin':
            return JsonResponse({'success': False, 'error': 'PIN-код не встановлено. Встановіть його спочатку.'}, status=400)
        elif status_code == 'invalid':
            attempts_left = 3 - request.user.pin_failed_attempts
            msg = f'Невірний PIN-код. Залишилось спроб: {attempts_left}' if attempts_left > 0 else 'Невірний PIN-код. Блокування на 15 хвилин!'
            return JsonResponse({'success': False, 'error': msg}, status=403)
            
        decrypted = decrypt_notes(patient.encrypted_confidential_notes)
        return JsonResponse({'success': True, 'notes': decrypted})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)

@login_required
@require_POST
def encrypt_patient_notes(request, pk):
    try:
        data = json.loads(request.body)
        pin = data.get('pin')
        notes = data.get('notes', '')
        if not pin:
            return JsonResponse({'success': False, 'error': 'Введіть PIN-код'}, status=400)
            
        patient = get_object_or_404(Patient, pk=pk)
        
        # Перевірка PIN-коду з брутфорс захистом
        success, status_code = request.user.check_pin(pin)
        if status_code == 'locked':
            from django.utils import timezone
            remaining = int((request.user.pin_lockout_until - timezone.now()).total_seconds())
            mins = max(1, remaining // 60)
            return JsonResponse({'success': False, 'error': f'Блокування. Спробуйте через {mins} хв.'}, status=403)
        elif status_code == 'no_pin':
            return JsonResponse({'success': False, 'error': 'PIN-код не встановлено. Встановіть його спочатку.'}, status=400)
        elif status_code == 'invalid':
            attempts_left = 3 - request.user.pin_failed_attempts
            msg = f'Невірний PIN-код. Залишилось спроб: {attempts_left}' if attempts_left > 0 else 'Невірний PIN-код. Блокування на 15 хвилин!'
            return JsonResponse({'success': False, 'error': msg}, status=403)
            
        patient.encrypted_confidential_notes = encrypt_notes(notes)
        patient.save()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)

@login_required
@require_POST
def toggle_fraction_status(request, pk):
    try:
        fraction = get_object_or_404(FractionHistory, pk=pk)
        old_status = fraction.status
        if old_status == 'scheduled':
            fraction.status = 'delivered'
        elif old_status == 'delivered':
            fraction.status = 'missed'
        else:
            fraction.status = 'scheduled'
            
        fraction.save()
        
        from .services import shift_patient_schedule
        shift_patient_schedule(fraction.patient)
        fraction.patient.recalculate_received_dose()
        
        from .services import get_patient_treatment_info
        info = get_patient_treatment_info(fraction.patient)
        
        return JsonResponse({
            'success': True,
            'status': fraction.status,
            'received_dose': fraction.patient.received_dose,
            'completed_fractions': info['completed_fractions'],
            'total_fractions': info['total_fractions']
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
@require_POST
def update_fraction_note_api(request, pk):
    try:
        data = json.loads(request.body)
        note = data.get('note', '').strip()
        fraction = get_object_or_404(FractionHistory, pk=pk)
        fraction.note = note
        fraction.save()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
@require_POST
def add_patient_fraction_api(request, pk):
    try:
        patient = get_object_or_404(Patient, pk=pk)
        
        # Визначаємо дату для нової фракції
        latest_fraction = patient.fractions.order_by('date').last()
        if latest_fraction:
            next_date = latest_fraction.date + timedelta(days=1)
        else:
            next_date = patient.treatment_start_date or timezone.localdate()
            
        # Пропускаємо вихідні
        while next_date.weekday() >= 5:
            next_date += timedelta(days=1)
            
        fraction = FractionHistory.objects.create(
            patient=patient,
            date=next_date,
            dose=patient.dose_per_fraction or 2.0,
            status='scheduled'
        )
        
        # Оновлюємо загальну кількість фракцій пацієнта
        patient.total_fractions = (patient.total_fractions or 0) + 1
        patient.discharge_date = next_date
        patient.save()
        
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
@require_POST
def save_ai_notes(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    notes = request.POST.get('clinical_state_notes', '').strip()
    
    from .models import PatientAIDocumentation
    ai_doc, created = PatientAIDocumentation.objects.get_or_create(patient=patient)
    ai_doc.clinical_state_notes = notes
    ai_doc.save()
    
    return JsonResponse({'success': True})


@login_required
@require_POST
def generate_ai_doc(request, pk, doc_type):
    patient = get_object_or_404(Patient, pk=pk)
    
    from .models import PatientAIDocumentation
    ai_doc, created = PatientAIDocumentation.objects.get_or_create(patient=patient)
    
    from .ai_service import generate_initial_assessment, generate_discharge_summary
    
    try:
        today = timezone.localdate()
        today_date_str = today.strftime('%d.%m.%Y')
        if doc_type == 'initial':
            text = generate_initial_assessment(
                gender=patient.gender,
                diagnosis=patient.diagnosis or patient.raw_diagnosis,
                clinical_state_notes=ai_doc.clinical_state_notes,
                total_fractions=patient.total_fractions,
                dose_per_fraction=patient.dose_per_fraction,
                irradiation_zone=patient.irradiation_zone,
                today_date_str=today_date_str
            )
            ai_doc.initial_assessment = text
            ai_doc.save()
        elif doc_type == 'discharge':
            patient.recalculate_received_dose()
            text = generate_discharge_summary(
                gender=patient.gender,
                diagnosis=patient.diagnosis or patient.raw_diagnosis,
                total_fractions=patient.total_fractions,
                dose_per_fraction=patient.dose_per_fraction,
                received_dose=patient.received_dose,
                clinical_state_notes=ai_doc.clinical_state_notes
            )
            ai_doc.discharge_summary = text
            ai_doc.save()
        else:
            return JsonResponse({'success': False, 'error': 'Invalid document type'}, status=400)
            
        return JsonResponse({'success': True, 'text': text})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_POST
def save_ai_doc_text(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    initial_text = request.POST.get('initial_assessment', '').strip()
    discharge_text = request.POST.get('discharge_summary', '').strip()
    
    from .models import PatientAIDocumentation
    ai_doc, created = PatientAIDocumentation.objects.get_or_create(patient=patient)
    ai_doc.initial_assessment = initial_text
    ai_doc.discharge_summary = discharge_text
    ai_doc.save()
    
    return JsonResponse({'success': True})


@login_required
@require_POST
def generate_ai_diary(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    
    diary_date_str = request.POST.get('date')
    fraction_number_str = request.POST.get('fraction_number')
    fraction_number = int(fraction_number_str) if fraction_number_str and fraction_number_str.strip().isdigit() else None
    ecog_status = int(request.POST.get('ecog_status', 0))
    ctcae_grade = int(request.POST.get('ctcae_grade', 0))
    clinical_state_notes = request.POST.get('clinical_state_notes', '').strip()
    diary_type = request.POST.get('diary_type', 'weekly').strip()
    
    if diary_type not in ['admission', 'weekly', 'discharge']:
        diary_type = 'weekly'
        
    if not diary_date_str:
        return JsonResponse({'success': False, 'error': 'Date is required'}, status=400)
        
    try:
        from django.utils.dateparse import parse_date
        diary_date = parse_date(diary_date_str)
        if not diary_date:
            raise ValueError("Неправильний формат дати")
            
        # Fetch previous diaries for context
        previous_diaries = patient.ai_diaries.all().order_by('date', 'fraction_number')
        previous_diaries_text = ""
        if previous_diaries.exists():
            lines = []
            for d in previous_diaries:
                lines.append(
                    f"- Фракція {d.fraction_number or '—'} ({d.date.strftime('%d.%m.%Y')}):\n"
                    f"  Текст щоденника:\n{d.generated_text.strip()}"
                )
            previous_diaries_text = "\n".join(lines)
            
        from .ai_service import generate_diary_entry
        text = generate_diary_entry(
            gender=patient.gender,
            diagnosis=patient.diagnosis or patient.raw_diagnosis,
            fraction_number=fraction_number,
            ecog_status=ecog_status,
            ctcae_grade=ctcae_grade,
            clinical_state_notes=clinical_state_notes,
            diary_type=diary_type,
            total_fractions=patient.total_fractions,
            dose_per_fraction=patient.dose_per_fraction,
            previous_diaries_text=previous_diaries_text
        )
        
        from .models import PatientAIDiary
        diary = PatientAIDiary.objects.create(
            patient=patient,
            date=diary_date,
            fraction_number=fraction_number or None,
            ecog_status=ecog_status,
            ctcae_grade=ctcae_grade,
            clinical_state_notes=clinical_state_notes,
            generated_text=text,
            diary_type=diary_type
        )
        
        return JsonResponse({
            'success': True,
            'diary_id': diary.id,
            'text': text,
            'date': diary.date.strftime('%d.%m.%Y'),
            'fraction_number': diary.fraction_number,
            'ecog_status': diary.ecog_status,
            'ctcae_grade': diary.ctcae_grade,
            'clinical_state_notes': diary.clinical_state_notes,
            'diary_type': diary.diary_type,
            'diary_type_display': diary.get_diary_type_display()
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_POST
def save_ai_diary(request, pk, diary_id):
    from .models import PatientAIDiary
    diary = get_object_or_404(PatientAIDiary, pk=diary_id, patient_id=pk)
    generated_text = request.POST.get('generated_text', '').strip()
    
    diary.generated_text = generated_text
    diary.save()
    
    return JsonResponse({'success': True})


@login_required
@require_POST
def delete_ai_diary(request, pk, diary_id):
    from .models import PatientAIDiary
    diary = get_object_or_404(PatientAIDiary, pk=diary_id, patient_id=pk)
    diary.delete()
    
    return JsonResponse({'success': True})


@login_required
def bulk_confirm_preview_api(request):
    """
    Повертає попередній розрахунок для масового підтвердження фракцій за період.
    """
    start_date_str = request.GET.get('start_date') or request.POST.get('start_date')
    end_date_str = request.GET.get('end_date') or request.POST.get('end_date')
    include_missed = request.GET.get('include_missed', 'true').lower() in ['true', '1', 'on']

    if not start_date_str or not end_date_str:
        return JsonResponse({'success': False, 'error': 'Потрібно вказати початкову та кінцеву дату.'}, status=400)

    try:
        from django.utils.dateparse import parse_date
        start_date = parse_date(start_date_str)
        end_date = parse_date(end_date_str)
        if not start_date or not end_date:
            raise ValueError("Неправильний формат дати")

        status_list = ['scheduled', 'missed'] if include_missed else ['scheduled']

        fractions = FractionHistory.objects.filter(
            date__gte=start_date,
            date__lte=end_date,
            status__in=status_list
        ).select_related('patient').order_by('patient__last_name', 'patient__first_name', 'date')

        patient_map = {}
        for f in fractions:
            p_id = f.patient.id
            if p_id not in patient_map:
                patient_map[p_id] = {
                    'id': p_id,
                    'full_name': f.patient.full_name,
                    'completed_fractions': f.patient.current_fraction,
                    'total_fractions': f.patient.total_fractions,
                    'dose_per_fraction': f.patient.dose_per_fraction or 0.0,
                    'count': 0,
                    'fractions': []
                }
            patient_map[p_id]['count'] += 1
            patient_map[p_id]['fractions'].append({
                'id': f.id,
                'date': f.date.strftime('%d.%m.%Y'),
                'status': f.status,
                'status_display': 'Пропущена' if f.status == 'missed' else 'Запланована'
            })

        patients_list = list(patient_map.values())
        total_fractions_count = sum(p['count'] for p in patients_list)

        return JsonResponse({
            'success': True,
            'start_date': start_date.strftime('%d.%m.%Y'),
            'end_date': end_date.strftime('%d.%m.%Y'),
            'total_patients': len(patients_list),
            'total_fractions': total_fractions_count,
            'patients': patients_list
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_POST
def bulk_confirm_period_api(request):
    """
    Масово підтверджує всі фракції за обраний період.
    """
    import json
    try:
        data = json.loads(request.body) if request.body else request.POST
        start_date_str = data.get('start_date')
        end_date_str = data.get('end_date')
        include_missed = str(data.get('include_missed', 'true')).lower() in ['true', '1', 'on']
        patient_ids = data.get('patient_ids', None)

        from django.utils.dateparse import parse_date
        start_date = parse_date(start_date_str)
        end_date = parse_date(end_date_str)
        if not start_date or not end_date:
            return JsonResponse({'success': False, 'error': 'Неправильний формат дати'}, status=400)

        status_list = ['scheduled', 'missed'] if include_missed else ['scheduled']

        query = FractionHistory.objects.filter(
            date__gte=start_date,
            date__lte=end_date,
            status__in=status_list
        )

        if patient_ids and isinstance(patient_ids, list):
            query = query.filter(patient_id__in=patient_ids)

        affected_patient_ids = list(query.values_list('patient_id', flat=True).distinct())
        confirmed_count = query.update(status='delivered')

        from .services import shift_patient_schedule, recalculate_discharge_date
        affected_patients = Patient.objects.filter(id__in=affected_patient_ids)
        for patient in affected_patients:
            shift_patient_schedule(patient)
            recalculate_discharge_date(patient)
            patient.recalculate_received_dose()

        return JsonResponse({
            'success': True,
            'confirmed_count': confirmed_count,
            'affected_patients_count': len(affected_patient_ids)
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_POST
def bulk_confirm_patient_up_to_date_api(request, patient_id):
    """
    Підтверджує всі непідтверджені та пропущені фракції конкретного пацієнта до вказаної дати.
    """
    patient = get_object_or_404(Patient, pk=patient_id)
    up_to_date_str = request.POST.get('up_to_date') or request.GET.get('up_to_date')
    include_missed = request.POST.get('include_missed', 'true').lower() in ['true', '1', 'on']

    today = timezone.localdate()
    if up_to_date_str:
        from django.utils.dateparse import parse_date
        target_date = parse_date(up_to_date_str) or today
    else:
        target_date = today

    status_list = ['scheduled', 'missed'] if include_missed else ['scheduled']

    query = patient.fractions.filter(
        date__lte=target_date,
        status__in=status_list
    )

    confirmed_count = query.update(status='delivered')

    from .services import shift_patient_schedule, recalculate_discharge_date
    shift_patient_schedule(patient)
    recalculate_discharge_date(patient)
    patient.recalculate_received_dose()
    patient.refresh_from_db()

    return JsonResponse({
        'success': True,
        'confirmed_count': confirmed_count,
        'up_to_date': target_date.strftime('%d.%m.%Y'),
        'completed_fractions': patient.current_fraction,
        'total_fractions': patient.total_fractions,
        'received_dose': patient.received_dose,
        'discharge_date': patient.discharge_date.strftime('%d.%m.%Y') if patient.discharge_date else None
    })


@login_required
def patient_blood_tests(request):
    """
    Відображає сторінку з датами останніх та наступних аналізів крові для пацієнтів на лікуванні.
    """
    today = timezone.localdate()
    search_query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', 'all').strip()

    # Отримуємо активних пацієнтів, які ВЖЕ розпочали лікування (дата початку настала або сьогодні)
    active_patients_q = Q(discharge_date__isnull=True) | Q(discharge_date__gte=today)
    patients = Patient.objects.filter(
        is_active=True,
        treatment_start_date__isnull=False,
        treatment_start_date__lte=today
    ).filter(active_patients_q)

    if search_query:
        patients = patients.filter(
            Q(last_name__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(middle_name__icontains=search_query) |
            Q(ambulatory_card_number__icontains=search_query)
        )

    patient_items = []
    urgent_count = 0
    radiomod_count = 0
    planned_count = 0

    for patient in patients:
        last_test = patient.last_blood_test_date
        next_due = patient.next_blood_test_due_date
        has_rm = patient.has_radiomodification
        if has_rm:
            radiomod_count += 1

        days_since_last = (today - last_test).days if last_test else None
        
        actual_discharge = patient.get_actual_discharge_date or patient.discharge_date

        if next_due:
            days_until_next = (next_due - today).days
            if next_due < today:
                status_code = 'overdue'
                status_label = f'Протерміновано (на {abs(days_until_next)} дн.)' if abs(days_until_next) > 0 else 'Протерміновано'
                badge_class = 'badge-danger'
                urgent_count += 1
            elif next_due == today:
                status_code = 'today'
                status_label = 'Сьогодні'
                badge_class = 'badge-warning'
                urgent_count += 1
            else:
                status_code = 'upcoming'
                if patient.treatment_start_date and patient.treatment_start_date > today:
                    status_label = f'Початок лікування {patient.treatment_start_date.strftime("%d.%m.%Y")}'
                else:
                    status_label = f'Через {days_until_next} дн.'
                badge_class = 'badge-info'
                planned_count += 1
        else:
            days_until_next = None
            status_code = 'no_due'
            if patient.treatment_start_date and patient.treatment_start_date > today:
                status_label = f'Початок лікування {patient.treatment_start_date.strftime("%d.%m.%Y")}'
            elif actual_discharge and actual_discharge >= today:
                status_label = f'Виписка {actual_discharge.strftime("%d.%m.%Y")} (аналіз не потрібен)'
            else:
                status_label = 'Не визначено'
            badge_class = 'badge-secondary'

        item = {
            'patient': patient,
            'last_test_date': last_test,
            'days_since_last': days_since_last,
            'next_due_date': next_due,
            'days_until_next': days_until_next,
            'actual_discharge_date': actual_discharge,
            'status_code': status_code,
            'status_label': status_label,
            'badge_class': badge_class,
            'has_radiomodification': has_rm,
        }

        # Фільтрація
        if status_filter == 'urgent' and status_code not in ['overdue', 'today']:
            continue
        elif status_filter == 'radiomod' and not has_rm:
            continue
        elif status_filter == 'standard' and has_rm:
            continue

        patient_items.append(item)

    # Сортування за терміновістю: протерміновані -> сьогодні -> майбутні -> без дати
    def sort_key(item):
        code = item['status_code']
        due = item['next_due_date']
        if code == 'overdue':
            return (0, due or date.max)
        elif code == 'today':
            return (1, due or date.max)
        elif code == 'upcoming':
            return (2, due or date.max)
        else:
            return (3, date.max)

    patient_items.sort(key=sort_key)

    context = {
        'patient_items': patient_items,
        'urgent_count': urgent_count,
        'radiomod_count': radiomod_count,
        'planned_count': planned_count,
        'total_count': patients.count(),
        'today': today,
        'search_query': search_query,
        'status_filter': status_filter,
    }
    return render(request, 'patients/blood_test_list.html', context)


def get_pending_mis_discharge_patients(today=None):
    if today is None:
        today = timezone.localdate()
    patients = Patient.objects.filter(mis_discharged=False).prefetch_related('fractions')
    pending = []
    for p in patients:
        actual_discharge = p.get_actual_discharge_date or p.discharge_date
        if actual_discharge and actual_discharge <= today:
            pending.append({
                'patient': p,
                'actual_discharge': actual_discharge,
                'is_today': actual_discharge == today,
                'days_ago': (today - actual_discharge).days,
            })
    return pending


@login_required
def mis_discharge_list(request):
    today = timezone.localdate()
    search_query = request.GET.get('q', '').strip()

    pending_items = get_pending_mis_discharge_patients(today)

    if search_query:
        q_lower = search_query.lower()
        pending_items = [
            item for item in pending_items
            if q_lower in item['patient'].full_name.lower() or
               (item['patient'].ambulatory_card_number and q_lower in item['patient'].ambulatory_card_number.lower()) or
               (item['patient'].diagnosis and q_lower in item['patient'].diagnosis.lower())
        ]

    # Сортування: сьогоднішні виписки спочатку, потім за датою
    pending_items.sort(key=lambda x: (0 if x['is_today'] else 1, x['actual_discharge']))

    today_count = sum(1 for item in pending_items if item['is_today'])
    past_count = sum(1 for item in pending_items if not item['is_today'])

    context = {
        'pending_items': pending_items,
        'today': today,
        'today_count': today_count,
        'past_count': past_count,
        'total_count': len(pending_items),
        'search_query': search_query,
    }
    return render(request, 'patients/mis_discharge_list.html', context)


@login_required
@require_POST
def confirm_mis_discharge_api(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    patient.mis_discharged = True
    patient.is_active = False  # Переносимо в Архів
    patient.save()

    today = timezone.localdate()
    pending_count = len(get_pending_mis_discharge_patients(today))

    return JsonResponse({
        'success': True,
        'message': f'Пацієнта {patient.full_name} виписано в МІС та перенесено в архів.',
        'patient_id': patient.id,
        'pending_mis_count': pending_count,
    })


@login_required
@require_POST
def quick_update_patient_api(request, pk):
    """
    Повне миттєве інлайн-оновлення ВСІХ полів пацієнта прямо в картці
    (ПІБ, Діагноз, Стадія, Гістологія, Лікування, Дати, Госпіталізація, Нотатки тощо)
    з автоматичним перерахунком фракцій, СОД та дати виписки без переходів на інші сторінки.
    """
    patient = get_object_or_404(Patient, pk=pk)
    
    try:
        data = json.loads(request.body)
    except Exception:
        data = request.POST
        
    from django.utils.dateparse import parse_date
    
    def parse_ukrainian_date(val_str):
        if not val_str or not str(val_str).strip():
            return None
        val_str = str(val_str).strip()
        parsed = parse_date(val_str)
        if not parsed:
            try:
                parts = val_str.split('.')
                if len(parts) == 3:
                    parsed = date(int(parts[2]), int(parts[1]), int(parts[0]))
            except (ValueError, IndexError):
                parsed = None
        return parsed

    # 1. Особисті дані
    if 'last_name' in data and data.get('last_name'):
        patient.last_name = data.get('last_name').strip()
    if 'first_name' in data and data.get('first_name'):
        patient.first_name = data.get('first_name').strip()
    if 'middle_name' in data:
        patient.middle_name = data.get('middle_name', '').strip() or None
    if 'birth_date' in data:
        patient.birth_date = parse_ukrainian_date(data.get('birth_date'))
    if 'gender' in data and data.get('gender') in ['M', 'F']:
        patient.gender = data.get('gender')
    if 'ambulatory_card_id' in data:
        patient.ambulatory_card_id = data.get('ambulatory_card_id', '').strip() or None
    if 'has_radiomodification' in data:
        patient.has_radiomodification = bool(data.get('has_radiomodification'))

    # 2. Діагноз та стадіювання
    if 'diagnosis' in data and data.get('diagnosis'):
        patient.diagnosis = data.get('diagnosis').strip()
    if 'tnm_staging' in data:
        patient.tnm_staging = data.get('tnm_staging', '').strip() or None
    if 'disease_stage' in data:
        patient.disease_stage = data.get('disease_stage', '').strip() or None
    if 'clinical_group' in data:
        patient.clinical_group = data.get('clinical_group', '').strip() or None
    if 'prior_radiation' in data:
        patient.prior_radiation = data.get('prior_radiation', '').strip() or None
    if 'raw_diagnosis' in data:
        patient.raw_diagnosis = data.get('raw_diagnosis', '').strip() or None

    # 3. Дати
    if 'ct_simulation_date' in data:
        patient.ct_simulation_date = parse_ukrainian_date(data.get('ct_simulation_date'))
        
    start_date_changed = False
    if 'treatment_start_date' in data:
        old_start = patient.treatment_start_date
        new_start = parse_ukrainian_date(data.get('treatment_start_date'))
        if old_start != new_start:
            patient.treatment_start_date = new_start
            start_date_changed = True
            
    # 4. Фракції та дози
    fractions_changed = False
    if 'total_fractions' in data:
        tf_raw = data.get('total_fractions')
        try:
            new_tf = int(tf_raw) if tf_raw is not None and str(tf_raw).strip() != '' else None
            if patient.total_fractions != new_tf:
                patient.total_fractions = new_tf
                fractions_changed = True
        except (ValueError, TypeError):
            pass
            
    if 'dose_per_fraction' in data:
        raw_dose = data.get('dose_per_fraction')
        patient.parse_and_set_doses(raw_dose)
        
    if 'treatment_type' in data:
        patient.treatment_type = data.get('treatment_type', '').strip() or None

    # 5. Госпіталізація та ліжковий фонд
    if 'hospitalization_status' in data:
        hs = data.get('hospitalization_status')
        if hs in ['outpatient', 'inpatient', 'queue']:
            patient.hospitalization_status = hs
            
    if 'bed_owner' in data:
        patient.bed_owner = data.get('bed_owner') or None
        
    if 'ward_number' in data:
        patient.ward_number = data.get('ward_number') or None
        
    if 'planned_admission_date' in data:
        patient.planned_admission_date = parse_ukrainian_date(data.get('planned_admission_date'))
        
    if 'irradiation_zone' in data:
        patient.irradiation_zone = data.get('irradiation_zone') or None

    # 6. Гістологія
    if 'histology_number' in data:
        patient.histology_number = data.get('histology_number', '').strip() or None
    if 'histology_date' in data:
        patient.histology_date = parse_ukrainian_date(data.get('histology_date'))
    if 'histology_description' in data:
        patient.histology_description = data.get('histology_description', '').strip() or None
        
    # 7. Нотатки
    if 'notes' in data:
        patient.notes = data.get('notes') or None

    # Авто-генерація або зсув фракцій
    if patient.treatment_start_date and patient.total_fractions and patient.dose_per_fraction:
        if not patient.fractions.exists():
            from .services import generate_fractions_for_patient
            generate_fractions_for_patient(patient)
        elif start_date_changed or fractions_changed:
            from .services import shift_patient_schedule
            shift_patient_schedule(patient)
            
    from .services import recalculate_discharge_date
    patient.recalculate_received_dose()
    recalculate_discharge_date(patient)
    patient.save()
    patient.refresh_from_db()
    
    actual_discharge = patient.get_actual_discharge_date
    actual_discharge_str = actual_discharge.strftime('%d.%m.%Y') if actual_discharge else '—'
    
    info = get_patient_treatment_info(patient)
    
    return JsonResponse({
        'success': True,
        'message': 'Дані пацієнта успішно збережено!',
        'full_name': patient.full_name,
        'last_name': patient.last_name,
        'first_name': patient.first_name,
        'middle_name': patient.middle_name or '',
        'birth_date': patient.birth_date.strftime('%d.%m.%Y') if patient.birth_date else '—',
        'gender_display': patient.get_gender_display(),
        'ambulatory_card_id': patient.ambulatory_card_id or '—',
        'has_radiomodification': patient.has_radiomodification,
        'diagnosis': patient.diagnosis,
        'tnm_staging': patient.tnm_staging or '—',
        'disease_stage': patient.disease_stage or '—',
        'clinical_group': patient.clinical_group or '—',
        'treatment_type': patient.treatment_type or '—',
        'display_stage': patient.display_stage,
        'discharge_date': actual_discharge_str,
        'ct_simulation_date': patient.ct_simulation_date.strftime('%d.%m.%Y') if patient.ct_simulation_date else '—',
        'treatment_start_date': patient.treatment_start_date.strftime('%d.%m.%Y') if patient.treatment_start_date else '—',
        'total_fractions': patient.total_fractions or 0,
        'dose_per_fraction_display': patient.dose_per_fraction_display,
        'received_dose_display': patient.received_dose_display,
        'planned_total_dose_display': patient.planned_total_dose_display,
        'current_fraction': patient.current_fraction,
        'hospitalization_status': patient.hospitalization_status,
        'hospitalization_status_display': patient.get_hospitalization_status_display(),
        'bed_owner': patient.bed_owner or '—',
        'ward_number': patient.ward_number or '—',
        'planned_admission_date': patient.planned_admission_date.strftime('%d.%m.%Y') if patient.planned_admission_date else '—',
        'irradiation_zone': patient.irradiation_zone or '—',
        'prior_radiation': patient.prior_radiation or '—',
        'histology_number': patient.histology_number or '—',
        'histology_date': patient.histology_date.strftime('%d.%m.%Y') if patient.histology_date else '—',
        'histology_description': patient.histology_description or '—',
        'notes': patient.notes or '',
        'completed_fractions': info['completed_fractions'],
        'has_fractions': patient.fractions.exists(),
    })


@login_required
def treatment_protocol_list(request):
    """Сторінка управління клінічними протоколами / шаблонами лікування"""
    protocols = TreatmentProtocol.objects.all()
    return render(request, 'patients/treatment_protocol_list.html', {
        'protocols': protocols,
    })


@login_required
@require_POST
def save_protocol_api(request):
    """Створення або редагування шаблону протоколу лікування"""
    try:
        data = json.loads(request.body)
    except Exception:
        data = request.POST
        
    pk = data.get('id')
    name = data.get('name', '').strip()
    if not name:
        return JsonResponse({'success': False, 'error': 'Вкажіть назву шаблону!'}, status=400)
        
    raw_dose = data.get('dose_per_fraction_raw', '').strip().replace(',', '.')
    if not raw_dose:
        return JsonResponse({'success': False, 'error': 'Вкажіть РОД (Гр)!'}, status=400)
        
    try:
        total_fractions = int(data.get('total_fractions', 0))
    except (ValueError, TypeError):
        return JsonResponse({'success': False, 'error': 'Вкажіть коректну кількість фракцій!'}, status=400)
        
    if pk:
        protocol = get_object_or_404(TreatmentProtocol, pk=pk)
    else:
        protocol = TreatmentProtocol()
        
    protocol.name = name
    protocol.irradiation_zone = data.get('irradiation_zone', '').strip() or None
    protocol.treatment_type = data.get('treatment_type', '').strip() or None
    protocol.total_fractions = total_fractions
    protocol.dose_per_fraction_raw = raw_dose
    protocol.has_radiomodification = bool(data.get('has_radiomodification', False))
    protocol.save()
    
    return JsonResponse({
        'success': True,
        'message': f'Шаблон "{protocol.name}" успішно збережено!',
        'id': protocol.id,
        'name': protocol.name,
    })


@login_required
@require_POST
def delete_protocol_api(request, pk):
    protocol = get_object_or_404(TreatmentProtocol, pk=pk)
    name = protocol.name
    protocol.delete()
    return JsonResponse({'success': True, 'message': f'Шаблон "{name}" успішно видалено!'})


@login_required
def get_protocols_api(request):
    protocols = list(TreatmentProtocol.objects.values(
        'id', 'name', 'irradiation_zone', 'treatment_type',
        'total_fractions', 'dose_per_fraction_raw', 'has_radiomodification'
    ))
    return JsonResponse({'success': True, 'protocols': protocols})


@login_required
@require_POST
def pause_patient_treatment_api(request, pk):
    """Індивідуальна пауза курсу пацієнта на N робочих днів"""
    patient = get_object_or_404(Patient, pk=pk)
    try:
        data = json.loads(request.body)
    except Exception:
        data = request.POST
        
    days = int(data.get('days', 1))
    reason = data.get('reason', 'Пауза лікування за клінічними показами').strip()
    
    today = timezone.localdate()
    future_fractions = patient.fractions.filter(date__gte=today, status='scheduled').order_by('date')
    
    if not future_fractions.exists():
        return JsonResponse({'success': False, 'error': 'Немає запланованих фракцій для зсуву!'}, status=400)
        
    from .services import recalculate_discharge_date
    for fr in future_fractions:
        new_date = fr.date
        added = 0
        while added < days:
            new_date += timedelta(days=1)
            if new_date.weekday() < 5:
                added += 1
        fr.date = new_date
        fr.reason = reason
        fr.save()
        
    patient.recalculate_received_dose()
    recalculate_discharge_date(patient)
    patient.save()
    patient.refresh_from_db()
    
    actual_discharge = patient.get_actual_discharge_date
    actual_discharge_str = actual_discharge.strftime('%d.%m.%Y') if actual_discharge else '—'
    
    return JsonResponse({
        'success': True,
        'message': f'Лікування пацієнта {patient.full_name} призупинено на {days} дн. Нова дата виписки: {actual_discharge_str}',
        'discharge_date': actual_discharge_str,
    })


@login_required
@require_POST
def machine_pause_fractions_api(request):
    """Масова технічна перерва лінійника на N робочих днів для всіх активних пацієнтів"""
    try:
        data = json.loads(request.body)
    except Exception:
        data = request.POST
        
    days = int(data.get('days', 1))
    reason = data.get('reason', 'Технічне обслуговування апарата / перерва').strip()
    
    today = timezone.localdate()
    active_patients = Patient.objects.filter(is_active=True, fractions__date__gte=today, fractions__status='scheduled').distinct()
    
    affected_count = 0
    from .services import recalculate_discharge_date
    for patient in active_patients:
        future_fractions = patient.fractions.filter(date__gte=today, status='scheduled').order_by('date')
        if future_fractions.exists():
            affected_count += 1
            for fr in future_fractions:
                new_date = fr.date
                added = 0
                while added < days:
                    new_date += timedelta(days=1)
                    if new_date.weekday() < 5:
                        added += 1
                fr.date = new_date
                fr.reason = reason
                fr.save()
            patient.recalculate_received_dose()
            recalculate_discharge_date(patient)
            patient.save()
            
    return JsonResponse({
        'success': True,
        'message': f'Масову перерву на {days} дн. успішно застосовано для {affected_count} пацієнтів!',
        'affected_count': affected_count,
    })


@login_required
@require_POST
def bulk_confirm_blood_tests_api(request):
    """Масове підтвердження здачі аналізів крові для вибраних пацієнтів за сьогодні"""
    try:
        data = json.loads(request.body)
    except Exception:
        data = request.POST
        
    patient_ids = data.get('patient_ids', [])
    if not patient_ids:
        return JsonResponse({'success': False, 'error': 'Виберіть хоча б одного пацієнта!'}, status=400)
        
    today = timezone.localdate()
    updated_count = 0
    for pid in patient_ids:
        try:
            patient = Patient.objects.get(pk=pid)
            patient.last_blood_test_date = today
            patient.save()
            updated_count += 1
        except Patient.DoesNotExist:
            continue
            
    return JsonResponse({
        'success': True,
        'message': f'Успішно підтверджено аналізи для {updated_count} пацієнтів!',
        'updated_count': updated_count,
    })



@login_required
@require_POST
def confirm_no_mvtn_api(request, pk):
    """Фіксує, що пацієнту лікарняний не потрібен (пенсіонер, безробітний тощо)"""
    patient = get_object_or_404(Patient, pk=pk)
    incapacity, created = MedicalIncapacity.objects.get_or_create(
        patient=patient,
        no_employment_relation=True,
        defaults={'created_at': timezone.now()}
    )
    incapacity.no_employment_relation = True
    incapacity.save()
    
    today = timezone.localdate()
    pending_count = len(get_pending_mvtn_staging_patients(today))
    
    return JsonResponse({
        'success': True,
        'message': f'Пацієнта {patient.full_name} знято з контролю МВТН.',
        'patient_id': patient.id,
        'incapacity_id': incapacity.id,
        'pending_mvtn_count': pending_count,
    })


@login_required
@require_POST
def undo_no_mvtn_api(request, pk):
    """Скасовує фіксацію "Лікарняний не потрібен", повертаючи пацієнта під контроль МВТН"""
    patient = get_object_or_404(Patient, pk=pk)
    MedicalIncapacity.objects.filter(patient=patient, no_employment_relation=True).delete()
    
    today = timezone.localdate()
    pending_count = len(get_pending_mvtn_staging_patients(today))
    
    return JsonResponse({
        'success': True,
        'message': f'Контроль МВТН відновлено для {patient.full_name}.',
        'patient_id': patient.id,
        'pending_mvtn_count': pending_count,
    })


@login_required
@require_POST
def save_mvtn_staging_api(request, pk):
    """Зберігає відкритий МВТН із валідацією дат для відстійника МВТН"""
    patient = get_object_or_404(Patient, pk=pk)
    
    try:
        data = json.loads(request.body)
    except Exception:
        data = request.POST
        
    start_date_str = data.get('start_date', '').strip()
    end_date_str = data.get('end_date', '').strip()
    mvt_number = data.get('mvt_number', '').strip()
    
    from django.utils.dateparse import parse_date
    def parse_ukrainian_date(val_str):
        if not val_str:
            return None
        parsed = parse_date(val_str)
        if not parsed:
            try:
                parts = val_str.split('.')
                if len(parts) == 3:
                    parsed = date(int(parts[2]), int(parts[1]), int(parts[0]))
            except (ValueError, IndexError):
                parsed = None
        return parsed

    start_date = parse_ukrainian_date(start_date_str) or patient.treatment_start_date or patient.ct_simulation_date
    end_date = parse_ukrainian_date(end_date_str)
    
    if not end_date:
        return JsonResponse({'success': False, 'error': 'Будь ласка, вкажіть дату закінчення МВТН!'}, status=400)
        
    today = timezone.localdate()
    if end_date < today:
        return JsonResponse({'success': False, 'error': 'Дата закінчення МВТН не може бути в минулому!'}, status=400)
        
    if start_date and end_date < start_date:
        return JsonResponse({'success': False, 'error': 'Дата закінчення МВТН не може бути раніше дати початку!'}, status=400)
        
    MedicalIncapacity.objects.create(
        patient=patient,
        mvt_number=mvt_number or None,
        start_date=start_date,
        end_date=end_date,
        created_at=timezone.now(),
        updated_at=timezone.now()
    )
    
    pending_count = len(get_pending_mvtn_staging_patients(today))
    
    return JsonResponse({
        'success': True,
        'message': f'МВТН для {patient.full_name} успішно збережено дійсним до {end_date.strftime("%d.%m.%Y")}.',
        'patient_id': patient.id,
        'end_date': end_date.strftime('%d.%m.%Y'),
        'pending_mvtn_count': pending_count,
    })


@login_required
@require_POST
def add_boost_phase_api(request, pk):
    """
    Додає послідовний буст / 2-й етап лікування до існуючого курсу пацієнта:
    - Зберігає всі попередні фракції (пройдені та заплановані) без змін.
    - Додає N нових фракцій з вказаною РОД бусту (наприклад 2.0 Гр) на наступні робочі дні.
    - Оновлює загальну кількість фракцій (total_fractions), планову СОД та дату виписки.
    """
    patient = get_object_or_404(Patient, pk=pk)
    
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Невірний JSON'}, status=400)
        
    try:
        boost_fractions = int(data.get('boost_fractions', 5))
        if boost_fractions <= 0:
            return JsonResponse({'success': False, 'error': 'Кількість фракцій повинна бути більше 0'}, status=400)
    except (ValueError, TypeError):
        return JsonResponse({'success': False, 'error': 'Некоректна кількість фракцій'}, status=400)
        
    try:
        boost_dose = float(str(data.get('boost_dose', 2.0)).replace(',', '.'))
        if boost_dose <= 0:
            return JsonResponse({'success': False, 'error': 'РОД бусту повинна бути більше 0'}, status=400)
    except (ValueError, TypeError):
        return JsonResponse({'success': False, 'error': 'Некоректна доза бусту'}, status=400)
        
    boost_zone = data.get('boost_zone', 'Ложе пухлини (буст)').strip()
    custom_start_date_str = data.get('boost_start_date', '').strip()
    
    # Визначаємо дату початку бусту
    start_date = None
    if custom_start_date_str:
        start_date = parse_ukrainian_date(custom_start_date_str)
        
    if not start_date:
        latest_fraction = patient.fractions.order_by('date').last()
        if latest_fraction:
            next_date = latest_fraction.date + timedelta(days=1)
            while next_date.weekday() >= 5:  # skip Sat/Sun
                next_date += timedelta(days=1)
            start_date = next_date
        elif patient.treatment_start_date:
            start_date = patient.treatment_start_date
        else:
            start_date = timezone.localdate()
            
    # Генеруємо нові фракції бусту
    new_fractions = []
    current_date = start_date
    for i in range(boost_fractions):
        while current_date.weekday() >= 5:
            current_date += timedelta(days=1)
            
        fraction = FractionHistory(
            patient=patient,
            date=current_date,
            dose=boost_dose,
            note=f"Буст: {boost_zone}" if boost_zone else "Буст",
            status='scheduled'
        )
        new_fractions.append(fraction)
        current_date += timedelta(days=1)
        
    FractionHistory.objects.bulk_create(new_fractions)
    
    # Оновлюємо загальну кількість фракцій пацієнта
    patient.total_fractions = patient.fractions.count()
    
    # Оновлюємо дату виписки
    latest_frac = patient.fractions.order_by('date').last()
    if latest_frac:
        patient.discharge_date = latest_frac.date
        
    patient.recalculate_received_dose()
    patient.save()
    
    return JsonResponse({
        'success': True,
        'message': f'Успішно додано буст: {boost_fractions} фр. × {boost_dose} Гр. Загальний курс: {patient.total_fractions} фр. (СОД: {patient.planned_total_dose_display}). Дата виписки: {patient.discharge_date.strftime("%d.%m.%Y") if patient.discharge_date else "—"}',
        'total_fractions': patient.total_fractions,
        'planned_total_dose_display': patient.planned_total_dose_display,
        'received_dose_display': patient.received_dose_display,
        'discharge_date': patient.discharge_date.strftime('%d.%m.%Y') if patient.discharge_date else '—',
        'next_boost_start': start_date.strftime('%d.%m.%Y'),
    })



