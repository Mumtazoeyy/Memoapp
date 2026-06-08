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

import re # Tambahkan import re di atas file

from .models import ReadingItem, Status, Category, ImportHistory # Pastikan ImportHistory diimpor
import re

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

        # --- TAMBAHAN: Simpan ke Histori Per User ---
        if count > 0:
            ImportHistory.objects.create(
                user=request.user,
                filename=file.name,
                total_items=count
            )
        # --------------------------------------------

        messages.success(request, f'Berhasil mengimport {count} data!')
        return redirect('reading_list')

    return redirect('reading_list')

from django.db.models import Sum
import datetime # Pastikan import ini ada

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
    
@login_required
def dashboard(request):
    # 1. Filter semua item berdasarkan user yang sedang login
    items = ReadingItem.objects.filter(user=request.user)
    
    total_titles = items.count()
    total_chapters = items.aggregate(Sum('chapters'))['chapters__sum'] or 0
    total_favorites = items.filter(favorit=True).count()
    
    # 2. Filter kategori dan status agar hanya menghitung milik user tersebut
    # Kita gunakan filter(items__user=request.user) untuk memastikan data yang dihitung adalah milik user
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

    # 3. Filter list series dan rating tetap dibatasi oleh 'items' (yang sudah di-filter user)
    ended_series = items.filter(status__name__iexact='Completed')[:5]
    top_rated = items.order_by('-rating')[:5]
    favorites = items.filter(favorit=True)[:5]

    context = {
        'total_titles': total_titles,
        'total_chapters': total_chapters,
        'total_favorites': total_favorites,
        'mvp': mvp,
        'all_categories': all_categories,
        'all_statuses': all_statuses,
        'ended_series': ended_series,
        'top_rated': top_rated,
        'favorites': favorites,
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

from django.db.models import Sum
import datetime
from django.shortcuts import get_object_or_404

@login_required
def download_history(request, history_id):
    # 1. Ambil histori yang diminta
    history = get_object_or_404(ImportHistory, id=history_id, user=request.user)
    
    # 2. Karena tidak ada relasi langsung di model, 
    # kita ambil semua ReadingItem milik user tersebut.
    # CATATAN: Jika Anda ingin memfilter berdasarkan waktu import, 
    # Anda perlu menyesuaikan logic ini (misal: filter berdasarkan created_at).
    items = ReadingItem.objects.filter(user=request.user).order_by('title')

    # Header Dokumen
    response_content = f"HISTORY EXPORT: {history.filename}\n"
    response_content += f"Imported: {history.imported_at.strftime('%d %B %Y, %H:%M')}\n"
    response_content += "="*40 + "\n"

    last_char = None
    total_titles = items.count()
    total_chapters = items.aggregate(Sum('chapters'))['chapters__sum'] or 0

    for item in items:
        # Header huruf
        current_char = item.title[0].upper() if item.title else "#"
        if current_char != last_char:
            response_content += f"\n{current_char} | ••••\n"
            last_char = current_char

        data_parts = []
        if item.title: data_parts.append(item.title)
        if item.chapters and item.chapters > 0: data_parts.append(f"Ch. {item.chapters}")
        if item.season and item.season != "-": data_parts.append(item.season)
        # Menggunakan item.status.name karena di model sudah ada relasi ke Status
        if item.status: data_parts.append(item.status.name)
        if item.notes and item.notes != "-": data_parts.append(item.notes)

        response_content += " » " + " | ".join(data_parts) + "\n"

    # Footer
    response_content += "\n" + "="*30 + "\n"
    response_content += f"Total Judul Terdata: {total_titles}\n"
    response_content += f"Total Seluruh Chapter: {total_chapters}\n"
    response_content += "="*30 + "\n"

    response = HttpResponse(response_content, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="history_{history.filename}.txt"'
    return response

@login_required
def history_detail_view(request, history_id):
    log = get_object_or_404(ImportHistory, id=history_id, user=request.user)
    
    # Ambil isi dari database atau file sesuai kebutuhan
    # Contoh: kita ambil data dari field di ReadingItem
    items = ReadingItem.objects.filter(user=request.user) # Sesuaikan query Anda
    
    # Membuat string untuk preview
    content = f"File: {log.filename}\nImported: {log.imported_at}\n\n"
    for item in items:
        content += f"{item.title} | {item.chapters}\n"
    
    # Mengembalikan HTML minimalis tanpa template
    html = f"""
    <html>
    <head><title>Preview {log.filename}</title></head>
    <body style="margin: 0; padding: 20px; font-family: monospace;">
        <button onclick="window.history.back()">Back</button>
        <hr>
        <pre style="background: #f4f4f4; padding: 15px; border: 1px solid #ccc;">{content}</pre>
    </body>
    </html>
    """
    return HttpResponse(html)