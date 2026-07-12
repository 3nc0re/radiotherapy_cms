from datetime import date, timedelta
from django.db.models import Q
from .models import Patient, FractionHistory

def generate_fractions_for_patient(patient, start_date=None, total_fractions=None, dose_per_fraction=None):
    """Генерує фракції для пацієнта"""
    if not start_date:
        start_date = patient.treatment_start_date
    if not total_fractions:
        total_fractions = patient.total_fractions
    if not dose_per_fraction:
        dose_per_fraction = patient.dose_per_fraction
    
    if not all([start_date, total_fractions, dose_per_fraction]):
        return False
    
    # Видаляємо існуючі фракції
    FractionHistory.objects.filter(patient=patient).delete()
    
    # Генеруємо нові фракції
    fractions = []
    current_date = start_date
    
    for i in range(total_fractions):
        # Пропускаємо вихідні (субота, неділя)
        while current_date.weekday() >= 5:  # 5=субота, 6=неділя
            current_date += timedelta(days=1)
        
        fraction = FractionHistory(
            patient=patient,
            date=current_date,
            dose=dose_per_fraction,
            status='scheduled'
        )
        fractions.append(fraction)
        current_date += timedelta(days=1)
    
    FractionHistory.objects.bulk_create(fractions)
    
    # Завжди встановлюємо дату виписки на основі останньої фракції
    if fractions:
        patient.discharge_date = fractions[-1].date
        patient.save()
        print(f"Встановлено дату виписки для {patient.full_name}: {patient.discharge_date}")
    
    return True

def auto_confirm_today_fractions():
    """Автоматично підтверджує фракції за сьогодні"""
    today = date.today()
    active_patients_q = Q(discharge_date__isnull=True) | Q(discharge_date__gte=today)
    active_patients = Patient.objects.filter(active_patients_q)
    
    today_fractions = FractionHistory.objects.filter(
        date=today,
        patient__in=active_patients,
        status='scheduled'
    )
    
    count = today_fractions.count()
    if count > 0:
        today_fractions.update(status='delivered')
        for patient in active_patients:
            patient.recalculate_received_dose()
            
    return count

def get_patient_treatment_info(patient):
    """Отримує інформацію про лікування пацієнта"""
    total_fractions = patient.total_fractions or 0
    completed_fractions = patient.fractions.filter(status='delivered').count()
    remaining_fractions = total_fractions - completed_fractions
    
    return {
        'total_fractions': total_fractions,
        'completed_fractions': completed_fractions,
        'remaining_fractions': remaining_fractions,
        'progress_percentage': (completed_fractions / total_fractions * 100) if total_fractions > 0 else 0
    }

def calculate_discharge_date(patient):
    """Розраховує очікувану дату виписки на основі фракцій"""
    if not patient.treatment_start_date or not patient.total_fractions:
        return None
    
    # Рахуємо робочі дні для всіх фракцій
    current_date = patient.treatment_start_date
    working_days = 0
    
    while working_days < patient.total_fractions:
        if current_date.weekday() < 5:  # Пн-Пт
            working_days += 1
        current_date += timedelta(days=1)
    
    return current_date - timedelta(days=1)

def recalculate_discharge_date(patient):
    """Перераховує дату виписки на основі поточних фракцій"""
    # Знаходимо останню фракцію
    last_fraction = patient.fractions.order_by('date').last()
    if last_fraction:
        patient.discharge_date = last_fraction.date
        patient.save()
        return patient.discharge_date
    return None

def set_discharge_date_from_fractions(patient):
    """Встановлює дату виписки на основі згенерованих фракцій"""
    if patient.fractions.exists():
        last_fraction = patient.fractions.order_by('date').last()
        patient.discharge_date = last_fraction.date
        patient.save()
        return patient.discharge_date
    return None

