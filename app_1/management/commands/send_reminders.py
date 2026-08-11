from django.core.management.base import BaseCommand
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from app_1.models import Profile
from django.urls import reverse
import datetime

class Command(BaseCommand):
    help = 'Mengirim email pengingat backup rutin'

    def handle(self, *args, **options):
        self.stdout.write("Memulai pengecekan jadwal pengingat backup...")
        
        # Ambil semua user yang mengaktifkan reminder
        profiles = Profile.objects.exclude(reminder_email__isnull=True).exclude(reminder_email='')
        
        count = 0
        for profile in profiles:
            # Hitung apakah sudah waktunya mengirim
            if profile.last_reminder_sent:
                # Cek jika selisih waktu sudah melebihi frekuensi (7, 30, atau 90 hari)
                if (timezone.now() - profile.last_reminder_sent).days >= profile.reminder_frequency:
                    self.kirim_email_rutin(profile)
                    count += 1
            else:
                # Jika profil aktif tapi last_reminder_sent masih kosong, set ke waktu sekarang atau lewati
                pass

        self.stdout.write(f"Pengecekan selesai. Total {count} email pengingat terkirim.")

    def kirim_email_rutin(self, profile):
        # Link ke halaman reading list
        domain = "https://MintChocolatte.pythonanywhere.com" 
        link = f"{domain}{reverse('reading_list')}"
        
        subject = "Reminder: Time to Backup Your Reading List!"
        message = (
            f"Hello {profile.user.username},\n\n"
            f"It's been {profile.reminder_frequency} days since your last backup reminder.\n"
            f"Please visit your reading list to download your data:\n{link}"
        )
        
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [profile.reminder_email])
        
        # Update tanggal terakhir dikirim
        profile.last_reminder_sent = timezone.now()
        profile.save()
        self.stdout.write(f"Email sent successfully to {profile.reminder_email}")