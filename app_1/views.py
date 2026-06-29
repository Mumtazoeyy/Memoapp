from urllib import request

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum, Count
from django.http import HttpResponse
from django import forms
import datetime, os
from django.conf import settings

from .models import ReadingItem, Category, Status

def login_view(request):
    if request.method == 'POST':
        user = authenticate(
            username=request.POST.get('username'),
            password=request.POST.get('password')
        )
        if user is not None:
            login(request, user)
            next_url = request.GET.get('next')
            if next_url:
                return redirect(next_url)
            return redirect('home')
        else:
            messages.error(request, "Username atau password salah.")

    return render(request, 'account/login.html')

def register_view(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, 'Akun berhasil dibuat! Selamat datang.')
            return redirect('home')
        else:
            messages.error(request, 'Mohon periksa kembali data Anda.')
    else:
        form = UserCreationForm()
    return render(request, 'account/register.html', {'form': form})

def logout_view(request):
    logout(request)
    messages.success(request, 'Anda telah berhasil logout.')
    return redirect('login')

def home_master(request):
    latest_reading = ReadingItem.objects.order_by('-created_at').first()
    total_count = ReadingItem.objects.count()

    context = {
        'latest_reading': latest_reading,
        'total_count': total_count,
    }
    return render(request, 'home_master.html', context)

def search_view(request):
    query = request.GET.get('q')
    search_type = request.GET.get('type')

    if search_type == 'history':
        items = ImportHistory.objects.filter(user=request.user)
        if query:
            items = items.filter(filename__icontains=query)
        # TAMBAHKAN search_type ke dalam context
        return render(request, 'search_results_partial.html', {
            'histories': items.order_by('-imported_at'),
            'search_type': 'history' 
        })
    else:
        category_id = request.GET.get('category')
        items = ReadingItem.objects.select_related('category').filter(user=request.user)
        if query:
            items = items.filter(title__icontains=query)
        if category_id:
            items = items.filter(category__id=category_id)
        # TAMBAHKAN search_type ke dalam context
        return render(request, 'search_results_partial.html', {
            'reading_items': items,
            'search_type': 'reading'
        })

def about_view(request):
    return render(request, 'about.html')

import re
from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .models import ReadingItem, Status, Category, ImportHistory

@login_required
def import_data(request):
    if request.method == 'POST' and request.FILES.get('import_file'):
        file = request.FILES['import_file']
        content = file.read().decode('utf-8')
        lines = content.splitlines()

        # Filter agar default status/kategori juga milik user tersebut jika perlu
        default_status = Status.objects.filter(id=1).first() or Status.objects.first()
        default_cat = Category.objects.filter(id=1).first() or Category.objects.first()

        count = 0
        for line in lines:
            if '»' not in line: continue

            try:
                raw_data = line.split('»')[1]
                parts = [p.strip() for p in raw_data.split('|') if p.strip()]
                
                title = parts[0]
                chapters = 0
                season = "-"
                status_obj = default_status
                category_obj = default_cat
                rating = "-"
                notes_list = []

                for p in parts[1:]:
                    p_lower = p.lower()
                    chapter_match = re.search(r'ch\.\s*(\d+)', p_lower)
                    if chapter_match:
                        chapters = int(chapter_match.group(1))
                    elif 's' in p_lower and any(char.isdigit() for char in p_lower):
                        season = p
                    elif Status.objects.filter(name__iexact=p).exists():
                        status_obj = Status.objects.filter(name__iexact=p).first()
                    elif Category.objects.filter(name__iexact=p).exists():
                        category_obj = Category.objects.filter(name__iexact=p).first()
                    elif any(arrow in p for arrow in ['↑', '↓', '→']):
                        rating = p
                    else:
                        notes_list.append(p)

                ReadingItem.objects.create(
                    user=request.user, 
                    title=title,
                    chapters=chapters,
                    season=season,
                    status=status_obj,
                    category=category_obj,
                    rating=rating,
                    notes=", ".join(notes_list)[:255] if notes_list else "-"
                )
                count += 1
            except Exception as e:
                print(f"Error pada baris '{line}': {e}")
                continue

        # --- TAMBAHAN: Simpan ke Histori Per User dengan filenya ---
        if count > 0:
            ImportHistory.objects.create(
                user=request.user,
                filename=file.name,
                total_items=count,
                file=file  # Menyimpan file ke model[cite: 3]
            )
        # --------------------------------------------

        messages.success(request, f'Berhasil mengimport {count} data!')
        return redirect('reading_list')

    return redirect('reading_list')

