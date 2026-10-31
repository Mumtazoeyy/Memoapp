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
from .forms import RegisterForm

from .models import ReadingItem, Type, Status

def login_view(request):
    if request.method == 'POST':
        user = authenticate(
            username=request.POST.get('username'),
            password=request.POST.get('password')
        )

        if user is not None:
            login(request, user)

            # Remember Me
            if request.POST.get('remember_me'):
                request.session.set_expiry(1209600)  # 14 days
            else:
                request.session.set_expiry(0)  # Browser session

            next_url = request.GET.get('next')
            if next_url:
                return redirect(next_url)

            return redirect('home')

        else:
            messages.error(request, "Invalid username or password.")

    return render(request, 'account/login.html')


from django.contrib.auth import login
from django.contrib import messages
from django.shortcuts import render, redirect

from .forms import RegisterForm


def register_view(request):
    if request.method == 'POST':
        form = RegisterForm(request.POST)

        if form.is_valid():
            user = form.save()
            login(request, user)

            messages.success(
                request,
                'Akun berhasil dibuat! Selamat datang.'
            )
            return redirect('home')
        else:
            messages.error(
                request,
                'Mohon periksa kembali data Anda.'
            )
    else:
        form = RegisterForm()

    return render(
        request,
        'account/register.html',
        {'form': form}
    )

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

from django.db.models import Q

def search_view(request):
    query = request.GET.get('q')
    search_type = request.GET.get('type')

    if search_type == 'history':
        items = ImportHistory.objects.filter(user=request.user)

        if query:
            items = items.filter(filename__icontains=query)

        return render(request, 'search_results_partial.html', {
            'histories': items.order_by('-imported_at'),
            'search_type': 'history'
        })

    else:
        Type_id = request.GET.get('Type')

        items = ReadingItem.objects.select_related('Type').filter(
            user=request.user
        )

        if query:
            items = items.filter(
                Q(title__icontains=query) |
                Q(alternative_title__icontains=query)
            )

        if Type_id:
            items = items.filter(Type__id=Type_id)

        return render(request, 'search_results_partial.html', {
            'reading_items': items,
            'search_type': 'reading'
        })


def about_view(request):
    return render(request, 'about.html')

import os
import re
import json
import sqlite3
import zipfile
import tempfile
import datetime
import shutil

from decimal import Decimal
from pathlib import PurePosixPath

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponse, FileResponse
from django.shortcuts import redirect, render
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.utils.dateparse import (
    parse_date,
    parse_datetime,
    parse_time,
)

from .models import ReadingItem, Status, Type, ImportHistory


# =========================================================
# BACKUP HELPERS
# =========================================================

BACKUP_FORMAT_VERSION = 2
BACKUP_JSON_NAME = "backup.json"


def _json_safe(value):
    """Mengubah nilai Django menjadi nilai yang aman disimpan sebagai JSON."""
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()

    if isinstance(value, Decimal):
        return str(value)

    return value


def _item_to_backup_dict(item, image_archive_path=None):
    """
    Mengambil seluruh field konkret ReadingItem secara dinamis.
    Relasi disimpan berdasarkan nama dan PK jika tersedia.
    """
    data = {}

    for field in item._meta.concrete_fields:
        name = field.name

        # PK dan pemilik akan dibuat ulang saat impor.
        if field.primary_key or name == "user":
            continue

        if field.is_relation and field.many_to_one:
            related = getattr(item, name, None)

            if related is None:
                data[name] = None
            else:
                data[name] = {
                    "__relation__": True,
                    "pk": related.pk,
                    "name": getattr(related, "name", str(related)),
                }

            continue

        if name == "image":
            data[name] = image_archive_path or (
                item.image.name if item.image else ""
            )
            continue

        value = field.value_from_object(item)
        data[name] = _json_safe(value)

    # Mendukung field ManyToMany jika model memilikinya.
    for field in item._meta.many_to_many:
        related_objects = getattr(item, field.name).all()

        data[field.name] = [
            {
                "pk": obj.pk,
                "name": getattr(obj, "name", str(obj)),
            }
            for obj in related_objects
        ]

    return data


def _parse_field_value(field, value):
    """Mengonversi nilai JSON sesuai tipe field Django."""
    if value is None:
        return None

    internal_type = field.get_internal_type()

    if internal_type == "DateTimeField" and isinstance(value, str):
        return parse_datetime(value) or value

    if internal_type == "DateField" and isinstance(value, str):
        return parse_date(value) or value

    if internal_type == "TimeField" and isinstance(value, str):
        return parse_time(value) or value

    if internal_type == "DecimalField":
        return Decimal(str(value))

    return value


def _resolve_relation(field, value):
    """Mengembalikan objek relasi dari data backup."""
    if value is None:
        return None

    related_model = field.remote_field.model

    if not isinstance(value, dict) or not value.get("__relation__"):
        # Mendukung data sederhana dari format backup lama.
        try:
            return related_model.objects.get(pk=value)
        except (related_model.DoesNotExist, ValueError, TypeError):
            return None

    name = value.get("name")
    pk = value.get("pk")

    # Status dan Type dicari berdasarkan nama agar tidak bergantung
    # pada ID dari database pengguna yang membuat backup.
    if field.name in ("status", "Type") and name:
        obj, _ = related_model.objects.get_or_create(name=name)
        return obj

    # Untuk relasi lain, coba gunakan PK yang masih tersedia.
    if pk is not None:
        try:
            return related_model.objects.get(pk=pk)
        except related_model.DoesNotExist:
            pass

    # Jika model relasi memiliki field name, coba cari/buat.
    if name and any(f.name == "name" for f in related_model._meta.fields):
        obj, _ = related_model.objects.get_or_create(name=name)
        return obj

    return None


def _create_item_from_payload(user, payload, archive=None, zip_file=None):
    """
    Membuat item dari data backup.
    Pemilik selalu request.user, bukan pemilik dari backup.
    """
    model = ReadingItem
    kwargs = {"user": user}
    deferred_values = {}
    image_reference = ""

    for name, value in payload.items():
        try:
            field = model._meta.get_field(name)
        except Exception:
            # Mengabaikan field yang tidak ada pada versi model saat ini.
            continue

        if field.primary_key or name == "user":
            continue

        if name == "image":
            image_reference = value or ""
            continue

        if field.many_to_many:
            deferred_values[name] = value or []
            continue

        if field.is_relation and field.many_to_one:
            kwargs[name] = _resolve_relation(field, value)
            continue

        try:
            parsed_value = _parse_field_value(field, value)
        except (ValueError, TypeError, ArithmeticError):
            parsed_value = value

        # Django akan menimpa nilai auto_now/auto_now_add saat save.
        if getattr(field, "auto_now", False) or getattr(
            field, "auto_now_add", False
        ):
            deferred_values[f"__scalar__{name}"] = parsed_value
        else:
            kwargs[name] = parsed_value

    # Biarkan Django menggunakan default untuk field wajib yang tidak
    # ada di backup versi lama.
    item = model.objects.create(**kwargs)

    # Pulihkan seluruh field waktu persis seperti pada backup.
    for key, value in deferred_values.items():
        if key.startswith("__scalar__"):
            field_name = key.replace("__scalar__", "", 1)

            try:
                field = model._meta.get_field(field_name)

                if value is not None:
                    value = _parse_field_value(field, value)

                model.objects.filter(pk=item.pk).update(
                    **{field_name: value}
                )
            except Exception as exc:
                print(
                    f"Gagal memulihkan {field_name} "
                    f"untuk item {item.pk}: {exc}"
                )

    if any(key.startswith("__scalar__") for key in deferred_values):
        item.refresh_from_db()

    # Pulihkan ManyToMany jika ada.
    for name, values in deferred_values.items():
        if name.startswith("__scalar__"):
            continue

        try:
            field = model._meta.get_field(name)
        except Exception:
            continue

        if not field.many_to_many:
            continue

        manager = getattr(item, name)
        related_model = field.remote_field.model

        for entry in values:
            if isinstance(entry, dict):
                pk = entry.get("pk")
                label = entry.get("name")
            else:
                pk = entry
                label = None

            related_obj = None

            if pk is not None:
                try:
                    related_obj = related_model.objects.get(pk=pk)
                except related_model.DoesNotExist:
                    pass

            if related_obj is None and label and any(
                f.name == "name" for f in related_model._meta.fields
            ):
                related_obj, _ = related_model.objects.get_or_create(
                    name=label
                )

            if related_obj is not None:
                manager.add(related_obj)

    # Pulihkan gambar dari ZIP tanpa mengekstrak path sembarangan.
    if archive is not None and zip_file is not None and image_reference:
        try:
            safe_path = str(PurePosixPath(image_reference))

            if (
                safe_path.startswith("/")
                or ".." in PurePosixPath(safe_path).parts
                or safe_path not in archive.namelist()
            ):
                return item

            image_bytes = archive.read(safe_path)
            original_name = os.path.basename(safe_path)
            filename = f"restored_{item.pk}_{original_name}"

            item.image.save(
                filename,
                ContentFile(image_bytes),
                save=True,
            )
        except (KeyError, OSError, ValueError, zipfile.BadZipFile):
            pass

    return item


