from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import HttpResponse
from django.db.models import Sum
from .models import ReadingItem, Category, Status, Memo
from django import forms
from django.contrib.auth.decorators import login_required

# =====================================================================
# FUNCTION-BASED VIEWS
# =====================================================================
from django.contrib.auth import authenticate, login
from django.shortcuts import render, redirect
from django.contrib import messages

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages

def login_view(request):
    if request.method == 'POST':
        user = authenticate(
            username=request.POST.get('username'),
            password=request.POST.get('password')
        )
        if user is not None:
            login(request, user)
            next_url = request.GET.get('next', 'reading_list')
            return redirect(next_url)
        else:
            messages.error(request, "Username atau password salah.")
            
    return render(request, 'account/login.html')

def register_view(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Akun berhasil dibuat! Silakan login.')
            return redirect('login')
    else:
        form = UserCreationForm()
    return render(request, 'account/register.html', {'form': form})

def logout_view(request):
    logout(request)
    return redirect('login')

def home_master(request):
    # Mengambil data untuk Memo dan ReadingItem
    latest_memo = Memo.objects.order_by('-tanggal_dibuat').first()
    latest_reading = ReadingItem.objects.order_by('-created_at').first()
    
    # Menambahkan hitungan total koleksi
    total_count = ReadingItem.objects.count()
    
    context = {
        'latest_memo': latest_memo,
        'latest_reading': latest_reading,
        'total_count': total_count, # Data ini yang akan muncul di {{ total_count }}
    }
    # Mengirim data ke home_master.html
    return render(request, 'home_master.html', context)

def search_view(request):
    query = request.GET.get('q')
    category_id = request.GET.get('category')
    
    # .select_related('category') mempercepat akses data kategori di template
    # agar Django tidak melakukan query berulang-ulang
    reading_items = ReadingItem.objects.select_related('category').all()
    
    # Filter pencarian berdasarkan judul
    if query:
        reading_items = reading_items.filter(title__icontains=query)
        
    # Filter berdasarkan kategori (menggunakan ID)
    if category_id:
        reading_items = reading_items.filter(category__id=category_id)
        
    return render(request, 'search_results_partial.html', {
        'reading_items': reading_items
    })

def import_data(request):
    if request.method == 'POST' and request.FILES.get('import_file'):
        file = request.FILES['import_file']
        content = file.read().decode('utf-8')
        lines = content.splitlines()
        
        # Ambil status dan category ID 1 sebagai fallback (default)
        default_status = Status.objects.filter(id=1).first()
        default_cat = Category.objects.filter(id=1).first()
        
        count = 0
        for line in lines:
            if '»' not in line: continue
            
            try:
                parts = [p.strip() for p in line.split('»')[1].split('|')]
                title = parts[0]
                
                chapters = 0
                season = "-"
                status_obj = default_status # Pakai default ID 1
                category_obj = default_cat # Pakai default ID 1
                rating = "-"
                notes_list = []
                
                for p in parts[1:]:
                    p_lower = p.lower()
                    
                    if p.isdigit():
                        chapters = int(p)
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
                
                notes = ", ".join(notes_list)
                
                # Simpan dengan status dan category yang sudah terjamin (tidak mungkin None)
                ReadingItem.objects.create(
                    title=title,
                    chapters=chapters,
                    season=season,
                    status=status_obj,
                    category=category_obj,
                    rating=rating,
                    notes=notes
                )
                count += 1
            except Exception as e:
                print(f"Error pada baris: {e}")
                continue
        
        messages.success(request, f'Berhasil mengimport {count} data!')
        return redirect('reading_list')
    
    return redirect('reading_list')

from django.db.models import Sum
from django.http import HttpResponse
import datetime

def export_data(request):
    # Urutkan berdasarkan title
    items = ReadingItem.objects.all().order_by('title')
    
    response_content = ""
    last_char = None
    
    # Hitung total
    total_titles = items.count()
    total_chapters = items.aggregate(Sum('chapters'))['chapters__sum'] or 0
    
    for item in items:
        # Header huruf
        current_char = item.title[0].upper() if item.title else "#"
        if current_char != last_char:
            response_content += f"\n{current_char} | ••••\n"
            last_char = current_char
            
        data_parts = []
        
        # Kumpulkan data hanya jika ada isinya
        if item.title: 
            data_parts.append(item.title)
        
        if item.chapters and item.chapters > 0: 
            data_parts.append(f"Ch. {item.chapters}")
            
        if item.season and item.season != "-": 
            data_parts.append(item.season)
            
        # Cek status: tambahkan hanya jika bukan "No Status"
        if item.status and item.status.name != "No Status": 
            data_parts.append(item.status.name)
            
        # Cek rating
        if item.rating and item.rating != "-": 
            data_parts.append(item.rating)
            
        # Cek kategori: tambahkan hanya jika bukan "No Category"
        if item.category and item.category.name != "No Category": 
            data_parts.append(item.category.name)
            
        if item.notes and item.notes != "-": 
            data_parts.append(item.notes)
        
        # Gabungkan hanya bagian yang tidak kosong dengan pemisah " | "
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
    # Gunakan select_related untuk kategori DAN status
    items = ReadingItem.objects.select_related('category', 'status').all()
    
    # Lakukan sorting (tetap gunakan cara yang efisien)
    reading_items = sorted(items, key=lambda x: x.title.upper())
    
    context = {
        'reading_items': reading_items,
        'categories': Category.objects.exclude(id=1), # Filter ID 1 agar tidak muncul di search
        'statuses': Status.objects.exclude(id=1),
    }
    return render(request, 'reading_list.html', context)

@login_required
def reading_add(request):
    """Menambah data baru dengan sistem notifikasi."""
    if request.method == 'POST':
        status_id = request.POST.get('status')
        category_id = request.POST.get('category')
        
        ReadingItem.objects.create(
            title=request.POST.get('title'),
            chapters=request.POST.get('chapters'),
            season=request.POST.get('season'),
            hype=request.POST.get('hype'),
            notes=request.POST.get('notes'),
            status=get_object_or_404(Status, id=status_id) if status_id else None,
            category=get_object_or_404(Category, id=category_id) if category_id else None
        )
        messages.success(request, 'Data berhasil ditambahkan!')
        return redirect('reading_list')
        
    context = {
        'statuses': Status.objects.all(),
        'categories': Category.objects.all()
    }
    return render(request, 'reading_add.html', context)

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from .models import ReadingItem, Category, Status

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

from django.contrib import messages
from django.shortcuts import redirect
from .models import ReadingItem

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

from django.shortcuts import render
from django.db.models import Sum, Count
from .models import ReadingItem, Category, Status

@login_required
def dashboard(request):
    # 1. Metrik Utama
    items = ReadingItem.objects.all()
    total_titles = items.count()
    total_chapters = items.aggregate(Sum('chapters'))['chapters__sum'] or 0
    total_categories = Category.objects.count()
    
    # Fungsi pembantu untuk mencegah ZeroDivisionError
    def safe_calc(value):
        return (value / total_titles * 377) if total_titles > 0 else 0
    
    # 2. MVP
    mvp = items.order_by('-chapters').first()
    
    # Warna untuk diagram
    colors = ["#000", "#333", "#666", "#999", "#bbb", "#555"]

    # 3. Distribusi Kategori
    all_categories = []
    running_offset = 0
    raw_cats = list(Category.objects.annotate(item_count=Count('items')))
    no_cat = items.filter(category__isnull=True).count()
    
    for i, cat in enumerate(raw_cats):
        all_categories.append({
            'name': cat.name,
            'item_count': cat.item_count,
            'color': colors[i % len(colors)],
            'offset': safe_calc(running_offset),
            'length': safe_calc(cat.item_count)
        })
        running_offset += cat.item_count
        
    if no_cat > 0:
        all_categories.append({
            'name': 'Uncategorized',
            'item_count': no_cat,
            'color': '#d3d3d3',
            'offset': safe_calc(running_offset),
            'length': safe_calc(no_cat)
        })

    # 4. Distribusi Status
    all_statuses = []
    running_offset = 0
    raw_stats = list(Status.objects.annotate(item_count=Count('items')))
    # PERBAIKAN: Menggunakan field 'status'
    no_status = items.filter(status__isnull=True).count()
    
    for i, stat in enumerate(raw_stats):
        all_statuses.append({
            'name': stat.name,
            'item_count': stat.item_count,
            'color': colors[i % len(colors)],
            'offset': safe_calc(running_offset),
            'length': safe_calc(stat.item_count)
        })
        running_offset += stat.item_count
        
    if no_status > 0:
        all_statuses.append({
            'name': 'No Status',
            'item_count': no_status,
            'color': '#d3d3d3',
            'offset': safe_calc(running_offset),
            'length': safe_calc(no_status)
        })

    # 5. Lists
    # PERBAIKAN: Menggunakan 'status__name' karena status adalah ForeignKey
    ended_series = items.filter(status__name__iexact='Ended')[:5]
    top_rated = items.order_by('-chapters')[:5]

    context = {
        'total_titles': total_titles,
        'total_chapters': total_chapters,
        'total_categories': total_categories,
        'mvp': mvp,
        'all_categories': all_categories,
        'all_statuses': all_statuses,
        'ended_series': ended_series,
        'top_rated': top_rated,
    }
    return render(request, 'dashboard.html', context)

from django.shortcuts import render, redirect, get_object_or_404
from .models import ReadingItem, Category, Status
from django.contrib import messages

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction

from django.shortcuts import render, redirect
from django.contrib import messages
from django.db import transaction
from .models import ReadingItem, Status, Category

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