import sqlite3
import zipfile
import os
import shutil
from django.shortcuts import redirect
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .models import ReadingItem, Status, Category, ImportHistory

@login_required
def import_full(request):
    if request.method == 'POST' and request.FILES.get('import_file'):
        zip_file = request.FILES['import_file']
        temp_dir = os.path.join(settings.MEDIA_ROOT, 'temp_import')
        
        # 1. Ekstrak ZIP
        with zipfile.ZipFile(zip_file, 'r') as zf:
            zf.extractall(temp_dir)
        
        # 2. Proses Database SQLite
        db_path = os.path.join(temp_dir, 'data.sqlite')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reading_items")
        rows = cursor.fetchall()
        
        imported_count = 0 # Inisialisasi counter
        
        for row in rows:
            # Sesuaikan urutan dengan kolom saat export
            # (title, chapters, season, status, rating, category, notes, image_filename, is_favorite)
            title, chaps, seas, stat_name, rat, cat_name, note, img_name, fav = row
            
            # Cari/Buat Object Status & Category (agar relasi tidak error)
            status_obj, _ = Status.objects.get_or_create(name=stat_name)
            category_obj, _ = Category.objects.get_or_create(name=cat_name)
            
            # Buat item baru
            item = ReadingItem.objects.create(
                user=request.user,
                title=title,
                chapters=chaps,
                season=seas,
                status=status_obj,
                rating=rat,
                category=category_obj,
                notes=note,
                favorit=bool(fav)
            )
            
            imported_count += 1 # Menghitung item yang berhasil dibuat
            
            # 3. Pindahkan Gambar
            if img_name:
                source_img = os.path.join(temp_dir, 'images', img_name)
                if os.path.exists(source_img):
                    # Catatan: Sesuaikan folder tujuan dengan upload_to='reading_covers/'
                    dest_path = os.path.join(settings.MEDIA_ROOT, 'uploads', img_name)
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    shutil.copy(source_img, dest_path)
                    item.image = f'uploads/{img_name}'
                    item.save()
        
        conn.close()
        
        # Simpan ke ImportHistory dengan menyertakan file ZIP-nya
        ImportHistory.objects.create(
            user=request.user,
            filename=zip_file.name,
            total_items=imported_count,
            status="Success",
            file=zip_file # Menyimpan file fisik ke database
        )
        
        # Bersihkan folder temp
        shutil.rmtree(temp_dir)
        
        messages.success(request, "Import successful!")
        return redirect('reading_list')
        
    return redirect('reading_list')

import sqlite3
import io
import datetime
from django.db.models import Sum
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from .models import ReadingItem

