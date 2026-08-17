from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone
from django.core.exceptions import ValidationError
from datetime import date, timedelta
from django.db.models.signals import post_save
from django.dispatch import receiver

class UserManager(BaseUserManager):
    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError('The Username must be set')
        user = self.model(username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('approved', True)
        extra_fields.setdefault('role', 'admin')

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
            
        return self.create_user(username, password, **extra_fields)

class User(AbstractBaseUser, PermissionsMixin):
    username = models.CharField(unique=True, max_length=255)
    password = models.CharField(max_length=255)
    role = models.CharField(max_length=255)
    doctor = models.ForeignKey('self', models.DO_NOTHING, blank=True, null=True, db_column='doctor_id')
    approved = models.BooleanField()
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)

    # These fields were added by the script
    last_login = models.DateTimeField(blank=True, null=True)
    is_superuser = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    pin_code = models.CharField(max_length=255, blank=True, null=True, help_text="Хеш PIN-коду")
    pin_failed_attempts = models.IntegerField(default=0, help_text="Кількість неуспішних спроб введення PIN-коду")
    pin_lockout_until = models.DateTimeField(blank=True, null=True, help_text="Час блокування введення PIN-коду")
    
    # To avoid clashes with default User model's relations
    groups = models.ManyToManyField(
        'auth.Group', blank=True, related_name="custom_user_groups", related_query_name="user"
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission', blank=True, related_name="custom_user_permissions", related_query_name="user"
    )

    objects = UserManager()
    USERNAME_FIELD = 'username'

    def set_pin(self, raw_pin):
        from django.contrib.auth.hashers import make_password
        self.pin_code = make_password(raw_pin)
        self.pin_failed_attempts = 0
        self.pin_lockout_until = None
        
    def check_pin(self, raw_pin):
        from django.contrib.auth.hashers import check_password
        from django.utils import timezone
        
        # Перевірка на блокування
        if self.pin_lockout_until and self.pin_lockout_until > timezone.now():
            return False, "locked"
            
        if not self.pin_code:
            return False, "no_pin"
            
        if check_password(raw_pin, self.pin_code):
            self.pin_failed_attempts = 0
            self.pin_lockout_until = None
            self.save()
            return True, "success"
        else:
            self.pin_failed_attempts += 1
            if self.pin_failed_attempts >= 3:
                self.pin_lockout_until = timezone.now() + timezone.timedelta(minutes=15)
            self.save()
            return False, "invalid"
    
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()
    
    def get_role_display(self):
        return self.role.capitalize()

    class Meta:
        db_table = 'users'

