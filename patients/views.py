from django.shortcuts import render, get_object_or_404, redirect
from .models import Patient, FractionHistory, MedicalIncapacity, User
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

@login_required
def dashboard(request):
    today = timezone.now().date()
    # Автоматично деактивуємо пацієнтів, у яких завершилося лікування (звільнення ліжок)
    Patient.objects.filter(is_active=True, discharge_date__lt=today).update(is_active=False)
    
    tomorrow = today + timedelta(days=1)
    
    ct_today_count = Patient.objects.filter(ct_simulation_date=today).count()
    start_today_count = Patient.objects.filter(treatment_start_date=today).count()
    
    active_patients_q = Q(discharge_date__isnull=True) | Q(discharge_date__gte=today)
    discharge_today_count = Patient.objects.filter(active_patients_q).annotate(
        actual_discharge_date=Coalesce(
            Max('fractions__date'),
            F('treatment_start_date'),
            output_field=DateField()
        )
    ).filter(
        actual_discharge_date__in=[today, tomorrow]
    ).count()
    
    ct_count = Patient.objects.filter(ct_simulation_date__isnull=False, treatment_start_date__isnull=True).count()
    start_count = Patient.objects.filter(treatment_start_date__isnull=False, treatment_start_date__gt=today).count()
    in_treatment_count = Patient.objects.filter(treatment_start_date__isnull=False, treatment_start_date__lte=today, discharge_date__isnull=True).count()
    
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
        
        # MVTN/Incapacity check
        incapacity = patient.prefetched_incapacities[0] if hasattr(patient, 'prefetched_incapacities') and patient.prefetched_incapacities else None
        if incapacity and incapacity.end_date and incapacity.end_date >= today:
            actual_end = patient.get_actual_discharge_date
            incapacity_end = incapacity.end_date
            cond_a = actual_end and actual_end > incapacity_end
            cond_b = (incapacity_end - today).days <= 2
            
            if cond_a or cond_b:
                actual_end_str = actual_end.strftime('%d.%m.%Y') if actual_end else '—'
                incapacity_end_str = incapacity_end.strftime('%d.%m.%Y')
                message = f"⚠️ У пацієнта {patient.full_name} МВТН НЕ покриває курс лікування або збігає! Діє до: {incapacity_end_str}. Реальне завершення лікування: {actual_end_str}. Потрібно продовжити вручну."
                notifications.append({
                    'type': 'incapacity_alert',
                    'patient': patient,
                    'message': message,
                    'incapacity_end_date': incapacity_end,
                    'actual_discharge_date': actual_end
                })
                
    notifications.sort(key=lambda n: 0 if n['type'] == 'incapacity_alert' else 1)
    
    from_date = today - timedelta(days=7)
    discharged_this_week = Patient.objects.filter(discharge_date__isnull=False, discharge_date__gte=from_date).count()
    
    context = {
        'ct_today_count': ct_today_count,
        'start_today_count': start_today_count,
        'discharge_today_count': discharge_today_count,
        'ct_count': ct_count,
        'start_count': start_count,
        'in_treatment_count': in_treatment_count,
        'discharged_this_week': discharged_this_week,
        'notifications': notifications,
    }
    return render(request, 'patients/dashboard.html', context)