@login_required # Menjaga agar hanya user yang login yang bisa export
def export_data(request):
    # FILTER: Ambil data hanya milik user yang sedang login
    items = ReadingItem.objects.filter(user=request.user).order_by('title')

    response_content = ""
    last_char = None

    # Hitung total khusus milik user
    total_titles = items.count()
    total_chapters = items.aggregate(Sum('chapters'))['chapters__sum'] or 0

    for item in items:
        # Header huruf
        current_char = item.title[0].upper() if item.title else "#"
        if current_char != last_char:
            response_content += f"\n{current_char} | ••••\n"
            last_char = current_char

        data_parts = []

        if item.title:
            data_parts.append(item.title)

        if item.chapters and item.chapters > 0:
            data_parts.append(f"Ch. {item.chapters}")

        if item.season and item.season != "-":
            data_parts.append(item.season)

        if item.status and item.status.id != 1:
            data_parts.append(item.status.name)

        if item.rating and item.rating != "-":
            data_parts.append(item.rating)

        if item.category and item.category.id != 1:
            data_parts.append(item.category.name)

        if item.notes and item.notes != "-":
            data_parts.append(item.notes)

        response_content += " » " + " | ".join(data_parts) + "\n"

    # Footer
    today = datetime.date.today().strftime("%d %B %Y")
    response_content += "\n" + "="*30 + "\n"
    response_content += f"Laporan Per: {today}\n"
    response_content += f"Total Judul Terdata: {total_titles}\n"
    response_content += f"Total Seluruh Chapter: {total_chapters}\n"
    response_content += "="*30 + "\n"

    response = HttpResponse(response_content, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="reading_list_export.txt"'
    return response

import sqlite3
import tempfile
import os
import zipfile
from django.http import FileResponse
from django.contrib.auth.decorators import login_required
from .models import ReadingItem

@login_required
def export_full(request):
    # 1. Ambil data
    items = ReadingItem.objects.filter(user=request.user).order_by('title')
    
    # 2. Buat folder sementara untuk proses backup
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, 'data.sqlite')
    
    # 3. Buat database SQLite
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE reading_items (
            title TEXT, 
            chapters INTEGER, 
            season TEXT, 
            status TEXT, 
            rating TEXT, 
            category TEXT, 
            notes TEXT, 
            image_filename TEXT, 
            favorit INTEGER
        )
    ''')
    
    for item in items:
        # Mengambil nama file foto saja
        img_name = os.path.basename(item.image.name) if item.image else ""
        # 1 untuk favorit (True), 0 untuk tidak (False)
        # Menggunakan field 'favorit' sesuai dengan models_2.py
        fav_val = 1 if item.favorit else 0 
        
        cursor.execute('''
            INSERT INTO reading_items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (item.title, item.chapters or 0, item.season or "-", 
              item.status.name if item.status else "-", item.rating or "-", 
              item.category.name if item.category else "-", item.notes or "-", 
              img_name, fav_val))
    
    conn.commit()
    conn.close()
    
    # 4. Bungkus ke dalam file ZIP
    zip_path = os.path.join(temp_dir, 'backup_full.zip')
    with zipfile.ZipFile(zip_path, 'w') as zf:
        # Masukkan file database
        zf.write(db_path, arcname='data.sqlite')
        
        # Masukkan file foto
        for item in items:
            if item.image and os.path.exists(item.image.path):
                # Memasukkan foto ke folder 'images' di dalam zip
                zf.write(item.image.path, arcname=os.path.join('images', os.path.basename(item.image.name)))

    # 5. Return response
    response = FileResponse(open(zip_path, 'rb'), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="backup_{request.user.username}.zip"'
    return response

@login_required
def reading_list(request):
    # TAMBAHKAN .filter(user=request.user) SEBELUM .all() ATAU .select_related()
    items = ReadingItem.objects.select_related('category', 'status').filter(user=request.user)

    # Lakukan sorting (tetap gunakan cara yang efisien)
    # Tips: Anda juga bisa melakukan sorting langsung di database dengan .order_by('title')
    reading_items = sorted(items, key=lambda x: x.title.upper())

    context = {
        'reading_items': reading_items,
        'categories': Category.objects.exclude(id=1), 
        'statuses': Status.objects.exclude(id=1),
    }
    return render(request, 'reading_list.html', context)

@login_required
def reading_add(request):
    """Menambah data baru dengan sistem notifikasi."""
    if request.method == 'POST':
        # Mengambil data dari form
        status_id = request.POST.get('status')
        category_id = request.POST.get('category')

        # Membuat objek baru
        ReadingItem.objects.create(
            user=request.user,  # <--- DITAMBAHKAN UNTUK MENGATASI ERROR
            title=request.POST.get('title'),
            chapters=request.POST.get('chapters', 0),
            season=request.POST.get('season', '-'),
            rating=request.POST.get('rating', '-'), 
            notes=request.POST.get('notes', '-'),
            image=request.FILES.get('image'), 

            # Mengambil objek ForeignKey (menggunakan .get() agar lebih aman)
            status=Status.objects.filter(id=status_id).first(),
            category=Category.objects.filter(id=category_id).first()
        )

        messages.success(request, 'Data berhasil ditambahkan!')
        return redirect('reading_list')

    context = {
        'statuses': Status.objects.all(),
        'categories': Category.objects.all()
    }
    return render(request, 'reading_add.html', context)

@login_required
def reading_edit(request, pk):
    """Edit data dan simpan perubahan dengan notifikasi."""
    item = get_object_or_404(ReadingItem, pk=pk)
    # Menangkap URL asal dari parameter GET atau POST
    next_url = request.POST.get('next') or request.GET.get('next')

    if request.method == 'POST':
        item.title = request.POST.get('title')
        item.chapters = request.POST.get('chapters')
        item.season = request.POST.get('season')
        item.rating = request.POST.get('rating')
        item.notes = request.POST.get('notes')
        item.synopsis = request.POST.get('synopsis')

        # Menggunakan _id langsung untuk efisiensi ForeignKey
        status_id = request.POST.get('status')
        item.status_id = status_id if status_id else None

        category_id = request.POST.get('category')
        item.category_id = category_id if category_id else None

        # Handle Image Upload
        if request.FILES.get('image'):
            item.image = request.FILES.get('image')

        item.save()
        messages.success(request, 'Perubahan berhasil disimpan!')

        # Redirect kembali ke halaman asal (next_url) jika ada
        return redirect(next_url) if next_url else redirect('reading_list')

    context = {
        'item': item,
        'statuses': Status.objects.all(),
        'categories': Category.objects.all(),
        'next': next_url
    }
    return render(request, 'reading_edit.html', context)

def reading_delete(request, pk):
    """Menghapus data dan mengirim notifikasi."""
    item = get_object_or_404(ReadingItem, pk=pk)
    item_title = item.title  # Simpan judul sebelum dihapus
    item.delete()
    messages.warning(request, f'Item "{item_title}" berhasil dihapus.')
    return redirect('reading_list')

@login_required
def delete_selected(request):
    if request.method == 'POST':
        selected_ids = request.POST.get('selected_ids', '')
        if selected_ids:
            # Memfilter agar hanya ID yang berupa angka yang diproses
            id_list = [i.strip() for i in selected_ids.split(',') if i.strip().isdigit()]

            if id_list:
                items = ReadingItem.objects.filter(id__in=id_list)
                count = items.count()

                if count > 0:
                    if count == 1:
                        # Mengambil objek pertama
                        item = items.first()
                        # Mengambil field 'title'. Jika field Anda namanya beda (misal: 'name'),
                        # silakan ganti string 'title' di bawah ini.
                        item_title = getattr(item, 'title', 'Item Tanpa Judul')
                        msg = f"Berhasil menghapus: {item_title}"
                    else:
                        msg = f"Berhasil menghapus {count} item"

                    # Eksekusi hapus
                    items.delete()
                    messages.success(request, msg)

    return redirect('reading_list')

@login_required
def reading_edit_bulk(request):
    ids_str = request.GET.get('ids', '')
    if not ids_str:
        return redirect('reading_list')

    ids = [int(i) for i in ids_str.split(',') if i.strip()]
    items = ReadingItem.objects.filter(id__in=ids)

    if request.method == 'POST':
        with transaction.atomic():
            for item in items:
                # Menggunakan request.POST.get untuk mengambil data
                item.title = request.POST.get(f'title_{item.id}', item.title)
                item.chapters = request.POST.get(f'chapters_{item.id}', 0)
                item.season = request.POST.get(f'season_{item.id}', '-')
                item.rating = request.POST.get(f'rating_{item.id}', '-')
                item.notes = request.POST.get(f'notes_{item.id}', '-')

                # Menangani ForeignKey
                new_status = request.POST.get(f'status_{item.id}')
                new_category = request.POST.get(f'category_{item.id}')

                # Jika user memilih opsi kosong, tetap gunakan relasi yang ada atau default
                if new_status:
                    item.status_id = new_status
                if new_category:
                    item.category_id = new_category

                item.save()

        messages.success(request, f"Berhasil mengupdate {items.count()} item!")
        return redirect('reading_list')

    context = {
        'items': items,
        # Menggunakan .distinct('name') jika database mendukung,
        # atau kita ambil hanya yang unik namanya secara manual
        'statuses': {s.name: s for s in Status.objects.all()}.values(),
        'categories': {c.name: c for c in Category.objects.all()}.values(),
    }
    return render(request, 'reading_edit_bulk.html', context)

def reading_item_detail(request, item_id):
    item = get_object_or_404(ReadingItem, id=item_id)
    return render(request, 'reading_item_detail.html', {'item': item})

# Tambahkan fungsi ini tepat di bawahnya
def toggle_favorite(request, pk):
    if request.method == "POST":
        item = get_object_or_404(ReadingItem, pk=pk)
        # Membalik status favorit (True jadi False, False jadi True)
        item.favorit = not item.favorit
        item.save()
    return redirect('reading_item_detail', item_id=pk)

from django.utils import timezone
from datetime import timedelta
    
@login_required
def dashboard(request):

    # Contoh query untuk item yang ditambahkan dalam 7 hari terakhir
    limit_date = timezone.now() - timedelta(days=7)
    # Kita ambil 5 saja untuk dashboard
    recently_added = ReadingItem.objects.filter(user=request.user, created_at__gte=limit_date).order_by('-created_at')[:5]

    # 1. Filter semua item berdasarkan user yang sedang login
    items = ReadingItem.objects.filter(user=request.user).order_by('title')
    
    total_titles = items.count()
    total_chapters = items.aggregate(Sum('chapters'))['chapters__sum'] or 0
    total_favorites = items.filter(favorit=True).count()
    
    # 2. Filter kategori dan status agar hanya menghitung milik user tersebut
    categories = Category.objects.filter(items__user=request.user).annotate(item_count=Count('items'))
    statuses = Status.objects.filter(items__user=request.user).annotate(item_count=Count('items'))

    def safe_calc(value):
        return int(round((value / total_titles * 377))) if total_titles > 0 else 0

    mvp = items.order_by('-chapters').first()
    colors = ["#000", "#333", "#666", "#999", "#bbb", "#555"]

    all_categories = []
    running_offset = 0
    for i, cat in enumerate(categories):
        all_categories.append({
            'name': cat.name,
            'item_count': cat.item_count,
            'color': colors[i % len(colors)],
            'offset': running_offset,
            'length': cat.item_count
        })
        running_offset += cat.item_count

    for cat in all_categories:
        cat['offset'] = safe_calc(cat['offset'])
        cat['length'] = safe_calc(cat['length'])

    all_statuses = []
    running_offset = 0
    for i, stat in enumerate(statuses):
        all_statuses.append({
            'name': stat.name,
            'item_count': stat.item_count,
            'color': colors[i % len(colors)],
            'offset': running_offset,
            'length': stat.item_count
        })
        running_offset += stat.item_count

    for stat in all_statuses:
        stat['offset'] = safe_calc(stat['offset'])
        stat['length'] = safe_calc(stat['length'])

    # 3. Stats & Lists
    completed_count = items.filter(status__name__iexact='Completed').count()
    percentage_completed = round((completed_count / total_titles * 100), 1) if total_titles > 0 else 0    
    
    # Kita buat query untuk modal (semua item yang baru ditambahkan)
    all_recently_added = ReadingItem.objects.filter(user=request.user).order_by('-created_at')
    
    recently_updated = items.order_by('-last_edited_at')[:5]
    all_recently_updated = ReadingItem.objects.filter(user=request.user).order_by('-last_edited_at')
    favorites = items.filter(favorit=True)[:5]
    favorites_list = items.filter(favorit=True)
    top_rated = items.order_by('-rating')[:5]

    context = {
        'total_titles': total_titles,
        'total_chapters': total_chapters,
        'total_favorites': total_favorites,
        'mvp': mvp,
        'all_categories': all_categories,
        'all_statuses': all_statuses,
        'ended_series': items.filter(status__name__iexact='Completed')[:5],
        'top_rated': top_rated,
        'favorites': favorites,
        'favorites_list': favorites_list,
        # Data tambahan
        'recently_added': recently_added, # Sudah terfilter 7 hari dari atas
        'all_recently_added': all_recently_added, # Untuk modal
        'recently_updated': recently_updated,
        'all_recently_updated': all_recently_updated,
        'percentage_completed': percentage_completed,
    }
    return render(request, 'dashboard.html', context)

import csv
from django.http import HttpResponse
from django.shortcuts import render
from .models import ImportHistory
from django.contrib.auth.decorators import login_required

@login_required
def history_view(request):
    histories = ImportHistory.objects.filter(user=request.user).order_by('-imported_at')
    return render(request, 'history.html', {
        'histories': histories,
        'search_type': 'history'  # Penting untuk sinkronisasi dengan form dan template partial
    })

from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import ImportHistory

@login_required
def download_history(request, history_id):
    # 1. Ambil histori yang diminta
    history = get_object_or_404(ImportHistory, id=history_id, user=request.user)
    
    # 2. Pastikan file benar-benar ada di database
    if not history.file:
        raise Http404("File tidak ditemukan.")
    
    # 3. Kembalikan file fisik sebagai download
    # FileResponse otomatis melakukan streaming file dengan efisien
    try:
        response = FileResponse(history.file.open('rb'), as_attachment=True)
        # Menggunakan nama file asli yang tersimpan di field filename
        response['Content-Disposition'] = f'attachment; filename="{history.filename}"'
        return response
    except FileNotFoundError:
        return HttpResponse("File fisik tidak ditemukan di server.", status=404)

import sqlite3
import os
import zipfile
import tempfile
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from .models import ImportHistory

@login_required
def history_detail_view(request, history_id):
    log = get_object_or_404(ImportHistory, id=history_id, user=request.user)
    
    # 1. Menyiapkan tampilan file
    file_display = f"""
    <div style="background: #e9ecef; padding: 15px; margin-bottom: 20px; border-radius: 5px;">
        <p><strong>File Terlampir:</strong> {log.filename}</p>
        <a href="{log.file.url}" download class="btn btn-dark" style="padding: 8px 16px; background: #333; color: #fff; text-decoration: none;">
            Download File
        </a>
    </div>
    """

    preview_html = "<p>Data tidak tersedia.</p>"
    
    if log.file and os.path.exists(log.file.path):
        try:
            # Menggunakan tempfile untuk mengekstrak sementara
            with tempfile.TemporaryDirectory() as temp_dir:
                with zipfile.ZipFile(log.file.path, 'r') as z:
                    if 'data.sqlite' in z.namelist():
                        z.extract('data.sqlite', path=temp_dir)
                        db_path = os.path.join(temp_dir, 'data.sqlite')
                        
                        # Koneksi ke database
                        conn = sqlite3.connect(db_path)
                        cursor = conn.cursor()
                        
                        # Ambil daftar tabel
                        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                        tables = cursor.fetchall()
                        
                        if tables:
                            # Ambil data dari tabel pertama yang ditemukan (LIMIT dihapus agar semua data muncul)
                            first_table = tables[0][0]
                            cursor.execute(f"SELECT * FROM {first_table}")
                            rows = cursor.fetchall()
                            columns = [description[0] for description in cursor.description]
                            
                            # Buat tabel HTML manual
                            table_rows = "".join([f"<tr>{''.join([f'<td>{cell}</td>' for cell in row])}</tr>" for row in rows])
                            table_headers = "".join([f"<th>{col}</th>" for col in columns])
                            
                            # Menambahkan container dengan scroll
                            preview_html = f"<h5>Preview Tabel: {first_table}</h5>"
                            preview_html += f"""
                            <div style="max-height: 600px; overflow-y: auto; overflow-x: auto; border: 1px solid #ddd;">
                                <table class='table'>
                                    <thead><tr>{table_headers}</tr></thead>
                                    <tbody>{table_rows}</tbody>
                                </table>
                            </div>
                            """
                        else:
                            preview_html = "<p>Database kosong (tidak ada tabel).</p>"
                        
                        conn.close()
                    else:
                        preview_html = "<p>File data.sqlite tidak ditemukan di dalam ZIP.</p>"
                        
        except Exception as e:
            preview_html = f"<p>Gagal membaca database: {e}</p>"
    
    # 3. HTML Output
    html = f"""
    <html>
    <head><style>
        .table {{ width: 100%; border-collapse: collapse; }}
        .table td, .table th {{ border: 1px solid #ddd; padding: 8px; }}
        .table th {{ background: #f2f2f2; }}
    </style></head>
    <body style="font-family: sans-serif; padding: 20px;">
        <button onclick="window.history.back()">Kembali</button>
        <hr>
        <h3>Detail Riwayat: {log.filename}</h3>
        {file_display}
        <h4>Data Preview (SQLite):</h4>
        <div style="overflow-x: auto; border: 1px solid #ccc; padding: 10px;">
            {preview_html}
        </div>
    </body>
    </html>
    """
    return HttpResponse(html)

import os
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from .models import ImportHistory

@login_required
def delete_history(request):
    if request.method == 'POST':
        selected_ids = request.POST.get('selected_ids', '')
        if selected_ids:
            # Mengubah string ID menjadi list
            id_list = [i.strip() for i in selected_ids.split(',') if i.strip().isdigit()]
            
            if id_list:
                # Mengambil data berdasarkan ID dan User agar aman
                histories = ImportHistory.objects.filter(id__in=id_list, user=request.user)
                
                for history in histories:
                    # Hapus file fisik jika ada
                    if history.file and os.path.exists(history.file.path):
                        os.remove(history.file.path)
                
                # Hapus record dari database
                histories.delete()
                
    return redirect('history_list')

from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from .forms import MinimalPasswordChangeForm # Impor form baru kita
from django.shortcuts import render, redirect
from django.contrib import messages

def password_change(request):
    if request.method == 'POST':
        # Gunakan form kustom kita
        form = MinimalPasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user) # Biar user tidak logout otomatis
            messages.success(request, 'Your password was successfully updated!')
            return redirect('profile')
    else:
        form = MinimalPasswordChangeForm(request.user)
    
    return render(request, 'password_change.html', {'form': form})

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Profile

@login_required
def profile(request):
    # Mengambil profil atau membuatnya jika belum ada
    user_profile, created = Profile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        # 1. Menangani Display Name
        # Mengambil input, jika kosong/spasi maka fallback ke username
        display_name_input = request.POST.get('display_name', '').strip()
        user_profile.display_name = display_name_input if display_name_input else request.user.username

        # 2. Menangani Bio
        user_profile.bio = request.POST.get('bio', user_profile.bio)

        # 3. Menangani Update Foto Profil
        if request.FILES.get('avatar'):
            user_profile.avatar = request.FILES.get('avatar')

        user_profile.save()
        messages.success(request, "Profil berhasil diperbarui!")
        return redirect('profile')

    return render(request, 'profile.html')