from django.shortcuts import render, get_object_or_404, redirect
from .models import Patient, FractionHistory, MedicalIncapacity, User
from .forms import PatientForm, FractionHistoryForm, MedicalIncapacityForm, UserRegistrationForm, UserLoginForm, FractionEditForm
from django.http import JsonResponse
from datetime import date, timedelta
from django.contrib.auth import login, logout, authenticate
from django.contrib import messages
from django.db.models import Q, Count
from django.db import models
from django.utils import timezone
from .services import generate_fractions_for_patient, auto_confirm_today_fractions, get_patient_treatment_info
from django.views.decorators.csrf import csrf_exempt
import json
from django.views.decorators.http import require_POST
from .decorators import login_required, staff_required, admin_required
import os
from google import genai
from pydantic import BaseModel, Field
from typing import Optional
from PIL import Image
import io

# Create your views here.

def splash(request):
    """Головна сторінка - перенаправляє на дашборд або логін"""
    if request.user.is_authenticated:
        return redirect('dashboard')
    else:
        return redirect('login')

@login_required
def dashboard(request):
    today = date.today()
    
    # Статистика на сьогодні
    ct_today_count = Patient.objects.filter(
        ct_simulation_date=today
    ).count()
    
    start_today_count = Patient.objects.filter(
        treatment_start_date=today
    ).count()
    
    discharge_today_count = Patient.objects.filter(
        discharge_date=today
    ).count()
    
    # Загальна статистика - використовуємо фільтрацію за датами замість current_stage
    ct_count = Patient.objects.filter(
        ct_simulation_date__isnull=False,
        treatment_start_date__isnull=True
    ).count()
    
    start_count = Patient.objects.filter(
        treatment_start_date__isnull=False,
        treatment_start_date__gt=today
    ).count()
    
    in_treatment_count = Patient.objects.filter(
        treatment_start_date__isnull=False,
        treatment_start_date__lte=today,
        discharge_date__isnull=True
    ).count()
    
    # Сповіщення про аналізи крові
    notifications = []
    in_treatment = Patient.objects.filter(
        treatment_start_date__isnull=False,
        treatment_start_date__lte=today,
        discharge_date__isnull=True
    )
    for patient in in_treatment:
        last = patient.last_blood_test_date or patient.treatment_start_date
        if not last or (today - last).days >= 10:
            notifications.append({'patient': patient})
    
    # Виписані цього тижня
    from_date = today - timedelta(days=7)
    discharged_this_week = Patient.objects.filter(
        discharge_date__isnull=False,
        discharge_date__gte=from_date
    ).count()
    
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
    
    # Фракції на сьогодні (для всіх пацієнтів)
    today_fractions = FractionHistory.objects.filter(
        date=today
    ).select_related('patient').order_by('patient__last_name', 'patient__first_name')
    
    # Отримуємо пацієнтів, які мають фракції
    patients_with_fractions = Patient.objects.filter(
        fractions__isnull=False
    ).distinct().prefetch_related(
        'fractions'
    ).order_by('last_name', 'first_name')
    
    # Групуємо фракції по пацієнтах
    patients_data = []
    for patient in patients_with_fractions:
        fractions = patient.fractions.all().order_by('date')
        patients_data.append({
            'patient': patient,
            'fractions': fractions,
            'total_fractions': fractions.count(),
            'completed_fractions': fractions.filter(delivered=True).count(),
            'pending_fractions': fractions.filter(delivered=False).count()
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
            
            fraction = form.save()
            
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
    fractions = patient.fractions.all().order_by('-date')
    incapacities = patient.medical_incapacities.all().order_by('-created_at')
    treatment_info = get_patient_treatment_info(patient)
    
    # Підрахунки для статистики фракцій
    missed_fractions_count = patient.fractions.filter(is_missed=True).count()
    postponed_fractions_count = patient.fractions.filter(is_postponed=True).count()
    
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
    """Список стаціонарних пацієнтів"""
    inpatients = Patient.objects.filter(
        inpatient_status='стаціонарно',
        discharge_date__isnull=True
    ).order_by('last_name', 'first_name')
    
    return render(request, 'patients/inpatient_list.html', {
        'patients': inpatients
    })

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
    
    # Отримуємо всі фракції на сьогодні
    today_fractions = FractionHistory.objects.filter(date=today)
    
    delivered_count = 0
    missed_count = 0
    
    for fraction in today_fractions:
        if fraction.id in delivered_ids:
            # Фракція виконана
            fraction.delivered = True
            fraction.confirmed_by_doctor = True
            fraction.is_missed = False
            delivered_count += 1
        else:
            # Фракція пропущена
            fraction.delivered = False
            fraction.confirmed_by_doctor = False
            fraction.is_missed = True
            missed_count += 1
        fraction.save()
    
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
    fractions_to_update = patient.fractions.filter(delivered=True, confirmed_by_doctor=False)
    count = fractions_to_update.count()
    if count > 0:
        for fraction in fractions_to_update:
            fraction.confirmed_by_doctor = True
        FractionHistory.objects.bulk_update(fractions_to_update, ['confirmed_by_doctor'])
        messages.success(request, f'Затверджено {count} виконаних фракцій для {patient.full_name}.')
    else:
        messages.info(request, f'Немає виконаних фракцій для затвердження для {patient.full_name}.')
        
    referer = request.META.get('HTTP_REFERER')
    if referer:
        return redirect(referer)
    return redirect('patient_detail', pk=pk)

class PatientData(BaseModel):
    last_name: Optional[str] = Field(None, description="Прізвище пацієнта (будь максимально точним при розпізнаванні літер!)")
    first_name: Optional[str] = Field(None, description="Ім'я пацієнта")
    middle_name: Optional[str] = Field(None, description="По батькові пацієнта")
    birth_date: Optional[str] = Field(None, description="Дата народження строго у форматі DD.MM.YYYY (наприклад: 15.04.1980)")
    gender: Optional[str] = Field(None, description="Стать пацієнта. Поверни 'Ч' для чоловічої, 'Ж' для жіночої.")
    icd_code: Optional[str] = Field(None, description="Код діагнозу за МКХ-10 (наприклад: C50.9, C34.1)")
    tumor_morphology: Optional[str] = Field(None, description="Морфологія пухлини (наприклад: інфільтруюча карцинома, аденокарцинома)")
    disease_stage: Optional[str] = Field(None, description="Стадія захворювання римськими цифрами (наприклад: IIA, III, IV). Не плутати з TNM!")
    tnm_t: Optional[str] = Field(None, description="Значення T з системи TNM (наприклад: 2, 3, 4a)")
    tnm_n: Optional[str] = Field(None, description="Значення N з системи TNM (наприклад: 0, 1, 2)")
    tnm_m: Optional[str] = Field(None, description="Значення M з системи TNM (наприклад: 0, 1)")
    clinical_group: Optional[str] = Field(None, description="Клінічна група (наприклад: 2, II, 3)")
    histology_date: Optional[str] = Field(None, description="Дата проведення гістологічного дослідження / ПГЗ строго у форматі DD.MM.YYYY")
    histology_number: Optional[str] = Field(None, description="Номер гістологічного висновку / ПГЗ (наприклад: 12345/23)")
    histology_description: Optional[str] = Field(None, description="Детальний опис патолого-гістологічного висновку")

@login_required
@require_POST
def parse_medical_document(request):
    try:
        if 'file' not in request.FILES:
            return JsonResponse({'error': 'Файл не знайдено'}, status=400)
            
        file = request.FILES['file']
        
        if not file.content_type.startswith('image/'):
            return JsonResponse({'error': 'Підтримуються лише зображення (JPEG, PNG, WEBP)'}, status=400)
            
        api_key = os.environ.get('GEMINI_API_KEY')
        if not api_key:
            return JsonResponse({'error': 'Ключ Gemini API не налаштовано в .env'}, status=500)
            
        client = genai.Client(api_key=api_key)
        
        image = Image.open(io.BytesIO(file.read()))
        
        prompt = """
Ти досвідчений медичний реєстратор. Прочитай надану медичну виписку (епікриз, направлення) та витягни наступні дані:
1. ПІБ пацієнта (звертай особливу увагу на правильність прізвища).
2. Дату народження (ОБОВ'ЯЗКОВО у форматі DD.MM.YYYY).
3. Стать (визнач за ПІБ або текстом: поверни букву 'Ч' для чоловічої, або 'Ж' для жіночої).
4. Діагноз (код МКХ-10 та морфологію).
5. Стадію захворювання (зверни увагу, стадія зазвичай позначається римськими цифрами, наприклад I, IIA, III, IV. Не вписуй сюди TNM).
6. TNM стадіювання (окремо індекси T, N, M).
7. Клінічну групу.
8. Дані гістологічного висновку (ПГЗ, пат. гістологічне дослідження): номер, дату та опис. Дата має бути у форматі DD.MM.YYYY.

Будь дуже уважним до дат і переконайся, що вони конвертовані у формат DD.MM.YYYY (День.Місяць.Рік). Якщо якихось даних немає в тексті, поверни null для цього поля.
"""
        
        response = client.models.generate_content(
            model='gemini-2.5-pro',
            contents=[image, prompt],
            config={
                'response_mime_type': 'application/json',
                'response_schema': PatientData,
            },
        )
        
        data = json.loads(response.text)
        return JsonResponse(data)
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