class Patient(models.Model):
    # Особиста інформація
    ambulatory_card_id = models.CharField(
        max_length=50, 
        blank=True, 
        null=True, 
        unique=True,
        help_text="ID амбулаторної картки (наприклад: 228435/2025 або 2025-9246582)",
        verbose_name="ID амбулаторної картки"
    )
    last_name = models.CharField(max_length=255, blank=True, null=True, help_text="Прізвище")
    first_name = models.CharField(max_length=255, blank=True, null=True, help_text="Ім'я")
    middle_name = models.CharField(max_length=255, blank=True, null=True, help_text="По батькові")
    birth_date = models.DateField(blank=True, null=True, help_text="Дата народження")
    gender = models.CharField(max_length=10, blank=True, null=True, choices=[('M', 'Чоловіча'), ('F', 'Жіноча')], help_text="Стать")
    
    # Діагноз та стадіювання
    diagnosis = models.CharField(max_length=255, blank=True, null=True, help_text="Діагноз")
    tnm_staging = models.CharField(max_length=255, blank=True, null=True, help_text="Стадіювання за TNM")
    disease_stage = models.CharField(max_length=255, blank=True, null=True, help_text="Стадія захворювання (текст)")
    clinical_group = models.CharField(max_length=255, blank=True, null=True, help_text="Клінічна група (текст)")

    # Інформація про лікування
    treatment_type = models.CharField(max_length=255, blank=True, null=True, help_text="Тип лікування")
    treatment_phase = models.CharField(max_length=255, blank=True, null=True, help_text="Фаза лікування")
    irradiation_zone = models.CharField(max_length=255, blank=True, null=True, help_text="Зона опромінення")
    total_fractions = models.IntegerField(blank=True, null=True, help_text="Загальна кількість фракцій")
    dose_per_fraction_raw = models.CharField(max_length=100, blank=True, null=True, help_text="Текстовий запис РОД (наприклад: 2.0 або 2.66/3.0)")
    dose_per_fraction = models.FloatField(blank=True, null=True, help_text="Основна РОД (Гр)")
    dose_per_fraction_secondary = models.FloatField(blank=True, null=True, help_text="Другорядна РОД (Гр) при SIB")
    received_dose = models.FloatField(blank=True, null=True, help_text="Основна СОД (Гр)")
    received_dose_secondary = models.FloatField(blank=True, null=True, help_text="Другорядна СОД (Гр) при SIB")
    is_sib = models.BooleanField(default=False, help_text="Чи застосовується симультанний буст (SIB)")

    # Дати
    ct_simulation_date = models.DateField(blank=True, null=True, help_text="Дата КТ-симуляції")
    treatment_start_date = models.DateField(blank=True, null=True, help_text="Дата початку лікування")
    discharge_date = models.DateField(blank=True, null=True, help_text="Дата виписки")
    last_blood_test_date = models.DateField(blank=True, null=True, help_text="Дата останнього аналізу крові")

    # Гістологія
    histology_number = models.CharField(max_length=255, blank=True, null=True, help_text="Номер гістології")
    histology_date = models.DateField(blank=True, null=True, help_text="Дата гістології")
    histology_description = models.TextField(blank=True, null=True, help_text="Опис гістології")
    
    # Стаціонар та інше
    is_active = models.BooleanField(default=True, help_text="Чи є пацієнт активним (не в архіві)")
    hospitalization_status = models.CharField(max_length=20, choices=[('outpatient', 'Амбулаторно'), ('inpatient', 'Стаціонар'), ('queue', 'У черзі')], default='outpatient', blank=True, help_text="Статус госпіталізації")
    planned_admission_date = models.DateField(null=True, blank=True, help_text="Планова дата госпіталізації")
    bed_owner = models.CharField(max_length=100, default='Олег', blank=True, help_text="Прізвище лікаря, чиє ліжко зайнято. Якщо 'Олег' — це власне ліжко.")
    ward_number = models.IntegerField(blank=True, null=True, help_text="Номер палати")
    prior_radiation = models.CharField(max_length=255, blank=True, null=True, help_text="Попереднє опромінення")
    notes = models.TextField(blank=True, null=True, help_text="Примітки")
    raw_diagnosis = models.TextField(blank=True, null=True, help_text="Оригінальний вставлений діагноз")
    has_radiomodification = models.BooleanField(default=False, help_text="Потребує радіомодифікації (щотижневий аналіз крові)")
    encrypted_confidential_notes = models.TextField(blank=True, null=True, help_text="Зашифровані конфіденційні примітки")
    
    #  Системні
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)

    @property
    def full_name(self):
        return f"{self.last_name} {self.first_name} {self.middle_name}".strip()

    @property
    def summary_text(self):
        """Сформована текстова довідка за даними пацієнта"""
        parts = []
        if self.diagnosis:
            parts.append(self.diagnosis)
        if self.tnm_staging:
            parts.append(self.tnm_staging)
        if self.disease_stage:
            parts.append(f"gr. {self.disease_stage}")
        if self.clinical_group:
            parts.append(f"кл. гр. {self.clinical_group}")
        if self.treatment_type:
            parts.append(f"стан після {self.treatment_type}")
        if self.histology_number or self.histology_date or self.histology_description:
            histology = "ПГЗ"
            if self.histology_number:
                histology += f" № {self.histology_number}"
            if self.histology_date:
                histology += f" від {self.histology_date.strftime('%d.%m.%Y')}р."
            if self.histology_description:
                histology += f" - {self.histology_description}"
            parts.append(histology)
        return ", ".join(parts)

    @property
    def display_stage(self):
        """
        Динамічно визначає поточний етап пацієнта на основі дат.
        """
        today = timezone.now().date()
        
        if self.discharge_date and self.discharge_date <= today:
            return "Архів"
        
        three_days_later = today + timedelta(days=3)
        if self.discharge_date and today < self.discharge_date <= three_days_later:
            return "Підготовка до виписки"
        
        if self.treatment_start_date and self.treatment_start_date <= today:
            return "Лікування"
            
        if self.ct_simulation_date and not self.treatment_start_date:
            return "КТ-симуляція"

        if self.treatment_start_date and self.treatment_start_date > today:
            return "Початок лікування"

        return "Новий"

    @property
    def get_actual_discharge_date(self):
        """
        Повертає дату найостаннішої фракції пацієнта з FractionHistory.
        Якщо фракції згенеровані, це дата останньої фракції.
        Якщо фракцій ще немає, повертає discharge_date або None.
        """
        if hasattr(self, '_prefetched_objects_cache') and 'fractions' in self._prefetched_objects_cache:
            fractions = list(self.fractions.all())
            if fractions:
                return max(f.date for f in fractions)
            return self.discharge_date or None
            
        latest_fraction = self.fractions.order_by('date').last()
        if latest_fraction:
            return latest_fraction.date
        return self.discharge_date or None

    @property
    def current_fraction(self):
        """Динамічно розраховує кількість проведених фракцій."""
        return self.fractions.filter(status='delivered').count()

    @property
    def missed_days(self):
        """Динамічно розраховує кількість пропущених робочих днів лікування."""
        return self.fractions.filter(status='missed').count()

    @property
    def next_blood_test_due_date(self):
        """
        Розраховує наступну рекомендовану дату аналізу крові:
        - Без радіомодифікації: +12 робочих днів від останнього аналізу (або від початку лікування, якщо аналізів не було).
        - З радіомодифікацією: +7 календарних днів від останнього аналізу (потрібно вказувати вручну).
        - Якщо розрахована дата виходить за межі періоду лікування (на або після дати виписки), аналіз НЕ призначається.
        """
        today = timezone.localdate()

        # Якщо пацієнт вже виписаний або неактивний, аналізи не призначаються
        if not self.is_active:
            return None
            
        actual_discharge = self.get_actual_discharge_date or self.discharge_date
        if actual_discharge and actual_discharge < today:
            return None

        if self.has_radiomodification:
            base_date = self.last_blood_test_date or (self.treatment_start_date if self.treatment_start_date and self.treatment_start_date >= today else None)
            if not base_date:
                due_date = None
            else:
                due_date = base_date + timedelta(days=7)
        else:
            base_date = self.last_blood_test_date or self.treatment_start_date
            if not base_date:
                due_date = None
            else:
                current_date = base_date
                added_working_days = 0
                while added_working_days < 12:
                    current_date += timedelta(days=1)
                    if current_date.weekday() < 5:  # 0-4 corresponds to Mon-Fri
                        added_working_days += 1
                due_date = current_date

        if not due_date:
            return None

        # Якщо дата виписки (завершення лікування) передує або ЗБІГАЄТЬСЯ з розрахованою датою аналізу,
        # то здавати аналіз не потрібно, оскільки в день виписки аналізи вже не проводяться!
        if actual_discharge and due_date >= actual_discharge:
            return None

        return due_date

    @property
    def is_in_treatment(self):
        """Перевіряє, чи пацієнт наразі проходить лікування."""
        today = timezone.localdate()
        if self.treatment_start_date and self.treatment_start_date <= today:
            if not self.discharge_date or self.discharge_date >= today:
                return True
        return False

    def get_latest_medical_incapacity(self):
        return self.medical_incapacities.order_by('-end_date').first()

    def parse_and_set_doses(self, raw_input):
        """
        Розбирає текстове значення РОД (наприклад '2.66/3.0', '2,66/3,0' або '2.0')
        та встановлює поля dose_per_fraction, dose_per_fraction_secondary, is_sib.
        """
        if raw_input is None or str(raw_input).strip() == '':
            self.dose_per_fraction_raw = None
            self.dose_per_fraction = None
            self.dose_per_fraction_secondary = None
            self.is_sib = False
            return

        raw_str = str(raw_input).strip()
        self.dose_per_fraction_raw = raw_str

        if '/' in raw_str:
            parts = [p.strip().replace(',', '.') for p in raw_str.split('/') if p.strip()]
            if len(parts) >= 2:
                try:
                    val1 = float(parts[0])
                    val2 = float(parts[1])
                    self.dose_per_fraction = val1
                    self.dose_per_fraction_secondary = val2
                    self.is_sib = True
                    return
                except ValueError:
                    pass
        
        # Одне число (не SIB)
        try:
            val = float(raw_str.replace(',', '.'))
            self.dose_per_fraction = val
            self.dose_per_fraction_secondary = None
            self.is_sib = False
        except ValueError:
            pass

    @property
    def dose_per_fraction_display(self):
        """Повертає форматований рядок РОД (наприклад '2.66/3.0 Гр' або '2.0 Гр')"""
        if self.is_sib and self.dose_per_fraction is not None and self.dose_per_fraction_secondary is not None:
            d1 = f"{self.dose_per_fraction:g}"
            d2 = f"{self.dose_per_fraction_secondary:g}"
            return f"{d1}/{d2} Гр"
        elif self.dose_per_fraction_raw and '/' in self.dose_per_fraction_raw:
            return f"{self.dose_per_fraction_raw} Гр"
        elif self.dose_per_fraction is not None:
            return f"{self.dose_per_fraction:g} Гр"
        return "—"

    @property
    def planned_total_dose_display(self):
        """Повертає форматовану планову СОД/СВД (наприклад '42.56/48.0 Гр' або '50.0 Гр')"""
        tf = self.total_fractions or 0
        if tf <= 0:
            return "—"
            
        if self.is_sib and self.dose_per_fraction is not None and self.dose_per_fraction_secondary is not None:
            tot1 = round(tf * self.dose_per_fraction, 2)
            tot2 = round(tf * self.dose_per_fraction_secondary, 2)
            return f"{tot1:g}/{tot2:g} Гр"
        elif self.dose_per_fraction is not None:
            tot = round(tf * self.dose_per_fraction, 2)
            return f"{tot:g} Гр"
        return "—"

    @property
    def received_dose_display(self):
        """Повертає форматовану накопичену СОД/СВД (наприклад '13.3/15.0 Гр' або '20.0 Гр')"""
        if self.is_sib and self.dose_per_fraction is not None and self.dose_per_fraction_secondary is not None:
            rd1 = self.received_dose if self.received_dose is not None else round((self.current_fraction or 0) * self.dose_per_fraction, 2)
            rd2 = self.received_dose_secondary if self.received_dose_secondary is not None else round((self.current_fraction or 0) * self.dose_per_fraction_secondary, 2)
            return f"{round(rd1, 2):g}/{round(rd2, 2):g} Гр"
        elif self.received_dose is not None:
            return f"{round(self.received_dose, 2):g} Гр"
        elif self.dose_per_fraction is not None:
            rd = round((self.current_fraction or 0) * self.dose_per_fraction, 2)
            return f"{rd:g} Гр"
        return "0.0 Гр"

    def recalculate_received_dose(self):
        """Перераховує отриману дозу на основі виконаних фракцій"""
        delivered_count = self.fractions.filter(status='delivered').count()
        dose1 = self.dose_per_fraction or 0.0
        self.received_dose = round(delivered_count * dose1, 2)
        
        if self.is_sib and self.dose_per_fraction_secondary is not None:
            dose2 = self.dose_per_fraction_secondary or 0.0
            self.received_dose_secondary = round(delivered_count * dose2, 2)
        else:
            self.received_dose_secondary = None
            
        self.save()

    def get_diagnosis_text_for_copy(self):
        """Формує текст діагнозу для копіювання в інші системи"""
        parts = []
        
        # Група 1: Діагноз, TNM, стадія, клінічна група (розділяються комами)
        basic_parts = []
        
        # Основний діагноз (видаляємо крапку в кінці, якщо є)
        if self.diagnosis:
            diagnosis = self.diagnosis.rstrip('. ')
            basic_parts.append(diagnosis)
        
        # TNM стадіювання
        if self.tnm_staging:
            basic_parts.append(self.tnm_staging)
        
        # Стадія захворювання
        if self.disease_stage:
            basic_parts.append(f"gr. {self.disease_stage}")
        
        # Клінічна група
        if self.clinical_group:
            basic_parts.append(f"кл. гр. {self.clinical_group}")
        
        # З'єднуємо базові частини комами
        if basic_parts:
            parts.append(", ".join(basic_parts))
        
        # Група 2: Стан після лікування (з крапкою перед)
        if self.treatment_type:
            if self.treatment_type == 'радикальне':
                parts.append("Стан після радикального лікування")
            elif self.treatment_type == 'паліативне':
                parts.append("Стан після паліативного лікування")
            elif self.treatment_type == 'симптоматичне':
                parts.append("Стан після симптоматичного лікування")
        
        # Група 3: ПГЗ (без крапки перед дефісом)
        histology_parts = []
        if self.histology_number and self.histology_date:
            hist_date = self.histology_date.strftime('%d.%m.%Y')
            histology_parts.append(f"ПГЗ № {self.histology_number} від {hist_date}")
        
        # Група 4: Опис гістології (з дефісом)
        if self.histology_description:
            histology_parts.append(self.histology_description)
        
        # З'єднуємо частини ПГЗ дефісом (якщо є опис) або просто додаємо ПГЗ
        if histology_parts:
            if len(histology_parts) == 2:
                # Є і номер, і опис - з'єднуємо дефісом
                parts.append(f"{histology_parts[0]} - {histology_parts[1]}")
            else:
                # Тільки номер або тільки опис
                parts.append(histology_parts[0])
        
        # З'єднуємо всі частини крапками (між групами)
        return ". ".join(parts) if parts else "Діагноз не вказано"

    def clean(self):
        """Валідація даних пацієнта"""
        import re
        
        # Валідація ambulatory_card_id
        if self.ambulatory_card_id:
            # Перевірка формату: дозволені тільки цифри, / та -
            # Формат може бути: 228435/2025, 2025-9246582, або інші комбінації
            pattern = r'^[0-9/\\-]+$'
            if not re.match(pattern, self.ambulatory_card_id):
                raise ValidationError({
                    'ambulatory_card_id': 'ID амбулаторної картки може містити тільки цифри, слеш (/) та дефіс (-)'
                })
            
            # Перевірка, що є хоча б одна цифра
            if not re.search(r'\d', self.ambulatory_card_id):
                raise ValidationError({
                    'ambulatory_card_id': 'ID амбулаторної картки повинен містити хоча б одну цифру'
                })
            
            # Перевірка унікальності (якщо не є поточним записом)
            existing = Patient.objects.filter(ambulatory_card_id=self.ambulatory_card_id).exclude(pk=self.pk)
            if existing.exists():
                raise ValidationError({
                    'ambulatory_card_id': 'Пацієнт з таким ID амбулаторної картки вже існує'
                })
        
        # Перевірка дат
        if self.treatment_start_date and self.discharge_date:
            if self.discharge_date < self.treatment_start_date:
                raise ValidationError({
                    'discharge_date': 'Дата виписки не може бути раніше дати початку лікування'
                })

    def validate_diagnosis_compliance(self):
        """
        Перевіряє, чи заповнені ключові поля відповідно до Наказу № 473.
        Шукає коди МКХ-10 та морфології у полях diagnosis та histology_description.
        Повертає True, якщо все заповнено коректно, інакше False.
        """
        import re
        diag = self.diagnosis or ''
        hist_desc = self.histology_description or ''
        
        # Код МКХ-10: C00-D48 (літера C або D, дві/три цифри)
        icd_pattern = r'\b[CDcd][0-9]{2}(\.[0-9])?\b'
        
        # Код морфології: XXXX/X (4 цифри, слеш, 1 цифра)
        morph_pattern = r'\b[0-9]{4}/[0-9]\b'
        
        has_icd = bool(re.search(icd_pattern, diag))
        has_morph = bool(re.search(morph_pattern, diag) or re.search(morph_pattern, hist_desc))
        
        return has_icd and has_morph
    
    def save(self, *args, **kwargs):
        """Перевизначений save для виклику clean та автоматичного оновлення статусу активності"""
        today = timezone.localdate()
        if self.discharge_date and self.discharge_date < today:
            self.is_active = False
        else:
            self.is_active = True
        self.full_clean()
        super().save(*args, **kwargs)


    def __str__(self):
        return self.full_name

    class Meta:
        db_table = 'patients'