@login_required
def patient_list(request, filter_type=None):
    today = date.today()
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
                treatment_start_date__lte=today,
                discharge_date__isnull=True
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
    
    # Визначаємо поле для сортування
    if sort_by == 'full_name':
        order_field = 'last_name'
    elif sort_by == 'ct_simulation_date':
        order_field = 'ct_simulation_date'
    elif sort_by == 'treatment_start_date':
        order_field = 'treatment_start_date'
    elif sort_by == 'discharge_date':
        order_field = 'discharge_date'
    elif sort_by == 'medical_incapacity_end':
        # Сортування за датою закінчення останнього МВТН
        if sort_order == 'desc':
            patients = patients.annotate(
                latest_incapacity_end=models.Subquery(
                    MedicalIncapacity.objects.filter(
                        patient=models.OuterRef('pk')
                    ).order_by('-end_date').values('end_date')[:1]
                )
            ).order_by('-latest_incapacity_end')
        else:
            patients = patients.annotate(
                latest_incapacity_end=models.Subquery(
                    MedicalIncapacity.objects.filter(
                        patient=models.OuterRef('pk')
                    ).order_by('-end_date').values('end_date')[:1]
                )
            ).order_by('latest_incapacity_end')
        return render(request, 'patients/patient_list.html', {
            'patients': patients,
            'filter_type': filter_type,
            'current_sort': sort_by,
            'current_order': sort_order
        })
    else:
        order_field = 'last_name'
    
    # Додаємо префікс для зворотного сортування
    if sort_order == 'desc':
        order_field = f'-{order_field}'
    
    # Застосовуємо сортування
    patients = patients.order_by(order_field)
        
    return render(request, 'patients/patient_list.html', {
        'patients': patients,
        'filter_type': filter_type,
        'current_sort': sort_by,
        'current_order': sort_order
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
    yesterday = date.today() - timedelta(days=1)
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
    today = date.today()
    active_patients_q = Q(discharge_date__isnull=True) | Q(discharge_date__gte=today)
    
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
        
        for patient_id, earliest_date in patient_earliest_dates.items():
            patient = Patient.objects.get(pk=patient_id)
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
    
    # Групуємо фракції по пацієнтах
    patients_data = []
    for patient in patients_with_fractions:
        fractions = patient.fractions.all().order_by('date')
        completed_count = fractions.filter(status='delivered').count()
        patients_data.append({
            'patient': patient,
            'fractions': fractions,
            'total_fractions': fractions.count(),
            'completed_fractions': completed_count,
            'pending_fractions': fractions.filter(status='scheduled').count(),
            'missed_fractions': fractions.filter(status='missed').count(),
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
    today = date.today()
    is_active = patient.discharge_date is None or patient.discharge_date >= today
    if is_active:
        overdue_fractions = patient.fractions.filter(date__lt=today, status='scheduled').order_by('date')
        if overdue_fractions.exists():
            earliest_date = overdue_fractions.first().date
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
    
    return render(request, 'patients/patient_detail.html', {
        'patient': patient,
        'fractions': fractions,
        'incapacities': incapacities,
        'treatment_info': treatment_info,
        'missed_fractions_count': missed_fractions_count,
        'postponed_fractions_count': postponed_fractions_count
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
    if request.method == 'POST':
        patient = get_object_or_404(Patient, pk=patient_id)
        patient.last_blood_test_date = date.today()
        patient.save()
        messages.success(request, f'Аналіз крові підтверджено для {patient.full_name}')
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
        from .services import recalculate_discharge_date
        new_date = recalculate_discharge_date(patient)
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
    today = timezone.now().date()
    # Автоматично деактивуємо пацієнтів, у яких завершилося лікування (звільнення ліжок)
    Patient.objects.filter(is_active=True, discharge_date__lt=today).update(is_active=False)
    
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
    patient.treatment_start_date = date.today()
    patient.bed_owner = bed_owner
    patient.save()
    
    # Автоматично генеруємо фракції, якщо вказано загальну кількість та РОД
    if patient.total_fractions and patient.dose_per_fraction:
        generate_fractions_for_patient(patient)
        
    messages.success(request, f'Пацієнта {patient.full_name} успішно госпіталізовано.')
    return redirect('inpatient_list')

@login_required
def patient_archive(request):
    """Список пацієнтів в архіві"""
    today = date.today()
    archived_patients = Patient.objects.filter(
        discharge_date__isnull=False,
        discharge_date__lt=today  # Тільки виписані пацієнти (дата виписки в минулому)
    ).order_by('-discharge_date')
    return render(request, 'patients/patient_list.html', {
        'patients': archived_patients,
        'is_archive': True
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
    today = date.today()
    
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
    today = date.today()
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
            next_date = patient.treatment_start_date or date.today()
            
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