def _record_import_history(user, uploaded_file, count):
    """Menyimpan riwayat impor untuk pengguna yang sedang login."""
    if count <= 0:
        return

    try:
        uploaded_file.seek(0)
    except (AttributeError, OSError):
        pass

    ImportHistory.objects.create(
        user=user,
        filename=uploaded_file.name,
        total_items=count,
        status="Success",
        file=uploaded_file,
    )


# =========================================================
# IMPORT TXT
# =========================================================

@login_required
def import_data(request):
    if request.method != "POST" or not request.FILES.get("import_file"):
        return redirect("reading_list")

    uploaded_file = request.FILES["import_file"]

    try:
        content = uploaded_file.read().decode("utf-8-sig")
    except (UnicodeDecodeError, AttributeError):
        messages.error(request, "File TXT tidak valid atau bukan UTF-8.")
        return redirect("reading_list")

    count = 0
    errors = 0

    # Format TXT baru menyimpan seluruh field dalam JSON.
    marker = "# DATA_JSON_BEGIN"

    if marker in content:
        try:
            json_section = content.split(marker, 1)[1].strip()
            payloads = json.loads(json_section)

            with transaction.atomic():
                for payload in payloads:
                    try:
                        _create_item_from_payload(request.user, payload)
                        count += 1
                    except Exception as exc:
                        errors += 1
                        print(f"TXT import error: {exc}")

        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            messages.error(
                request,
                f"Format data TXT tidak valid: {exc}",
            )
            return redirect("reading_list")

    else:
        # Kompatibilitas dengan TXT format lama.
        default_status = (
            Status.objects.filter(id=1).first()
            or Status.objects.first()
        )
        default_type = (
            Type.objects.filter(id=1).first()
            or Type.objects.first()
        )

        with transaction.atomic():
            for line in content.splitlines():
                if "»" not in line:
                    continue

                try:
                    raw_data = line.split("»", 1)[1].strip()
                    parts = [p.strip() for p in raw_data.split("|")]

                    parts = [p for p in parts if p]
                    if not parts:
                        continue

                    title = parts[0]
                    chapters = 0
                    season = "-"
                    status_obj = default_status
                    type_obj = default_type
                    rating = "-"
                    notes = []

                    for part in parts[1:]:
                        lower = part.lower()

                        chapter_match = re.search(
                            r"\bch\.?\s*(\d+)\b",
                            lower,
                        )

                        if chapter_match:
                            chapters = int(chapter_match.group(1))
                        elif re.fullmatch(
                            r"s\d+(?:\s*[-–]\s*\d+)?",
                            lower,
                        ):
                            season = part
                        elif Status.objects.filter(
                            name__iexact=part
                        ).exists():
                            status_obj = Status.objects.filter(
                                name__iexact=part
                            ).first()
                        elif Type.objects.filter(
                            name__iexact=part
                        ).exists():
                            type_obj = Type.objects.filter(
                                name__iexact=part
                            ).first()
                        elif any(mark in part for mark in ("↑", "↓", "→")):
                            rating = part
                        else:
                            notes.append(part)

                    ReadingItem.objects.create(
                        user=request.user,
                        title=title,
                        chapters=chapters,
                        season=season,
                        status=status_obj,
                        Type=type_obj,
                        rating=rating,
                        notes=", ".join(notes)[:255] if notes else "-",
                    )
                    count += 1

                except Exception as exc:
                    errors += 1
                    print(f"Error pada baris TXT '{line}': {exc}")

    if count:
        _record_import_history(request.user, uploaded_file, count)
        messages.success(
            request,
            f"Berhasil mengimpor {count} data TXT.",
        )
    else:
        messages.warning(
            request,
            "Tidak ada data yang berhasil diimpor.",
        )

    if errors:
        messages.warning(
            request,
            f"{errors} data dilewati karena format atau field tidak sesuai.",
        )

    return redirect("reading_list")


# =========================================================
# IMPORT ZIP
# =========================================================

@login_required
def import_full(request):
    if request.method != "POST" or not request.FILES.get("import_file"):
        return redirect("reading_list")

    uploaded_file = request.FILES["import_file"]
    imported_count = 0
    errors = 0

    try:
        with zipfile.ZipFile(uploaded_file, "r") as archive:
            names = set(archive.namelist())

            # Format backup ZIP baru.
            if BACKUP_JSON_NAME in names:
                manifest = json.loads(
                    archive.read(BACKUP_JSON_NAME).decode("utf-8")
                )

                if not isinstance(manifest, dict):
                    raise ValueError("Struktur backup.json tidak valid.")

                payloads = manifest.get("items", [])
                if not isinstance(payloads, list):
                    raise ValueError("Daftar item pada backup tidak valid.")

                with transaction.atomic():
                    for payload in payloads:
                        if not isinstance(payload, dict):
                            errors += 1
                            continue

                        try:
                            _create_item_from_payload(
                                request.user,
                                payload,
                                archive=archive,
                                zip_file=uploaded_file,
                            )
                            imported_count += 1
                        except Exception as exc:
                            errors += 1
                            print(f"ZIP import error: {exc}")

            # Kompatibilitas dengan ZIP lama yang menggunakan SQLite.
            elif "data.sqlite" in names:
                conn = sqlite3.connect(":memory:")
                conn.row_factory = sqlite3.Row

                try:
                    conn.deserialize(archive.read("data.sqlite"))
                    cursor = conn.cursor()

                    columns = {
                        row["name"]
                        for row in cursor.execute(
                            "PRAGMA table_info(reading_items)"
                        ).fetchall()
                    }

                    if "title" not in columns:
                        raise ValueError(
                            "Tabel reading_items tidak memiliki kolom title."
                        )

                    rows = cursor.execute(
                        "SELECT * FROM reading_items"
                    ).fetchall()

                    with transaction.atomic():
                        for row in rows:
                            try:
                                values = dict(row)

                                status_name = values.get("status") or "-"
                                type_name = (
                                    values.get("Type")
                                    or values.get("type")
                                    or "-"
                                )

                                status_obj = (
                                    Status.objects.filter(
                                        name__iexact=status_name
                                    ).first()
                                    or Status.objects.create(
                                        name=status_name
                                    )
                                )

                                type_obj = (
                                    Type.objects.filter(
                                        name__iexact=type_name
                                    ).first()
                                    or Type.objects.create(
                                        name=type_name
                                    )
                                )

                                # Kolom legacy yang sudah dikenal.
                                legacy_payload = {
                                    "title": values.get("title") or "",
                                    "chapters": values.get("chapters") or 0,
                                    "season": values.get("season") or "-",
                                    "status": {
                                        "__relation__": True,
                                        "name": status_obj.name,
                                        "pk": status_obj.pk,
                                    },
                                    "rating": values.get("rating") or "-",
                                    "Type": {
                                        "__relation__": True,
                                        "name": type_obj.name,
                                        "pk": type_obj.pk,
                                    },
                                    "notes": values.get("notes") or "-",
                                    "favorit": bool(
                                        values.get("favorit", 0)
                                    ),
                                }

                                item = _create_item_from_payload(
                                    request.user,
                                    legacy_payload,
                                )

                                image_name = values.get("image_filename")
                                if image_name:
                                    image_path = (
                                        f"images/{os.path.basename(image_name)}"
                                    )
                                    if image_path in names:
                                        item.image.save(
                                            f"restored_{item.pk}_"
                                            f"{os.path.basename(image_name)}",
                                            ContentFile(
                                                archive.read(image_path)
                                            ),
                                            save=True,
                                        )

                                imported_count += 1

                            except Exception as exc:
                                errors += 1
                                print(f"Legacy ZIP import error: {exc}")

                finally:
                    conn.close()

            else:
                raise ValueError(
                    "ZIP tidak berisi backup.json atau data.sqlite."
                )

    except (
        zipfile.BadZipFile,
        json.JSONDecodeError,
        UnicodeDecodeError,
        sqlite3.Error,
        ValueError,
        OSError,
    ) as exc:
        messages.error(request, f"File backup tidak valid: {exc}")
        return redirect("reading_list")

    if imported_count:
        _record_import_history(
            request.user,
            uploaded_file,
            imported_count,
        )
        messages.success(
            request,
            f"Berhasil mengimpor {imported_count} item dari ZIP.",
        )
    else:
        messages.warning(
            request,
            "Tidak ada item yang berhasil diimpor.",
        )

    if errors:
        messages.warning(
            request,
            f"{errors} item dilewati karena data tidak cocok.",
        )

    return redirect("reading_list")