def shift_patient_schedule(patient, from_date=None):
    """
    Повністю перебудовує розклад майбутніх фракцій пацієнта.
    Замість того, щоб просто зсувати дати (що створює порожні дні),
    ми рахуємо скільки фракцій залишилося отримати, і безперервно
    заповнюємо ними майбутні робочі дні.
    Оновлює існуючі заплановані фракції in-place, щоб зберегти їхні ID,
    і достворює/видаляє зайві при необхідності.
    """
    from django.utils import timezone
    total = patient.total_fractions or 0
    if total <= 0:
        return

    today = timezone.localdate()
    
    if from_date is None:
        if patient.treatment_start_date:
            from_date = max(today, patient.treatment_start_date)
        else:
            from_date = today

    delivered_count = patient.fractions.filter(status='delivered').count()
    remaining = total - delivered_count
    
    # Отримуємо заплановані фракції на/після from_date
    scheduled_to_update = list(patient.fractions.filter(status='scheduled', date__gte=from_date).order_by('date'))
    
    # Визначаємо список "зайнятих" дат (де вже є delivered, missed, або scheduled ДО from_date)
    occupied_dates = set(patient.fractions.filter(
        Q(status__in=['delivered', 'missed']) | Q(status='scheduled', date__lt=from_date)
    ).values_list('date', flat=True))
    
    if remaining <= 0:
        patient.fractions.filter(status='scheduled', date__gte=from_date).delete()
        recalculate_discharge_date(patient)
        return

    # Скільки фракцій заплановано ДО from_date?
    scheduled_before_from_date = patient.fractions.filter(status='scheduled', date__lt=from_date).count()
    
    # Отже, на/після from_date нам потрібно запланувати:
    needed_on_or_after = remaining - scheduled_before_from_date
    
    if needed_on_or_after <= 0:
        patient.fractions.filter(status='scheduled', date__gte=from_date).delete()
        recalculate_discharge_date(patient)
        return
        
    target_dates = []
    current_date = from_date
    while len(target_dates) < needed_on_or_after:
        while current_date.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
            current_date += timezone.timedelta(days=1)
        if current_date in occupied_dates:
            current_date += timezone.timedelta(days=1)
            continue
        target_dates.append(current_date)
        current_date += timezone.timedelta(days=1)

    # Оновлюємо або створюємо/видаляємо фракції in-place
    num_to_update = min(len(scheduled_to_update), len(target_dates))
    
    for i in range(num_to_update):
        fraction = scheduled_to_update[i]
        fraction.date = target_dates[i]
        fraction.dose = patient.dose_per_fraction or 0.0
        fraction.save()
        
    if len(target_dates) > len(scheduled_to_update):
        new_fractions = []
        for i in range(num_to_update, len(target_dates)):
            new_fractions.append(FractionHistory(
                patient=patient,
                date=target_dates[i],
                dose=patient.dose_per_fraction or 0.0,
                status='scheduled'
            ))
        if new_fractions:
            FractionHistory.objects.bulk_create(new_fractions)
            
    elif len(scheduled_to_update) > len(target_dates):
        ids_to_delete = [f.id for f in scheduled_to_update[num_to_update:]]
        patient.fractions.filter(id__in=ids_to_delete).delete()
        
    recalculate_discharge_date(patient)


def encrypt_notes(text: str) -> str:
    """Шифрує текст нотаток за допомогою Fernet та SECRET_KEY сервера"""
    if not text:
        return ""
    import base64
    import hashlib
    from django.conf import settings
    from cryptography.fernet import Fernet
    
    key_hash = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    key = base64.urlsafe_b64encode(key_hash)
    f = Fernet(key)
    return f.encrypt(text.encode()).decode()


def decrypt_notes(encrypted_text: str) -> str:
    """Розшифровує текст нотаток за допомогою Fernet та SECRET_KEY сервера"""
    if not encrypted_text:
        return ""
    import base64
    import hashlib
    from django.conf import settings
    from cryptography.fernet import Fernet
    
    key_hash = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    key = base64.urlsafe_b64encode(key_hash)
    f = Fernet(key)
    try:
        return f.decrypt(encrypted_text.encode()).decode()
    except Exception:
        return "[Помилка дешифрування]"