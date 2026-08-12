# Tests file

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from datetime import date, timedelta
from .models import Patient, FractionHistory, MedicalIncapacity
from .forms import PatientForm, MedicalIncapacityForm, FractionEditForm
from .services import (
    generate_fractions_for_patient, 
    auto_confirm_today_fractions,
    get_patient_treatment_info,
    recalculate_discharge_date,
    shift_patient_schedule
)

User = get_user_model()

class CriticalModelTests(TestCase):
    """Критичні тести моделей - можуть викликати падіння сервісу"""
    
    def test_patient_creation_minimal(self):
        """Тест створення пацієнта з мінімальними даними"""
        patient = Patient.objects.create(
            last_name='Тестовий',
            first_name='Пацієнт',
            middle_name='Тестовий',
            diagnosis='Тестовий діагноз'
        )
        self.assertIsNotNone(patient.id)
        self.assertEqual(patient.full_name, 'Тестовий Пацієнт Тестовий')
    
    def test_ambulatory_card_id_creation(self):
        """Тест створення пацієнта з ID амбулаторної картки"""
        # Тест з форматом 228435/2025
        patient1 = Patient.objects.create(
            last_name='Тестовий',
            first_name='Пацієнт',
            ambulatory_card_id='228435/2025'
        )
        self.assertEqual(patient1.ambulatory_card_id, '228435/2025')
        
        # Тест з форматом 2025-9246582
        patient2 = Patient.objects.create(
            last_name='Тестовий',
            first_name='Пацієнт2',
            ambulatory_card_id='2025-9246582'
        )
        self.assertEqual(patient2.ambulatory_card_id, '2025-9246582')
        
        # Тест без ID (опціональне поле)
        patient3 = Patient.objects.create(
            last_name='Тестовий',
            first_name='Пацієнт3'
        )
        self.assertIsNone(patient3.ambulatory_card_id)
    
    def test_ambulatory_card_id_uniqueness(self):
        """Тест унікальності ID амбулаторної картки"""
        Patient.objects.create(
            last_name='Тестовий',
            first_name='Пацієнт',
            ambulatory_card_id='228435/2025'
        )
        
        # Спробуємо створити другого пацієнта з тим самим ID
        # Може викликати IntegrityError (рівень БД) або ValidationError (рівень моделі)
        with self.assertRaises((IntegrityError, ValidationError)):
            patient2 = Patient(
                last_name='Інший',
                first_name='Пацієнт',
                ambulatory_card_id='228435/2025'
            )
            patient2.full_clean()  # Викликаємо валідацію
            patient2.save()  # Може викликати IntegrityError
    
    def test_ambulatory_card_id_validation_invalid_chars(self):
        """Тест валідації: недозволені символи в ID"""
        patient = Patient(
            last_name='Тестовий',
            first_name='Пацієнт',
            ambulatory_card_id='228435/2025 ABC'  # Містить літери та пробіли
        )
        
        with self.assertRaises(ValidationError):
            patient.full_clean()
    
    def test_ambulatory_card_id_validation_no_digits(self):
        """Тест валідації: ID без цифр"""
        patient = Patient(
            last_name='Тестовий',
            first_name='Пацієнт',
            ambulatory_card_id='---///'  # Тільки символи, без цифр
        )
        
        with self.assertRaises(ValidationError):
            patient.full_clean()
    
    def test_ambulatory_card_id_valid_formats(self):
        """Тест валідації: правильні формати ID"""
        valid_formats = [
            '228435/2025',
            '2025-9246582',
            '12345/67',
            '2024-123',
            '123/456/789',
            '2025-123-456',
            '12345',
            '2025/12345'
        ]
        
        for i, card_id in enumerate(valid_formats):
            patient = Patient(
                last_name=f'Тестовий{i}',
                first_name='Пацієнт',
                ambulatory_card_id=card_id
            )
            try:
                patient.full_clean()
            except ValidationError:
                self.fail(f"Валідний формат '{card_id}' не пройшов валідацію")
    
    def test_display_stage_property(self):
        """Тест властивості display_stage - критична для відображення"""
        today = date.today()
        
        # Тест 1: Пацієнт в архіві (discharge_date <= today)
        patient_archived = Patient.objects.create(
            last_name='Тестовий',
            first_name='Архів',
            diagnosis='Тестовий діагноз',
            discharge_date=today - timedelta(days=1)
        )
        self.assertEqual(patient_archived.display_stage, "Архів")
        
        # Тест 2: Підготовка до виписки (discharge_date через 1-3 дні)
        patient_discharge_prep = Patient.objects.create(
            last_name='Тестовий',
            first_name='Виписка',
            diagnosis='Тестовий діагноз',
            treatment_start_date=today - timedelta(days=10),
            discharge_date=today + timedelta(days=2)
        )
        self.assertEqual(patient_discharge_prep.display_stage, "Підготовка до виписки")
        
        # Тест 3: Пацієнт в лікуванні (treatment_start_date <= today, немає discharge_date)
        patient_treatment = Patient.objects.create(
            last_name='Тестовий',
            first_name='Лікування',
            diagnosis='Тестовий діагноз',
            treatment_start_date=today - timedelta(days=5)
        )
        self.assertEqual(patient_treatment.display_stage, "Лікування")
        
        # Тест 4: КТ-симуляція (є ct_simulation_date, немає treatment_start_date)
        patient_ct = Patient.objects.create(
            last_name='Тестовий',
            first_name='КТ',
            diagnosis='Тестовий діагноз',
            ct_simulation_date=today - timedelta(days=2)
        )
        self.assertEqual(patient_ct.display_stage, "КТ-симуляція")
        
        # Тест 5: Початок лікування (treatment_start_date > today)
        patient_future = Patient.objects.create(
            last_name='Тестовий',
            first_name='Майбутнє',
            diagnosis='Тестовий діагноз',
            treatment_start_date=today + timedelta(days=5)
        )
        self.assertEqual(patient_future.display_stage, "Початок лікування")
        
        # Тест 6: Новий пацієнт (немає дат)
        patient_new = Patient.objects.create(
            last_name='Тестовий',
            first_name='Новий',
            diagnosis='Тестовий діагноз'
        )
        self.assertEqual(patient_new.display_stage, "Новий")
    
    def test_current_fraction_property(self):
        """Тест властивості current_fraction - критична для розрахунків"""
        patient = Patient.objects.create(
            last_name='Тестовий',
            first_name='Пацієнт',
            diagnosis='Тестовий діагноз'
        )
        
        # Створюємо фракції
        FractionHistory.objects.create(
            patient=patient,
            date=date.today() - timedelta(days=1),
            dose=2.0,
            status='delivered'
        )
        
        self.assertEqual(patient.current_fraction, 1)

    def test_summary_text_property(self):
        patient = Patient.objects.create(
            last_name='Тестовий',
            first_name='Пацієнт',
            diagnosis='Са прямої кишки',
            tnm_staging='T2N0M0',
            disease_stage='II',
            clinical_group='2',
            histology_number='123',
            histology_date=date(2025, 1, 28),
            histology_description='Аденокарцинома (G2)'
        )

        summary = patient.summary_text
        self.assertIn('T2N0M0', summary)
        self.assertIn('Аденокарцинома', summary)


class CriticalViewsTests(TestCase):
    """Критичні тести представлень - можуть викликати падіння сервісу"""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            role='doctor',
            approved=True
        )
        
        self.patient = Patient.objects.create(
            last_name='Тестовий',
            first_name='Пацієнт',
            diagnosis='Тестовий діагноз'
        )
    
    def test_dashboard_view_requires_login(self):
        """Тест що дашборд вимагає авторизації"""
        # Без авторизації - має показувати сторінку unauthorized
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'unauthorized', status_code=200)
        
        # Після авторизації - має показувати dashboard
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        # Перевіряємо, що це не сторінка unauthorized
        self.assertNotContains(response, 'unauthorized', status_code=200)
    
    def test_patient_list_view(self):
        """Тест списку пацієнтів - критична функція"""
        self.client.login(username='testuser', password='testpass123')
        
        response = self.client.get(reverse('patient_list'))
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.patient, response.context['patients'])
    
    def test_patient_detail_view(self):
        """Тест деталей пацієнта - критична функція"""
        self.client.login(username='testuser', password='testpass123')
        
        response = self.client.get(reverse('patient_detail', kwargs={'pk': self.patient.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['patient'], self.patient)

    def test_summary_text_displayed(self):
        self.client.login(username='testuser', password='testpass123')
        self.patient.tnm_staging = 'T2N0M0'
        self.patient.histology_description = 'Carcinoma'
        self.patient.save()

        response = self.client.get(reverse('patient_detail', kwargs={'pk': self.patient.pk}))
        self.assertContains(response, 'T2N0M0')
        self.assertContains(response, 'Carcinoma')
    
    def test_nonexistent_patient_detail(self):
        """Тест обробки неіснуючого пацієнта - критична для стабільності"""
        self.client.login(username='testuser', password='testpass123')
        
        response = self.client.get(reverse('patient_detail', kwargs={'pk': 99999}))
        self.assertEqual(response.status_code, 404)


class CriticalURLTests(TestCase):
    """Критичні тести URL-ів - можуть викликати падіння сервісу"""
    
    def setUp(self):
        self.client = Client()
    
    def test_critical_urls_require_login(self):
        """Тест що критичні URL вимагають авторизації"""
        critical_urls = [
            'dashboard',
            'patient_list',
            'patient_create',
            'fraction_list'
        ]
        
        for url_name in critical_urls:
            response = self.client.get(reverse(url_name))
            # Декоратор @login_required повертає 200 з шаблоном unauthorized.html
            self.assertEqual(response.status_code, 200)
            # Перевіряємо, що відображається сторінка unauthorized
            self.assertContains(response, 'unauthorized', status_code=200)
    
    def test_login_url_accessible(self):
        """Тест що сторінка логіну доступна"""
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)
    
    def test_register_url_accessible(self):
        """Тест що сторінка реєстрації доступна"""
        response = self.client.get(reverse('register'))
        self.assertEqual(response.status_code, 200)


class CriticalErrorHandlingTests(TestCase):
    """Критичні тести обробки помилок - можуть викликати падіння сервісу"""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            role='doctor',
            approved=True
        )
    
    def test_invalid_patient_id_handling(self):
        """Тест обробки невалідного ID пацієнта"""
        self.client.login(username='testuser', password='testpass123')
        
        # Неіснуючий ID
        response = self.client.get(reverse('patient_detail', kwargs={'pk': 99999}))
        self.assertEqual(response.status_code, 404)
    
    def test_invalid_url_handling(self):
        """Тест обробки невалідних URL"""
        response = self.client.get('/patients/nonexistent/')
        self.assertEqual(response.status_code, 404)