# =========================================================
# EXPORT TXT
# =========================================================

def get_export_txt_content(user):
    """
    Membuat TXT yang tetap menampilkan ringkasan manusiawi,
    lalu menyertakan JSON lengkap untuk proses restore.
    """
    items = ReadingItem.objects.filter(user=user).select_related(
        "status", "Type"
    ).order_by("title")

    lines = []
    last_char = None

    total_titles = items.count()
    total_chapters = (
        items.aggregate(total=Sum("chapters"))["total"] or 0
    )

    for item in items:
        current_char = item.title[0].upper() if item.title else "#"

        if current_char != last_char:
            lines.append(f"\n{current_char} | ••••")
            last_char = current_char

        parts = [item.title] if item.title else []

        if item.chapters and item.chapters > 0:
            parts.append(f"Ch. {item.chapters}")

        if item.season and item.season != "-":
            parts.append(item.season)

        if item.status and item.status.id != 1:
            parts.append(item.status.name)

        if item.rating and item.rating != "-":
            parts.append(item.rating)

        if item.Type and item.Type.id != 1:
            parts.append(item.Type.name)

        if item.notes and item.notes != "-":
            parts.append(item.notes)

        if getattr(item, "alternative_title", ""):
            parts.append(
                f"Alternative Title: {item.alternative_title}"
            )

        if getattr(item, "synopsis", ""):
            parts.append(f"Synopsis: {item.synopsis}")

        if getattr(item, "tags", ""):
            parts.append(f"Tags: {item.tags}")

        if getattr(item, "favorit", False):
            parts.append("Favorite")

        lines.append(" » " + " | ".join(parts))

    lines.extend([
        "",
        "=" * 30,
        f"Laporan Per: {datetime.date.today():%d %B %Y}",
        f"Total Judul Terdata: {total_titles}",
        f"Total Seluruh Chapter: {total_chapters}",
        "=" * 30,
        "",
        "# DATA_JSON_BEGIN",
    ])

    # Data lengkap untuk restore TXT.
    payloads = [_item_to_backup_dict(item) for item in items]

    lines.append(
        json.dumps(
            payloads,
            ensure_ascii=False,
            cls=DjangoJSONEncoder,
        )
    )

    return "\n".join(lines) + "\n"


@login_required
def export_data(request):
    content = get_export_txt_content(request.user)

    response = HttpResponse(
        content,
        content_type="text/plain; charset=utf-8",
    )
    response["Content-Disposition"] = (
        'attachment; filename="reading_list_export.txt"'
    )
    return response


# =========================================================
# EXPORT ZIP
# =========================================================

def generate_zip_logic(user, zip_path):
    """
    Membuat ZIP versi baru.
    Seluruh field ReadingItem disimpan dalam backup.json,
    sedangkan semua file gambar disimpan dalam folder images/.
    """
    items = ReadingItem.objects.filter(user=user).select_related(
        "status", "Type"
    ).order_by("title")

    manifest = {
        "format": "reading-list-backup",
        "version": BACKUP_FORMAT_VERSION,
        "created_at": timezone.now().isoformat(),
        "items": [],
    }

    with zipfile.ZipFile(
        zip_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for index, item in enumerate(items, start=1):
            image_archive_path = None

            if item.image:
                image_archive_path = (
                    f"images/item_{index}_{os.path.basename(item.image.name)}"
                )

            payload = _item_to_backup_dict(
                item,
                image_archive_path=image_archive_path,
            )
            manifest["items"].append(payload)

            if item.image:
                try:
                    item.image.open("rb")
                    image_bytes = item.image.read()
                    item.image.close()

                    archive.writestr(image_archive_path, image_bytes)

                except (OSError, ValueError) as exc:
                    print(
                        f"Gagal memasukkan gambar item {item.pk}: {exc}"
                    )

                    # Jika gambar gagal dibaca, jangan menyimpan referensi
                    # ke file yang tidak ikut dimasukkan ke ZIP.
                    payload["image"] = ""

        archive.writestr(
            BACKUP_JSON_NAME,
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
                cls=DjangoJSONEncoder,
            ),
        )


@login_required
def export_full(request):
    temp_dir = tempfile.mkdtemp(prefix="reading_backup_")
    zip_path = os.path.join(temp_dir, "backup_full.zip")

    try:
        generate_zip_logic(request.user, zip_path)

        file_handle = open(zip_path, "rb")
        response = FileResponse(
            file_handle,
            content_type="application/zip",
        )
        response["Content-Disposition"] = (
            f'attachment; filename="backup_{request.user.username}.zip"'
        )

        # Bersihkan folder sementara setelah respons selesai dikirim.
        response._resource_closers.append(
            lambda: shutil.rmtree(temp_dir, ignore_errors=True)
        )
        return response

    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


# =========================================================
# READING LIST PAGE
# =========================================================

def estimate_zip_size(user):
    """
    Estimasi ukuran backup tanpa membuat ZIP setiap kali halaman dibuka.
    Ukuran akhir ZIP bisa berbeda tergantung kompresi.
    """
    items = ReadingItem.objects.filter(user=user).select_related(
        "status", "Type"
    )

    payloads = [_item_to_backup_dict(item) for item in items]

    json_bytes = len(
        json.dumps(
            payloads,
            ensure_ascii=False,
            cls=DjangoJSONEncoder,
        ).encode("utf-8")
    )

    image_bytes = 0

    for item in items:
        if item.image:
            try:
                image_bytes += item.image.size
            except (OSError, ValueError):
                pass

    # JSON umumnya terkompresi cukup baik, gambar biasanya tidak.
    estimated_bytes = int(json_bytes * 0.5) + image_bytes
    return f"{estimated_bytes / (1024 * 1024):.2f} MB"


@login_required
def reading_list(request):
    # Ambil data ReadingItem milik user
    items = ReadingItem.objects.select_related(
        "Type", "status"
    ).filter(user=request.user)

    # ==========================================
    # FILTER TYPE / KATEGORI
    # ==========================================
    type_id = request.GET.get("Type")

    if type_id:
        items = items.filter(Type_id=type_id)

    # ==========================================
    # FILTER STATUS
    # ==========================================
    status_name = request.GET.get("status")

    if status_name:
        items = items.filter(status__name__iexact=status_name)

    # ==========================================
    # FILTER TAG / GENRE
    # ==========================================
    tag_ids = [
        tag_id for tag_id in request.GET.getlist("tag")
        if tag_id.isdigit()
    ]

    active_tags = [int(tag_id) for tag_id in tag_ids]

    if tag_ids:
        items = items.filter(
            tags__id__in=tag_ids
        ).distinct()

    # ==========================================
    # SORTING
    # ==========================================
    sort = request.GET.get("sort", "az")

    sort_options = [
        ("relevance", "Relevance"),
        ("latest", "Latest"),
        ("az", "A-Z"),
        ("new", "New"),
    ]

    if sort == "az":
        items = items.order_by("title", "id")

    elif sort in ["latest", "new"]:
        items = items.order_by("-created_at")

    elif sort == "relevance":
        items = items.order_by("title", "id")

    else:
        sort = "az"
        items = items.order_by("title", "id")

    # ==========================================
    # EXPORT DATA
    # ==========================================
    txt_content = get_export_txt_content(request.user)
    txt_size = f"{len(txt_content.encode('utf-8')) / 1024:.1f} KB"

    # ==========================================
    # CONTEXT
    # ==========================================
    context = {
        "reading_items": items,

        "categories": Type.objects.exclude(id=1),
        "statuses": Status.objects.exclude(id=1),

        # Data untuk filter tag
        "tags": Tag.objects.exclude(id=1),
        "active_tags": active_tags,

        # Data untuk sorting
        "sort_options": sort_options,

        # Nilai filter yang sedang aktif
        "selected_type": type_id,
        "selected_status": status_name,
        "selected_sort": sort,

        # Export
        "txt_size": txt_size,
        "zip_size": estimate_zip_size(request.user),
    }

    return render(request, "reading_list.html", context)