class FractionHistory(models.Model):
    patient = models.ForeignKey('Patient', models.CASCADE, related_name='fractions')
    date = models.DateField()
    dose = models.FloatField()
    note = models.TextField(blank=True, null=True)
    original_date = models.DateField(blank=True, null=True, help_text="Оригінальна дата фракції")
    reason = models.CharField(max_length=255, blank=True, null=True, help_text="Причина зміни дати")

    STATUS_CHOICES = [
        ('scheduled', 'Запланована'),
        ('delivered', 'Отримана'),
        ('missed', 'Пропущена'),
    ]
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='scheduled',
        help_text="Статус фракції"
    )

    class Meta:
        db_table = 'fraction_history'

class MedicalIncapacity(models.Model):
    patient = models.ForeignKey('Patient', models.CASCADE, related_name='medical_incapacities')
    mvt_number = models.CharField(max_length=19, blank=True, null=True)
    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    no_employment_relation = models.BooleanField(blank=True, null=True)
    no_employment_relation_text = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        db_table = 'medical_incapacity'

@receiver(post_save, sender=Patient)
def auto_generate_fractions(sender, instance, created, **kwargs):
    """Автоматично генерує фракції при збереженні пацієнта з датою початку лікування"""
    # Перевіряємо, чи всі необхідні поля заповнені
    if (instance.treatment_start_date and 
        instance.total_fractions and 
        instance.dose_per_fraction and
        not instance.fractions.exists()):
        
        from .services import generate_fractions_for_patient
        generate_fractions_for_patient(instance)