class PatientFormDateTest(TestCase):
    """Тести для перевірки правильного форматування дат у формі пацієнта"""
    
    def setUp(self):
        # Створюємо тестового користувача
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            role='doctor',
            approved=True
        )
        self.client = Client()
        self.client.login(username='testuser', password='testpass123')
        
        # Створюємо тестового пацієнта з датами
        self.patient = Patient.objects.create(
            last_name='Тестовий',
            first_name='Пацієнт',
            birth_date=date(1980, 5, 15),
            ct_simulation_date=date(2024, 3, 20),
            treatment_start_date=date(2024, 4, 1),
            discharge_date=date(2024, 6, 30),
            last_blood_test_date=date(2024, 4, 15),
            histology_date=date(2024, 2, 10)
        )
    
    def test_patient_form_date_formatting(self):
        """Тест перевіряє, що дати правильно форматуются у формі редагування"""
        # Створюємо форму з існуючим пацієнтом
        form = PatientForm(instance=self.patient)
        
        # Перевіряємо, що дати відображаються у правильному форматі
        self.assertEqual(form.initial.get('birth_date'), '15.05.1980')
        self.assertEqual(form.initial.get('ct_simulation_date'), '20.03.2024')
        self.assertEqual(form.initial.get('treatment_start_date'), '01.04.2024')
        self.assertEqual(form.initial.get('discharge_date'), '30.06.2024')
        self.assertEqual(form.initial.get('last_blood_test_date'), '15.04.2024')
        self.assertEqual(form.initial.get('histology_date'), '10.02.2024')
    
    def test_patient_edit_page_loads_with_correct_dates(self):
        """Тест перевіряє, що сторінка редагування завантажується з правильними датами"""
        response = self.client.get(reverse('patient_update', kwargs={'pk': self.patient.pk}))
        self.assertEqual(response.status_code, 200)
        
        # Перевіряємо, що форма містить правильні дати
        form = response.context['form']
        self.assertEqual(form.initial.get('birth_date'), '15.05.1980')
        self.assertEqual(form.initial.get('treatment_start_date'), '01.04.2024')
    
    def test_patient_form_saves_dates_correctly(self):
        """Тест перевіряє, що форма правильно зберігає дати"""
        form_data = {
            'last_name': 'Тестовий',
            'first_name': 'Пацієнт',
            'birth_date': '20.12.1985',
            'ct_simulation_date': '25.03.2024',
            'treatment_start_date': '01.04.2024',
            'discharge_date': '30.06.2024',
            'last_blood_test_date': '15.04.2024',
            'histology_date': '10.02.2024'
        }
        
        form = PatientForm(data=form_data, instance=self.patient)
        self.assertTrue(form.is_valid())
        
        patient = form.save()
        self.assertEqual(patient.birth_date, date(1985, 12, 20))
        self.assertEqual(patient.ct_simulation_date, date(2024, 3, 25))
    
    def test_diagnosis_text_generation(self):
        """Тест перевіряє правильне формування тексту діагнозу для копіювання"""
        # Оновлюємо пацієнта з повними даними діагнозу
        self.patient.diagnosis = 'Са правої молочної залози'
        self.patient.tnm_staging = 'T4N0M0'
        self.patient.disease_stage = 'IIIA'
        self.patient.clinical_group = '2'
        self.patient.treatment_type = 'радикальне'
        self.patient.histology_number = '46779-90'
        self.patient.histology_date = date(2024, 11, 22)
        self.patient.histology_description = 'Внутрішньопротоковий інвазивний Са (G2), mts в л/в'
        self.patient.save()
        
        # Перевіряємо згенерований текст (новий формат з комами)
        expected_text = "Са правої молочної залози, T4N0M0, gr. IIIA, кл. гр. 2. Стан після радикального лікування. ПГЗ № 46779-90 від 22.11.2024 - Внутрішньопротоковий інвазивний Са (G2), mts в л/в"
        self.assertEqual(self.patient.get_diagnosis_text_for_copy(), expected_text)
    
    def test_diagnosis_text_generation_with_dot_in_diagnosis(self):
        """Тест перевіряє видалення крапки з кінця діагнозу"""
        # Тест з прикладом з крапкою в кінці діагнозу
        self.patient.diagnosis = 'Са правого піднебінного мигдалика ВПЛ+.'
        self.patient.tnm_staging = 'T2N0M0'
        self.patient.disease_stage = 'І'
        self.patient.clinical_group = '2'
        self.patient.treatment_type = 'радикальне'
        self.patient.histology_number = '29777-79'
        self.patient.histology_date = date(2023, 8, 8)
        self.patient.histology_description = 'Плоскоклітинний Са'
        self.patient.save()
        
        # Перевіряємо, що крапка видалена і формат правильний
        expected_text = "Са правого піднебінного мигдалика ВПЛ+, T2N0M0, gr. І, кл. гр. 2. Стан після радикального лікування. ПГЗ № 29777-79 від 08.08.2023 - Плоскоклітинний Са"
        self.assertEqual(self.patient.get_diagnosis_text_for_copy(), expected_text)
    
    def test_diagnosis_text_generation_without_tnm_and_stage(self):
        """Тест форматування діагнозу без TNM та стадії"""
        # Тест з прикладом без TNM та стадії
        self.patient.diagnosis = 'Внутрішньомозкове утворення лівої скроневої ділянки.'
        self.patient.tnm_staging = None  # Немає TNM
        self.patient.disease_stage = None  # Немає стадії
        self.patient.clinical_group = '2'
        self.patient.treatment_type = 'радикальне'
        self.patient.histology_number = '25CN014222'
        self.patient.histology_date = date(2025, 7, 4)
        self.patient.histology_description = 'Гліома (WHO grade 4)'
        self.patient.save()
        
        # Перевіряємо правильне форматування без TNM та стадії
        expected_text = "Внутрішньомозкове утворення лівої скроневої ділянки, кл. гр. 2. Стан після радикального лікування. ПГЗ № 25CN014222 від 04.07.2025 - Гліома (WHO grade 4)"
        self.assertEqual(self.patient.get_diagnosis_text_for_copy(), expected_text)
    
    def test_diagnosis_text_generation_minimal(self):
        """Тест форматування з мінімальними даними"""
        # Тільки діагноз
        self.patient.diagnosis = 'Тестовий діагноз'
        self.patient.save()
        
        result = self.patient.get_diagnosis_text_for_copy()
        self.assertEqual(result, "Тестовий діагноз")
        
        # Діагноз + клінічна група
        self.patient.clinical_group = '1'
        self.patient.save()
        result = self.patient.get_diagnosis_text_for_copy()
        self.assertEqual(result, "Тестовий діагноз, кл. гр. 1")
        
        # Діагноз + TNM (без стадії та клінічної групи)
        self.patient.clinical_group = None
        self.patient.tnm_staging = 'T1N0M0'
        self.patient.save()
        result = self.patient.get_diagnosis_text_for_copy()
        self.assertEqual(result, "Тестовий діагноз, T1N0M0")


