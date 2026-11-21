from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.http import HttpResponse
from django.test import TestCase
from unittest.mock import patch

from .forms import normalize_recovery_answer


User = get_user_model()


class AdminAccountRecoveryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.rendered_contexts = []
        render_patch = patch('accounts.views.render', side_effect=self.capture_render)
        render_patch.start()
        self.addCleanup(render_patch.stop)
        self.admin = User.objects.create_superuser(
            username='initial-admin',
            email='initial@example.com',
            password='Initial-Admin-Password-928!',
        )

    def capture_render(self, request, template_name, context=None, status=200, **kwargs):
        self.rendered_contexts.append((template_name, context or {}))
        return HttpResponse(status=status)

    def recovery_answers(self):
        return {
            'first_school': make_password(normalize_recovery_answer('Harbor School')),
            'first_job': make_password(normalize_recovery_answer('Library assistant')),
            'childhood_city': make_password(normalize_recovery_answer('Northfield')),
        }

    def recovery_data(self, **overrides):
        data = {
            'email': 'new-admin@example.com',
            'question_1': 'first_school',
            'answer_1': ' harbor   school ',
            'question_2': 'first_job',
            'answer_2': 'LIBRARY ASSISTANT',
            'question_3': 'childhood_city',
            'answer_3': 'Northfield',
            'new_password': 'Recovered-Admin-Password-374!',
            'confirm_password': 'Recovered-Admin-Password-374!',
        }
        data.update(overrides)
        return data

    def test_authenticated_admin_can_change_email_password_and_recovery_answers(self):
        self.client.force_login(self.admin)
        response = self.client.post('/accounts/admin-security/', {
            'email': 'secure-admin@example.com',
            'current_password': 'Initial-Admin-Password-928!',
            'new_password': 'Updated-Admin-Password-481!',
            'confirm_password': 'Updated-Admin-Password-481!',
            'question_1': 'first_school',
            'answer_1': 'Harbor School',
            'question_2': 'first_job',
            'answer_2': 'Library assistant',
            'question_3': 'childhood_city',
            'answer_3': 'Northfield',
        })

        if response.status_code != 302:
            self.fail(f'Account security form errors: {self.rendered_contexts[-1][1]["form"].errors}')
        self.assertRedirects(
            response, '/accounts/admin-security/', fetch_redirect_response=False,
        )
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.email, 'secure-admin@example.com')
        self.assertEqual(self.admin.username, 'secure-admin@example.com')
        self.assertTrue(self.admin.check_password('Updated-Admin-Password-481!'))
        self.assertTrue(check_password(
            normalize_recovery_answer('harbor school'),
            self.admin.recovery_answers['first_school'],
        ))
        self.assertNotIn('Harbor School', str(self.admin.recovery_answers))

    def test_recovery_resets_admin_email_and_password_with_all_answers(self):
        self.admin.recovery_answers = self.recovery_answers()
        self.admin.save(update_fields=['recovery_answers'])

        response = self.client.post('/accounts/admin-recovery/', self.recovery_data())

        self.assertRedirects(response, '/accounts/login/', fetch_redirect_response=False)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.email, 'new-admin@example.com')
        self.assertEqual(self.admin.username, 'new-admin@example.com')
        self.assertTrue(self.admin.check_password('Recovered-Admin-Password-374!'))

        login_response = self.client.post('/accounts/login/', {
            'username': 'new-admin@example.com',
            'password': 'Recovered-Admin-Password-374!',
        })
        self.assertRedirects(
            login_response, '/admin-dashboard/dashboard/',
            fetch_redirect_response=False,
        )

    def test_incorrect_recovery_answers_do_not_change_admin_credentials(self):
        self.admin.recovery_answers = self.recovery_answers()
        self.admin.save(update_fields=['recovery_answers'])

        response = self.client.post(
            '/accounts/admin-recovery/',
            self.recovery_data(answer_1='incorrect answer'),
        )

        self.assertEqual(response.status_code, 200)
        form = self.rendered_contexts[-1][1]['form']
        self.assertIn(
            'The recovery answers could not be verified. No account was changed.',
            form.non_field_errors(),
        )
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.email, 'initial@example.com')
        self.assertTrue(self.admin.check_password('Initial-Admin-Password-928!'))

    def test_non_admin_cannot_configure_admin_recovery(self):
        student = User.objects.create_user(
            username='student',
            email='student@example.com',
            password='Student-Password-239!',
            role=User.ROLE_STUDENT,
        )
        self.client.force_login(student)

        response = self.client.get('/accounts/admin-security/')

        self.assertRedirects(response, '/', fetch_redirect_response=False)

    def test_recovery_attempts_are_rate_limited(self):
        with patch('accounts.views._match_admin_recovery_answers', return_value=None):
            for attempt in range(5):
                response = self.client.post(
                    '/accounts/admin-recovery/',
                    self.recovery_data(),
                )
                self.assertEqual(response.status_code, 200, f'Unexpected status on attempt {attempt + 1}')

            response = self.client.post(
                '/accounts/admin-recovery/',
                self.recovery_data(),
            )

        self.assertEqual(response.status_code, 429)

    def test_admin_can_change_password_with_current_password(self):
        self.client.force_login(self.admin)
        response = self.client.post('/accounts/admin-change-password/', {
            'old_password': 'Initial-Admin-Password-928!',
            'new_password1': 'Changed-Admin-Password-615!',
            'new_password2': 'Changed-Admin-Password-615!',
        })

        self.assertRedirects(
            response, '/accounts/admin-change-password/',
            fetch_redirect_response=False,
        )
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password('Changed-Admin-Password-615!'))
        self.assertFalse(self.admin.check_password('Initial-Admin-Password-928!'))

    def test_admin_cannot_change_password_with_wrong_current_password(self):
        self.client.force_login(self.admin)
        response = self.client.post('/accounts/admin-change-password/', {
            'old_password': 'wrong-current-password',
            'new_password1': 'Changed-Admin-Password-615!',
            'new_password2': 'Changed-Admin-Password-615!',
        })

        self.assertEqual(response.status_code, 200)
        form = self.rendered_contexts[-1][1]['form']
        self.assertIn(
            'Your old password was entered incorrectly. Please enter it again.',
            form.errors['old_password'],
        )
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password('Initial-Admin-Password-928!'))