@login_required
def reading_add(request):
    """Menambah data baru dengan sistem notifikasi."""
    if request.method == 'POST':
        status_id = request.POST.get('status')
        Type_id = request.POST.get('Type')

        synopsis_text = request.POST.get('synopsis')

        # --- ALTERNATIVE TITLES ---
        alternative_titles = request.POST.getlist('alternative_title')

        alternative_title_text = '\n'.join(
            title.strip()
            for title in alternative_titles
            if title.strip()
        )
        # --------------------------

        # --- VALIDASI & AMANKAN FIELD CHAPTERS ---
        raw_chapters = request.POST.get('chapters', '0')
        try:
            chapters_val = int(raw_chapters) if str(raw_chapters).isdigit() else 0

            if chapters_val > 999999999:
                chapters_val = 0
        except (ValueError, TypeError):
            chapters_val = 0
        # ----------------------------------------

        new_item = ReadingItem.objects.create(
            user=request.user,
            title=request.POST.get('title'),
            alternative_title=alternative_title_text,
            chapters=chapters_val,
            season=request.POST.get('season', '-'),
            rating=request.POST.get('rating', '-'),
            notes=request.POST.get('notes', '-'),
            synopsis=synopsis_text if synopsis_text else '-',
            image=request.FILES.get('image'),
            status=Status.objects.filter(id=status_id).first(),
            Type=Type.objects.filter(id=Type_id).first()
        )

        # Handle Tags secara otomatis
        selected_tags = request.POST.getlist('tags')

        if selected_tags:
            new_item.tags.set(selected_tags)
        else:
            new_item.tags.set([1])

        messages.success(request, 'Data berhasil ditambahkan!')
        return redirect('reading_list')

    context = {
        'statuses': Status.objects.all(),
        'categories': Type.objects.all(),
        'tags': Tag.objects.all()
    }

    return render(request, 'reading_add.html', context)