class PatientModelPropertiesTests(TestCase):
    """Тести для властивостей моделі Patient"""
    
    def setUp(self):
        self.patient = Patient.objects.create(
            last_name='Тестовий',
            first_name='Пацієнт',
            diagnosis='Тестовий діагноз',
            treatment_start_date=date.today() - timedelta(days=10),
            total_fractions=20,
            dose_per_fraction=2.0
        )
    
    def test_missed_days_property(self):
        """Тест властивості missed_days - розрахунок пропущених днів"""
        # Створюємо кілька виконаних фракцій
        for i in range(5):
            FractionHistory.objects.create(
                patient=self.patient,
                date=self.patient.treatment_start_date + timedelta(days=i),
                dose=2.0,
                status='delivered'
            )
        # Створюємо кілька пропущених фракцій
        for i in range(5, 8):
            FractionHistory.objects.create(
                patient=self.patient,
                date=self.patient.treatment_start_date + timedelta(days=i),
                dose=2.0,
                status='missed'
            )
        
        # Кількість пропущених днів має бути 3
        self.assertEqual(self.patient.missed_days, 3)
    
    def test_next_blood_test_due_date_property(self):
        """Тест властивості next_blood_test_due_date для звичайних пацієнтів"""
        # Пацієнт без радіомодифікації, з вказаним last_blood_test_date
        # Якщо last_blood_test_date = 5 днів тому, то наступний аналіз через 12 робочих днів
        self.patient.last_blood_test_date = date.today() - timedelta(days=5)
        self.patient.save()
        
        # Додаємо 12 робочих днів вручну для перевірки
        expected_date = self.patient.last_blood_test_date
        added = 0
        while added < 12:
            expected_date += timedelta(days=1)
            if expected_date.weekday() < 5:
                added += 1
                
        self.assertEqual(self.patient.next_blood_test_due_date, expected_date)

        # Тест без last_blood_test_date (має рахувати від treatment_start_date)
        self.patient.last_blood_test_date = None
        self.patient.save()
        
        expected_date_start = self.patient.treatment_start_date
        added = 0
        while added < 12:
            expected_date_start += timedelta(days=1)
            if expected_date_start.weekday() < 5:
                added += 1
        self.assertEqual(self.patient.next_blood_test_due_date, expected_date_start)
        
        # Якщо пацієнт не в лікуванні, має повертати None
        self.patient.discharge_date = date.today() - timedelta(days=1)
        self.patient.save()
        self.assertIsNone(self.patient.next_blood_test_due_date)
        
    def test_next_blood_test_due_date_radiomodification(self):
        """Тест розрахунку дати аналізу крові для радіомодифікації (щотижнево, 7 календарних днів)"""
        # Пацієнт з радіомодифікацією та встановленим last_blood_test_date
        patient_rm = Patient.objects.create(
            last_name='Модифікований',
            first_name='Пацієнт',
            treatment_start_date=date.today() - timedelta(days=2),
            last_blood_test_date=date.today() - timedelta(days=3),
            has_radiomodification=True
        )
        # Очікується рівно 7 календарних днів без зсувів на вихідні
        expected_date = patient_rm.last_blood_test_date + timedelta(days=7)
        self.assertEqual(patient_rm.next_blood_test_due_date, expected_date)

        # Якщо last_blood_test_date не вказано, має повертати None
        patient_rm.last_blood_test_date = None
        patient_rm.save()
        self.assertIsNone(patient_rm.next_blood_test_due_date)
     
    def test_is_in_treatment_property(self):
        """Тест властивості is_in_treatment"""
        # Пацієнт в лікуванні
        self.assertTrue(self.patient.is_in_treatment)
        
        # Виписали пацієнта
        self.patient.discharge_date = date.today() - timedelta(days=1)
        self.patient.save()
        self.assertFalse(self.patient.is_in_treatment)
        
        # Пацієнт ще не почав лікування
        patient_future = Patient.objects.create(
            last_name='Тестовий',
            first_name='Майбутнє',
            treatment_start_date=date.today() + timedelta(days=5)
        )
        self.assertFalse(patient_future.is_in_treatment)
    
    def test_get_latest_medical_incapacity(self):
        """Тест методу get_latest_medical_incapacity"""
        # Створюємо кілька МВТН
        incapacity1 = MedicalIncapacity.objects.create(
            patient=self.patient,
            start_date=date.today() - timedelta(days=30),
            end_date=date.today() - timedelta(days=20)
        )
        incapacity2 = MedicalIncapacity.objects.create(
            patient=self.patient,
            start_date=date.today() - timedelta(days=10),
            end_date=date.today() - timedelta(days=5)
        )
        
        # Має повернути останнє МВТН
        latest = self.patient.get_latest_medical_incapacity()
        self.assertEqual(latest, incapacity2)
        
        # Якщо немає МВТН
        patient_no_incapacity = Patient.objects.create(
            last_name='Тестовий',
            first_name='Без МВТН'
        )
        self.assertIsNone(patient_no_incapacity.get_latest_medical_incapacity())


class ServicesTests(TestCase):
    """Тести для сервісів (services.py)"""
    
    def setUp(self):
        self.patient = Patient.objects.create(
            last_name='Тестовий',
            first_name='Пацієнт',
            diagnosis='Тестовий діагноз',
            treatment_start_date=date.today(),
            total_fractions=5,
            dose_per_fraction=2.0
        )
    
    def test_generate_fractions_for_patient(self):
        """Тест генерації фракцій для пацієнта"""
        result = generate_fractions_for_patient(self.patient)
        self.assertTrue(result)
        
        # Перевіряємо, що створено правильну кількість фракцій
        fractions = self.patient.fractions.all()
        self.assertEqual(fractions.count(), 5)
        
        # Перевіряємо, що фракції створені тільки в робочі дні
        for fraction in fractions:
            self.assertLess(fraction.date.weekday(), 5)  # Пн-Пт
        
        # Перевіряємо, що дата виписки встановлена
        self.assertIsNotNone(self.patient.discharge_date)
        self.assertEqual(self.patient.discharge_date, fractions.order_by('date').last().date)
    
    def test_generate_fractions_without_data(self):
        """Тест генерації фракцій без необхідних даних"""
        patient_no_data = Patient.objects.create(
            last_name='Тестовий',
            first_name='Без даних'
        )
        result = generate_fractions_for_patient(patient_no_data)
        self.assertFalse(result)
    
    def test_auto_confirm_today_fractions(self):
        """Тест автоматичного підтвердження сьогоднішніх фракцій"""
        # Спочатку очищаємо всі фракції на сьогодні (якщо є з інших тестів)
        FractionHistory.objects.filter(date=date.today()).delete()
        
        # Створюємо фракцію на сьогодні
        fraction = FractionHistory.objects.create(
            patient=self.patient,
            date=date.today(),
            dose=2.0,
            status='scheduled'
        )
        
        count = auto_confirm_today_fractions()
        # Може бути більше 1, якщо інші тести створили фракції, тому перевіряємо >= 1
        self.assertGreaterEqual(count, 1)
        
        # Перевіряємо, що наша фракція підтверджена
        fraction.refresh_from_db()
        self.assertEqual(fraction.status, 'delivered')
    
    def test_get_patient_treatment_info(self):
        """Тест отримання інформації про лікування"""
        # Створюємо кілька виконаних фракцій
        for i in range(3):
            FractionHistory.objects.create(
                patient=self.patient,
                date=self.patient.treatment_start_date + timedelta(days=i),
                dose=2.0,
                status='delivered'
            )
        
        info = get_patient_treatment_info(self.patient)
        
        self.assertEqual(info['total_fractions'], 5)
        self.assertEqual(info['completed_fractions'], 3)
        self.assertEqual(info['remaining_fractions'], 2)
        self.assertEqual(info['progress_percentage'], 60.0)
    
    def test_recalculate_discharge_date(self):
        """Тест перерахунку дати виписки"""
        # Створюємо фракції
        FractionHistory.objects.create(
            patient=self.patient,
            date=date.today() + timedelta(days=5),
            dose=2.0
        )
        FractionHistory.objects.create(
            patient=self.patient,
            date=date.today() + timedelta(days=10),
            dose=2.0
        )
        
        new_date = recalculate_discharge_date(self.patient)
        self.assertIsNotNone(new_date)
        self.assertEqual(new_date, date.today() + timedelta(days=10))
        self.assertEqual(self.patient.discharge_date, date.today() + timedelta(days=10))
    
    def test_shift_patient_schedule(self):
        """Тест зсуву запланованих фракцій пацієнта"""
        from unittest.mock import patch
        import datetime
        
        with patch('django.utils.timezone.now') as mock_now:
            mock_now.return_value = datetime.datetime(2026, 5, 25, 12, 0, 0, tzinfo=datetime.timezone.utc)
            
            # Створюємо 3 заплановані фракції починаючи з понеділка
            # Щоб дата була фіксованою, візьмемо 2026-05-25 (це понеділок)
            start_date = datetime.date(2026, 5, 25)
            FractionHistory.objects.filter(patient=self.patient).delete()
            
            f1 = FractionHistory.objects.create(patient=self.patient, date=start_date, dose=2.0, status='scheduled')
            f2 = FractionHistory.objects.create(patient=self.patient, date=start_date + timedelta(days=1), dose=2.0, status='scheduled')
            f3 = FractionHistory.objects.create(patient=self.patient, date=start_date + timedelta(days=2), dose=2.0, status='scheduled')
            
            self.patient.treatment_start_date = start_date
            self.patient.discharge_date = f3.date
            self.patient.save()
            
            # Робимо другу фракцію (вівторок) пропущеною
            f2.status = 'missed'
            f2.save()
            
            # Зсуваємо розклад
            shift_patient_schedule(self.patient)
            
            f1.refresh_from_db()
            f2.refresh_from_db()
            f3.refresh_from_db()
            
            # f1 не має змінитись
            self.assertEqual(f1.date, start_date)
            # f2 залишається на вівторок, але статус тепер 'missed'
            self.assertEqual(f2.date, start_date + timedelta(days=1))
            self.assertEqual(f2.status, 'missed')
            # f3 залишається на середу
            self.assertEqual(f3.date, start_date + timedelta(days=2))
            
            # Перевіряємо кількість запланованих фракцій (має бути 5)
            all_scheduled = self.patient.fractions.filter(status='scheduled').order_by('date')
            self.assertEqual(all_scheduled.count(), 5)
            self.assertEqual(all_scheduled[0].date, datetime.date(2026, 5, 25))
            self.assertEqual(all_scheduled[1].date, datetime.date(2026, 5, 27))
            self.assertEqual(all_scheduled[2].date, datetime.date(2026, 5, 28))
            self.assertEqual(all_scheduled[3].date, datetime.date(2026, 5, 29))
            self.assertEqual(all_scheduled[4].date, datetime.date(2026, 6, 1))
            
            self.patient.refresh_from_db()
            self.assertEqual(self.patient.discharge_date, datetime.date(2026, 6, 1))


