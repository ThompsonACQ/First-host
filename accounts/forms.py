from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

User = get_user_model()

RECOVERY_QUESTIONS = (
    ('first_school', 'What was the name of your first school?'),
    ('childhood_friend', 'What was the first name of your childhood best friend?'),
    ('first_job', 'What was your first job?'),
    ('favorite_teacher', 'What was the name of a favorite teacher?'),
    ('childhood_city', 'In what city or town did you grow up?'),
    ('memorable_place', 'What is the name of a place that is memorable to you?'),
)


def normalize_recovery_answer(answer):
    return ' '.join(answer.split()).casefold()


class AdminSecuritySetupForm(forms.Form):
    email = forms.EmailField(
        max_length=150,
        widget=forms.EmailInput(attrs={'class': 'form-input', 'autocomplete': 'email'}),
    )
    current_password = forms.CharField(
        label='Current password',
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'autocomplete': 'current-password'}),
    )
    new_password = forms.CharField(
        label='New password',
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'autocomplete': 'new-password'}),
    )
    confirm_password = forms.CharField(
        label='Confirm new password',
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'autocomplete': 'new-password'}),
    )
    question_1 = forms.ChoiceField(choices=RECOVERY_QUESTIONS, label='Recovery question 1')
    answer_1 = forms.CharField(
        label='Answer 1',
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'form-input', 'autocomplete': 'off'}),
    )
    question_2 = forms.ChoiceField(choices=RECOVERY_QUESTIONS, label='Recovery question 2')
    answer_2 = forms.CharField(
        label='Answer 2',
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'form-input', 'autocomplete': 'off'}),
    )
    question_3 = forms.ChoiceField(choices=RECOVERY_QUESTIONS, label='Recovery question 3')
    answer_3 = forms.CharField(
        label='Answer 3',
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'form-input', 'autocomplete': 'off'}),
    )

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields['email'].initial = user.email
        for field in ('question_1', 'question_2', 'question_3'):
            self.fields[field].widget.attrs['class'] = 'form-input'

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        users = User.objects.exclude(pk=self.user.pk)
        if users.filter(email__iexact=email).exists() or users.filter(username__iexact=email).exists():
            raise ValidationError('This email is already in use.')
        return email

    def clean(self):
        cleaned_data = super().clean()
        current_password = cleaned_data.get('current_password')
        new_password = cleaned_data.get('new_password')
        confirm_password = cleaned_data.get('confirm_password')

        if current_password and not self.user.check_password(current_password):
            self.add_error('current_password', 'Enter your current password to confirm this change.')
        if new_password and confirm_password and new_password != confirm_password:
            self.add_error('confirm_password', 'The new passwords do not match.')
        if new_password:
            try:
                validate_password(new_password, self.user)
            except ValidationError as error:
                self.add_error('new_password', error)

        questions = [cleaned_data.get(f'question_{index}') for index in range(1, 4)]
        if all(questions) and len(set(questions)) != 3:
            raise ValidationError('Choose three different recovery questions.')
        for index in range(1, 4):
            answer = cleaned_data.get(f'answer_{index}')
            if answer is not None:
                answer = answer.strip()
                if len(answer) < 2:
                    self.add_error(f'answer_{index}', 'Enter an answer with at least 2 characters.')
                else:
                    cleaned_data[f'answer_{index}'] = answer
        return cleaned_data

    def recovery_answers(self):
        return {
            self.cleaned_data[f'question_{index}']: make_password(
                normalize_recovery_answer(self.cleaned_data[f'answer_{index}'])
            )
            for index in range(1, 4)
        }


class AdminRecoveryForm(forms.Form):
    email = forms.EmailField(
        max_length=150,
        widget=forms.EmailInput(attrs={'class': 'form-input', 'autocomplete': 'email'}),
        help_text='Choose the email address you will use to sign in.',
    )
    question_1 = forms.ChoiceField(choices=RECOVERY_QUESTIONS, label='Recovery question 1')
    answer_1 = forms.CharField(
        label='Answer 1',
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'form-input', 'autocomplete': 'off'}),
    )
    question_2 = forms.ChoiceField(choices=RECOVERY_QUESTIONS, label='Recovery question 2')
    answer_2 = forms.CharField(
        label='Answer 2',
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'form-input', 'autocomplete': 'off'}),
    )
    question_3 = forms.ChoiceField(choices=RECOVERY_QUESTIONS, label='Recovery question 3')
    answer_3 = forms.CharField(
        label='Answer 3',
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'form-input', 'autocomplete': 'off'}),
    )
    new_password = forms.CharField(
        label='New password',
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'autocomplete': 'new-password'}),
    )
    confirm_password = forms.CharField(
        label='Confirm new password',
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'autocomplete': 'new-password'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ('question_1', 'question_2', 'question_3'):
            self.fields[field].widget.attrs['class'] = 'form-input'

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        if User.objects.filter(email__iexact=email).exists() or User.objects.filter(username__iexact=email).exists():
            raise ValidationError('This email is already in use. Choose another email.')
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('new_password')
        confirmation = cleaned_data.get('confirm_password')
        if password and confirmation and password != confirmation:
            self.add_error('confirm_password', 'The new passwords do not match.')
        if password:
            try:
                validate_password(password)
            except ValidationError as error:
                self.add_error('new_password', error)

        questions = [cleaned_data.get(f'question_{index}') for index in range(1, 4)]
        if all(questions) and len(set(questions)) != 3:
            raise ValidationError('Choose the three different questions you registered.')
        for index in range(1, 4):
            answer = cleaned_data.get(f'answer_{index}')
            if answer is not None:
                answer = answer.strip()
                if not answer:
                    self.add_error(f'answer_{index}', 'Enter your answer.')
                else:
                    cleaned_data[f'answer_{index}'] = answer
        return cleaned_data


class BaseRegistrationForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, validators=[validate_password])
    confirm_password = forms.CharField(widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if not email:
            raise ValidationError("Email is required.")
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("A user with that email already exists.")
        return email
        
    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        if password and confirm_password and password != confirm_password:
            self.add_error('confirm_password', "Passwords do not match.")
            
        return cleaned_data
        
    def save(self, commit=True):
        user = super().save(commit=False)
        # Using email as username as requested ("Prefer email as the login identifier")
        user.username = self.cleaned_data.get('email')
        user.set_password(self.cleaned_data.get('password'))
        if commit:
            user.save()
        return user


class StudentRegistrationForm(BaseRegistrationForm):
    student_id = forms.CharField(required=False, label="Student ID (Optional)")
    phone = forms.CharField(required=False, label="Phone Number (Optional)")

    class Meta(BaseRegistrationForm.Meta):
        fields = ['first_name', 'last_name', 'email', 'student_id', 'phone']

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.ROLE_STUDENT
        if commit:
            user.save()
        return user


class DriverRegistrationForm(BaseRegistrationForm):
    phone = forms.CharField(required=True, label="Phone Number")

    class Meta(BaseRegistrationForm.Meta):
        fields = ['first_name', 'last_name', 'email', 'phone']

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.ROLE_DRIVER
        if commit:
            user.save()
            from .models import DriverProfile
            DriverProfile.objects.create(user=user, status=DriverProfile.STATUS_PENDING)
        return user