@login_required
def reading_edit(request, pk):
    """Edit data dan simpan perubahan dengan notifikasi."""
    item = get_object_or_404(ReadingItem, pk=pk)
    next_url = request.POST.get('next') or request.GET.get('next')

    if request.method == 'POST':
        item.title = request.POST.get('title')

        # --- VALIDASI & AMANKAN FIELD CHAPTERS ---
        raw_chapters = request.POST.get('chapters', '0')
        try:
            chapters_val = int(raw_chapters) if str(raw_chapters).isdigit() else 0
            if chapters_val > 999999999:
                chapters_val = 0
        except (ValueError, TypeError):
            chapters_val = 0
        item.chapters = chapters_val
        # ----------------------------------------

        item.season = request.POST.get('season')
        item.rating = request.POST.get('rating')
        item.notes = request.POST.get('notes')
        item.synopsis = request.POST.get('synopsis')

        # --- ALTERNATIVE TITLES ---
        alternative_titles = request.POST.getlist('alternative_title')
        alternative_title_text = '\n'.join(
            title.strip()
            for title in alternative_titles
            if title.strip()
        )
        item.alternative_title = alternative_title_text
        # --------------------------

        status_id = request.POST.get('status')
        item.status_id = status_id if status_id else None

        Type_id = request.POST.get('Type')
        item.Type_id = Type_id if Type_id else None

        if request.FILES.get('image'):
            item.image = request.FILES.get('image')

        item.save()

        # Handle Tags
        tag_ids = request.POST.getlist('tags')
        if tag_ids:
            item.tags.set(tag_ids)
        else:
            # Jika user tidak mencentang apa pun, otomatis set ke Tag ID 1 (No Tag)
            item.tags.set([1])

        messages.success(request, 'Perubahan berhasil disimpan!')
        return redirect('reading_item_detail', item_id=item.id)

    # --- AMBIL ALTERNATIVE TITLES UNTUK DITAMPILKAN DI FORM ---
    alternative_titles = [
        title.strip()
        for title in (item.alternative_title or '').splitlines()
        if title.strip()
    ]

    context = {
        'item': item,
        'statuses': Status.objects.all(),
        'categories': Type.objects.all(),
        'tags': Tag.objects.all(),
        'next': next_url,
        'alternative_titles': alternative_titles,
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
    # Menambahkan .order_by('title') agar item terurut berdasarkan judul
    items = ReadingItem.objects.filter(id__in=ids).order_by('title')

    if request.method == 'POST':
        with transaction.atomic():
            for item in items:
                # Menggunakan request.POST.get untuk mengambil data
                item.title = request.POST.get(f'title_{item.id}', item.title)
                
                # --- VALIDASI & AMANKAN FIELD CHAPTERS BULK ---
                raw_chapters = request.POST.get(f'chapters_{item.id}', 0)
                try:
                    chapters_val = int(raw_chapters) if str(raw_chapters).isdigit() else 0
                    if chapters_val > 999999999:
                        chapters_val = 0
                except (ValueError, TypeError):
                    chapters_val = 0
                item.chapters = chapters_val
                # ---------------------------------------------

                item.season = request.POST.get(f'season_{item.id}', '-')
                item.rating = request.POST.get(f'rating_{item.id}', '-')
                item.notes = request.POST.get(f'notes_{item.id}', '-')

                # Menangani ForeignKey
                new_status = request.POST.get(f'status_{item.id}')
                new_Type = request.POST.get(f'Type_{item.id}')

                # Jika user memilih opsi kosong, tetap gunakan relasi yang ada atau default
                if new_status:
                    item.status_id = new_status
                if new_Type:
                    item.Type_id = new_Type
                
                # Menangani Many-to-Many Tags (jika dikirim dari form per baris)
                tags_list = request.POST.getlist(f'tags_{item.id}')
                if tags_list:
                    item.tags.set(tags_list)

                # Menangani upload gambar
                if f'image_{item.id}' in request.FILES:
                    item.image = request.FILES[f'image_{item.id}']

                item.save()

        messages.success(request, f"Berhasil mengupdate {items.count()} item!")
        return redirect('reading_list')

    context = {
        'items': items,
        'statuses': {s.name: s for s in Status.objects.all()}.values(),
        'categories': {c.name: c for c in Type.objects.all()}.values(),
        'tags': Tag.objects.all(),  # <-- Ditambahkan untuk memuat data tags ke HTML
    }
    return render(request, 'reading_edit_bulk.html', context)

def reading_item_detail(request, item_id):
    item = get_object_or_404(ReadingItem, id=item_id)

    # Ambil alternative titles dan pisahkan berdasarkan baris baru
    alternative_titles = [
        title.strip()
        for title in (item.alternative_title or '').splitlines()
        if title.strip()
    ]

    context = {
        'item': item,
        'alternative_titles': alternative_titles,
    }

    return render(request, 'reading_item_detail.html', context)

# Tambahkan fungsi ini tepat di bawahnya
def toggle_favorite(request, pk):
    if request.method == "POST":
        item = get_object_or_404(ReadingItem, pk=pk)
        # Membalik status favorit (True jadi False, False jadi True)
        item.favorit = not item.favorit
        item.save()
    return redirect('reading_item_detail', item_id=pk)

from django.utils import timezone
from datetime import timedelta, date
from django.db.models import Count, Sum, Avg, Q
import calendar
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

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
    categories = Type.objects.filter(items__user=request.user).annotate(item_count=Count('items'))
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

    # =========================================================
    # TAMBAHAN: KALKULASI ANALITIK BARU (STREAK, PACE, STALLED, ONGOING, MONTHLY 1-31 & HISTORY 3 BULAN)
    # =========================================================
    today = timezone.localdate()

    requested_month_str = request.GET.get('month')

    if requested_month_str:
        try:
            parts = requested_month_str.split('-')
            current_year = int(parts[0])
            current_month = int(parts[1])
            target_date_obj = date(current_year, current_month, 1)
        except (ValueError, IndexError):
            current_year = today.year
            current_month = today.month
            target_date_obj = today
    else:
        current_year = today.year
        current_month = today.month
        target_date_obj = today

    current_month_name = target_date_obj.strftime('%B %Y')

    # Buat daftar 3 bulan terakhir untuk ditampilkan di Modal History
    last_three_months = []
    for i in range(3):
        m_target = today.month - i
        y_target = today.year
        while m_target <= 0:
            m_target += 12
            y_target -= 1
            
        m_date = date(y_target, m_target, 1)
        m_code = m_date.strftime('%Y-%m')
        m_name = m_date.strftime('%B %Y')
        
        m_days = calendar.monthrange(y_target, m_target)[1]
        m_start = date(y_target, m_target, 1)
        m_end = date(y_target, m_target, m_days)
        m_total_activity = items.filter(last_edited_at__date__gte=m_start, last_edited_at__date__lte=m_end).count()
        
        last_three_months.append({
            'code': m_code,
            'name': m_name,
            'total_activity': m_total_activity
        })
    
    # A. Monthly Activity Data (Sesuai Bulan yang Terpilih)
    days_in_month = calendar.monthrange(current_year, current_month)[1]
    monthly_activity_data = []
    max_count = 1

    for day_num in range(1, days_in_month + 1):
        target_date = date(current_year, current_month, day_num)
        count = items.filter(last_edited_at__date=target_date).count()

        if count > max_count:
            max_count = count

        monthly_activity_data.append({
            'day': day_num,
            'count': count
        })

    max_scale = max(10, max_count)

    # B. Reading Streak
    streak_count = 0
    check_date = today
    while True:
        has_activity = items.filter(last_edited_at__date=check_date).exists()
        if has_activity:
            streak_count += 1
            check_date -= timedelta(days=1)
        else:
            if check_date == today:
                check_date -= timedelta(days=1)
                continue
            break

    # C. Weekly Velocity & Average Pace
    start_of_week = timezone.now() - timedelta(days=7)
    updates_this_week = items.filter(last_edited_at__gte=start_of_week).count()
    avg_per_day = round(updates_this_week / 7, 1)

    # D. Stalled / On-Hold Items (>30 Hari tanpa update atau status On-Hold)
    thirty_days_ago = timezone.now() - timedelta(days=30)
    stalled_items = items.filter(
        Q(status__name__iexact='On-Hold') | Q(last_edited_at__lt=thirty_days_ago)
    ).distinct().order_by('last_edited_at')

    # E. Completion Time Estimate untuk Series Ongoing
    ongoing_items = items.filter(status__name__iexact='Ongoing')
    for item in ongoing_items:
        if avg_per_day > 0 and hasattr(item, 'total_chapters') and item.total_chapters:
            remaining_ch = item.total_chapters - item.chapters
            if remaining_ch > 0:
                item.estimated_days = round(remaining_ch / avg_per_day)
            else:
                item.estimated_days = 0
        else:
            item.estimated_days = None

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
        'recently_added': recently_added,
        'all_recently_added': all_recently_added,
        'recently_updated': recently_updated,
        'all_recently_updated': all_recently_updated,
        'percentage_completed': percentage_completed,
        # Variabel tambahan baru
        'monthly_activity_data': monthly_activity_data,
        'max_scale': max_scale,
        'streak_count': streak_count,
        'updates_this_week': updates_this_week,
        'avg_per_day': avg_per_day,
        'stalled_items': stalled_items,
        'ongoing_items': ongoing_items,
        'days_in_month': days_in_month,
        # Variabel pendukung Modal 3 Bulan Terakhir
        'current_month_name': current_month_name,
        'last_three_months': last_three_months,
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

import os
import json
import sqlite3
import zipfile

from html import escape as html_escape
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import ImportHistory


@login_required
def history_detail_view(request, history_id):
    log = get_object_or_404(
        ImportHistory,
        id=history_id,
        user=request.user
    )

    def safe(value):
        """Mengubah nilai menjadi teks HTML yang aman."""
        if value is None:
            return "-"

        if isinstance(value, dict):
            if value.get("__relation__"):
                return html_escape(
                    str(value.get("name") or value.get("pk") or "-")
                )
            value = json.dumps(value, ensure_ascii=False)

        elif isinstance(value, (list, tuple)):
            value = ", ".join(str(v) for v in value) if value else "-"

        return html_escape(str(value))

    def build_table(columns, rows):
        """Membuat tabel preview responsif."""
        if not columns:
            return """
                <div class="empty-state">
                    <div class="empty-icon">📂</div>
                    <h3>Belum ada data untuk ditampilkan</h3>
                    <p>File tidak memiliki tabel atau data yang bisa dibaca.</p>
                </div>
            """

        headers = "".join(
            f"<th>{safe(column)}</th>" for column in columns
        )

        if rows:
            body = "".join(
                "<tr>" + "".join(
                    f"<td>{safe(cell)}</td>" for cell in row
                ) + "</tr>"
                for row in rows
            )
        else:
            body = f"""
                <tr>
                    <td colspan="{len(columns)}" class="no-data">
                        Tidak ada data dalam file ini.
                    </td>
                </tr>
            """

        return f"""
            <div class="table-wrapper">
                <table class="data-table">
                    <thead>
                        <tr>{headers}</tr>
                    </thead>
                    <tbody>{body}</tbody>
                </table>
            </div>
        """

    preview_html = """
        <div class="empty-state">
            <div class="empty-icon">📄</div>
            <h3>Preview belum tersedia</h3>
            <p>File belum dapat dibaca atau tidak ditemukan.</p>
        </div>
    """

    file_path = None

    if log.file:
        try:
            file_path = log.file.path
        except (ValueError, NotImplementedError):
            file_path = None

    file_exists = bool(file_path and os.path.isfile(file_path))
    file_name = log.filename or "File impor"
    extension = os.path.splitext(file_name)[1].lower()

    format_label = {
        ".zip": "ZIP Archive",
        ".txt": "Text File",
        ".json": "JSON File",
        ".sqlite": "SQLite Database",
        ".db": "Database File",
    }.get(extension, "File Import")

    total_rows = 0
    preview_title = "Preview Data"
    preview_description = "Berikut data yang ditemukan dalam file impor."

    if file_exists:
        try:
            # =====================================================
            # FORMAT ZIP
            # =====================================================
            if zipfile.is_zipfile(file_path):
                with zipfile.ZipFile(file_path, "r") as archive:
                    names = archive.namelist()

                    if "backup.json" in names:
                        with archive.open("backup.json") as backup:
                            manifest = json.load(backup)

                        if isinstance(manifest, dict):
                            items = manifest.get("items", [])
                        elif isinstance(manifest, list):
                            items = manifest
                        else:
                            items = []

                        if not isinstance(items, list):
                            items = []

                        total_rows = len(items)
                        preview_title = "Preview Data Backup"
                        preview_description = (
                            "Data item yang tersimpan di dalam backup ZIP."
                        )

                        if items:
                            columns = list(dict.fromkeys(
                                key
                                for item in items
                                if isinstance(item, dict)
                                for key in item.keys()
                            ))

                            rows = [
                                [
                                    item.get(column, "-")
                                    for column in columns
                                ]
                                for item in items
                                if isinstance(item, dict)
                            ]

                            preview_html = build_table(columns, rows)
                        else:
                            preview_html = build_table([], [])

                    # Mendukung format ZIP lama
                    elif "data.sqlite" in names:
                        with archive.open("data.sqlite") as source:
                            import tempfile

                            with tempfile.NamedTemporaryFile(
                                suffix=".sqlite",
                                delete=True
                            ) as temp_file:
                                temp_file.write(source.read())
                                temp_file.flush()

                                connection = sqlite3.connect(
                                    temp_file.name
                                )

                                try:
                                    cursor = connection.cursor()

                                    cursor.execute("""
                                        SELECT name
                                        FROM sqlite_master
                                        WHERE type = 'table'
                                          AND name NOT LIKE 'sqlite_%'
                                    """)

                                    tables = [
                                        row[0]
                                        for row in cursor.fetchall()
                                    ]

                                    if "reading_items" in tables:
                                        table_name = "reading_items"
                                    elif tables:
                                        table_name = tables[0]
                                    else:
                                        table_name = None

                                    if table_name:
                                        # Nama tabel berasal dari hasil
                                        # pemeriksaan database SQLite.
                                        cursor.execute(
                                            f'SELECT * FROM "{table_name}"'
                                        )
                                        rows = cursor.fetchall()
                                        columns = [
                                            description[0]
                                            for description
                                            in cursor.description
                                        ]

                                        total_rows = len(rows)
                                        preview_title = (
                                            f"Preview Tabel: {table_name}"
                                        )
                                        preview_html = build_table(
                                            columns,
                                            rows
                                        )
                                    else:
                                        preview_html = build_table([], [])

                                finally:
                                    connection.close()

                    else:
                        preview_html = """
                            <div class="notice">
                                <strong>Format backup tidak dikenali.</strong>
                                <p>
                                    File ZIP tidak memiliki backup.json
                                    atau data.sqlite.
                                </p>
                            </div>
                        """

            # =====================================================
            # FORMAT TXT / JSON
            # =====================================================
            elif extension in (".txt", ".json"):
                with open(
                    file_path,
                    "r",
                    encoding="utf-8-sig"
                ) as source:
                    content = source.read()

                payload = None

                if extension == ".json":
                    try:
                        payload = json.loads(content)
                    except json.JSONDecodeError:
                        payload = None
                else:
                    marker = "# DATA_JSON_BEGIN"

                    if marker in content:
                        json_content = content.split(marker, 1)[1].strip()

                        try:
                            payload = json.loads(json_content)
                        except json.JSONDecodeError:
                            payload = None

                if isinstance(payload, dict):
                    items = payload.get("items", [])
                elif isinstance(payload, list):
                    items = payload
                else:
                    items = None

                if isinstance(items, list):
                    total_rows = len(items)
                    preview_title = "Preview Data TXT"
                    preview_description = (
                        "Data terstruktur yang ditemukan dalam file TXT."
                    )

                    if items:
                        columns = list(dict.fromkeys(
                            key
                            for item in items
                            if isinstance(item, dict)
                            for key in item.keys()
                        ))

                        rows = [
                            [
                                item.get(column, "-")
                                for column in columns
                            ]
                            for item in items
                            if isinstance(item, dict)
                        ]

                        preview_html = build_table(columns, rows)
                    else:
                        preview_html = build_table([], [])

                else:
                    # TXT biasa ditampilkan sebagai catatan teks.
                    preview_title = "Isi File TXT"
                    preview_description = (
                        "Pratinjau isi catatan dari file yang diimpor."
                    )

                    preview_html = f"""
                        <pre class="text-preview">{html_escape(content)}</pre>
                    """

            # =====================================================
            # FORMAT SQLITE LANGSUNG
            # =====================================================
            elif extension in (".sqlite", ".db"):
                connection = sqlite3.connect(file_path)

                try:
                    cursor = connection.cursor()
                    cursor.execute("""
                        SELECT name
                        FROM sqlite_master
                        WHERE type = 'table'
                          AND name NOT LIKE 'sqlite_%'
                    """)

                    tables = [row[0] for row in cursor.fetchall()]

                    if "reading_items" in tables:
                        table_name = "reading_items"
                    elif tables:
                        table_name = tables[0]
                    else:
                        table_name = None

                    if table_name:
                        cursor.execute(
                            f'SELECT * FROM "{table_name}"'
                        )
                        rows = cursor.fetchall()
                        columns = [
                            description[0]
                            for description in cursor.description
                        ]

                        total_rows = len(rows)
                        preview_title = f"Preview Tabel: {table_name}"
                        preview_html = build_table(columns, rows)
                    else:
                        preview_html = build_table([], [])

                finally:
                    connection.close()

            else:
                preview_html = """
                    <div class="notice">
                        Format file ini belum didukung untuk preview.
                    </div>
                """

        except (OSError, ValueError, KeyError, zipfile.BadZipFile,
                sqlite3.Error, json.JSONDecodeError) as error:
            preview_html = f"""
                <div class="notice error">
                    <strong>Gagal membaca file.</strong>
                    <p>{html_escape(str(error))}</p>
                </div>
            """

        except Exception:
            preview_html = """
                <div class="notice error">
                    <strong>Terjadi kesalahan saat membaca preview.</strong>
                    <p>Periksa format file dan coba kembali.</p>
                </div>
            """

    download_url = log.file.url if log.file else ""
    status = str(log.status or "Unknown")
    status_class = (
        "success"
        if status.lower() in ("success", "berhasil", "sukses")
        else "neutral"
    )

    html = f"""
    <!DOCTYPE html>
    <html lang="id">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Detail Riwayat Impor</title>

        <style>
            * {{
                box-sizing: border-box;
            }}

            body {{
                margin: 0;
                padding: 0;
                background: #f4f6fa;
                color: #1e293b;
                font-family: Inter, "Segoe UI", Arial, sans-serif;
                font-size: 14px;
                line-height: 1.6;
            }}

            .page {{
                width: min(1440px, 100%);
                margin: 0 auto;
                padding: 32px;
            }}

            .topbar {{
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 16px;
                margin-bottom: 28px;
                flex-wrap: wrap;
            }}

            .back-link {{
                display: inline-flex;
                align-items: center;
                gap: 8px;
                color: #475569;
                text-decoration: none;
                font-weight: 600;
                padding: 10px 14px;
                background: #fff;
                border: 1px solid #e2e8f0;
                border-radius: 10px;
                transition: .2s;
            }}

            .back-link:hover {{
                color: #2563eb;
                border-color: #93c5fd;
                background: #eff6ff;
            }}

            .eyebrow {{
                margin: 0 0 5px;
                color: #64748b;
                text-transform: uppercase;
                letter-spacing: 1.5px;
                font-size: 11px;
                font-weight: 800;
            }}

            h1 {{
                margin: 0;
                color: #0f172a;
                font-size: clamp(24px, 3vw, 32px);
                line-height: 1.25;
                letter-spacing: -.7px;
                overflow-wrap: anywhere;
            }}

            .subtitle {{
                margin: 9px 0 0;
                color: #64748b;
                font-size: 14px;
            }}

            .card {{
                background: #fff;
                border: 1px solid #e8edf4;
                border-radius: 16px;
                box-shadow: 0 5px 24px rgba(15, 23, 42, .035);
                margin-bottom: 22px;
                overflow: hidden;
            }}

            .card-header {{
                padding: 22px 24px;
                border-bottom: 1px solid #edf0f5;
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 14px;
                flex-wrap: wrap;
            }}

            .card-header h2 {{
                margin: 0;
                font-size: 17px;
                color: #0f172a;
                letter-spacing: -.2px;
            }}

            .card-header p {{
                margin: 5px 0 0;
                color: #64748b;
                font-size: 13px;
            }}

            .card-body {{
                padding: 24px;
            }}

            .file-info {{
                display: flex;
                align-items: center;
                gap: 16px;
                min-width: 0;
            }}

            .file-icon {{
                width: 54px;
                height: 54px;
                flex-shrink: 0;
                display: grid;
                place-items: center;
                border-radius: 14px;
                background: #eff6ff;
                color: #2563eb;
                font-size: 25px;
            }}

            .file-name {{
                margin: 0;
                font-size: 16px;
                font-weight: 700;
                color: #0f172a;
                overflow-wrap: anywhere;
            }}

            .file-type {{
                display: inline-block;
                margin-top: 5px;
                color: #64748b;
                font-size: 12px;
            }}

            .btn {{
                display: inline-flex;
                justify-content: center;
                align-items: center;
                gap: 8px;
                min-height: 42px;
                padding: 10px 16px;
                border-radius: 10px;
                font-size: 13px;
                font-weight: 700;
                text-decoration: none;
                border: 1px solid transparent;
                cursor: pointer;
                transition: .2s;
                white-space: nowrap;
            }}

            .btn-primary {{
                background: #2563eb;
                color: #fff;
            }}

            .btn-primary:hover {{
                background: #1d4ed8;
            }}

            .btn-secondary {{
                background: #fff;
                border-color: #dbe2ea;
                color: #334155;
            }}

            .btn-secondary:hover {{
                background: #f8fafc;
                border-color: #94a3b8;
            }}

            .metadata {{
                display: grid;
                grid-template-columns: repeat(3, minmax(0, 1fr));
                gap: 14px;
                margin-top: 24px;
            }}

            .meta-box {{
                background: #f8fafc;
                border: 1px solid #edf0f5;
                border-radius: 12px;
                padding: 16px;
                min-width: 0;
            }}

            .meta-label {{
                display: block;
                margin-bottom: 7px;
                color: #64748b;
                font-size: 12px;
                font-weight: 600;
            }}

            .meta-value {{
                color: #0f172a;
                font-size: 15px;
                font-weight: 700;
                overflow-wrap: anywhere;
            }}

            .status {{
                display: inline-flex;
                align-items: center;
                gap: 6px;
                border-radius: 999px;
                padding: 5px 10px;
                font-size: 12px;
                font-weight: 700;
            }}

            .status.success {{
                color: #047857;
                background: #d1fae5;
            }}

            .status.neutral {{
                color: #475569;
                background: #e2e8f0;
            }}

            .preview-heading {{
                display: flex;
                align-items: flex-start;
                justify-content: space-between;
                gap: 16px;
                flex-wrap: wrap;
            }}

            .count-badge {{
                display: inline-flex;
                align-items: center;
                background: #eff6ff;
                color: #1d4ed8;
                border-radius: 8px;
                padding: 7px 11px;
                font-size: 12px;
                font-weight: 700;
                white-space: nowrap;
            }}

            .table-wrapper {{
                width: 100%;
                max-height: 620px;
                overflow: auto;
                border: 1px solid #e2e8f0;
                border-radius: 11px;
            }}

            .data-table {{
                width: 100%;
                min-width: 650px;
                border-collapse: separate;
                border-spacing: 0;
                font-size: 13px;
            }}

            .data-table th {{
                position: sticky;
                top: 0;
                z-index: 1;
                padding: 13px 16px;
                text-align: left;
                white-space: nowrap;
                background: #f8fafc;
                color: #475569;
                border-bottom: 1px solid #e2e8f0;
                font-size: 11px;
                text-transform: uppercase;
                letter-spacing: .5px;
            }}

            .data-table td {{
                padding: 13px 16px;
                max-width: 360px;
                overflow-wrap: anywhere;
                vertical-align: top;
                color: #334155;
                border-bottom: 1px solid #edf0f5;
            }}

            .data-table tbody tr:last-child td {{
                border-bottom: none;
            }}

            .data-table tbody tr:nth-child(even) {{
                background: #fafbfd;
            }}

            .data-table tbody tr:hover {{
                background: #eff6ff;
            }}

            .no-data {{
                text-align: center;
                padding: 32px !important;
                color: #64748b !important;
            }}

            .empty-state {{
                padding: 48px 20px;
                text-align: center;
                border: 1px dashed #cbd5e1;
                border-radius: 12px;
                background: #fafcff;
            }}

            .empty-icon {{
                font-size: 32px;
                margin-bottom: 10px;
            }}

            .empty-state h3 {{
                margin: 0 0 6px;
                color: #334155;
                font-size: 16px;
            }}

            .empty-state p {{
                margin: 0;
                color: #64748b;
                font-size: 13px;
            }}

            .text-preview {{
                margin: 0;
                padding: 20px;
                max-height: 620px;
                overflow: auto;
                white-space: pre-wrap;
                overflow-wrap: anywhere;
                color: #334155;
                background: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 11px;
                font-family: Consolas, "Courier New", monospace;
                font-size: 13px;
                line-height: 1.8;
            }}

            .notice {{
                padding: 18px;
                border-radius: 10px;
                background: #eff6ff;
                border: 1px solid #bfdbfe;
                color: #1e40af;
            }}

            .notice p {{
                margin: 6px 0 0;
            }}

            .notice.error {{
                color: #991b1b;
                background: #fef2f2;
                border-color: #fecaca;
            }}

            .footer {{
                text-align: center;
                padding: 10px 0 0;
                color: #94a3b8;
                font-size: 12px;
            }}

            @media (max-width: 700px) {{
                .page {{
                    padding: 18px 14px;
                }}

                .topbar {{
                    align-items: flex-start;
                    flex-direction: column;
                    margin-bottom: 20px;
                }}

                .card-header,
                .card-body {{
                    padding: 18px;
                }}

                .metadata {{
                    grid-template-columns: 1fr;
                    gap: 10px;
                }}

                .file-info {{
                    align-items: flex-start;
                }}

                .file-icon {{
                    width: 44px;
                    height: 44px;
                    font-size: 21px;
                }}

                .file-card-actions {{
                    width: 100%;
                }}

                .file-card-actions .btn {{
                    width: 100%;
                }}

                .preview-heading {{
                    flex-direction: column;
                }}
            }}
        </style>
    </head>

    <body>
        <main class="page">

            <header class="topbar">
                <div>
                    <p class="eyebrow">Data Management</p>
                    <h1>Detail Riwayat Impor</h1>
                    <p class="subtitle">
                        Informasi file dan pratinjau data hasil impor.
                    </p>
                </div>

                <a class="back-link"
                   href="javascript:history.back()">
                    <span>←</span> Kembali
                </a>
            </header>

            <section class="card">
                <div class="card-header">
                    <div>
                        <h2>Informasi File</h2>
                        <p>Informasi file yang tercatat dalam riwayat impor.</p>
                    </div>
                </div>

                <div class="card-body">
                    <div class="file-info">
                        <div class="file-icon">📁</div>

                        <div style="flex: 1; min-width: 0;">
                            <p class="file-name">{safe(file_name)}</p>
                            <span class="file-type">
                                {safe(format_label)}
                            </span>
                        </div>
                    </div>

                    <div class="metadata">
                        <div class="meta-box">
                            <span class="meta-label">Waktu Impor</span>
                            <div class="meta-value">
                                {safe(log.imported_at)}
                            </div>
                        </div>

                        <div class="meta-box">
                            <span class="meta-label">Jumlah Data Impor</span>
                            <div class="meta-value">
                                {safe(log.total_items)}
                            </div>
                        </div>

                        <div class="meta-box">
                            <span class="meta-label">Status Impor</span>
                            <div class="meta-value">
                                <span class="status {status_class}">
                                    {safe(status)}
                                </span>
                            </div>
                        </div>
                    </div>

                    <div style="margin-top: 22px;"
                         class="file-card-actions">
                        {
                            f'''
                            <a class="btn btn-primary"
                               href="{html_escape(download_url, quote=True)}"
                               download>
                                ↓ Download File
                            </a>
                            '''
                            if download_url and file_exists
                            else '''
                            <span class="btn btn-secondary"
                                  style="opacity:.65;cursor:not-allowed;">
                                File tidak tersedia
                            </span>
                            '''
                        }
                    </div>
                </div>
            </section>

            <section class="card">
                <div class="card-header">
                    <div class="preview-heading">
                        <div>
                            <h2>{safe(preview_title)}</h2>
                            <p>{safe(preview_description)}</p>
                        </div>

                        <span class="count-badge">
                            {total_rows:,} baris data
                        </span>
                    </div>
                </div>

                <div class="card-body">
                    {preview_html}
                </div>
            </section>

            <footer class="footer">
                Import History · Data pratinjau riwayat impor
            </footer>

        </main>
    </body>
    </html>
    """

    return HttpResponse(html)

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

from django.shortcuts import render, get_object_or_404
from .models import Item, Type, Status, Tag

def item_detail_view(request, pk):
    item = get_object_or_404(Item, pk=pk)

    alternative_titles = []

    if item.alternative_title:
        alternative_titles = [
            title.strip()
            for title in item.alternative_title.split(',')
            if title.strip()
        ]

    return render(
        request,
        'library_item_detail.html',
        {
            'item': item,
            'alternative_titles': alternative_titles,
        }
    )

from django.shortcuts import render
from .models import Item, Type, Status, Tag

from django.shortcuts import render
from django.db.models import Case, When, Value, IntegerField
from .models import Item, Type, Status, Tag

def library_view(request):
    items = Item.objects.all()

    # Ambil nilai pencarian judul atau judul alternatif
    query = request.GET.get('q', '').strip()

    if query:
        items = items.filter(
            Q(title__icontains=query) |
            Q(alternative_title__icontains=query)
        )

    # Ambil nilai filter
    type_id = request.GET.get('Type')
    status_slug = request.GET.get('status')

    # Ambil tag_ids (pastikan hanya angka)
    tag_ids = [
        t for t in request.GET.getlist('tag')
        if t.isdigit()
    ]

    # Filter Tipe
    if type_id:
        items = items.filter(Type_id=type_id)

    # Filter Status
    if status_slug:
        items = items.filter(status__name__iexact=status_slug)

    # Filter Tag
    if tag_ids:
        items = items.filter(
            tags__id__in=tag_ids
        ).distinct()

    # Sorting logic
    sort = request.GET.get('sort')

    if sort in ['new', 'latest']:
        items = items.order_by('-created_at')
    elif sort == 'az':
        items = items.order_by('title')
    else:
        items = items.order_by('-created_at')

    # Urutan kategori: No Type di atas, sisanya berdasarkan abjad
    categories = Type.objects.annotate(
        order=Case(
            When(name__iexact='No Type', then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        )
    ).order_by('order', 'name')

    # Urutan status: No Status di atas, sisanya berdasarkan abjad
    statuses = Status.objects.annotate(
        order=Case(
            When(name__iexact='No Status', then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        )
    ).order_by('order', 'name')

    return render(request, 'library.html', {
        'items': items,
        'categories': categories,
        'statuses': statuses,
        'tags': Tag.objects.all(),
        'active_tags': [int(t) for t in tag_ids],
        'sort_options': [
            ('relevance', 'Relevance'),
            ('latest', 'Latest'),
            ('az', 'A-Z'),
            ('new', 'New')
        ],
    })


def library_results(request):
    items = Item.objects.all()

    # Ambil query pencarian
    query = request.GET.get('q', '').strip()
    type_val = request.GET.get('type')

    # Cari berdasarkan judul utama ATAU judul alternatif
    if query:
        items = items.filter(
            Q(title__icontains=query) |
            Q(alternative_title__icontains=query)
        )

    # Filter Type tetap dipertahankan
    if type_val:
        items = items.filter(Type__id=type_val)

    return render(request, 'library_results.html', {
        'items': items
    })


def library_item_detail(request, pk):
    item = get_object_or_404(Item, pk=pk)

    reading_item = None
    if request.user.is_authenticated:
        reading_item = ReadingItem.objects.filter(
            user=request.user,
            title=item.title
        ).first()

    all_user_ratings = (
        ReadingItem.objects
        .filter(title=item.title)
        .exclude(rating='-')
        .exclude(rating='')
    )

    # Pisahkan judul alternatif berdasarkan koma atau baris baru.
    alternative_titles = [
        title.strip()
        for title in (item.alternative_title or '').replace('\r\n', '\n').replace('\r', '\n').replace('\n', ',').split(',')
        if title.strip()
    ]

    return render(request, 'library_item_detail.html', {
        'item': item,
        'reading_item': reading_item,
        'is_already_added': reading_item is not None,
        'all_user_ratings': all_user_ratings,
        'alternative_titles': alternative_titles,
    })

@login_required
def add_to_reading_list(request, pk):
    item = get_object_or_404(Item, pk=pk)

    existing_item = ReadingItem.objects.filter(
        user=request.user,
        title=item.title
    ).first()

    if existing_item:
        messages.info(
            request,
            f'"{item.title}" sudah ada di Reading List Anda.'
        )
    else:
        reading_item = ReadingItem.objects.create(
            user=request.user,
            title=item.title,
            alternative_title=item.alternative_title,
            Type=item.Type,
            image=item.image,
            status=item.status,
            synopsis=item.synopsis,
        )

        # Salin tag dari master
        reading_item.tags.set(item.tags.all())

        messages.success(
            request,
            f'"{item.title}" telah ditambahkan ke Reading List!'
        )

    return redirect('library_item_detail', pk=pk)

@login_required
def remove_from_reading_list(request, pk):
    # Cari item berdasarkan ID item asli atau judulnya
    item = get_object_or_404(Item, pk=pk)
    reading_item = ReadingItem.objects.filter(user=request.user, title=item.title)
    
    if reading_item.exists():
        reading_item.delete()
        messages.success(request, f'"{item.title}" telah dihapus dari Reading List.')
    else:
        messages.error(request, 'Data tidak ditemukan di Reading List Anda.')
        
    return redirect('library_item_detail', pk=pk)

from .models import Profile
from django.contrib.auth import update_session_auth_hash
from .forms import MinimalPasswordChangeForm # Pastikan form ini ada
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.mail import send_mail
from django.urls import reverse

import re # Tambahkan import ini di paling atas file views.py Anda

@login_required
def profile(request):
    user_profile, created = Profile.objects.get_or_create(user=request.user)
    
    # Inisialisasi form password untuk modal
    pwd_form = MinimalPasswordChangeForm(request.user)

    if request.method == 'POST':
        # 1. Cek jika form ganti password yang dikirim
        if 'old_password' in request.POST:
            pwd_form = MinimalPasswordChangeForm(request.user, request.POST)
            if pwd_form.is_valid():
                user = pwd_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, "Password berhasil diubah!")
                return redirect('profile')
            else:
                messages.error(request, "Gagal mengubah password. Periksa kembali input Anda.")
        
        # 2. Cek jika form reminder yang dikirim
        elif 'update_reminder' in request.POST:
            is_active = request.POST.get('is_reminder_active')
            
            if is_active:
                user_profile.reminder_email = request.POST.get('reminder_email')
                user_profile.reminder_frequency = int(request.POST.get('reminder_frequency', 30))
                user_profile.last_reminder_sent = timezone.now()
                user_profile.save()

                # Proses pengiriman email tes/konfirmasi saat diaktifkan
                try:
                    total_items = ReadingItem.objects.filter(user=request.user).count()
                    link_backup = request.build_absolute_uri(reverse('reading_list'))
                    
                    subject = "Backup Reminder Setup: Your Reading List Data"
                    message = (
                        f"Hello {user_profile.display_name or request.user.username},\n\n"
                        f"Your backup reminder has been successfully updated!\n"
                        f"You currently have {total_items} items saved in your reading list.\n\n"
                        f"Please remember to download your backup regularly!\n"
                        f"Click the link below to access your reading list:\n{link_backup}"
                    )
                    
                    send_mail(
                        subject,
                        message,
                        settings.DEFAULT_FROM_EMAIL,
                        [user_profile.reminder_email],
                        fail_silently=False,
                    )
                    messages.success(request, "Reminder preferences saved & test email sent successfully!")
                except Exception as e:
                    messages.warning(request, f"Preferences saved, but failed to send email: {e}")
            else:
                # Jika switch dimatikan, kosongkan data reminder
                user_profile.reminder_email = None
                user_profile.reminder_frequency = 30
                user_profile.last_reminder_sent = None
                user_profile.save()
                messages.success(request, "Backup reminder has been disabled.")

            return redirect('profile')
            
        # 3. Jika bukan keduanya, berarti form update profil biasa (Display name, Bio, dll)
        else:
            user_profile.display_name = request.POST.get('display_name', user_profile.display_name)
            user_profile.bio = request.POST.get('bio', user_profile.bio)
            user_profile.location = request.POST.get('location', user_profile.location)
            
            if request.FILES.get('avatar'):
                user_profile.avatar = request.FILES.get('avatar')
            if request.FILES.get('cover'):
                user_profile.cover = request.FILES.get('cover')
                
            user_profile.save()
            messages.success(request, "Profil berhasil diperbarui!")
            return redirect('profile')

    return render(request, 'profile.html', {
        'profile': user_profile,
        'pwd_form': pwd_form
    })

from django.db.models import Count
from django.contrib.auth.models import User

def manage_view(request):
    # Menggunakan 'reading_items' sesuai dengan petunjuk dari error
    users = User.objects.annotate(item_count=Count('reading_items')) 
    return render(request, 'manage.html', {'users': users})

from django.shortcuts import render, get_object_or_404
from django.contrib.auth.models import User
from django.http import JsonResponse
import json
from .models import Item, ReadingItem

def sync_item_detail(request, user_id):
    selected_user = get_object_or_404(User, id=user_id)

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            selected_ids = data.get('selected_ids', [])
            added_count = 0

            for reading_id in selected_ids:
                # 1. Ambil data dari ReadingItem milik user
                user_item = ReadingItem.objects.get(id=reading_id, user=selected_user)
                
                # 2. Cek apakah item dengan judul tersebut sudah ada di Master (Item)
                exists = Item.objects.filter(title=user_item.title).exists()

                if not exists:
                    # 3. Tambahkan ke Database Master (Admin)
                    new_master_item = Item.objects.create(
                        title=user_item.title,
                        chapters=user_item.chapters,
                        season=user_item.season,
                        status=user_item.status,
                        Type=user_item.Type,
                        synopsis=user_item.synopsis,
                        image=user_item.image
                    )
                    
                    # 4. Sinkronisasi Tags
                    tags = user_item.tags.all()
                    if tags.exists():
                        new_master_item.tags.set(tags)
                    else:
                        # Jaring pengaman: jika user_item tidak punya tag, masukkan ID 1
                        new_master_item.tags.add(1)
                        
                    added_count += 1
                
            return JsonResponse({'message': f'Berhasil mengirim {added_count} item ke database admin!', 'status': 'success'})
        except Exception as e:
            return JsonResponse({'message': str(e), 'status': 'error'}, status=400)

    # Menampilkan daftar ReadingItem milik user untuk dipilih
    items = selected_user.reading_items.all()
    
    return render(request, 'sync_item_detail.html', {
        'selected_user': selected_user,
        'items': items
    })

from django.shortcuts import redirect

def redirect_whatsapp(request):
    phone_number = "6282264974290"
    return redirect(f"https://wa.me/{phone_number}")

from django.http import HttpResponse
from django.core.management import call_command
from django.views.decorators.http import require_GET

@require_GET
def trigger_reminder(request):
    # Kunci keamanan sederhana agar orang lain tidak bisa mengaksesnya
    if request.GET.get('key') == 'rahasia123':
        call_command('send_reminders')
        return HttpResponse("Pengingat berhasil diproses.")
    return HttpResponse("Akses ditolak.", status=403)

from django.shortcuts import render

def notes_view(request):
    """
    View untuk merender halaman catatan (Notes).
    Catatan disimpan di sisi client menggunakan LocalStorage, 
    jadi view ini cukup merender template HTML-nya saja.
    """
    return render(request, 'notes.html') # Sesuaikan nama file HTML Anda jika berbeda