class FormValidationTests(TestCase):
    """Тести для валідації форм"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            role='doctor',
            approved=True
        )
        self.patient = Patient.objects.create(
            last_name='Тестовий',
            first_name='Пацієнт',
            treatment_start_date=date.today()
        )
    
    def test_ambulatory_card_id_form_validation_valid(self):
        """Тест валідації форми: правильний ID амбулаторної картки"""
        form_data = {
            'last_name': 'Тестовий',
            'first_name': 'Пацієнт',
            'ambulatory_card_id': '228435/2025'
        }
        
        form = PatientForm(data=form_data)
        self.assertTrue(form.is_valid())
    
    def test_ambulatory_card_id_form_validation_invalid_chars(self):
        """Тест валідації форми: недозволені символи"""
        form_data = {
            'last_name': 'Тестовий',
            'first_name': 'Пацієнт',
            'ambulatory_card_id': '228435/2025 ABC'
        }
        
        form = PatientForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('ambulatory_card_id', form.errors)
    
    def test_ambulatory_card_id_form_validation_duplicate(self):
        """Тест валідації форми: дублікат ID"""
        # Створюємо пацієнта з ID
        Patient.objects.create(
            last_name='Існуючий',
            first_name='Пацієнт',
            ambulatory_card_id='228435/2025'
        )
        
        # Спробуємо створити нового з тим самим ID
        form_data = {
            'last_name': 'Новий',
            'first_name': 'Пацієнт',
            'ambulatory_card_id': '228435/2025'
        }
        
        form = PatientForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('ambulatory_card_id', form.errors)
    
    def test_ambulatory_card_id_form_validation_update_same_id(self):
        """Тест валідації форми: оновлення з тим самим ID (дозволено)"""
        patient = Patient.objects.create(
            last_name='Тестовий',
            first_name='Пацієнт',
            ambulatory_card_id='228435/2025'
        )
        
        # Оновлюємо пацієнта з тим самим ID
        form_data = {
            'last_name': 'Тестовий',
            'first_name': 'Оновлений',
            'ambulatory_card_id': '228435/2025'
        }
        
        form = PatientForm(data=form_data, instance=patient)
        self.assertTrue(form.is_valid())
    
    def test_ambulatory_card_id_form_validation_empty(self):
        """Тест валідації форми: порожнє поле (дозволено)"""
        form_data = {
            'last_name': 'Тестовий',
            'first_name': 'Пацієнт',
            'ambulatory_card_id': ''
        }
        
        form = PatientForm(data=form_data)
        self.assertTrue(form.is_valid())
    
    def test_ambulatory_card_id_form_validation_whitespace_stripping(self):
        """Тест валідації форми: видалення пробілів"""
        form_data = {
            'last_name': 'Тестовий',
            'first_name': 'Пацієнт',
            'ambulatory_card_id': '  228435/2025  '  # З пробілами
        }
        
        form = PatientForm(data=form_data)
        self.assertTrue(form.is_valid())
        
        # Перевіряємо, що пробіли видалені
        patient = form.save()
        self.assertEqual(patient.ambulatory_card_id, '228435/2025')
    
    def test_patient_form_discharge_before_start_validation(self):
        """Тест валідації: дата виписки не може бути раніше дати початку"""
        form_data = {
            'last_name': 'Тестовий',
            'first_name': 'Пацієнт',
            'treatment_start_date': '01.04.2024',
            'discharge_date': '30.03.2024'  # Раніше дати початку
        }
        
        form = PatientForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('Дата виписки не може бути раніше дати початку лікування', str(form.errors))
    
    def test_patient_form_valid_dates(self):
        """Тест валідації: правильні дати"""
        form_data = {
            'last_name': 'Тестовий',
            'first_name': 'Пацієнт',
            'treatment_start_date': '01.04.2024',
            'discharge_date': '30.04.2024'  # Після дати початку
        }
        
        form = PatientForm(data=form_data)
        self.assertTrue(form.is_valid())
    
    def test_medical_incapacity_form_end_before_start_validation(self):
        """Тест валідації МВТН: дата закінчення не може бути раніше дати початку"""
        form_data = {
            'start_date': '01.04.2024',
            'end_date': '30.03.2024'  # Раніше дати початку
        }
        
        form = MedicalIncapacityForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('Дата закінчення не може бути раніше дати початку', str(form.errors))
    
    def test_fraction_edit_form_valid(self):
        """Тест валідації FractionEditForm"""
        fraction = FractionHistory.objects.create(
            patient=self.patient,
            date=date.today() + timedelta(days=5),
            dose=2.0
        )
        
        form_data = {
            'date': (date.today() + timedelta(days=5)).strftime('%d.%m.%Y'),
            'dose': 2.0,
            'status': 'delivered',
            'note': 'Отримана вчасно',
            'reason': ''
        }
        
        form = FractionEditForm(data=form_data, instance=fraction)
        self.assertTrue(form.is_valid())


class DecoratorTests(TestCase):
    """Тести для декораторів"""
    
    def setUp(self):
        self.client = Client()
        self.doctor = User.objects.create_user(
            username='doctor',
            password='testpass123',
            role='doctor',
            approved=True
        )
        self.nurse = User.objects.create_user(
            username='nurse',
            password='testpass123',
            role='nurse',
            approved=True
        )
        self.admin = User.objects.create_user(
            username='admin',
            password='testpass123',
            role='admin',
            approved=True,
            is_staff=True
        )
    
    def test_login_required_decorator(self):
        """Тест декоратора @login_required"""
        # Без авторизації
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'unauthorized', status_code=200)
        
        # З авторизацією
        self.client.login(username='doctor', password='testpass123')
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'unauthorized', status_code=200)
    
    def test_admin_required_decorator(self):
        """Тест декоратора @admin_required та перевірки ролі в view"""
        # Лікар не може отримати доступ - view перевіряє роль і перенаправляє на dashboard
        self.client.login(username='doctor', password='testpass123')
        response = self.client.get(reverse('admin_users'))
        # View admin_users використовує @login_required і перевіряє роль всередині
        # Якщо роль не admin, перенаправляє на dashboard (302)
        self.assertEqual(response.status_code, 302)
        
        # Адміністратор може отримати доступ
        self.client.login(username='admin', password='testpass123')
        response = self.client.get(reverse('admin_users'))
        self.assertEqual(response.status_code, 200)


class CRUDOperationsTests(TestCase):
    """Тести для CRUD операцій"""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            role='doctor',
            approved=True
        )
        self.client.login(username='testuser', password='testpass123')
    
    def test_patient_create(self):
        """Тест створення пацієнта через форму"""
        form_data = {
            'last_name': 'Новий',
            'first_name': 'Пацієнт',
            'middle_name': 'Тестовий',
            'diagnosis': 'Тестовий діагноз',
            'treatment_start_date': date.today().strftime('%d.%m.%Y'),
            'total_fractions': 20,
            'dose_per_fraction': 2.0
        }
        
        response = self.client.post(reverse('patient_create'), data=form_data)
        self.assertEqual(response.status_code, 302)  # Редирект після створення
        
        # Перевіряємо, що пацієнт створений
        patient = Patient.objects.get(last_name='Новий')
        self.assertIsNotNone(patient)
        self.assertEqual(patient.first_name, 'Пацієнт')
    
    def test_patient_update(self):
        """Тест оновлення пацієнта"""
        patient = Patient.objects.create(
            last_name='Тестовий',
            first_name='Пацієнт',
            diagnosis='Старий діагноз'
        )
        
        form_data = {
            'last_name': 'Тестовий',
            'first_name': 'Пацієнт',
            'diagnosis': 'Новий діагноз'
        }
        
        response = self.client.post(
            reverse('patient_update', kwargs={'pk': patient.pk}),
            data=form_data
        )
        self.assertEqual(response.status_code, 302)
        
        # Перевіряємо оновлення
        patient.refresh_from_db()
        self.assertEqual(patient.diagnosis, 'Новий діагноз')
    
    def test_patient_delete(self):
        """Тест видалення пацієнта"""
        patient = Patient.objects.create(
            last_name='Тестовий',
            first_name='Видалити'
        )
        patient_id = patient.id
        
        response = self.client.post(
            reverse('patient_delete', kwargs={'pk': patient.pk})
        )
        self.assertEqual(response.status_code, 302)
        
        # Перевіряємо, що пацієнт видалений
        self.assertFalse(Patient.objects.filter(id=patient_id).exists())


class MVTNNotificationTests(TestCase):
    """Тести для сповіщень МВТН (лікарняних листів)"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='doctor_mvtn',
            password='testpass123',
            role='doctor',
            approved=True
        )

    def test_mvtn_notification_flow(self):
        """
        Тест-кейс:
        1. Створюємо пацієнта з 5 фракціями починаючи з понеділка 2026-05-25.
        2. Додаємо MedicalIncapacity, що повністю покриває курс (2026-05-25 по 2026-05-29).
        3. Перевіряємо відсутність критичного алерта на дашборді.
        4. Робимо одну фракцію пропущеною (missed) -> курс зсувається на 1 робочий день (до 2026-06-01).
        5. Перевіряємо появу критичного алерта на дашборді з правильними датами.
        """
        import datetime
        from unittest.mock import patch

        # Заморозимо час на понеділок, 2026-05-25
        with patch('django.utils.timezone.now') as mock_now:
            mock_now.return_value = datetime.datetime(2026, 5, 25, 12, 0, 0, tzinfo=datetime.timezone.utc)
            
            # 1. Створюємо пацієнта
            patient = Patient.objects.create(
                last_name='Петренко',
                first_name='Іван',
                middle_name='Петрович',
                diagnosis='Тестовий діагноз',
                treatment_start_date=datetime.date(2026, 5, 25),
                total_fractions=5,
                dose_per_fraction=2.0
            )
            
            # Перевіряємо, що фракції згенеровані
            fractions = list(patient.fractions.all().order_by('date'))
            self.assertEqual(len(fractions), 5)
            self.assertEqual(fractions[0].date, datetime.date(2026, 5, 25))
            self.assertEqual(fractions[4].date, datetime.date(2026, 5, 29))
            
            # 2. Додаємо МВТН, що покриває курс (з 25 по 29 травня)
            incapacity = MedicalIncapacity.objects.create(
                patient=patient,
                start_date=datetime.date(2026, 5, 25),
                end_date=datetime.date(2026, 5, 29),
                mvt_number='1234-5678-9012-3456'
            )
            
            # Авторизуємо клієнта
            self.client.login(username='doctor_mvtn', password='testpass123')
            
            # 3. Перевіряємо відсутність критичного алерта на дашборді
            response = self.client.get(reverse('dashboard'))
            self.assertEqual(response.status_code, 200)
            
            # Перевіряємо context
            notifications = response.context['notifications']
            incapacity_alerts = [n for n in notifications if n['type'] == 'incapacity_alert']
            self.assertEqual(len(incapacity_alerts), 0)
            
            # 4. Пропускаємо одну фракцію (наприклад, у вівторок 26 травня)
            tuesday_fraction = patient.fractions.get(date=datetime.date(2026, 5, 26))
            tuesday_fraction.status = 'missed'
            tuesday_fraction.save()
            
            # Зсуваємо розклад
            shift_patient_schedule(patient, tuesday_fraction.date)
            patient.recalculate_received_dose()
            patient.refresh_from_db()
            
            # Перевіряємо, що дата останньої фракції змістилася на понеділок 2026-06-01
            new_last_date = patient.get_actual_discharge_date
            self.assertEqual(new_last_date, datetime.date(2026, 6, 1))
            
            # На 25.05 залишилося 4 дні до закінчення МВТН (29.05), тому алерт ще НЕ показується (>3 днів)
            response = self.client.get(reverse('dashboard'))
            notifications = response.context['notifications']
            incapacity_alerts = [n for n in notifications if n['type'] == 'incapacity_alert']
            self.assertEqual(len(incapacity_alerts), 0)

        # Тепер переміщуємось на 26.05 (залишилося 3 дні до 29.05) -> алерт МАЄ з'явитися!
        with patch('django.utils.timezone.now') as mock_now:
            mock_now.return_value = datetime.datetime(2026, 5, 26, 12, 0, 0, tzinfo=datetime.timezone.utc)
            response = self.client.get(reverse('dashboard'))
            self.assertEqual(response.status_code, 200)
            
            notifications = response.context['notifications']
            incapacity_alerts = [n for n in notifications if n['type'] == 'incapacity_alert']
            self.assertEqual(len(incapacity_alerts), 1)
            
            alert = incapacity_alerts[0]
            self.assertEqual(alert['patient'], patient)
            self.assertEqual(alert['incapacity_end_date'], datetime.date(2026, 5, 29))
            self.assertEqual(alert['actual_discharge_date'], datetime.date(2026, 6, 1))
            
            # Перевіряємо, що в HTML є правильний текст попередження
            self.assertIn('МВТН закінчується через 3 дн.', alert['message'])
            self.assertContains(response, 'Петренко Іван Петрович')
            self.assertContains(response, '29.05.2026')
            self.assertContains(response, '01.06.2026')

    def test_mvtn_expiring_soon_alert(self):
        """
        Тест-кейс:
        1. МВТН закінчується через 2 дні від 'сьогодні' і курс закінчується пізніше.
        2. Перевіряємо появу алерта про швидке закінчення МВТН за 2 дні.
        """
        import datetime
        from unittest.mock import patch

        with patch('django.utils.timezone.now') as mock_now:
            # Співпадіння: сьогодні понеділок 2026-05-25
            mock_now.return_value = datetime.datetime(2026, 5, 25, 12, 0, 0, tzinfo=datetime.timezone.utc)
            
            # Створюємо пацієнта з лікуванням, що закінчується через 3 дні (2026-05-28)
            patient = Patient.objects.create(
                last_name='Коваленко',
                first_name='Ольга',
                middle_name='Миколаївна',
                diagnosis='Тестовий діагноз',
                treatment_start_date=datetime.date(2026, 5, 25),
                total_fractions=4,
                dose_per_fraction=2.0
            )
            
            # МВТН діє до 2026-05-26 (закінчується через 1 день і не покриває курс до 28.05)
            MedicalIncapacity.objects.create(
                patient=patient,
                start_date=datetime.date(2026, 5, 25),
                end_date=datetime.date(2026, 5, 26),
                mvt_number='9876-5432-1098-7654'
            )
            
            self.client.login(username='doctor_mvtn', password='testpass123')
            response = self.client.get(reverse('dashboard'))
            self.assertEqual(response.status_code, 200)
            
            notifications = response.context['notifications']
            incapacity_alerts = [n for n in notifications if n['type'] == 'incapacity_alert']
            self.assertEqual(len(incapacity_alerts), 1)
            
            self.assertContains(response, 'Коваленко Ольга Миколаївна')
            self.assertContains(response, '26.05.2026')

    def test_mvtn_distant_future_no_alert(self):
        """
        Тест-кейс: МВТН закінчується через 20 днів. Попри те, що курс лікування триваліший,
        сповіщення НЕ повинно показуватися, поки до закінчення МВТН залишається більше 3 днів.
        """
        import datetime
        from unittest.mock import patch

        with patch('django.utils.timezone.now') as mock_now:
            mock_now.return_value = datetime.datetime(2026, 8, 12, 12, 0, 0, tzinfo=datetime.timezone.utc)
            
            patient = Patient.objects.create(
                last_name='Сажнев',
                first_name='Віктор',
                middle_name='Леонідович',
                diagnosis='Тестовий',
                treatment_start_date=datetime.date(2026, 8, 10),
                total_fractions=30,
                dose_per_fraction=2.0
            )
            
            # МВТН діє до 08.09.2026 (через 27 днів). Завершення лікування: 21.09.2026
            MedicalIncapacity.objects.create(
                patient=patient,
                start_date=datetime.date(2026, 8, 10),
                end_date=datetime.date(2026, 9, 8),
                mvt_number='1111-2222-3333-4444'
            )
            
            self.client.login(username='doctor_mvtn', password='testpass123')
            response = self.client.get(reverse('dashboard'))
            self.assertEqual(response.status_code, 200)
            
            notifications = response.context['notifications']
            incapacity_alerts = [n for n in notifications if n['type'] == 'incapacity_alert']
            self.assertEqual(len(incapacity_alerts), 0)


