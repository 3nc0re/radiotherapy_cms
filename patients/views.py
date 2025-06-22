from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from .models import Patient, FractionHistory, MedicalIncapacity, User
from .forms import PatientForm, FractionHistoryForm, MedicalIncapacityForm, UserRegistrationForm, UserLoginForm
from django.http import JsonResponse
from datetime import date, timedelta
from django.contrib.auth import login, logout, authenticate
from django.contrib import messages
from django.db.models import Q, Count
from django.utils import timezone
from .services import generate_fractions_for_patient, auto_confirm_today_fractions, get_patient_treatment_info
from django.views.decorators.csrf import csrf_exempt
import json
from django.views.decorators.http import require_POST

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
    
    active_patients = Patient.objects.filter(Q(discharge_date__isnull=True) | Q(discharge_date__gt=today))
    
    # Події на сьогодні
    ct_today_count = active_patients.filter(ct_simulation_date=today).count()
    start_today_count = active_patients.filter(treatment_start_date=today).count()
    discharge_today_count = Patient.objects.filter(discharge_date=today).count()
    
    # Загальна статистика (активні пацієнти)
    ct_count = active_patients.filter(ct_simulation_date__isnull=False, treatment_start_date__isnull=True).count()
    start_count = active_patients.filter(treatment_start_date__gt=today).count()
    in_treatment_count = active_patients.filter(treatment_start_date__lte=today).count()

    # Сповіщення
    notifications = []
    
    # 1. Сповіщення про аналізи крові
    in_treatment_patients = active_patients.filter(treatment_start_date__lte=today)
    for patient in in_treatment_patients:
        reference_date = patient.last_blood_test_date or patient.treatment_start_date
        if reference_date:
            due_date = reference_date + timedelta(days=10)
            if due_date.weekday() == 5: due_date -= timedelta(days=1)
            elif due_date.weekday() == 6: due_date -= timedelta(days=2)
            if today >= due_date:
                notifications.append({'type': 'blood_test', 'patient': patient, 'due_date': due_date})

    # 2. Сповіщення про закінчення МВТН
    expiry_limit_date = today + timedelta(days=3)
    patients_with_incapacity = active_patients.filter(medical_incapacities__isnull=False).distinct()
    for patient in patients_with_incapacity:
        latest_incapacity = patient.get_latest_medical_incapacity()
        if latest_incapacity and today <= latest_incapacity.end_date <= expiry_limit_date:
            if patient.discharge_date is None or patient.discharge_date > latest_incapacity.end_date:
                notifications.append({'type': 'incapacity', 'patient': patient, 'incapacity_end_date': latest_incapacity.end_date})

    # Виписані за останні 7 днів
    seven_days_ago = today - timedelta(days=7)
    discharged_this_week = Patient.objects.filter(discharge_date__gte=seven_days_ago, discharge_date__lte=today).count()
    
    context = {
        'ct_today_count': ct_today_count, 'start_today_count': start_today_count, 'discharge_today_count': discharge_today_count,
        'ct_count': ct_count, 'start_count': start_count, 'in_treatment_count': in_treatment_count,
        'discharged_this_week': discharged_this_week, 'notifications': notifications,
    }
    return render(request, 'patients/dashboard.html', context)

@login_required
def patient_list(request, filter_type=None):
    today = timezone.now().date()
    
    active_patients = Patient.objects.filter(Q(discharge_date__isnull=True) | Q(discharge_date__gt=today))

    if filter_type == 'ct-simulation':
        patients = active_patients.filter(ct_simulation_date__isnull=False, treatment_start_date__isnull=True).order_by('ct_simulation_date')
    elif filter_type == 'treatment-start':
        patients = active_patients.filter(treatment_start_date__gt=today).order_by('treatment_start_date')
    elif filter_type == 'in-treatment':
        # Пацієнти, що на лікуванні, але ще не готуються до виписки
        three_days_later = today + timedelta(days=3)
        patients = active_patients.filter(
            treatment_start_date__lte=today
        ).exclude(
            discharge_date__gt=today,
            discharge_date__lte=three_days_later
        ).order_by('last_name')
    elif filter_type == 'discharge-prep':
        three_days_later = today + timedelta(days=3)
        patients = active_patients.filter(discharge_date__gt=today, discharge_date__lte=three_days_later).order_by('discharge_date')
    elif filter_type == 'archive':
        patients = Patient.objects.filter(discharge_date__lte=today).order_by('-discharge_date')
    else:
        patients = active_patients.order_by('last_name', 'first_name')
        
    return render(request, 'patients/patient_list.html', {
        'patients': patients,
        'filter_type': filter_type
    })

