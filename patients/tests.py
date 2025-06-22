from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import date, timedelta
from .models import Patient, FractionHistory, MedicalIncapacity

User = get_user_model()

class PatientFilterTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            role='doctor',
            approved=True
        )
        self.client.login(username='testuser', password='testpass123')
        
        # Очищаємо базу даних перед тестами
        Patient.objects.all().delete()
        
        # Створюємо тестові дані
        today = date.today()
        
        # Пацієнт для КТ-симуляції (КТ-симуляція сьогодні або в минулому)
        self.ct_patient = Patient.objects.create(
            first_name="КТ",
            last_name="Пацієнт",
            ct_simulation_date=today,
            current_stage="КТ-симуляція"
        )
        
        # Пацієнт для підготовки до лікування (КТ пройшов, лікування в майбутньому)
        self.prep_patient = Patient.objects.create(
            first_name="Підготовка",
            last_name="Пацієнт",
            ct_simulation_date=today - timedelta(days=5),
            treatment_start_date=today + timedelta(days=3),
            current_stage="початок лікування"
        )
        
        # Пацієнт на лікуванні (лікування почалося в минулому, виписка через 15 днів)
        self.treatment_patient = Patient.objects.create(
            first_name="Лікування",
            last_name="Пацієнт",
            treatment_start_date=today - timedelta(days=10),
            discharge_date=today + timedelta(days=15),
            current_stage="лікування"
        )
        
        # Пацієнт на підготовці до виписки (виписка через 2 дні)
        self.discharge_patient = Patient.objects.create(
            first_name="Виписка",
            last_name="Пацієнт",
            treatment_start_date=today - timedelta(days=20),
            discharge_date=today + timedelta(days=2),
            current_stage="підготовка до виписки"
        )

    def test_ct_simulation_filter(self):
        """Тест фільтра КТ-симуляції"""
        response = self.client.get(reverse('patient_list_filtered', args=['ct-simulation']))
        self.assertEqual(response.status_code, 200)
        patients = response.context['patients']
        # Перевіряємо, що пацієнт з КТ-симуляцією є в результатах
        self.assertTrue(any(p.id == self.ct_patient.id for p in patients))

    def test_treatment_start_filter(self):
        """Тест фільтра підготовки до лікування"""
        response = self.client.get(reverse('patient_list_filtered', args=['treatment-start']))
        self.assertEqual(response.status_code, 200)
        patients = response.context['patients']
        # Перевіряємо, що пацієнт на підготовці є в результатах
        self.assertTrue(any(p.id == self.prep_patient.id for p in patients))

    def test_in_treatment_filter(self):
        """Тест фільтра лікування"""
        response = self.client.get(reverse('patient_list_filtered', args=['in-treatment']))
        self.assertEqual(response.status_code, 200)
        patients = response.context['patients']
        # Перевіряємо, що пацієнт на лікуванні є в результатах
        self.assertTrue(any(p.id == self.treatment_patient.id for p in patients))

    def test_discharge_prep_filter(self):
        """Тест фільтра підготовки до виписки"""
        response = self.client.get(reverse('patient_list_filtered', args=['discharge-prep']))
        self.assertEqual(response.status_code, 200)
        patients = response.context['patients']
        # Перевіряємо, що пацієнт на підготовці до виписки є в результатах
        self.assertTrue(any(p.id == self.discharge_patient.id for p in patients))


class AuthenticationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            role='doctor',
            approved=True
        )

    def test_login_success(self):
        """Тест успішного входу"""
        response = self.client.post(reverse('login'), {
            'username': 'testuser',
            'password': 'testpass123'
        })
        self.assertEqual(response.status_code, 302)  # Redirect after login

    def test_login_failure(self):
        """Тест невдалого входу"""
        response = self.client.post(reverse('login'), {
            'username': 'testuser',
            'password': 'wrongpass'
        })
        self.assertEqual(response.status_code, 200)  # Stay on login page

    def test_logout(self):
        """Тест виходу"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('logout'))
        self.assertEqual(response.status_code, 302)  # Redirect after logout


class PatientCRUDTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            role='doctor',
            approved=True
        )
        self.client.login(username='testuser', password='testpass123')
        
        self.patient = Patient.objects.create(
            first_name="Тестовий",
            last_name="Пацієнт",
            diagnosis="Тестова діагноза"
        )

    def test_patient_list(self):
        """Тест списку пацієнтів"""
        response = self.client.get(reverse('patient_list'))
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.patient, response.context['patients'])

    def test_patient_detail(self):
        """Тест деталей пацієнта"""
        response = self.client.get(reverse('patient_detail', args=[self.patient.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['patient'], self.patient)

    def test_patient_create(self):
        """Тест створення пацієнта"""
        response = self.client.post(reverse('patient_create'), {
            'first_name': 'Новий',
            'last_name': 'Пацієнт',
            'diagnosis': 'Нова діагноза'
        })
        self.assertEqual(response.status_code, 302)  # Redirect after create
        self.assertTrue(Patient.objects.filter(first_name='Новий').exists())

    def test_patient_update(self):
        """Тест оновлення пацієнта"""
        response = self.client.post(reverse('patient_update', args=[self.patient.id]), {
            'first_name': 'Оновлений',
            'last_name': 'Пацієнт',
            'diagnosis': 'Оновлена діагноза'
        })
        self.assertEqual(response.status_code, 302)  # Redirect after update
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.first_name, 'Оновлений')

    def test_patient_delete(self):
        """Тест видалення пацієнта"""
        response = self.client.post(reverse('patient_delete', args=[self.patient.id]))
        self.assertEqual(response.status_code, 302)  # Redirect after delete
        self.assertFalse(Patient.objects.filter(id=self.patient.id).exists())


class FractionTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            role='doctor',
            approved=True
        )
        self.client.login(username='testuser', password='testpass123')
        
        self.patient = Patient.objects.create(
            first_name="Тестовий",
            last_name="Пацієнт",
            treatment_start_date=date.today(),
            total_fractions=5
        )
        
        self.fraction = FractionHistory.objects.create(
            patient=self.patient,
            date=date.today(),
            dose=2.0,
            delivered=False,
            confirmed_by_doctor=False
        )

    def test_fraction_list(self):
        """Тест списку фракцій"""
        response = self.client.get(reverse('fraction_list'))
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.fraction, response.context['fractions'])

    def test_fraction_confirm_doctor(self):
        """Тест підтвердження фракції лікарем"""
        response = self.client.post(reverse('confirm_fractions_doctor'), {
            'fraction_ids': [self.fraction.id]
        })
        self.assertEqual(response.status_code, 302)
        self.fraction.refresh_from_db()
        self.assertTrue(self.fraction.confirmed_by_doctor)

    def test_fraction_confirm_nurse(self):
        """Тест підтвердження фракції медсестрою"""
        response = self.client.post(reverse('confirm_fractions_nurse'), {
            'fraction_ids': [self.fraction.id]
        })
        self.assertEqual(response.status_code, 302)
        self.fraction.refresh_from_db()
        self.assertTrue(self.fraction.delivered)


class MedicalIncapacityTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            role='doctor',
            approved=True
        )
        self.client.login(username='testuser', password='testpass123')
        
        self.patient = Patient.objects.create(
            first_name="Тестовий",
            last_name="Пацієнт"
        )

    def test_medical_incapacity_create(self):
        """Тест створення лікарняного"""
        response = self.client.get(reverse('medical_incapacity_create', args=[self.patient.id]))
        self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse('medical_incapacity_create', args=[self.patient.id]), {
            'mvt_number': '1234567890123456789',
            'start_date': date.today(),
            'end_date': date.today() + timedelta(days=7),
            'no_employment_relation': False
        })
        if response.status_code == 200:
            print('Form errors:', response.context['form'].errors)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(MedicalIncapacity.objects.filter(patient=self.patient).exists())

    def test_medical_incapacity_delete(self):
        """Тест видалення лікарняного"""
        incapacity = MedicalIncapacity.objects.create(
            patient=self.patient,
            mvt_number='1234567890123456789',
            start_date=date.today()
        )
        response = self.client.post(reverse('medical_incapacity_delete', args=[incapacity.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(MedicalIncapacity.objects.filter(id=incapacity.id).exists())


class AdminTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_user(
            username='admin',
            password='adminpass123',
            role='admin',
            approved=True
        )
        self.client.login(username='admin', password='adminpass123')
        self.nurse_user = User.objects.create_user(
            username='nurse',
            password='nursepass123',
            role='nurse',
            approved=False
        )

    def test_admin_users_list(self):
        """Тест списку користувачів для адміністратора"""
        response = self.client.get(reverse('admin_users'))
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.nurse_user, response.context['users'])

    def test_approve_user(self):
        """Тест затвердження користувача"""
        response = self.client.post(reverse('approve_user', args=[self.nurse_user.id]))
        self.assertEqual(response.status_code, 302)
        self.nurse_user.refresh_from_db()
        self.assertTrue(self.nurse_user.approved)