class InpatientModuleTests(TestCase):
    """Тести для модуля стаціонару та ліжкового фонду"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='doctor_inpatient',
            password='testpass123',
            role='doctor',
            approved=True
        )

    def test_bed_allocation_and_free_beds(self):
        """
        Тест розрахунку ліжкового фонду:
        - 2 власні чоловічі та 2 власні жіночі ліжка
        - Розрахунок вільних ліжок та виявлення позичених ліжок
        """
        # Створюємо 2 власних госпіталізованих чоловіків
        p_male1 = Patient.objects.create(
            last_name='Чоловік', first_name='Один', gender='M',
            hospitalization_status='inpatient', bed_owner='Олег', is_active=True
        )
        p_male2 = Patient.objects.create(
            last_name='Чоловік', first_name='Два', gender='M',
            hospitalization_status='inpatient', bed_owner='Олег', is_active=True
        )
        # Створюємо 1 позиченого чоловіка
        p_male_borrowed = Patient.objects.create(
            last_name='Чоловік', first_name='Позичений', gender='M',
            hospitalization_status='inpatient', bed_owner='Петренко', is_active=True
        )

        # Створюємо 1 власну госпіталізовану жінку
        p_female1 = Patient.objects.create(
            last_name='Жінка', first_name='Одна', gender='F',
            hospitalization_status='inpatient', bed_owner='Олег', is_active=True
        )

        self.client.login(username='doctor_inpatient', password='testpass123')
        response = self.client.get(reverse('inpatient_list'))
        self.assertEqual(response.status_code, 200)

        # Перевіряємо завантажену матрицю ліжок
        own_male_beds = response.context['own_male_beds']
        own_female_beds = response.context['own_female_beds']
        borrowed_male_patients = response.context['borrowed_male_patients']
        borrowed_female_patients = response.context['borrowed_female_patients']

        # Перевіряємо кількість власних ліжок (завжди 2)
        self.assertEqual(len(own_male_beds), 2)
        self.assertEqual(len(own_female_beds), 2)

        # Обидва чоловічі ліжка зайняті
        self.assertTrue(own_male_beds[0]['occupied'])
        self.assertEqual(own_male_beds[0]['patient'], p_male2)
        self.assertTrue(own_male_beds[1]['occupied'])
        self.assertEqual(own_male_beds[1]['patient'], p_male1)

        # Тільки одне жіноче ліжко зайняте
        self.assertTrue(own_female_beds[0]['occupied'])
        self.assertEqual(own_female_beds[0]['patient'], p_female1)
        self.assertFalse(own_female_beds[1]['occupied'])
        self.assertIsNone(own_female_beds[1]['patient'])

        # Чоловік-позичений має бути в списку позичених
        self.assertEqual(len(borrowed_male_patients), 1)
        self.assertEqual(borrowed_male_patients[0], p_male_borrowed)
        self.assertEqual(len(borrowed_female_patients), 0)

        # Перевіряємо наявність тексту "Позичено у: Петренко" в HTML
        self.assertContains(response, 'Позичено у: Петренко')

    def test_admit_patient_from_queue(self):
        """
        Тест переходу пацієнта з черги в стаціонар:
        - Перевірка зміни статусу на 'inpatient'
        - Встановлення дати початку на сьогодні
        - Призначення bed_owner
        - Автоматичне генерування фракцій
        """
        # Створюємо пацієнта у черзі з плановою кількістю фракцій
        patient = Patient.objects.create(
            last_name='Черговий',
            first_name='Пацієнт',
            gender='M',
            hospitalization_status='queue',
            planned_admission_date=date.today(),
            total_fractions=10,
            dose_per_fraction=2.0,
            is_active=True
        )

        self.client.login(username='doctor_inpatient', password='testpass123')
        
        # Виконуємо POST запит на госпіталізацію з призначенням ліжка лікаря 'Петренко'
        response = self.client.post(
            reverse('admit_patient', kwargs={'pk': patient.pk}),
            data={'bed_owner': 'Петренко'}
        )
        self.assertEqual(response.status_code, 302) # редірект назад на inpatient_list

        patient.refresh_from_db()
        self.assertEqual(patient.hospitalization_status, 'inpatient')
        self.assertEqual(patient.treatment_start_date, date.today())
        self.assertEqual(patient.bed_owner, 'Петренко')

        # Фракції мають бути автоматично згенеровані
        fractions_count = patient.fractions.count()
        self.assertEqual(fractions_count, 10)
        # Перевіримо статус першої фракції
        first_fraction = patient.fractions.order_by('date').first()
        self.assertEqual(first_fraction.status, 'scheduled')

    def test_auto_deactivate_past_discharge_date(self):
        """
        Тест автоматичного звільнення ліжка / деактивації пацієнта,
        у якого дата виписки у минулому (discharge_date < today)
        """
        # Створюємо пацієнта, у якого дата виписки вчора, але is_active=True в базі
        yesterday = date.today() - timedelta(days=1)
        patient = Patient.objects.create(
            last_name='Виписаний',
            first_name='Пацієнт',
            gender='M',
            hospitalization_status='inpatient',
            bed_owner='Олег',
            discharge_date=yesterday,
            is_active=True
        )

        self.client.login(username='doctor_inpatient', password='testpass123')
        
        # Перевіряємо, що після запиту inpatient_list пацієнт автоматично деактивується і зникає зі списку
        response = self.client.get(reverse('inpatient_list'))
        self.assertEqual(response.status_code, 200)

        # Пацієнт більше не є активним у базі даних
        patient.refresh_from_db()
        self.assertFalse(patient.is_active)

        # Ліжко має бути вільним
        own_male_beds = response.context['own_male_beds']
        self.assertFalse(own_male_beds[0]['occupied'])
        self.assertFalse(own_male_beds[1]['occupied'])

    def test_blood_test_dashboard_notifications(self):
        """
        Тест нагадувань про аналізи на дашборді:
        - Для звичайного пацієнта без радіомодифікації нагадування з'являється у день аналізу (через 12 робочих днів).
        - Для пацієнта з радіомодифікацією нагадування з'являється за 1 день до дати аналізу (через 6 календарних днів після останнього).
        """
        self.client.login(username='doctor_inpatient', password='testpass123')
        today = date.today()

        # 1. Створюємо звичайного пацієнта (без радіомодифікації)
        # Ставимо дату початку лікування так, щоб 12 робочих днів закінчилися сьогодні.
        # Рахуємо 12 робочих днів назад від сьогодні:
        start_date = today
        subtracted = 0
        while subtracted < 12:
            start_date -= timedelta(days=1)
            if start_date.weekday() < 5:
                subtracted += 1
        
        patient_normal = Patient.objects.create(
            last_name='Нормальний',
            first_name='Пацієнт',
            gender='M',
            treatment_start_date=start_date,
            has_radiomodification=False,
            is_active=True
        )
        
        # 2. Створюємо пацієнта з радіомодифікацією
        # Дата останнього аналізу: 6 днів тому (нагадування має з'явитися сьогодні, за 1 день до 7-го дня)
        patient_rm = Patient.objects.create(
            last_name='Модифікований',
            first_name='Пацієнт',
            gender='M',
            treatment_start_date=today - timedelta(days=10),
            last_blood_test_date=today - timedelta(days=6),
            has_radiomodification=True,
            is_active=True
        )

        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)

        # Перевіряємо, що обидва нагадування є в контексті дашборду
        notifications = response.context['notifications']
        blood_test_notifications = [n for n in notifications if n['type'] == 'blood_test']
        
        # Очікуємо 2 нагадування про аналізи крові
        self.assertEqual(len(blood_test_notifications), 2)
        
        # Перевіряємо пацієнтів та очікувані дати
        patients_notified = [n['patient'] for n in blood_test_notifications]
        self.assertIn(patient_normal, patients_notified)
        self.assertIn(patient_rm, patients_notified)

        # Для радіомодифікації очікувана дата виписки/аналізу (due_date) - рівно 7 днів від останнього
        rm_notification = [n for n in blood_test_notifications if n['patient'] == patient_rm][0]
        self.assertEqual(rm_notification['due_date'], patient_rm.last_blood_test_date + timedelta(days=7))






class OncologyCodingTests(TestCase):
    """Тести для модуля автоматизації онкологічного кодування та Наказу № 473"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='doctor_oncologist',
            password='testpass123',
            role='doctor',
            approved=True
        )

    def test_validate_diagnosis_compliance_valid(self):
        """Тест правильного визначення відповідності діагнозу Наказу № 473"""
        # Діагноз містить МКХ-10 (C50) та опис містить код морфології (8070/3)
        patient_valid = Patient(
            last_name='Петров',
            first_name='Іван',
            diagnosis='Рак легень C34.1',
            histology_description='Плоскоклітинний рак 8070/3'
        )
        self.assertTrue(patient_valid.validate_diagnosis_compliance())

        # Діагноз містить і МКХ-10, і код морфології в одному полі
        patient_valid_combined = Patient(
            last_name='Петров',
            first_name='Іван',
            diagnosis='C50.9 - 8140/3 аденокарцинома',
            histology_description='Гістологічне підтвердження'
        )
        self.assertTrue(patient_valid_combined.validate_diagnosis_compliance())

    def test_validate_diagnosis_compliance_invalid(self):
        """Тест виявлення невідповідностей у діагнозах (відсутні коди)"""
        # Відсутній код МКХ-10
        patient_no_icd = Patient(
            last_name='Петров',
            first_name='Іван',
            diagnosis='Рак легень без коду',
            histology_description='Плоскоклітинний рак 8070/3'
        )
        self.assertFalse(patient_no_icd.validate_diagnosis_compliance())

        # Відсутній код морфології
        patient_no_morph = Patient(
            last_name='Петров',
            first_name='Іван',
            diagnosis='Рак легень C34.1',
            histology_description='Плоскоклітинний рак'
        )
        self.assertFalse(patient_no_morph.validate_diagnosis_compliance())

    def test_patient_form_validation_warning(self):
        """Тест появи попередження (messages.warning) у представленнях при неповному діагнозі"""
        self.client.login(username='doctor_oncologist', password='testpass123')
        
        # Створення пацієнта з неповним діагнозом (без кодів)
        response = self.client.post(
            reverse('patient_create'),
            data={
                'last_name': 'Тестовий',
                'first_name': 'Неповний',
                'gender': 'M',
                'diagnosis': 'Діагноз без кодів',
                'hospitalization_status': 'outpatient'
            }
        )
        self.assertEqual(response.status_code, 302) # успішне створення (редірект)
        
        # Перевірка наявності попередження в повідомленнях
        response_list = self.client.get(reverse('patient_list'))
        messages = list(response_list.context['messages'])
        warning_messages = [str(m) for m in messages if 'Наказом № 473' in str(m)]
        self.assertEqual(len(warning_messages), 1)
        self.assertEqual(warning_messages[0], "Діагноз неповний згідно з Наказом № 473")