@login_required
def inpatient_list(request):
    patients = Patient.objects.filter(inpatient_status='стаціонарно').order_by('ward_number', 'last_name')
    return render(request, 'patients/inpatient_list.html', {'patients': patients})

@login_required
def patient_create(request):
    if request.method == 'POST':
        form = PatientForm(request.POST)
        if form.is_valid():
            form.save()
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
            form.save()
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
def fraction_list(request):
    fractions = FractionHistory.objects.filter(
        Q(confirmed_by_doctor=False) | Q(delivered=False)
    ).select_related('patient').order_by('date')
    return render(request, 'patients/fraction_list.html', {'fractions': fractions})

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
def medical_incapacity_delete(request, pk):
    incapacity = get_object_or_404(MedicalIncapacity, pk=pk)
    patient_pk = incapacity.patient_id
    if request.method == 'POST':
        incapacity.delete()
        return redirect('patient_detail', pk=patient_pk)
    return render(request, 'patients/medical_incapacity_confirm_delete.html', {'incapacity': incapacity})

@login_required
def patient_detail(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    fractions = patient.fractions.all().order_by('-date')
    incapacities = patient.medical_incapacities.all().order_by('-created_at')
    treatment_info = get_patient_treatment_info(patient)

    # Логіка сповіщень для конкретного пацієнта
    today = timezone.now().date()
    notifications = []

    # 1. Сповіщення про аналіз крові
    if patient.display_stage == "Лікування":
        reference_date = patient.last_blood_test_date or patient.treatment_start_date
        if reference_date:
            due_date = reference_date + timedelta(days=10)
            if due_date.weekday() == 5: due_date -= timedelta(days=1)
            elif due_date.weekday() == 6: due_date -= timedelta(days=2)
            if today >= due_date:
                notifications.append({'type': 'blood_test', 'due_date': due_date})

    # 2. Сповіщення про закінчення МВТН
    latest_incapacity = patient.get_latest_medical_incapacity()
    if latest_incapacity:
        expiry_limit_date = today + timedelta(days=3)
        if today <= latest_incapacity.end_date <= expiry_limit_date:
            if patient.discharge_date is None or patient.discharge_date > latest_incapacity.end_date:
                notifications.append({'type': 'incapacity', 'incapacity_end_date': latest_incapacity.end_date})
    
    return render(request, 'patients/patient_detail.html', {
        'patient': patient,
        'fractions': fractions,
        'incapacities': incapacities,
        'treatment_info': treatment_info,
        'notifications': notifications
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

@login_required
def admin_approve_user(request, user_id):
    if request.user.role != 'admin':
        messages.error(request, 'Доступ заборонено')
        return redirect('dashboard')
    
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
@require_POST
def approve_user(request, pk):
    if not request.user.is_superuser and request.user.role != 'admin':
        return redirect('dashboard')
    user_to_approve = get_object_or_404(User, pk=pk)
    user_to_approve.approved = True
    user_to_approve.save()
    messages.success(request, f"Користувача {user_to_approve.username} було затверджено.")
    return redirect('admin_users')

@login_required
@require_POST
def confirm_fractions_doctor(request):
    fraction_ids = request.POST.getlist('fraction_ids')
    if fraction_ids:
        FractionHistory.objects.filter(id__in=fraction_ids).update(confirmed_by_doctor=True)
        messages.success(request, f"Підтверджено {len(fraction_ids)} фракцій лікарем.")
    return redirect('fraction_list')

@login_required
@require_POST
def confirm_fractions_nurse(request):
    fraction_ids = request.POST.getlist('fraction_ids')
    if fraction_ids:
        FractionHistory.objects.filter(id__in=fraction_ids).update(delivered=True)
        messages.success(request, f"Підтверджено {len(fraction_ids)} фракцій медсестрою.")
    return redirect('fraction_list')
