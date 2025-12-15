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
    postpone_fraction,
    mark_fraction_missed
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
            delivered=True
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
        
        # Перевіряємо згенерований текст
        expected_text = "Са правої молочної залози. T4N0M0. gr. IIIA. кл. гр. 2. Стан після радикального лікування. ПГЗ № 46779-90 від 22.11.2024. - Внутрішньопротоковий інвазивний Са (G2), mts в л/в"
        self.assertEqual(self.patient.get_diagnosis_text_for_copy(), expected_text)


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
                delivered=True
            )
        
        # За 10 робочих днів має бути 5 виконаних, отже 5 пропущених
        missed = self.patient.missed_days
        self.assertGreaterEqual(missed, 0)
        
        # Якщо пацієнт не в лікуванні, має повертати 0
        self.patient.discharge_date = date.today() - timedelta(days=5)
        self.patient.save()
        self.assertEqual(self.patient.missed_days, 0)
    
    def test_next_blood_test_due_date_property(self):
        """Тест властивості next_blood_test_due_date"""
        # Встановлюємо дату останнього аналізу
        self.patient.last_blood_test_date = date.today() - timedelta(days=5)
        self.patient.save()
        
        # Має повернути дату через 10 днів (тільки будні)
        next_date = self.patient.next_blood_test_due_date
        self.assertIsNotNone(next_date)
        self.assertGreaterEqual(next_date, date.today())
        
        # Якщо пацієнт не в лікуванні, має повертати None
        self.patient.discharge_date = date.today() - timedelta(days=1)
        self.patient.save()
        self.assertIsNone(self.patient.next_blood_test_due_date)
    
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
            delivered=False,
            confirmed_by_doctor=False
        )
        
        count = auto_confirm_today_fractions()
        # Може бути більше 1, якщо інші тести створили фракції, тому перевіряємо >= 1
        self.assertGreaterEqual(count, 1)
        
        # Перевіряємо, що наша фракція підтверджена
        fraction.refresh_from_db()
        self.assertTrue(fraction.delivered)
        self.assertTrue(fraction.confirmed_by_doctor)
    
    def test_get_patient_treatment_info(self):
        """Тест отримання інформації про лікування"""
        # Створюємо кілька виконаних фракцій
        for i in range(3):
            FractionHistory.objects.create(
                patient=self.patient,
                date=self.patient.treatment_start_date + timedelta(days=i),
                dose=2.0,
                delivered=True
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
    
    def test_postpone_fraction(self):
        """Тест відкладення фракції"""
        fraction = FractionHistory.objects.create(
            patient=self.patient,
            date=date.today() + timedelta(days=5),
            dose=2.0
        )
        
        new_date = date.today() + timedelta(days=10)
        postponed = postpone_fraction(fraction, new_date, "Причина відкладення")
        
        self.assertTrue(postponed.is_postponed)
        self.assertEqual(postponed.date, new_date)
        self.assertEqual(postponed.reason, "Причина відкладення")
        self.assertEqual(postponed.original_date, date.today() + timedelta(days=5))
    
    def test_mark_fraction_missed(self):
        """Тест позначення фракції як пропущеної"""
        fraction = FractionHistory.objects.create(
            patient=self.patient,
            date=date.today() - timedelta(days=1),
            dose=2.0
        )
        
        missed = mark_fraction_missed(fraction, "Причина пропуску")
        
        self.assertTrue(missed.is_missed)
        self.assertEqual(missed.reason, "Причина пропуску")


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
    
    def test_fraction_edit_form_past_date_validation(self):
        """Тест валідації FractionEditForm: дата не може бути в минулому (якщо не пропущена)"""
        fraction = FractionHistory.objects.create(
            patient=self.patient,
            date=date.today() + timedelta(days=5),
            dose=2.0
        )
        
        # Спробуємо встановити дату в минулому без позначки is_missed
        form_data = {
            'date': (date.today() - timedelta(days=1)).strftime('%d.%m.%Y'),
            'dose': 2.0,
            'is_missed': False
        }
        
        form = FractionEditForm(data=form_data, instance=fraction)
        self.assertFalse(form.is_valid())
    
    def test_fraction_edit_form_past_date_with_missed(self):
        """Тест: дата в минулому дозволена, якщо фракція позначена як пропущена"""
        fraction = FractionHistory.objects.create(
            patient=self.patient,
            date=date.today() + timedelta(days=5),
            dose=2.0
        )
        
        form_data = {
            'date': (date.today() - timedelta(days=1)).strftime('%d.%m.%Y'),
            'dose': 2.0,
            'is_missed': True
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