class PatientAIDocumentation(models.Model):
    """Спільна ШІ-документація (первинний огляд, дані для виписки)"""
    patient = models.OneToOneField('Patient', on_delete=models.CASCADE, related_name='ai_documentation')
    clinical_state_notes = models.TextField(blank=True, null=True, help_text="Загальні нотатки про стан пацієнта для ШІ")
    initial_assessment = models.TextField(blank=True, null=True, help_text="Згенерований ШІ первинний огляд")
    discharge_summary = models.TextField(blank=True, null=True, help_text="Згенеровані ШІ дані для виписки")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'patient_ai_documentation'


class PatientAIDiary(models.Model):
    """Щоденникові записи пацієнта, згенеровані за допомогою ШІ"""
    patient = models.ForeignKey('Patient', on_delete=models.CASCADE, related_name='ai_diaries')
    date = models.DateField(help_text="Дата щоденникового запису")
    fraction_number = models.IntegerField(blank=True, null=True, help_text="Номер фракції")
    ecog_status = models.IntegerField(default=0, help_text="Статус ECOG (0-4)")
    ctcae_grade = models.IntegerField(default=0, help_text="Ступінь токсичності CTCAE (0-4)")
    clinical_state_notes = models.TextField(help_text="Скарги та опис об'єктивного стану на цю дату")
    generated_text = models.TextField(help_text="Згенерований ШІ текст щоденника")
    diary_type = models.CharField(
        max_length=20,
        default='weekly',
        choices=[
            ('admission', 'При поступленні'),
            ('weekly', 'Щотижневий'),
            ('discharge', 'Виписний')
        ],
        help_text="Тип щоденникового запису"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'patient_ai_diary'
        ordering = ['date', 'fraction_number']
