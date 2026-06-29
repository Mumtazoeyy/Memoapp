from django import forms
from django.contrib.auth.forms import PasswordChangeForm

class MinimalPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Mengubah label agar lebih minimalis
        self.fields['old_password'].label = "Current Password"
        self.fields['new_password1'].label = "New Password"
        self.fields['new_password1'].help_text = None # Menghapus teks bantuan default yang panjang
        self.fields['new_password1'].widget.attrs.update({'placeholder': 'Enter new password'})
        self.fields['new_password2'].label = "Confirm New Password"