import json

class PINAndConfidentialNotesTests(TestCase):
    """Тести для PIN-кодів, шифрування нотаток та інтерактивних фракцій"""

    def setUp(self):
        self.user = User.objects.create_user(username='doctor_test', password='password123', role='doctor', approved=True)
        self.client = Client()
        self.client.login(username='doctor_test', password='password123')
        
        self.patient = Patient.objects.create(
            last_name='Тестовий',
            first_name='Пацієнт',
            treatment_start_date=date.today(),
            total_fractions=5,
            dose_per_fraction=2.0
        )
        # Створюємо фракцію
        self.fraction = FractionHistory.objects.create(
            patient=self.patient,
            date=date.today(),
            dose=2.0,
            status='scheduled'
        )

    def test_user_pin_set_and_check(self):
        """Тест встановлення та перевірки PIN-коду з брутфорс захистом"""
        user = self.user
        
        # 1. PIN не встановлено
        success, status = user.check_pin('1234')
        self.assertFalse(success)
        self.assertEqual(status, 'no_pin')
        
        # 2. Встановлюємо PIN
        user.set_pin('1234')
        user.save()
        
        # 3. Перевіряємо правильний PIN
        success, status = user.check_pin('1234')
        self.assertTrue(success)
        self.assertEqual(status, 'success')
        self.assertEqual(user.pin_failed_attempts, 0)
        
        # 4. Перевіряємо неправильний PIN (спроба 1)
        success, status = user.check_pin('1111')
        self.assertFalse(success)
        self.assertEqual(status, 'invalid')
        self.assertEqual(user.pin_failed_attempts, 1)
        
        # 5. Спроба 2
        success, status = user.check_pin('2222')
        self.assertFalse(success)
        self.assertEqual(user.pin_failed_attempts, 2)
        
        # 6. Спроба 3 -> має викликати блокування
        success, status = user.check_pin('3333')
        self.assertFalse(success)
        self.assertEqual(status, 'invalid') # в цей момент отримали 3 спроби і встановили блокування
        self.assertEqual(user.pin_failed_attempts, 3)
        self.assertIsNotNone(user.pin_lockout_until)
        
        # 7. Наступна перевірка має повернути 'locked'
        success, status = user.check_pin('1234')
        self.assertFalse(success)
        self.assertEqual(status, 'locked')

    def test_encrypt_decrypt_services(self):
        """Тест шифрування та дешифрування приміток"""
        from .services import encrypt_notes, decrypt_notes
        original_text = "Сума подяки: 10000 грн"
        
        encrypted = encrypt_notes(original_text)
        self.assertNotEqual(encrypted, original_text)
        self.assertIn("gAAAAA", encrypted) # Fernet токени починаються з gAAAAA
        
        decrypted = decrypt_notes(encrypted)
        self.assertEqual(decrypted, original_text)

    def test_api_endpoints_pin_and_notes(self):
        """Тест API ендпоінтів для PIN-коду та нотаток"""
        # Встановлюємо PIN
        response = self.client.post(
            reverse('set_user_pin'),
            data=json.dumps({'password': 'password123', 'pin': '9999'}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        
        # Перевіряємо, що PIN зберігся
        self.user.refresh_from_db()
        success, status = self.user.check_pin('9999')
        self.assertTrue(success)
        
        # Зберігаємо конфіденційні нотатки
        response = self.client.post(
            reverse('encrypt_patient_notes', kwargs={'pk': self.patient.pk}),
            data=json.dumps({'pin': '9999', 'notes': 'Секретні нотатки 500'}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        
        # Дешифруємо нотатки через API з правильним PIN-кодом
        response = self.client.post(
            reverse('decrypt_patient_notes', kwargs={'pk': self.patient.pk}),
            data=json.dumps({'pin': '9999'}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['notes'], 'Секретні нотатки 500')
        
        # Спроба дешифрувати з неправильним PIN-кодом
        response = self.client.post(
            reverse('decrypt_patient_notes', kwargs={'pk': self.patient.pk}),
            data=json.dumps({'pin': '1111'}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 403)

    def test_toggle_fraction_status_api(self):
        """Тест швидкого AJAX-ендпоінту перемикання статусу фракцій"""
        self.assertEqual(self.fraction.status, 'scheduled')
        
        # Перемикаємо: scheduled -> delivered
        response = self.client.post(
            reverse('toggle_fraction_status', kwargs={'pk': self.fraction.pk})
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['status'], 'delivered')
        
        self.fraction.refresh_from_db()
        self.assertEqual(self.fraction.status, 'delivered')


from unittest.mock import patch, MagicMock
from django.utils import timezone
from .models import PatientAIDocumentation, PatientAIDiary

class AIAssistantTests(TestCase):
    def setUp(self):
        # Очищуємо та створюємо тестового користувача
        self.user = User.objects.create_user(username='testdoctor', password='password123', role='doctor', approved=True)
        self.client.login(username='testdoctor', password='password123')
        
        # Створюємо тестового пацієнта
        self.patient = Patient.objects.create(
            last_name='Тестовий',
            first_name='Пацієнт',
            gender='M',
            diagnosis='C34.9',
            treatment_start_date=timezone.localdate(),
            total_fractions=10,
            dose_per_fraction=2.0,
            is_active=True
        )

    def test_ai_notes_save(self):
        """Тест збереження клінічних нотаток стану для ШІ"""
        url = reverse('save_ai_notes', kwargs={'pk': self.patient.pk})
        response = self.client.post(url, {
            'clinical_state_notes': 'Пацієнт скаржиться на легкий кашель, ECOG 1'
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        
        # Перевіряємо збереження в БД
        ai_doc = PatientAIDocumentation.objects.get(patient=self.patient)
        self.assertEqual(ai_doc.clinical_state_notes, 'Пацієнт скаржиться на легкий кашель, ECOG 1')

    def test_ai_doc_text_save(self):
        """Тест збереження редагованого тексту первинного огляду та виписки"""
        url = reverse('save_ai_doc_text', kwargs={'pk': self.patient.pk})
        response = self.client.post(url, {
            'initial_assessment': 'Текст первинного огляду',
            'discharge_summary': 'Текст виписки'
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        
        # Перевіряємо в БД
        ai_doc = PatientAIDocumentation.objects.get(patient=self.patient)
        self.assertEqual(ai_doc.initial_assessment, 'Текст первинного огляду')
        self.assertEqual(ai_doc.discharge_summary, 'Текст виписки')

    def test_ai_diary_save_and_delete(self):
        """Тест редагування та видалення щоденникових записів"""
        # Створюємо щоденник у БД
        diary = PatientAIDiary.objects.create(
            patient=self.patient,
            date=timezone.localdate(),
            fraction_number=1,
            ecog_status=1,
            ctcae_grade=1,
            clinical_state_notes='Помірна сухість шкіри',
            generated_text='Згенерований щоденник фракції 1'
        )
        
        # 1. Редагуємо текст щоденника через POST
        save_url = reverse('save_ai_diary', kwargs={'pk': self.patient.pk, 'diary_id': diary.pk})
        response = self.client.post(save_url, {
            'generated_text': 'Оновлений текст щоденника'
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        
        diary.refresh_from_db()
        self.assertEqual(diary.generated_text, 'Оновлений текст щоденника')
        
        # 2. Видаляємо щоденник через POST
        delete_url = reverse('delete_ai_diary', kwargs={'pk': self.patient.pk, 'diary_id': diary.pk})
        response = self.client.post(delete_url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        
        # Перевіряємо видалення з БД
        self.assertFalse(PatientAIDiary.objects.filter(pk=diary.pk).exists())

    @patch('patients.ai_service.generate_initial_assessment')
    def test_generate_ai_doc_initial(self, mock_generate):
        """Тест виклику генерації первинного огляду"""
        # Налаштовуємо мок
        mock_generate.return_value = 'Mocked Initial Assessment Content'
        
        # Створюємо нотатки стану спочатку
        ai_doc = PatientAIDocumentation.objects.create(
            patient=self.patient,
            clinical_state_notes='Тестові нотатки'
        )
        
        url = reverse('generate_ai_doc', kwargs={'pk': self.patient.pk, 'doc_type': 'initial'})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['text'], 'Mocked Initial Assessment Content')
        
        # Перевіряємо збереження в БД
        ai_doc.refresh_from_db()
        self.assertEqual(ai_doc.initial_assessment, 'Mocked Initial Assessment Content')

    @patch('patients.ai_service.generate_diary_entry')
    def test_generate_ai_diary(self, mock_generate):
        """Тест генерації нового щоденника фракції через ендпоінт"""
        mock_generate.return_value = 'Mocked Diary Content'
        
        url = reverse('generate_ai_diary', kwargs={'pk': self.patient.pk})
        response = self.client.post(url, {
            'date': timezone.localdate().strftime('%Y-%m-%d'),
            'fraction_number': '2',
            'ecog_status': '1',
            'ctcae_grade': '1',
            'clinical_state_notes': 'Скарги на еритему',
            'diary_type': 'admission'
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['text'], 'Mocked Diary Content')
        self.assertEqual(data['fraction_number'], 2)
        self.assertEqual(data['diary_type'], 'admission')
        
        # Перевіряємо створення щоденника в БД
        diary = PatientAIDiary.objects.get(id=data['diary_id'])
        self.assertEqual(diary.generated_text, 'Mocked Diary Content')
        self.assertEqual(diary.ecog_status, 1)
        self.assertEqual(diary.ctcae_grade, 1)
        self.assertEqual(diary.clinical_state_notes, 'Скарги на еритему')
        self.assertEqual(diary.diary_type, 'admission')

    def test_dashboard_planned_discharges(self):
        """Тест розрахунку запланованих виписок на дашборді"""
        today = timezone.localdate()
        
        if today.weekday() < 4:
            start_of_week = today - timedelta(days=today.weekday())
            expected_label = "Випишуться цього тижня"
        else:
            start_of_week = today + timedelta(days=(7 - today.weekday()))
            expected_label = "Випишуться наступного тижня"
            
        target_discharge_date = start_of_week + timedelta(days=3)
        
        discharge_patient = Patient.objects.create(
            last_name='Виписка',
            first_name='Тест',
            gender='F',
            diagnosis='C50.9',
            treatment_start_date=today - timedelta(days=10),
            discharge_date=target_discharge_date,
            is_active=True
        )
        
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['planned_discharge_label'], expected_label)
        self.assertGreaterEqual(response.context['planned_discharge_count'], 1)

    def test_filtered_patient_list_in_treatment(self):
        """Тест фільтрації пацієнтів "В лікуванні" на наявність пацієнтів з датою виписки"""
        today = timezone.localdate()
        active_patient = Patient.objects.create(
            last_name='Активний',
            first_name='Пацієнт',
            gender='M',
            diagnosis='C34.9',
            treatment_start_date=today - timedelta(days=2),
            discharge_date=today + timedelta(days=5),
            is_active=True
        )
        
        url = reverse('patient_list_filtered', kwargs={'filter_type': 'in-treatment'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn(active_patient, response.context['patients'])

    def test_dashboard_quote_of_the_day(self):
        """Тест отримання випадкової щоденної цитати на дашборді"""
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('quote_of_the_day', response.context)
        self.assertTrue(response.context['quote_of_the_day'].startswith('💡'))
    def test_completed_patient_extra_missed_fractions_cleanup(self):
        """Тест автоматичного видалення фракцій зі статусом missed/scheduled після завершення повного курсу"""
        today = timezone.localdate()
        patient = Patient.objects.create(
            last_name='Тинятовський',
            first_name='Михайло',
            gender='M',
            diagnosis='C30.0',
            treatment_start_date=today - timedelta(days=10),
            total_fractions=5,
            dose_per_fraction=2.0,
            is_active=True
        )
        # Створюємо 5 виконаних фракцій
        last_delivered_date = today - timedelta(days=3)
        for i in range(5):
            FractionHistory.objects.create(
                patient=patient,
                date=today - timedelta(days=7 - i),
                dose=2.0,
                status='delivered'
            )
        # Створюємо 2 зайві "missed" фракції за минулі дні (коли лікар був у відпустці)
        FractionHistory.objects.create(
            patient=patient,
            date=today - timedelta(days=2),
            dose=2.0,
            status='missed'
        )
        FractionHistory.objects.create(
            patient=patient,
            date=today - timedelta(days=1),
            dose=2.0,
            status='missed'
        )
        
        # Оскільки post_save автоматично створює 5 scheduled фракцій при створенні пацієнта,
        # загальна кількість до очищення становить 5 (scheduled) + 5 (delivered) + 2 (missed) = 12.
        self.assertEqual(patient.fractions.count(), 12)
        self.assertEqual(patient.fractions.filter(status='missed').count(), 2)
        
        # Перераховуємо розклад / дату виписки
        from .services import shift_patient_schedule, recalculate_discharge_date
        shift_patient_schedule(patient)
        recalculate_discharge_date(patient)
        patient.refresh_from_db()
        
        # Перевіряємо: всі зайві (scheduled та missed) фракції видалено, виписку оновлено до дати 5-ї виконаної фракції
        self.assertEqual(patient.fractions.count(), 5)
        self.assertEqual(patient.fractions.filter(status='missed').count(), 0)
        self.assertEqual(patient.discharge_date, last_delivered_date)

    def test_bulk_confirm_period_api_and_preview(self):
        """Тест API модального вікна масового підтвердження за період та попереднього перегляду"""
        today = timezone.localdate()
        start = (today - timedelta(days=7)).strftime('%Y-%m-%d')
        end = (today - timedelta(days=1)).strftime('%Y-%m-%d')
        
        patient = Patient.objects.create(
            last_name='Петренко',
            first_name='Петро',
            gender='M',
            diagnosis='C15.4',
            treatment_start_date=today - timedelta(days=14),
            total_fractions=10,
            dose_per_fraction=2.0,
            is_active=True
        )
        
        # 1. Тест preview API
        url_preview = reverse('bulk_confirm_preview_api') + f'?start_date={start}&end_date={end}&include_missed=true'
        res_preview = self.client.get(url_preview)
        self.assertEqual(res_preview.status_code, 200)
        data_preview = res_preview.json()
        self.assertTrue(data_preview['success'])
        self.assertGreater(data_preview['total_fractions'], 0)
        
        # 2. Тест period confirm API
        url_confirm = reverse('bulk_confirm_period_api')
        res_confirm = self.client.post(
            url_confirm,
            data=json.dumps({'start_date': start, 'end_date': end, 'include_missed': True}),
            content_type='application/json'
        )
        self.assertEqual(res_confirm.status_code, 200)
        data_confirm = res_confirm.json()
        self.assertTrue(data_confirm['success'])
        self.assertGreater(data_confirm['confirmed_count'], 0)

    def test_bulk_confirm_patient_up_to_date_api(self):
        """Тест API підтвердження фракцій конкретного пацієнта до обраної дати"""
        today = timezone.localdate()
        patient = Patient.objects.create(
            last_name='Коваленко',
            first_name='Іван',
            gender='M',
            diagnosis='C34.1',
            treatment_start_date=today - timedelta(days=5),
            total_fractions=10,
            dose_per_fraction=2.0,
            is_active=True
        )
        
        target_date_str = (today - timedelta(days=1)).strftime('%Y-%m-%d')
        url = reverse('bulk_confirm_patient_up_to_date_api', kwargs={'patient_id': patient.id})
        res = self.client.post(url, {'up_to_date': target_date_str, 'include_missed': 'true'})
        
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertGreater(data['confirmed_count'], 0)
        patient.refresh_from_db()
        self.assertGreater(patient.current_fraction, 0)

    def test_archive_and_filtered_tabs_sorting(self):
        """Тест збереження вкладки Архів та інших фільтрів при сортуванні за різними колонками"""
        today = timezone.localdate()
        # Архівний пацієнт
        p_arch = Patient.objects.create(
            last_name='Архівний',
            first_name='Тест',
            gender='M',
            diagnosis='C50.9',
            treatment_start_date=today - timedelta(days=30),
            discharge_date=today - timedelta(days=5),
            total_fractions=10,
            dose_per_fraction=2.0
        )
        
        # 1. Запит на архів з сортуванням по даті виписки
        url_arch = reverse('patient_archive') + '?sort=discharge_date&order=asc'
        res_arch = self.client.get(url_arch)
        self.assertEqual(res_arch.status_code, 200)
        self.assertTrue(res_arch.context['is_archive'])
        self.assertEqual(res_arch.context['filter_type'], 'archive')
        self.assertEqual(res_arch.context['current_sort'], 'discharge_date')
        
        # 2. Запит через filter_type='archive'
        url_filter_arch = reverse('patient_list_filtered', kwargs={'filter_type': 'archive'}) + '?sort=discharge_date&order=desc'
        res_filter_arch = self.client.get(url_filter_arch)
        self.assertEqual(res_filter_arch.status_code, 200)
        self.assertTrue(res_filter_arch.context['is_archive'])
        
        # 3. Запит на підготовку до виписки з сортуванням
        url_prep = reverse('patient_list_filtered', kwargs={'filter_type': 'discharge-prep'}) + '?sort=full_name&order=asc'
        res_prep = self.client.get(url_prep)
        self.assertEqual(res_prep.status_code, 200)
        self.assertFalse(res_prep.context['is_archive'])
        self.assertEqual(res_prep.context['filter_type'], 'discharge-prep')

    def test_simultaneous_integrated_boost_sib(self):
        """Тест роботи симультанного бусту (SIB): парсинг 2.66/3.0, розрахунок планової та виписаної СОД/СВД"""
        today = timezone.localdate()
        patient = Patient(
            last_name='Симультанний',
            first_name='Буст',
            gender='M',
            diagnosis='C15.4',
            treatment_start_date=today,
            total_fractions=16
        )
        patient.parse_and_set_doses("2.66/3.0")
        patient.save()
        
        self.assertTrue(patient.is_sib)
        self.assertEqual(patient.dose_per_fraction, 2.66)
        self.assertEqual(patient.dose_per_fraction_secondary, 3.0)
        self.assertEqual(patient.dose_per_fraction_display, "2.66/3 Гр")
        self.assertEqual(patient.planned_total_dose_display, "42.56/48 Гр")
        
        # Додаємо 5 виконаних фракцій
        for i in range(5):
            FractionHistory.objects.create(
                patient=patient,
                date=today + timedelta(days=i),
                dose=2.66,
                status='delivered'
            )
            
        patient.recalculate_received_dose()
        patient.refresh_from_db()
        
        self.assertEqual(patient.received_dose, 13.3)
        self.assertEqual(patient.received_dose_secondary, 15.0)
        self.assertEqual(patient.received_dose_display, "13.3/15 Гр")






